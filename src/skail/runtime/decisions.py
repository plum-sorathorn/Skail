from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelResponse, ToolCallRequest
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
    ) -> None:
        self._admit_plan = admit_plan
        self._revise_plan = revise_plan
        self._persist_decision = persist_decision
        self.decision: ExecutionDecision | None = None
        if restored_decision is not None:
            self.decision = restored_decision
        self._repairs_remaining = 1
        self._prepared_decision_ids: set[str] = set()
        self._rejected_tool_codes: dict[str, str] = {}

    @property
    def repairs_remaining(self) -> int:
        return self._repairs_remaining

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

        for message in response.result:
            if not isinstance(message, AIMessage):
                continue
            for call in message.tool_calls:
                name = call.get("name")
                call_id = call.get("id")
                if not isinstance(name, str) or not isinstance(call_id, str):
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
        self._record(candidate)
        return candidate

    def _parse(self, value: dict[str, Any]) -> ExecutionDecision:
        try:
            return ExecutionDecision.model_validate(value)
        except ValidationError as exc:
            message = str(exc)
            if "revision_mismatch" in message or "revision_required" in message:
                raise DecisionAdmissionError("decision.revision_conflict") from exc
            self._consume_repair()
            raise DecisionAdmissionError("decision.plan_invalid") from exc

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
                raise DecisionAdmissionError("decision.plan_refused") from exc
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
        return _decision_required(request)


def _decision_required(request: ToolCallRequest) -> ToolMessage:
    return ToolMessage(
        content="execution.decision_required: record execution_decision before operational tools",
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
