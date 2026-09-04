from __future__ import annotations

import asyncio
import random
import subprocess
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable

from evals.report import compare_policies, generate_policy_summary
from evals.schema import (
    ContextEvalMetrics,
    EvaluationFixture,
    EvaluationPolicy,
    EvaluationReport,
    OracleSpec,
    OracleType,
    PolicySummary,
    TaskEvalResult,
)
from rudder.agents.lead import LeadControls
from rudder.domain.ids import new_session_id
from rudder.domain.routing import TaskAssignment
from rudder.providers.fake import FakeProviderAdapter
from rudder.providers.models import CapabilityVector, ModelProfile, ProviderSupportLevel
from rudder.routing.assignment import RoutingSnapshot, config_revision
from rudder.routing.estimates import AttemptEstimateInput, estimate_attempt_cost
from rudder.routing.selector import RouteCandidate
from rudder.runtime.run_controller import RunController
from rudder.sessions.journal import Journal, SessionSnapshot


class _FixtureChatModel(BaseChatModel):
    """Offline fixture behavior that exercises Rudder's actual tool boundary."""

    model_name: str = "eval-model"
    turns: tuple[list[dict[str, Any]], ...] = ()
    is_child: bool = False
    child_delay: float = 0.0
    cost_usd: Decimal = Decimal("0.001")
    _cursor: int = 0

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        if self.is_child and self.child_delay > 0:
            time.sleep(self.child_delay)
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content=(
                                '{"status":"succeeded",'
                                '"summary":"Exploration and verification complete",'
                                '"verification":[{'
                                '"criterion":"Provide evidence for the completed task",'
                                '"passed":true,'
                                '"evidence":"bounded explorer work completed"}]}'
                            ),
                            response_metadata={"rudder_cost_usd": str(self.cost_usd)},
                        )
                    )
                ]
            )
        if self._cursor < len(self.turns):
            calls = self.turns[self._cursor]
            self._cursor += 1
            message = AIMessage(
                content="",
                tool_calls=calls,
                response_metadata={"rudder_cost_usd": str(self.cost_usd)},
            )
        else:
            message = AIMessage(
                content="Fixture work completed through Rudder tools.",
                response_metadata={"rudder_cost_usd": str(self.cost_usd)},
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.is_child and self.child_delay > 0:
            await asyncio.sleep(self.child_delay)
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content=(
                                '{"status":"succeeded",'
                                '"summary":"Exploration and verification complete",'
                                '"verification":[{'
                                '"criterion":"Provide evidence for the completed task",'
                                '"passed":true,'
                                '"evidence":"bounded explorer work completed"}]}'
                            ),
                            response_metadata={"rudder_cost_usd": str(self.cost_usd)},
                        )
                    )
                ]
            )
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "rudder-evaluation-fixture"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, AIMessage]:
        del tools, kwargs
        return self


def _build_fixture_turns(
    fixture: EvaluationFixture,
    *,
    allow_delegation: bool,
) -> tuple[list[dict[str, Any]], ...]:
    def write_call(target: str, content: str, index: int) -> dict[str, Any]:
        return {
            "name": "write_file",
            "args": {"file_path": target, "content": content},
            "id": f"eval-write-{index}",
        }

    oracle = fixture.oracle
    if oracle.type in {OracleType.FILE_EXISTS, OracleType.FILE_CONTAINS, OracleType.FILE_CONTENT}:
        return ([write_call(oracle.target, oracle.expected or "ok\n", 1)],)

    if oracle.type is OracleType.MULTI_ASSERT:
        targets = [
            (str(assertion["target"]), str(assertion.get("expected", "ok\n")))
            for assertion in oracle.assertions
            if assertion.get("type", "file_exists")
            in {
                OracleType.FILE_EXISTS.value,
                OracleType.FILE_CONTAINS.value,
                OracleType.FILE_CONTENT.value,
            }
            and assertion.get("target")
        ]
        if not targets:
            return ()

        # Delegate independent analysis concurrently, then apply the resulting writes.
        if fixture.parallel_eligible and allow_delegation and len(targets) >= 2:
            task_calls = [
                {
                    "name": "task",
                    "args": {
                        "subagent_type": "explorer",
                        "description": f"Analyze and verify requirements for {target}",
                    },
                    "id": f"eval-task-{i}",
                }
                for i, (target, _) in enumerate(targets, start=1)
            ]
            write_turns = [
                [write_call(target, content, i)]
                for i, (target, content) in enumerate(targets, start=1)
            ]
            return (task_calls, *write_turns)

        return tuple(
            [write_call(target, content, i)]
            for i, (target, content) in enumerate(targets, start=1)
        )

    return ()


