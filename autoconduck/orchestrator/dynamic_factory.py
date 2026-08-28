"""Dynamic DAG Factory.

Compiles transient StateGraph DAGs on the fly with parallel subtask fan-out,
conditional LanceDB RAG node injection, terminal Synthesizer node on frontier_reasoning,
and SqliteSaver checkpointer keyed by session_id/thread_id.
"""
from __future__ import annotations

import asyncio
import logging
import operator
from typing import Annotated, Any, Callable, Sequence
from pydantic import BaseModel, Field, ConfigDict

from autoconduck.routing.slm_planner import ExecutionPlan, SubTaskSpec

logger = logging.getLogger(__name__)


def _merge_dict(left: dict[str, str] | None, right: dict[str, str] | None) -> dict[str, str]:
    """Merge dictionary updates across concurrent graph branches."""
    merged = dict(left or {})
    if right:
        merged.update(right)
    return merged


def _latest_val(left: Any, right: Any) -> Any:
    """Take latest non-null value across graph transitions."""
    return right if right is not None else left


class DynamicState(BaseModel):
    """Dynamic execution state container for DAG pipelines."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: Annotated[list[dict[str, Any]], _latest_val] = Field(default_factory=list)
    session_id: str = "default"
    thread_id: str = "default"
    plan: Annotated[ExecutionPlan | None, _latest_val] = None
    tools: Annotated[list[dict[str, Any]], _latest_val] = Field(default_factory=list)
    client_type: Annotated[str | None, _latest_val] = None
    user_agent: Annotated[str, _latest_val] = ""
    is_nested: Annotated[bool, _latest_val] = False
    verified_context: Annotated[list[str], operator.add] = Field(default_factory=list)
    subtask_outputs: Annotated[dict[str, str], _merge_dict] = Field(default_factory=dict)
    subtask_errors: Annotated[dict[str, str], _merge_dict] = Field(default_factory=dict)
    active_node: Annotated[str, _latest_val] = "init"
    synthesizer_output: Annotated[str | None, _latest_val] = None
    final_result: Annotated[Any, _latest_val] = None
    is_fallback: Annotated[bool, _latest_val] = False


async def _rag_node_handler(state: DynamicState | dict[str, Any], on_progress: Any = None) -> dict[str, Any]:
    """Extract context snippets from LanceDB vector store."""
    plan = getattr(state, "plan", None) if not isinstance(state, dict) else state.get("plan")
    new_snippets: list[str] = []

    if plan and getattr(plan, "needs_rag", False):
        queries = getattr(plan, "rag_queries", []) or ["codebase dependencies"]
        if on_progress:
            try:
                on_progress({"node": "rag", "state": "running", "step_detail": f"Querying vector store ({len(queries)} queries)"})
            except Exception:
                pass
        try:
            from autoconduck.knowledge.vector_store import KnowledgeVectorStore
            store = KnowledgeVectorStore()
            for q in queries:
                snippets = store.get_context_snippets(q, max_tokens=125)
                new_snippets.extend(snippets)
            if on_progress:
                try:
                    on_progress({"node": "rag", "state": "completed", "step_detail": f"Retrieved {len(new_snippets)} context snippets"})
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("RAG node extraction warning: %s", exc)
            if on_progress:
                try:
                    on_progress({"node": "rag", "state": "failed", "step_detail": f"RAG extraction warning: {exc}"})
                except Exception:
                    pass

    return {
        "verified_context": new_snippets,
        "active_node": "rag",
    }


def _make_subtask_handler(task: SubTaskSpec, on_progress: Any = None) -> Callable[[Any], Any]:
    """Factory for bounded planning-time reconnaissance nodes.

    The durable implementation phase is harness-owned; this legacy DAG only
    gathers optional read-only context for initial plan construction.
    """
    async def subtask_handler(state: DynamicState | dict[str, Any]) -> dict[str, Any]:
        if on_progress:
            try:
                on_progress({"node": task.id, "state": "running", "step_detail": f"Subagent [{task.role}]: {task.goal}"})
            except Exception:
                pass
        logger.info("Subagent [%s] (role=%s) starting: %s", task.id, task.role, task.goal)
        try:
            from autoconduck.orchestrator.subagents import run_subagent
            from autoconduck.orchestrator.planner import SubTask, OutputContract

            subtask_obj = SubTask(
                id=task.id,
                goal=task.goal,
                scope=task.scope,
                constraints=task.constraints,
                depends_on=task.depends_on,
                verified_context=getattr(task, "verified_context", []) or [],
                read_budget=getattr(task, "read_budget", 5),
                role=task.role,
                output_contract=OutputContract(
                    description=getattr(task.output_contract, "description", "") if getattr(task, "output_contract", None) else "",
                    verify=getattr(task.output_contract, "verify", []) if getattr(task, "output_contract", None) else [],
                ),
            )
            current_outputs = getattr(state, "subtask_outputs", {}) if not isinstance(state, dict) else state.get("subtask_outputs", {})
            upstream_text = "\n".join(
                f"[{dep}]: {current_outputs[dep]}"
                for dep in task.depends_on
                if dep in current_outputs
            )
            plan = getattr(state, "plan", None) if not isinstance(state, dict) else state.get("plan")
            plan_breadth = len(plan.subtasks) if plan and hasattr(plan, "subtasks") and plan.subtasks else 1

            harness_tools = getattr(state, "tools", []) if not isinstance(state, dict) else state.get("tools", [])
            output = await run_subagent(
                subtask_obj,
                upstream_summaries=upstream_text,
                plan_breadth=plan_breadth,
                tools=harness_tools,
            )
            is_error = not output or output.startswith("__SUBAGENT_ERROR__")

            if is_error:
                error_msg = output if output else f"__SUBAGENT_ERROR__[{task.id}]: Empty response"
                if on_progress:
                    try:
                        on_progress({
                            "node": task.id,
                            "state": "failed",
                            "step_detail": f"Subagent [{task.id}] failed: {error_msg.replace('__SUBAGENT_ERROR__', '')}",
                        })
                    except Exception:
                        pass
                logger.warning("Subagent [%s] failed: %s", task.id, error_msg)
                return {
                    "subtask_errors": {task.id: error_msg},
                    "active_node": task.id,
                }

            if on_progress:
                try:
                    on_progress({
                        "node": task.id,
                        "state": "completed",
                        "step_detail": f"Subagent [{task.id}] ({task.role}) done: {task.goal}",
                    })
                except Exception:
                    pass
            logger.info("Subagent [%s] completed", task.id)

            return {
                "subtask_outputs": {task.id: output},
                "active_node": task.id,
            }
        except Exception as exc:
            if on_progress:
                try:
                    on_progress({"node": task.id, "state": "failed", "step_detail": f"Subagent [{task.id}] error: {exc}"})
                except Exception:
                    pass
            logger.warning("Subagent [%s] failed: %s", task.id, exc)
            return {
                "subtask_errors": {task.id: f"Failed to execute subtask [{task.id}]: {exc}"},
                "active_node": task.id,
            }

    return subtask_handler


async def _synthesizer_node_handler(state: DynamicState | dict[str, Any], on_progress: Any = None) -> dict[str, Any]:
    """Terminal node aggregating subtask outputs and producing actionable execution handoff."""
    outputs = getattr(state, "subtask_outputs", {}) if not isinstance(state, dict) else state.get("subtask_outputs", {})
    errors = getattr(state, "subtask_errors", {}) if not isinstance(state, dict) else state.get("subtask_errors", {})
    verified = getattr(state, "verified_context", []) if not isinstance(state, dict) else state.get("verified_context", [])
    plan = getattr(state, "plan", None) if not isinstance(state, dict) else state.get("plan")
    client_type = getattr(state, "client_type", None) if not isinstance(state, dict) else state.get("client_type")
    user_agent = getattr(state, "user_agent", "") if not isinstance(state, dict) else state.get("user_agent", "")
    is_nested = getattr(state, "is_nested", False) if not isinstance(state, dict) else state.get("is_nested", False)

    if on_progress:
        try:
            on_progress({"node": "synthesizer", "state": "running", "step_detail": f"Synthesizing handoff across {len(outputs)} subagent outputs"})
        except Exception:
            pass

    from autoconduck.orchestrator.handoff import format_execution_handoff
    compacted = "\n".join(f"• {c}" for c in verified) if verified else ""
    handoff = format_execution_handoff(
        plan=plan,
        subagent_outputs=outputs,
        compacted=compacted,
        user_agent=user_agent or "",
        client_type=client_type,
        is_nested=is_nested,
    )
    result_text = str(handoff)
    final_dict: dict[str, Any] = {
        "content": result_text,
        "subtask_outputs": outputs,
        "subtask_errors": errors,
    }
    if getattr(handoff, "tool_calls", None):
        final_dict["tool_calls"] = handoff.tool_calls

    if on_progress:
        try:
            from autoconduck.orchestrator.handoff import render_plan_summary_for_user
            plan_summary = render_plan_summary_for_user(plan, outputs)
            on_progress({"node": "synthesized_plan", "state": "completed", "step_detail": plan_summary})
            on_progress({"node": "synthesizer", "state": "completed", "step_detail": "Execution plan & handoff ready"})
        except Exception:
            pass
    logger.info("DAG Synthesizer finished: plan synthesized")

    return {
        "synthesizer_output": result_text,
        "final_result": final_dict,
        "active_node": "synthesizer",
    }


class DynamicGraphRunner:
    """Runnable wrapper for execution graph using native asyncio."""

    def __init__(self, plan: ExecutionPlan | None = None, on_progress: Any = None) -> None:
        self.plan = plan
        self.on_progress = on_progress

    def invoke(self, input_state: Any, config: dict[str, Any] | None = None) -> Any:
        return asyncio.run(self.ainvoke(input_state, config))

    async def ainvoke(self, input_state: Any, config: dict[str, Any] | None = None) -> Any:
        state = input_state if isinstance(input_state, DynamicState) else DynamicState(**(input_state if isinstance(input_state, dict) else input_state.model_dump()))

        # 1. RAG Node
        if self.plan and self.plan.needs_rag:
            rag_res = await _rag_node_handler(state, self.on_progress)
            state.verified_context.extend(rag_res.get("verified_context", []))

        # 2. Subtask Nodes
        if self.plan and self.plan.subtasks:
            task_coros = {}
            
            async def run_task_wrapper(task: SubTaskSpec) -> Any:
                # Wait for dependencies
                deps = [d for d in task.depends_on if d in task_coros]
                if deps:
                    await asyncio.gather(*(task_coros[d] for d in deps), return_exceptions=True)
                
                handler = _make_subtask_handler(task, self.on_progress)
                res = await handler(state)
                
                if isinstance(res, dict):
                    if "subtask_outputs" in res:
                        state.subtask_outputs.update(res["subtask_outputs"])
                    if "subtask_errors" in res:
                        state.subtask_errors.update(res["subtask_errors"])
                return res

            # Pre-create all tasks to allow dependency resolution
            for task in self.plan.subtasks:
                task_coros[task.id] = asyncio.create_task(run_task_wrapper(task))
                
            await asyncio.gather(*task_coros.values(), return_exceptions=True)

        # 3. Synthesizer Terminal Node
        synth_res = await _synthesizer_node_handler(state, self.on_progress)
        state.synthesizer_output = synth_res.get("synthesizer_output")
        state.final_result = synth_res.get("final_result")

        return state

    async def astream(self, input_state: Any, config: dict[str, Any] | None = None) -> Any:
        # Compatibility for astream if needed, though run() just uses ainvoke
        yield await self.ainvoke(input_state, config)


class DummyRunner:
    def __init__(self, plan: ExecutionPlan | None = None):
        self.plan = plan

    def invoke(self, input_state: Any, config: dict[str, Any] | None = None) -> Any:
        return input_state

    async def ainvoke(self, input_state: Any, config: dict[str, Any] | None = None) -> Any:
        return input_state

    async def astream(self, input_state: Any, config: dict[str, Any] | None = None) -> Any:
        yield input_state


def build_dynamic_graph(plan: ExecutionPlan, checkpointer: Any = None, on_progress: Any = None) -> Any:
    """Return a DynamicGraphRunner for the given ExecutionPlan without external DAG overhead."""
    
    # Detect cycles
    if plan and plan.subtasks:
        task_ids = {t.id for t in plan.subtasks}
        adj = {t.id: [d for d in t.depends_on if d in task_ids] for t in plan.subtasks}
        
        visited = set()
        path = set()
        has_cycle = False
        
        def dfs(node: str) -> None:
            nonlocal has_cycle
            if node in path:
                has_cycle = True
                return
            if node in visited:
                return
            path.add(node)
            for neighbor in adj.get(node, []):
                dfs(neighbor)
            path.remove(node)
            visited.add(node)
            
        for t in plan.subtasks:
            if t.id not in visited:
                dfs(t.id)
                
        if has_cycle:
            return DummyRunner(plan=plan)
            
    return DynamicGraphRunner(plan=plan, on_progress=on_progress)
