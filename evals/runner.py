from __future__ import annotations

import asyncio
import hashlib
import json
import random
import subprocess
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable

from evals.evidence import evaluation_provenance
from evals.provider_adapter import EvaluationUsageAdapter
from evals.report import compare_policies, generate_policy_summary
from evals.schema import (
    CANONICAL_PAIRED_RUNTIME_PROFILE,
    ContextEvalMetrics,
    EvaluationFixture,
    EvaluationPolicy,
    EvaluationPolicyControls,
    EvaluationReport,
    ExecutedAssignment,
    ExecutionScript,
    OracleSpec,
    OracleType,
    PolicySummary,
    RawExecutionRecord,
    ScriptedModelResponse,
    ScriptedToolCall,
    TaskEvalResult,
)
from skail.agents.lead import LeadControls
from skail.agents.profiles import builtin_profiles
from skail.domain.ids import new_session_id
from skail.domain.routing import TaskAssignment
from skail.providers.models import CapabilityVector, ModelProfile, ProviderSupportLevel
from skail.routing.assignment import RoutingSnapshot, config_revision
from skail.routing.estimates import AttemptEstimateInput, estimate_attempt_cost
from skail.routing.selector import RouteCandidate
from skail.runtime.run_controller import RunController  # type: ignore[import-untyped]
from skail.sessions.journal import Journal, SessionSnapshot  # type: ignore[import-untyped]