def _default_eval_candidates() -> tuple[RouteCandidate, ...]:
    profiles = [
        ModelProfile(
            provider="eval-provider",
            model="eval-mini",
            support_level=ProviderSupportLevel.NATIVE,
            input_usd_per_million=Decimal("0.20"),
            output_usd_per_million=Decimal("0.80"),
            context_tokens=65536,
            max_output_tokens=4096,
            supports_tools=True,
            supports_structured_output=True,
            auto_eligible=True,
            capability=CapabilityVector(
                coding=0.45,
                reasoning=0.42,
                tool_reliability=0.75,
                latency=0.20,
            ),
        ),
        ModelProfile(
            provider="eval-provider",
            model="eval-standard",
            support_level=ProviderSupportLevel.NATIVE,
            input_usd_per_million=Decimal("1.25"),
            output_usd_per_million=Decimal("5.00"),
            context_tokens=131072,
            max_output_tokens=8192,
            supports_tools=True,
            supports_structured_output=True,
            auto_eligible=True,
            capability=CapabilityVector(
                coding=0.68,
                reasoning=0.70,
                tool_reliability=0.88,
                latency=0.45,
            ),
        ),
        ModelProfile(
            provider="eval-provider",
            model="eval-flagship",
            support_level=ProviderSupportLevel.NATIVE,
            input_usd_per_million=Decimal("3.00"),
            output_usd_per_million=Decimal("15.00"),
            context_tokens=262144,
            max_output_tokens=16384,
            supports_tools=True,
            supports_structured_output=True,
            auto_eligible=True,
            capability=CapabilityVector(
                coding=0.92,
                reasoning=0.94,
                tool_reliability=0.98,
                latency=0.80,
            ),
        ),
        ModelProfile(
            provider="fake",
            model="explorer",
            support_level=ProviderSupportLevel.NATIVE,
            input_usd_per_million=Decimal("1.25"),
            output_usd_per_million=Decimal("5.00"),
            context_tokens=131072,
            max_output_tokens=8192,
            supports_tools=True,
            supports_structured_output=True,
            auto_eligible=False,
            capability=CapabilityVector(
                coding=0.68,
                reasoning=0.70,
                tool_reliability=0.88,
                latency=0.45,
            ),
        ),
    ]

    candidates: list[RouteCandidate] = []
    for p in profiles:
        est = estimate_attempt_cost(
            AttemptEstimateInput(
                context_tokens=p.context_tokens or 16000,
                output_tokens=min(p.max_output_tokens or 4096, 2048),
                expected_calls=6,
                input_usd_per_million=p.input_usd_per_million,
                output_usd_per_million=p.output_usd_per_million,
            )
        )
        candidates.append(
            RouteCandidate(
                profile=p,
                estimated_cost_usd=est.cost_usd,
                configured=True,
                healthy=True,
                enabled=True,
            )
        )
    return tuple(candidates)


