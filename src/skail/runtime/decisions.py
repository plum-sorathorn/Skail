from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError

from skail.domain.decisions import ExecutionDecision, ExecutionMode
from skail.domain.plans import ExecutionPlan, PlanRevision


class DecisionAdmissionError(ValueError):
    """A stable, model-visible rejection of an execution decision."""


class ExecutionDecisionGate:
    """Accept one initial decision and gate every operational tool behind it."""

    def __init__(
        self,
        *,
        admit_plan: Callable[[ExecutionPlan], Any],
        revise_plan: Callable[[PlanRevision, ExecutionPlan], Any] | None = None,
        persist_decision: Callable[[ExecutionDecision], Any] | None = None,
        restored_decision: ExecutionDecision | None = None,
        required_mode: ExecutionMode | None = None,
        required_agent_count: int | None = None,
    ) -> None:
        self._admit_plan = admit_plan
        self._revise_plan = revise_plan
        self._persist_decision = persist_decision
        self._required_mode = required_mode
        self._required_agent_count = required_agent_count
        self.decision: ExecutionDecision | None = None
        if restored_decision is not None:
            parsed = ExecutionDecision.model_validate(restored_decision.model_dump(mode="json"))
            self._validate_constraints(parsed)
            self.decision = parsed
        self._repairs_remaining = 2
        self._prepared_decision_ids: set[str] = set()
        self._rejected_tool_codes: dict[str, str] = {}

    @property
    def repairs_remaining(self) -> int:
        return self._repairs_remaining

    @property
    def is_exhausted(self) -> bool:
        """Terminal lock: repairs spent with no admitted decision."""

        return self.decision is None and self._repairs_remaining == 0

    def admit(self, value: dict[str, Any]) -> ExecutionDecision:
        if self.decision is not None:
            return self._admit_transition(value)
        return self._validate_and_record(value)

    def allows(self, tool_name: str, tool_call_id: str | None = None) -> bool:
        if tool_call_id is not None and tool_call_id in self._rejected_tool_codes:
            return False
        return tool_name == "ask_user" or self.decision is not None

    def is_prepared_decision(self, tool_call_id: str | None) -> bool:
        return tool_call_id is not None and tool_call_id in self._prepared_decision_ids

    def rejection_code(self, tool_call_id: str | None) -> str | None:
        return None if tool_call_id is None else self._rejected_tool_codes.get(tool_call_id)

    def prepare_response(self, response: ModelResponse[Any]) -> None:
        """Admit an ordered response before DeepAgents starts its parallel tool fan-out."""

        result = getattr(response, "result", None)
        messages: list[Any] = []
        if isinstance(result, (list, tuple)):
            messages = list(result)
        elif isinstance(result, AIMessage):
            messages = [result]

        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            for call in message.tool_calls:
                name = call.get("name")
                call_id = call.get("id")
                if not isinstance(name, str) or not isinstance(call_id, str):
                    continue
                if (
                    call_id in self._prepared_decision_ids
                    or call_id in self._rejected_tool_codes
                ):
                    continue
                if name == "execution_decision":
                    args = call.get("args")
                    if not isinstance(args, dict):
                        self._reject(call_id, "decision.plan_invalid")
                        continue
                    try:
                        self.admit(args)
                    except DecisionAdmissionError as exc:
                        self._reject(call_id, str(exc))
                    else:
                        self._prepared_decision_ids.add(call_id)
                    continue
                if not self.allows(name, call_id):
                    self._reject(call_id, "execution.decision_required")

    def _reject(self, tool_call_id: str, code: str) -> None:
        self._rejected_tool_codes[tool_call_id] = code

    def _admit_transition(self, value: dict[str, Any]) -> ExecutionDecision:
        candidate = self._parse(value)
        self._validate_constraints(candidate)
        if candidate.mode is ExecutionMode.DIRECT:
            raise DecisionAdmissionError("decision.already_recorded")
        if self.decision is not None and self.decision.plan is not None:
            if candidate.revision is None:
                if (
                    candidate.plan is not None
                    and candidate.plan.revision != self.decision.plan.revision
                ):
                    raise DecisionAdmissionError("decision.revision_conflict")
                raise DecisionAdmissionError("decision.already_recorded")
            expected = candidate.revision.expected_revision
            current = self.decision.plan.revision
            if expected != current or (
                candidate.plan is not None
                and candidate.plan.revision != expected + 1
            ):
                raise DecisionAdmissionError("decision.revision_conflict")
        self._record(candidate)
        return candidate

    def _validate_and_record(self, value: dict[str, Any]) -> ExecutionDecision:
        candidate = self._parse(value)
        self._validate_constraints(candidate)
        self._record(candidate)
        return candidate

    def _validate_constraints(self, candidate: ExecutionDecision) -> None:
        if self._required_mode is not None and candidate.mode is not self._required_mode:
            raise DecisionAdmissionError(
                "execution.intent_conflict: explicit user intent requires "
                f"mode={self._required_mode.value}"
            )
        if self._required_agent_count is None:
            return
        plan = candidate.plan
        agents = [] if plan is None else [
            node for node in plan.nodes if node.kind.value == "agent"
        ]
        if len(agents) != self._required_agent_count:
            raise DecisionAdmissionError(
                "execution.agent_count_conflict: explicit user intent requires "
                f"exactly {self._required_agent_count} agent plan nodes"
            )
        owned_scopes: list[str] = []
        for node in agents:
            scopes = tuple(
                scope.strip().replace("\\", "/").strip("/")
                for scope in node.resource_scopes
                if scope.strip().strip("/")
            )
            if not scopes:
                raise DecisionAdmissionError(
                    "execution.agent_scope_conflict: every requested agent needs "
                    "a non-overlapping resource scope"
                )
            for scope in scopes:
                parts = PurePosixPath(scope).parts
                if not parts or any(
                    parts[: len(existing_parts)] == existing_parts
                    or existing_parts[: len(parts)] == parts
                    for existing_parts in (
                        PurePosixPath(existing).parts for existing in owned_scopes
                    )
                ):
                    raise DecisionAdmissionError(
                        "execution.agent_scope_conflict: requested agent resource "
                        "scopes must be disjoint"
                    )
                owned_scopes.append(scope)

    def _parse(self, value: dict[str, Any]) -> ExecutionDecision:
        normalized = _normalize_decision_args(dict(value))
        try:
            return ExecutionDecision.model_validate(normalized)
        except ValidationError as exc:
            message = str(exc)
            if "revision_mismatch" in message or "revision_required" in message:
                raise DecisionAdmissionError("decision.revision_conflict") from exc
            if "decision.plan_required" in message or "plan_required" in message:
                self._consume_repair()
                raise DecisionAdmissionError(
                    "decision.plan_required: planned/discovery need a "
                    "validated finite plan (checkpoint + read-only for "
                    "discovery); direct must not send plan"
                ) from exc
            self._consume_repair()
            raise DecisionAdmissionError(_actionable_plan_invalid(exc)) from exc

    def _record(self, decision: ExecutionDecision) -> None:
        if decision.plan is not None:
            try:
                if decision.revision is None:
                    self._admit_plan(decision.plan)
                elif self._revise_plan is None:
                    raise DecisionAdmissionError("decision.revision_unavailable")
                else:
                    self._revise_plan(decision.revision, decision.plan)
            except Exception as exc:
                self._consume_repair()
                raise DecisionAdmissionError(_actionable_plan_refused(exc)) from exc
        self.decision = decision
        if self._persist_decision is not None:
            self._persist_decision(decision)

    def restore(self, decision: ExecutionDecision) -> None:
        """Reload a persisted accepted decision without admitting a plan twice."""
        parsed = ExecutionDecision.model_validate(decision.model_dump(mode="json"))
        self.decision = parsed

    def _consume_repair(self) -> None:
        if self._repairs_remaining == 0:
            raise DecisionAdmissionError("decision.repair_exhausted")
        self._repairs_remaining -= 1


