from __future__ import annotations

import asyncio
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
from rudder.agents.context import ContextAssembler, ContextComponent
from rudder.agents.lead import LeadControls
from rudder.domain.events import SecretRedactor
from rudder.domain.ids import new_assignment_id, new_reservation_id, new_session_id, new_task_id
from rudder.domain.routing import TaskAssignment
from rudder.providers.models import CapabilityVector, ModelProfile, ProviderSupportLevel
from rudder.routing.estimates import AttemptEstimateInput, estimate_attempt_cost
from rudder.routing.requirements import ROLE_FLOORS, RequirementBuilder, TaskRisk
from rudder.routing.selector import RouteCandidate, select_model
from rudder.runtime.run_controller import RunController
from rudder.sessions.journal import Journal


class _FixtureChatModel(BaseChatModel):
    """Offline fixture behavior that exercises Rudder's actual tool boundary."""

    model_name: str = "eval-model"
    tool_calls: tuple[dict[str, Any], ...] = ()
    _cursor: int = 0

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        if self._cursor < len(self.tool_calls):
            call = self.tool_calls[self._cursor]
            self._cursor += 1
            message = AIMessage(content="", tool_calls=[call])
        else:
            message = AIMessage(content="Fixture work completed through Rudder tools.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "rudder-evaluation-fixture"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, AIMessage]:
        del tools, kwargs
        return self


def _fixture_tool_calls(oracle: OracleSpec) -> tuple[dict[str, Any], ...]:
    def write_call(target: str, content: str, index: int) -> dict[str, Any]:
        return {
            "name": "write_file",
            "args": {"file_path": target, "content": content},
            "id": f"eval-write-{index}",
        }

    if oracle.type in {OracleType.FILE_EXISTS, OracleType.FILE_CONTAINS, OracleType.FILE_CONTENT}:
        return (write_call(oracle.target, oracle.expected or "ok\n", 1),)
    if oracle.type is OracleType.MULTI_ASSERT:
        return tuple(
            write_call(
                str(assertion["target"]),
                str(assertion.get("expected", "ok\n")),
                index,
            )
            for index, assertion in enumerate(oracle.assertions, start=1)
            if assertion.get("type", "file_exists")
            in {
                OracleType.FILE_EXISTS.value,
                OracleType.FILE_CONTAINS.value,
                OracleType.FILE_CONTENT.value,
            }
            and assertion.get("target")
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
        live: bool = False,
        seed: int = 42,
    ) -> None:
        self.fixtures = list(fixtures)
        self.policies = list(policies)
        self.candidates = candidates or _default_eval_candidates()
        self.base_workspace = base_workspace
        self.live = live
        self.seed = seed
        self.redactor = SecretRedactor()
        self.assembler = ContextAssembler(redactor=self.redactor)
        self.req_builder = RequirementBuilder()

    def run(self, *, catalog_revision: str = "eval-v1") -> EvaluationReport:
        import uuid
        run_id = f"eval-{uuid.uuid4().hex[:8]}"
        results: list[TaskEvalResult] = []

        for fixture in self.fixtures:
            for policy in self.policies:
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
            provider_mode="live" if self.live else "fake",
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
        start_time = time.perf_counter()

        with tempfile.TemporaryDirectory(prefix=f"rudder-eval-{fixture.id}-") as tmp_dir_str:
            workspace = Path(tmp_dir_str)
            # 1. Populate initial files
            for rel_path, content in fixture.initial_files.items():
                target_file = workspace / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content, encoding="utf-8")

            # 2. Build requirements for role & risk
            routing_mode = policy.to_routing_mode()
            reqs = self.req_builder.build(
                role=fixture.role if fixture.role in ROLE_FLOORS else "implementer",
                risk=fixture.risk,
                mode=routing_mode,
                required_tools=bool(fixture.allowed_tools),
            )

            # 3. Model selection
            selection = select_model(self.candidates, reqs)
            assignments: list[TaskAssignment] = []
            escalations = 0
            completed = True
            error_msg: str | None = None
            models_used: list[str] = []

            if isinstance(selection, RouteCandidate):
                chosen_candidate = selection
            elif hasattr(selection, "candidate"):
                chosen_candidate = selection.candidate
            else:
                chosen_candidate = None

            if chosen_candidate is None:
                completed = False
                error_msg = "No qualified model found for requirements"
                selected_model_name = "none"
                cost = Decimal("0.00")
            else:
                selected_model_name = chosen_candidate.profile.model
                models_used.append(selected_model_name)
                cost = chosen_candidate.estimated_cost_usd or Decimal("0.01")

                t_id = new_task_id()
                r_id = new_reservation_id()
                a_id = new_assignment_id()
                asgn = TaskAssignment(
                    assignment_id=a_id,
                    task_id=t_id,
                    attempt_number=1,
                    provider=chosen_candidate.profile.provider,
                    model=chosen_candidate.profile.model,
                    routing_mode=routing_mode,
                    capability_floor=reqs.capability_floor,
                    estimated_attempt_cost_usd=cost,
                    reservation_id=r_id,
                    catalog_revision=catalog_revision,
                    explanation=("eval_selection",),
                )
                assignments.append(asgn)

                # Simulated attempt failure & escalation logic for economy vs auto
                # Economy reduces floor by 0.10, which may under-tier complex/high-risk tasks
                capability_fit = (
                    chosen_candidate.profile.capability.coding
                    if chosen_candidate.profile.capability
                    else 0.5
                )

                if (
                    policy == EvaluationPolicy.ECONOMY
                    and fixture.risk in (TaskRisk.COMPLEX, TaskRisk.HIGH)
                    and capability_fit < 0.80
                ):
                    # Attempt 1 fails due to under-tiering -> triggers escalation attempt
                    escalations += 1
                    escalated_reqs = self.req_builder.build(
                        role=fixture.role,
                        risk=fixture.risk,
                        mode=routing_mode,
                        escalated=True,
                        failed_model=(
                            chosen_candidate.profile.provider,
                            chosen_candidate.profile.model,
                        ),
                    )
                    esc_selection = select_model(self.candidates, escalated_reqs)
                    if hasattr(esc_selection, "candidate"):
                        esc_candidate = esc_selection.candidate
                        cost += esc_candidate.estimated_cost_usd or Decimal("0.02")
                        models_used.append(esc_candidate.profile.model)
                        asgn2 = TaskAssignment(
                            assignment_id=new_assignment_id(),
                            task_id=t_id,
                            attempt_number=2,
                            provider=esc_candidate.profile.provider,
                            model=esc_candidate.profile.model,
                            routing_mode=routing_mode,
                            capability_floor=escalated_reqs.capability_floor,
                            estimated_attempt_cost_usd=cost,
                            reservation_id=new_reservation_id(),
                            catalog_revision=catalog_revision,
                            explanation=("escalated_attempt",),
                        )
                        assignments.append(asgn2)
                    else:
                        completed = False
                        error_msg = "Escalation failed: no candidate"

            # 4. Context packet inspection
            lead_packet = self.assembler.assemble(
                task_id=str(new_task_id()),
                objective=fixture.prompt,
                constraints=("offline_eval",),
                state="eval_running",
                references=(
                    ContextComponent(
                        label="fixture_files",
                        revision="rev1",
                        content=str(fixture.initial_files),
                        rationale="workspace initial files",
                        estimated_tokens=len(str(fixture.initial_files)) // 4,
                    ),
                ),
            )

            # 5. Execute fixture work through the real controller and tool boundary.
            if completed:
                session_id = new_session_id()
                journal = Journal(workspace / ".rudder-eval.sqlite")
                journal.migrate()
                journal.create_session(
                    session_id=str(session_id),
                    title=fixture.title,
                    created_at=datetime.now(UTC),
                )
                fixture_model = _FixtureChatModel(
                    model_name=selected_model_name,
                    tool_calls=_fixture_tool_calls(fixture.oracle),
                )
                controls = LeadControls(
                    delegation="off" if policy is EvaluationPolicy.NO_DELEGATION else "auto",
                    max_children=1 if policy is EvaluationPolicy.SERIAL else 3,
                )
                try:
                    run_result = asyncio.run(
                        RunController(
                            session_id=session_id,
                            workspace=workspace,
                            journal=journal,
                            models={selected_model_name: fixture_model},
                            default_lead_model=selected_model_name,
                            budget_limit_usd=Decimal("10.00"),
                        ).run_instruction(fixture.prompt, controls=controls)
                    )
                except Exception as exc:
                    completed = False
                    error_msg = f"runtime execution failed: {exc}"
                else:
                    assignments = [run_result.lead_assignment]

            # 6. Evaluate oracle against filesystem / environment
            passed_oracle, oracle_err = evaluate_oracle(workspace, fixture.oracle)
            if not passed_oracle and completed:
                completed = False
                error_msg = oracle_err

            # 7. Check route invariants
            safety_defects = check_route_invariants(fixture, assignments, cost, policy=policy)

            elapsed = time.perf_counter() - start_time

            selected_tokens = sum(c.estimated_tokens for c in lead_packet.components)
            dropped_tokens = len(lead_packet.omissions) * 100
            context_metrics = ContextEvalMetrics(
                estimated_tokens=lead_packet.estimated_tokens,
                selected_tokens=selected_tokens,
                compressed_tokens=0,
                dropped_tokens=dropped_tokens,
                omissions_count=len(lead_packet.omissions),
                artifact_retrievals=1,
                handoff_bytes=len(fixture.prompt.encode("utf-8")),
            )

            return TaskEvalResult(
                fixture_id=fixture.id,
                policy=policy,
                completed=completed,
                passed_oracle=passed_oracle,
                wall_time_seconds=round(elapsed, 4),
                total_cost_usd=cost,
                models_used=tuple(models_used),
                assignments_count=len(assignments),
                escalations_count=escalations,
                interrupts_count=0,
                safety_defects=tuple(safety_defects),
                context_metrics=context_metrics,
                error=error_msg,
                catalog_revision=catalog_revision,
                provider_mode="live" if self.live else "fake",
            )