def evaluate_oracle(workspace: Path, oracle: OracleSpec) -> tuple[bool, str | None]:
    try:
        match oracle.type:
            case OracleType.FILE_EXISTS:
                target_path = workspace / oracle.target
                if not target_path.exists():
                    return False, f"File does not exist: {oracle.target}"
                return True, None

            case OracleType.FILE_CONTAINS:
                target_path = workspace / oracle.target
                if not target_path.exists():
                    return False, f"File does not exist: {oracle.target}"
                content = target_path.read_text(encoding="utf-8", errors="replace")
                expected = oracle.expected or ""
                if expected not in content:
                    return False, f"File {oracle.target} missing expected string: '{expected}'"
                return True, None

            case OracleType.FILE_CONTENT:
                target_path = workspace / oracle.target
                if not target_path.exists():
                    return False, f"File does not exist: {oracle.target}"
                content = target_path.read_text(encoding="utf-8", errors="replace").strip()
                expected = (oracle.expected or "").strip()
                if content != expected:
                    return False, (
                        f"File {oracle.target} content mismatch. "
                        f"Got '{content}', expected '{expected}'"
                    )
                return True, None

            case OracleType.COMMAND_EXIT_ZERO:
                cmd = oracle.command or oracle.target
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode != 0:
                    return False, f"Command exited with code {proc.returncode}: {proc.stderr[:200]}"
                return True, None

            case OracleType.MULTI_ASSERT:
                for a in oracle.assertions:
                    sub_type = a.get("type", "file_exists")
                    sub_target = a.get("target", "")
                    sub_expected = a.get("expected")
                    sub_spec = OracleSpec(
                        type=OracleType(sub_type),
                        target=sub_target,
                        expected=sub_expected,
                    )
                    passed, err = evaluate_oracle(workspace, sub_spec)
                    if not passed:
                        return False, err
                return True, None

            case _:
                return False, f"Unknown oracle type: {oracle.type}"
    except Exception as exc:
        return False, f"Oracle evaluation exception: {exc}"


def check_route_invariants(
    fixture: EvaluationFixture,
    assignments: Sequence[TaskAssignment],
    total_cost: Decimal,
    policy: EvaluationPolicy = EvaluationPolicy.AUTO,
) -> list[str]:
    defects: list[str] = []
    inv = fixture.route_invariants

    for asgn in assignments:
        if (
            inv.min_floor is not None
            and asgn.capability_floor is not None
            and policy != EvaluationPolicy.ECONOMY
        ):
            if asgn.capability_floor < inv.min_floor:
                defects.append(
                    f"Assignment floor {asgn.capability_floor} below "
                    f"required minimum {inv.min_floor}"
                )
        if asgn.model in inv.forbid_models:
            defects.append(f"Assignment used forbidden model: {asgn.model}")
        if inv.expected_model and asgn.model != inv.expected_model:
            defects.append(f"Expected model {inv.expected_model} but got {asgn.model}")
        if inv.required_role and asgn.task_id and fixture.role != inv.required_role:
            defects.append(f"Expected role {inv.required_role} but task role was {fixture.role}")

    if inv.max_cost_usd is not None and total_cost > inv.max_cost_usd:
        defects.append(f"Total cost ${total_cost} exceeded max allowed ${inv.max_cost_usd}")

    return defects


def _runtime_integrity_defects(snapshot: SessionSnapshot) -> list[str]:
    defects: list[str] = []
    assignments = {item.attempt_id: item for item in snapshot.assignments}
    reservations = {item.reservation_id: item for item in snapshot.budget_reservations}
    for event in snapshot.events:
        if event.type != "model.started":
            continue
        if event.attempt_id is None or str(event.attempt_id) not in assignments:
            defects.append("model call started without a persisted assignment")
            continue
        assignment = assignments[str(event.attempt_id)]
        reservation_id = str(assignment.payload.get("reservation_id", ""))
        if reservation_id not in reservations:
            defects.append("model call started without a persisted reservation")
    if snapshot.assignments and not snapshot.usage_records:
        defects.append("completed runtime recorded no journal usage")
    defects.extend(
        f"runtime emitted {event.type}"
        for event in snapshot.events
        if event.type == "invariant.failed"
    )
    return defects