class _FixtureChatModel(BaseChatModel):
    """Offline fixture behavior that exercises Skail's actual tool boundary."""

    model_name: str = "eval-model"
    responses: tuple[ScriptedModelResponse, ...] = ()
    final_response: ScriptedModelResponse
    child_response: ScriptedModelResponse | None = None
    is_child: bool = False
    child_delay: float = 0.0
    _cursor: int = 0

    @staticmethod
    def _message(response: ScriptedModelResponse) -> AIMessage:
        return AIMessage(
            content=response.content,
            tool_calls=[call.model_dump() for call in response.tool_calls],
            usage_metadata={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            },
            response_metadata={"skail_cost_usd": str(response.usage.cost_usd)},
        )

    def _is_child_call(self, messages: Sequence[BaseMessage]) -> bool:
        if self.is_child:
            return True
        return any(
            isinstance(message, HumanMessage)
            and isinstance(message.content, str)
            and message.content.lstrip().startswith("<context_packet")
            for message in messages
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        if self._is_child_call(messages):
            if self.child_delay > 0:
                time.sleep(self.child_delay)
            response = self.child_response or self.final_response
            return ChatResult(generations=[ChatGeneration(message=self._message(response))])
        if self._cursor < len(self.responses):
            response = self.responses[self._cursor]
            self._cursor += 1
        else:
            response = self.final_response
        return ChatResult(generations=[ChatGeneration(message=self._message(response))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self._is_child_call(messages):
            if self.child_delay > 0:
                await asyncio.sleep(self.child_delay)
            response = self.child_response or self.final_response
            return ChatResult(generations=[ChatGeneration(message=self._message(response))])
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "skail-evaluation-fixture"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, AIMessage]:
        del tools, kwargs
        return self


def _with_execution_decision(script: ExecutionScript, objective: str) -> ExecutionScript:
    """Compile the fixture protocol without consulting its scoring oracle."""
    if not script.responses:
        return script
    first = script.responses[0]
    if any(call.name == "execution_decision" for call in first.tool_calls):
        return script
    decision = ScriptedToolCall(
        name="execution_decision",
        args={
            "mode": "direct",
            "objective": objective,
            "constraints": [],
            "reason": "The deterministic fixture performs bounded direct work.",
        },
        id="fixture-execution-decision",
    )
    return script.model_copy(
        update={
            "responses": (
                first.model_copy(update={"tool_calls": (decision, *first.tool_calls)}),
                *script.responses[1:],
            )
        }
    )


def _fixed_profile_models(model: str | None) -> dict[str, str]:
    return {} if model is None else {name: model for name in builtin_profiles()}


def default_eval_candidates() -> tuple[RouteCandidate, ...]:
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
            provider="eval-provider",
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


def _token_count(value: object) -> int:
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def _context_metrics(snapshot: SessionSnapshot) -> ContextEvalMetrics:
    estimated = 0
    selected = 0
    compressed = 0
    dropped = 0
    omissions = 0
    handoff_bytes = 0
    for packet in snapshot.context_packets:
        payload = packet.payload
        estimated += _token_count(payload.get("estimated_tokens", 0))
        packet_omissions = payload.get("omissions", ())
        omissions += len(packet_omissions) if isinstance(packet_omissions, list) else 0
        for component in payload.get("components", ()):
            if not isinstance(component, dict):
                continue
            tokens = _token_count(component.get("estimated_tokens", 0))
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


def _raw_execution_record(
    *,
    fixture: EvaluationFixture,
    policy: EvaluationPolicy,
    script: ExecutionScript,
    workspace: Path,
    run_status: str | None,
    error: str | None,
    wall_time_seconds: float,
    usage_records: tuple[Decimal, ...],
    assignments: tuple[TaskAssignment, ...],
) -> RawExecutionRecord:
    script_json = json.dumps(script.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    workspace_files = tuple(
        sorted(
            (
                str(path.relative_to(workspace)).replace("\\", "/"),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in workspace.rglob("*")
            if path.is_file()
            and ".skail" not in path.relative_to(workspace).parts
            and path.name != ".skail-eval.sqlite"
        )
    )
    workspace_text_files = tuple(
        sorted(
            (
                str(path.relative_to(workspace)).replace("\\", "/"),
                path.read_bytes().decode("utf-8", errors="replace"),
            )
            for path in workspace.rglob("*")
            if path.is_file()
            and ".skail" not in path.relative_to(workspace).parts
            and path.name != ".skail-eval.sqlite"
        )
    )
    return RawExecutionRecord(
        fixture_id=fixture.id,
        policy=policy,
        script_digest=hashlib.sha256(script_json.encode("utf-8")).hexdigest(),
        run_status=run_status,
        error=error,
        wall_time_seconds=wall_time_seconds,
        usage_cost_usd=sum(usage_records, Decimal("0.00")),
        usage_records=usage_records,
        assignments=tuple(
            ExecutedAssignment(
                attempt_number=assignment.attempt_number,
                provider=assignment.provider,
                model=assignment.model,
                routing_mode=assignment.routing_mode,
                capability_floor=assignment.capability_floor,
                estimated_attempt_cost_usd=assignment.estimated_attempt_cost_usd,
                explanation=assignment.explanation,
                catalog_revision=assignment.catalog_revision,
            )
            for assignment in assignments
        ),
        workspace_files=workspace_files,
        workspace_text_files=workspace_text_files,
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
        paired_seeds: tuple[int, ...] | None = None,
        repetitions: int = 1,
        runtime_writes_enabled: bool = True,
        command: tuple[str, ...] = ("EvaluationRunner.run",),
        cell_timeout_seconds: float = 15.0,
    ) -> None:
        self.fixtures = list(fixtures)
        self.policies = list(policies)
        self.candidates = candidates or default_eval_candidates()
        self.base_workspace = base_workspace
        self.seed = seed
        self.paired_seeds = (seed,) if paired_seeds is None else paired_seeds
        if not self.paired_seeds:
            raise ValueError("paired_seeds must not be empty")
        if repetitions < 1:
            raise ValueError("repetitions must be at least one")
        self.repetitions = repetitions
        self.runtime_writes_enabled = runtime_writes_enabled
        self.command = command
        if cell_timeout_seconds <= 0:
            raise ValueError("cell_timeout_seconds must be positive")
        self.cell_timeout_seconds = cell_timeout_seconds
        self._run_profile_id: str | None = None

    @classmethod
    def paired_runtime(
        cls,
        *,
        fixtures: Sequence[EvaluationFixture],
        candidates: tuple[RouteCandidate, ...] | None = None,
        base_workspace: Path | None = None,
        runtime_writes_enabled: bool = True,
        command: tuple[str, ...] = ("EvaluationRunner.run",),
    ) -> EvaluationRunner:
        """Build the plan-required, deterministic paired runtime matrix."""
        profile = CANONICAL_PAIRED_RUNTIME_PROFILE
        runner = cls(
            fixtures=fixtures,
            policies=profile.policies,
            candidates=candidates,
            base_workspace=base_workspace,
            paired_seeds=profile.paired_seeds,
            repetitions=profile.repetitions,
            runtime_writes_enabled=runtime_writes_enabled,
            command=command,
        )
        runner._run_profile_id = profile.id
        return runner

    def run(self, *, catalog_revision: str = "eval-v1") -> EvaluationReport:
        import uuid

        run_id = f"eval-{uuid.uuid4().hex[:8]}"
        results: list[TaskEvalResult] = []
        raw_records: list[RawExecutionRecord] = []

        policy_controls = {policy.value: policy.controls() for policy in self.policies}
        provenance = evaluation_provenance(
            fixtures=self.fixtures,
            catalog_revision=catalog_revision,
            candidates=self.candidates,
            policy_controls=policy_controls,
            command=self.command,
        )
        cases: list[tuple[EvaluationFixture, EvaluationPolicy, int, int]] = []
        for seed in self.paired_seeds:
            for repetition in range(1, self.repetitions + 1):
                seeded_cases = [
                    (fixture, policy, seed, repetition)
                    for fixture in self.fixtures
                    for policy in self.policies
                ]
                random.Random(f"{seed}:{repetition}").shuffle(seeded_cases)
                cases.extend(seeded_cases)
        for execution_order, (fixture, policy, seed, repetition) in enumerate(cases):
            res, raw_record = self._run_fixture_policy(
                fixture=fixture,
                policy=policy,
                policy_controls=policy_controls[policy.value],
                catalog_revision=catalog_revision,
            )
            identity = {
                "seed": seed,
                "repetition": repetition,
                "execution_order": execution_order,
            }
            results.append(res.model_copy(update=identity))
            raw_records.append(raw_record.model_copy(update=identity))

        economic_fixture_ids = {
            fixture.id for fixture in self.fixtures if fixture.economic_eligible
        }
        economic_results = [
            result for result in results if result.fixture_id in economic_fixture_ids
        ]
        summaries: dict[str, PolicySummary] = {
            pol.value: generate_policy_summary(economic_results, pol) for pol in self.policies
        }
        comparison = compare_policies(
            summaries,
            economic_results,
            self.fixtures,
            paired_seeds=self.paired_seeds,
            repetitions=self.repetitions,
        )

        return EvaluationReport(
            run_id=run_id,
            timestamp=datetime.now(UTC),
            catalog_revision=catalog_revision,
            provider_mode="deterministic",
            fixture_count=len(self.fixtures),
            run_profile_id=self._run_profile_id,
            paired_seeds=self.paired_seeds,
            repetitions=self.repetitions,
            provenance=provenance,
            policy_controls=policy_controls,
            policy_summaries=summaries,
            comparison=comparison,
            results=tuple(results),
            raw_records=tuple(raw_records),
        )

    def _run_fixture_policy(
        self,
        *,
        fixture: EvaluationFixture,
        policy: EvaluationPolicy,
        policy_controls: EvaluationPolicyControls,
        catalog_revision: str,
    ) -> tuple[TaskEvalResult, RawExecutionRecord]:
        import tempfile

        workspace_parent = None
        if self.base_workspace is not None:
            self.base_workspace.mkdir(parents=True, exist_ok=True)
            workspace_parent = str(self.base_workspace)
        with tempfile.TemporaryDirectory(
            prefix=f"skail-eval-{fixture.id}-{policy.value}-",
            dir=workspace_parent,
        ) as directory:
            workspace = Path(directory)
            for rel_path, content in fixture.initial_files.items():
                target_file = workspace / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content, encoding="utf-8")

            script = fixture.execution
            if script is None:
                error = "fixture execution script is required"
                raw_record = RawExecutionRecord(
                    fixture_id=fixture.id,
                    policy=policy,
                    script_digest="",
                    error=error,
                    usage_cost_usd=Decimal("0.00"),
                )
                return (
                    TaskEvalResult(
                        fixture_id=fixture.id,
                        policy=policy,
                        completed=False,
                        passed_oracle=False,
                        wall_time_seconds=0.0,
                        total_cost_usd=Decimal("0.00"),
                        models_used=(),
                        assignments_count=0,
                        escalations_count=0,
                        interrupts_count=0,
                        error=error,
                        catalog_revision=catalog_revision,
                        provider_mode="deterministic",
                    ),
                    raw_record,
                )

            script = _with_execution_decision(script, fixture.prompt)
            routing_mode = policy_controls.routing_mode
            child_response = script.child_response or script.final_response
            runtime_models: dict[str, BaseChatModel] = {}
            for candidate in self.candidates:
                model = _FixtureChatModel(
                    model_name=candidate.profile.model,
                    responses=script.responses,
                    final_response=script.final_response,
                    child_response=child_response,
                    child_delay=0.45,
                )
                runtime_models[candidate.profile.model] = model
                runtime_models[f"{candidate.profile.provider}:{candidate.profile.model}"] = model

            child_model_name = "eval-provider:explorer"
            child_model = _FixtureChatModel(
                model_name="explorer",
                final_response=script.final_response,
                child_response=child_response,
                is_child=True,
                child_delay=0.45,
            )
            runtime_models["explorer"] = child_model
            runtime_models[child_model_name] = child_model

            session_id = new_session_id()
            journal = Journal(workspace / ".skail-eval.sqlite")
            journal.migrate()
            journal.create_session(
                session_id=str(session_id),
                title=fixture.title,
                created_at=datetime.now(UTC),
            )
            controls = LeadControls(
                delegation=policy_controls.delegation,
                model=policy_controls.lead_model,
                write_allowed=self.runtime_writes_enabled,
                max_children=policy_controls.max_children,
                routing_mode=routing_mode,
                risk=fixture.risk,
            )
            started = time.perf_counter()
            error_msg: str | None = None
            try:
                try:
                    controller = RunController(
                        session_id=session_id,
                        workspace=workspace,
                        journal=journal,
                        models=runtime_models,
                        default_lead_model=(
                            policy_controls.lead_model or self.candidates[0].profile.model
                        ),
                        default_child_model=policy_controls.child_model or child_model_name,
                        fixed_profile_models={
                            "explorer": child_model_name,
                            **_fixed_profile_models(policy_controls.child_model),
                        },
                        budget_limit_usd=Decimal("100.00"),
                        catalog_revision=catalog_revision,
                        providers={
                            "eval-provider": EvaluationUsageAdapter(),
                        },
                        candidates_fn=lambda: RoutingSnapshot(
                            catalog_revision=catalog_revision,
                            config_revision=config_revision(
                                {"routing": {"mode": routing_mode.value}}
                            ),
                            health_revision="eval-health-v1",
                            candidates=self.candidates,
                        ),
                    )
                    run_result = asyncio.run(
                        asyncio.wait_for(
                            controller.run_instruction(fixture.prompt, controls=controls),
                            timeout=self.cell_timeout_seconds,
                        )
                    )
                except TimeoutError:
                    run_result = None
                    error_msg = (
                        f"runtime execution timed out after {self.cell_timeout_seconds:.1f}s"
                    )
                except Exception as exc:
                    run_result = None
                    error_msg = f"runtime execution failed ({type(exc).__name__}): {exc}"
                elapsed = time.perf_counter() - started
                snapshot = journal.get_session_snapshot(str(session_id))
            finally:
                journal.close()
            assignments = [
                TaskAssignment.model_validate(assignment.payload)
                for assignment in snapshot.assignments
            ]
            total_cost = sum(
                (usage.amount_usd for usage in snapshot.usage_records),
                Decimal("0.00"),
            )
            raw_record = _raw_execution_record(
                fixture=fixture,
                policy=policy,
                script=script,
                workspace=workspace,
                run_status=None if run_result is None else run_result.status,
                error=error_msg,
                wall_time_seconds=round(elapsed, 4),
                usage_records=tuple(usage.amount_usd for usage in snapshot.usage_records),
                assignments=tuple(assignments),
            )
            passed_oracle, oracle_error = evaluate_oracle(workspace, fixture.oracle)
            completed = bool(
                run_result is not None and run_result.status == "completed" and passed_oracle
            )
            run_status = None if run_result is None else run_result.status
            contract_passed = run_status == fixture.expected_run_status and passed_oracle
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
                contract_passed=contract_passed,
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
                provider_mode="deterministic",
                child_wall_seconds=(0.0 if run_result is None else run_result.child_wall_seconds),
                child_peak_active=(0 if run_result is None else run_result.child_peak_active),
                child_count=(0 if run_result is None else run_result.child_count),
            ), raw_record