def execution_decision_tool(gate: ExecutionDecisionGate) -> BaseTool:
    @tool("execution_decision")
    def record_execution_decision(
        mode: str,
        objective: str,
        reason: str,
        constraints: tuple[str, ...] = (),
        plan: dict[str, Any] | None = None,
        revision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Choose direct, discovery, or planned execution before operational work."""

        try:
            decision = gate.admit(
                {
                    "mode": mode,
                    "objective": objective,
                    "reason": reason,
                    "constraints": constraints,
                    "plan": plan,
                    "revision": revision,
                }
            )
        except DecisionAdmissionError as exc:
            return {
                "status": "rejected",
                "code": str(exc),
                "repairs_remaining": gate.repairs_remaining,
            }
        return {
            "status": "accepted",
            "mode": decision.mode.value,
            "repairs_remaining": gate.repairs_remaining,
        }

    return record_execution_decision


class ExecutionDecisionMiddleware(AgentMiddleware[Any, Any, Any]):
    """Reject tools until the lead has recorded a valid execution decision."""

    def __init__(self, gate: ExecutionDecisionGate) -> None:
        self._gate = gate

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        response = handler(request)
        self._gate.prepare_response(response)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        response = await handler(request)
        self._gate.prepare_response(response)
        return response

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        return self._guard(request, handler)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Any]],
    ) -> ToolMessage | Any:
        name = request.tool_call["name"]
        call_id = request.tool_call["id"]
        rejection = self._gate.rejection_code(call_id)
        if rejection is not None:
            return _decision_rejected(request, rejection)
        if name == "execution_decision" and self._gate.is_prepared_decision(call_id):
            return _decision_accepted(request, self._gate)
        if self._gate.allows(name, call_id) or name == "execution_decision":
            return await handler(request)
        if self._gate.is_exhausted:
            return _decision_exhausted(request)
        return _decision_required(request)

    def _guard(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        name = request.tool_call["name"]
        call_id = request.tool_call["id"]
        rejection = self._gate.rejection_code(call_id)
        if rejection is not None:
            return _decision_rejected(request, rejection)
        if name == "execution_decision" and self._gate.is_prepared_decision(call_id):
            return _decision_accepted(request, self._gate)
        if self._gate.allows(name, call_id) or name == "execution_decision":
            return handler(request)
        if self._gate.is_exhausted:
            return _decision_exhausted(request)
        return _decision_required(request)


def _normalize_decision_args(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize model-supplied decision args before validation."""
    normalized = dict(value)
    constraints = normalized.get("constraints", ())
    if isinstance(constraints, str):
        parts = [part.strip() for part in re.split(r"[;\n]+", constraints)]
        normalized["constraints"] = tuple(part for part in parts if part)
    elif isinstance(constraints, list):
        normalized["constraints"] = tuple(
            str(item).strip() for item in constraints if str(item).strip()
        )
    plan = normalized.get("plan")
    if isinstance(plan, str):
        stripped = plan.strip()
        if stripped:
            try:
                normalized["plan"] = json.loads(stripped)
            except json.JSONDecodeError:
                pass
        else:
            normalized.pop("plan", None)
    plan = normalized.get("plan")
    if isinstance(plan, dict) and isinstance(plan.get("plan"), dict):
        # Some tool-capable models wrap the complete execution-decision object
        # inside the plan argument. Preserve the explicit top-level values and
        # validate the actual nested ExecutionPlan object.
        for name in ("mode", "objective", "reason", "constraints", "revision"):
            if name not in plan:
                continue
            if name in normalized and _comparable_decision_field(
                name, normalized[name]
            ) != _comparable_decision_field(name, plan[name]):
                raise DecisionAdmissionError("decision.payload_conflict")
            if name not in normalized:
                normalized[name] = plan[name]
        normalized["plan"] = plan["plan"]
    revision = normalized.get("revision")
    if isinstance(revision, str):
        stripped = revision.strip()
        if stripped:
            try:
                normalized["revision"] = json.loads(stripped)
            except json.JSONDecodeError:
                pass
        else:
            normalized.pop("revision", None)
    return normalized


def _comparable_decision_field(name: str, value: Any) -> Any:
    if name == "constraints":
        if isinstance(value, str):
            return tuple(part.strip() for part in re.split(r"[;\n]+", value) if part.strip())
        if isinstance(value, list):
            return tuple(str(item).strip() for item in value if str(item).strip())
    if name == "revision" and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value.strip()
    if isinstance(value, str):
        value = value.strip()
        if name == "mode":
            return value.casefold()
    return value


def _actionable_plan_invalid(exc: ValidationError) -> str:
    """Render missing/unexpected fields plus a minimal valid skeleton."""

    missing: list[str] = []
    unexpected: list[str] = []
    for error in exc.errors():
        kind = str(error.get("type", ""))
        loc = ".".join(str(part) for part in error.get("loc", ()))
        if kind == "missing":
            missing.append(loc or "<unknown>")
        elif kind in {"extra_forbidden", "unexpected_keyword_argument"}:
            unexpected.append(loc or "<unknown>")
    details: list[str] = []
    if missing:
        details.append(f"missing={sorted(set(missing))}")
    if unexpected:
        details.append(f"unexpected={sorted(set(unexpected))}")
    detail = f" ({'; '.join(details)})" if details else ""
    return (
        "decision.plan_invalid: resend mode=planned with objective, reason, "
        "and a validated plan; minimal plan skeleton="
        "{'schema_version': 1, 'policy_version': 'adaptive-v1', 'revision': 1, "
        "'nodes': [{'local_id': '<id>', 'kind': 'checkpoint', "
        "'objective': '<what>', 'effect_scope': 'read'}]}"
        f"{detail}"
    )


def _actionable_plan_refused(exc: Exception) -> str:
    """Render why the plan store refused a validated plan."""

    skeleton = (
        "{'schema_version': 1, 'policy_version': 'adaptive-v1', 'revision': 1, "
        "'nodes': [{'local_id': '<id>', 'kind': 'checkpoint', "
        "'objective': '<what>', 'effect_scope': 'read'}]}"
    )
    if isinstance(exc, DecisionAdmissionError):
        detail = str(exc)
        if detail and detail != "decision.plan_refused":
            return f"decision.plan_refused: {detail}"
    elif isinstance(exc, ValidationError):
        return f"decision.plan_refused: {_actionable_plan_invalid(exc)}"
    detail = f"{type(exc).__name__}: {exc}".strip()
    if not detail or detail.endswith(":"):
        detail = f"{type(exc).__name__} (no detail)"
    return (
        "decision.plan_refused: plan store rejected the validated plan "
        f"({detail}); resend mode=planned with objective, reason, "
        f"and a validated plan; minimal plan skeleton={skeleton}"
    )


def _decision_required(request: ToolCallRequest) -> ToolMessage:
    return ToolMessage(
        content=(
            "execution.decision_required: call execution_decision with "
            "mode='direct', objective='<goal>', reason='<why>' before any "
            "other tool"
        ),
        tool_call_id=request.tool_call["id"],
        status="error",
    )


def _decision_exhausted(request: ToolCallRequest) -> ToolMessage:
    return ToolMessage(
        content=(
            "execution.decision_exhausted: decision repairs exhausted with no "
            "admitted decision; failing loudly instead of silent completion"
        ),
        tool_call_id=request.tool_call["id"],
        status="error",
    )


def _decision_rejected(request: ToolCallRequest, code: str) -> ToolMessage:
    return ToolMessage(content=code, tool_call_id=request.tool_call["id"], status="error")


def _decision_accepted(
    request: ToolCallRequest, gate: ExecutionDecisionGate
) -> ToolMessage:
    assert gate.decision is not None
    return ToolMessage(
        content=str(
            {
                "status": "accepted",
                "mode": gate.decision.mode.value,
                "repairs_remaining": gate.repairs_remaining,
            }
        ),
        tool_call_id=request.tool_call["id"],
    )