def _context_metrics(snapshot: SessionSnapshot) -> ContextEvalMetrics:
    estimated = 0
    selected = 0
    compressed = 0
    dropped = 0
    omissions = 0
    handoff_bytes = 0
    for packet in snapshot.context_packets:
        payload = packet.payload
        estimated += int(payload.get("estimated_tokens", 0))
        packet_omissions = payload.get("omissions", ())
        omissions += len(packet_omissions) if isinstance(packet_omissions, list) else 0
        for component in payload.get("components", ()):
            if not isinstance(component, dict):
                continue
            tokens = int(component.get("estimated_tokens", 0))
            disposition = component.get("disposition", "selected")
            if disposition == "selected":
                selected += tokens
            elif disposition == "compressed":
                compressed += tokens
            else:
                dropped += tokens
            if component.get("label") == "failure-handoff":
                handoff_bytes += len(str(component.get("content", "")).encode("utf-8"))
    artifact_retrievals = sum(
        1
        for event in snapshot.events
        if event.type == "tool.completed"
        and getattr(event.payload, "tool", None) in {"read_file", "grep", "glob", "ls"}
    )
    return ContextEvalMetrics(
        estimated_tokens=estimated,
        selected_tokens=selected,
        compressed_tokens=compressed,
        dropped_tokens=dropped,
        omissions_count=omissions,
        artifact_retrievals=artifact_retrievals,
        handoff_bytes=handoff_bytes,
    )


class EvaluationRunner:
    def __init__(
        self,
        *,
        fixtures: Sequence[EvaluationFixture],
        policies: Sequence[EvaluationPolicy] = (
            EvaluationPolicy.AUTO,
            EvaluationPolicy.ECONOMY,
            EvaluationPolicy.QUALITY,
            EvaluationPolicy.SERIAL,
            EvaluationPolicy.NO_DELEGATION,
        ),
        candidates: tuple[RouteCandidate, ...] | None = None,
        base_workspace: Path | None = None,
        seed: int = 42,
    ) -> None:
        self.fixtures = list(fixtures)
        self.policies = list(policies)
        self.candidates = candidates or _default_eval_candidates()
        self.base_workspace = base_workspace
        self.seed = seed

    def run(self, *, catalog_revision: str = "eval-v1") -> EvaluationReport:
        import uuid
        run_id = f"eval-{uuid.uuid4().hex[:8]}"
        results: list[TaskEvalResult] = []

        cases = [(fixture, policy) for fixture in self.fixtures for policy in self.policies]
        random.Random(self.seed).shuffle(cases)
        for fixture, policy in cases:
            res = self._run_fixture_policy(
                fixture=fixture,
                policy=policy,
                catalog_revision=catalog_revision,
            )
            results.append(res)

        summaries: dict[str, PolicySummary] = {
            pol.value: generate_policy_summary(results, pol) for pol in self.policies
        }
        comparison = compare_policies(summaries, results, self.fixtures)

        return EvaluationReport(
            run_id=run_id,
            timestamp=datetime.now(UTC),
            catalog_revision=catalog_revision,
            provider_mode="fake",
            fixture_count=len(self.fixtures),
            policy_summaries=summaries,
            comparison=comparison,
            results=tuple(results),
        )

    def _run_fixture_policy(
        self,
        *,
        fixture: EvaluationFixture,
        policy: EvaluationPolicy,
        catalog_revision: str,
    ) -> TaskEvalResult:
        import tempfile
        workspace_parent = None
        if self.base_workspace is not None:
            self.base_workspace.mkdir(parents=True, exist_ok=True)
            workspace_parent = str(self.base_workspace)
        with tempfile.TemporaryDirectory(
            prefix=f"rudder-eval-{fixture.id}-{policy.value}-",
            dir=workspace_parent,
        ) as directory:
            workspace = Path(directory)
            for rel_path, content in fixture.initial_files.items():
                target_file = workspace / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content, encoding="utf-8")

            routing_mode = policy.to_routing_mode()
            allow_delegation = policy is not EvaluationPolicy.NO_DELEGATION
            turns = _build_fixture_turns(fixture, allow_delegation=allow_delegation)
            runtime_models: dict[str, BaseChatModel] = {}
            for candidate in self.candidates:
                estimate = candidate.estimated_cost_usd or Decimal("0.001")
                call_count = max(len(turns) + 1, 1)
                model = _FixtureChatModel(
                    model_name=candidate.profile.model,
                    turns=turns,
                    cost_usd=estimate / call_count,
                )
                runtime_models[candidate.profile.model] = model
                runtime_models[
                    f"{candidate.profile.provider}:{candidate.profile.model}"
                ] = model

            child_model_name = "fake:explorer"
            child_model = _FixtureChatModel(
                model_name="explorer",
                is_child=True,
                child_delay=0.45,
                cost_usd=Decimal("0.001"),
            )
            runtime_models["explorer"] = child_model
            runtime_models[child_model_name] = child_model

            session_id = new_session_id()
            journal = Journal(workspace / ".rudder-eval.sqlite")
            journal.migrate()
            journal.create_session(
                session_id=str(session_id),
                title=fixture.title,
                created_at=datetime.now(UTC),
            )
            controls = LeadControls(
                delegation="off" if policy is EvaluationPolicy.NO_DELEGATION else "auto",
                max_children=1 if policy is EvaluationPolicy.SERIAL else 3,
                routing_mode=routing_mode,
                risk=fixture.risk,
            )
            started = time.perf_counter()
            error_msg: str | None = None
            try:
                run_result = asyncio.run(
                    RunController(
                        session_id=session_id,
                        workspace=workspace,
                        journal=journal,
                        models=runtime_models,
                        default_lead_model=self.candidates[0].profile.model,
                        default_child_model=child_model_name,
                        budget_limit_usd=Decimal("100.00"),
                        catalog_revision=catalog_revision,
                        providers={
                            "eval-provider": FakeProviderAdapter(),
                            "fake": FakeProviderAdapter(),
                        },
                        candidates_fn=lambda: RoutingSnapshot(
                            catalog_revision=catalog_revision,
                            config_revision=config_revision(
                                {"routing": {"mode": routing_mode.value}}
                            ),
                            health_revision="eval-health-v1",
                            candidates=self.candidates,
                        ),
                    ).run_instruction(fixture.prompt, controls=controls)
                )
            except Exception as exc:
                run_result = None
                error_msg = f"runtime execution failed: {exc}"
            elapsed = time.perf_counter() - started
            snapshot = journal.get_session_snapshot(str(session_id))
            assignments = [
                TaskAssignment.model_validate(assignment.payload)
                for assignment in snapshot.assignments
            ]
            total_cost = sum(
                (usage.amount_usd for usage in snapshot.usage_records),
                Decimal("0.00"),
            )
            passed_oracle, oracle_error = evaluate_oracle(workspace, fixture.oracle)
            completed = bool(
                run_result is not None
                and run_result.status == "completed"
                and passed_oracle
            )
            if error_msg is None and not passed_oracle:
                error_msg = oracle_error

            safety_defects = check_route_invariants(
                fixture,
                assignments,
                total_cost,
                policy=policy,
            )
            safety_defects.extend(_runtime_integrity_defects(snapshot))
            context_metrics = _context_metrics(snapshot)
            events = snapshot.events
            return TaskEvalResult(
                fixture_id=fixture.id,
                policy=policy,
                completed=completed,
                passed_oracle=passed_oracle,
                wall_time_seconds=round(elapsed, 4),
                total_cost_usd=total_cost,
                models_used=tuple(dict.fromkeys(item.model for item in assignments)),
                assignments_count=len(assignments),
                escalations_count=sum(1 for item in snapshot.attempts if item.number == 2),
                interrupts_count=sum(1 for event in events if event.type == "user.question"),
                safety_defects=tuple(safety_defects),
                context_metrics=context_metrics,
                error=error_msg,
                catalog_revision=catalog_revision,
                provider_mode="fake",
                child_wall_seconds=(0.0 if run_result is None else run_result.child_wall_seconds),
                child_peak_active=(0 if run_result is None else run_result.child_peak_active),
                child_count=(0 if run_result is None else run_result.child_count),
            )
