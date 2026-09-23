from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.filesystem import FilesystemPermission
from deepagents.middleware.subagents import CompiledSubAgent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from skail.runtime.errors import FrameworkContractError


@dataclass(frozen=True)
class FrameworkEvent:
    namespace: tuple[str, ...]
    stream_mode: str
    payload: Any
    task_id: str | None = None


def is_graph_interrupt(error: BaseException) -> bool:
    """Identify LangGraph's expected control-flow exception behind this adapter."""

    return isinstance(error, GraphInterrupt)


def adapt_stream_part(part: Mapping[str, Any], *, task_id: str | None = None) -> FrameworkEvent:
    try:
        namespace = tuple(part["ns"])
        stream_mode = str(part["type"])
        payload = part["data"]
    except (KeyError, TypeError) as exc:
        raise FrameworkContractError(
            "runtime.framework_contract_changed",
            "LangGraph v2 stream part has an unexpected shape",
        ) from exc
    return FrameworkEvent(
        namespace=namespace,
        stream_mode=stream_mode,
        payload=payload,
        task_id=task_id,
    )


def build_lead_agent(
    model: BaseChatModel,
    *,
    tools: Sequence[BaseTool | Callable[..., Any] | dict[str, Any]] = (),
    subagents: Sequence[CompiledSubAgent] | None = None,
    middleware: Sequence[AgentMiddleware[Any, Any, Any]] = (),
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    backend: BackendProtocol | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    permissions: list[FilesystemPermission] | None = None,
    name: str = "skail-lead",
    system_prompt: str | None = None,
) -> Runnable[Any, Any]:
    """Build a DeepAgent while keeping its concrete type behind this adapter."""

    return create_deep_agent(
        model=model,
        tools=tools,
        subagents=subagents,
        middleware=middleware,
        checkpointer=checkpointer,
        interrupt_on=interrupt_on,
        backend=backend,
        skills=skills,
        memory=memory,
        permissions=permissions,
        name=name,
        system_prompt=system_prompt,
    )


async def stream_events(
    agent: Runnable[Any, Any],
    input_state: Mapping[str, Any],
    *,
    config: RunnableConfig | None = None,
    task_id: str | None = None,
) -> AsyncIterator[FrameworkEvent]:
    nested_task_ids: dict[str, str] = {}
    async for part in agent.astream(
        dict(input_state),
        config=config,
        stream_mode=["updates", "messages"],
        subgraphs=True,
        version="v2",
    ):
        if not isinstance(part, Mapping):
            raise FrameworkContractError(
                "runtime.framework_contract_changed",
                "LangGraph v2 stream yielded a non-mapping part",
            )
        event = adapt_stream_part(part)
        discovered = _find_task_id(event.payload)
        if event.namespace and discovered is not None:
            nested_task_ids[event.namespace[0]] = discovered
        resolved_task_id = (
            task_id
            if not event.namespace
            else nested_task_ids.get(event.namespace[0])
        )
        yield replace(event, task_id=resolved_task_id)


async def resume_agent(
    agent: Runnable[Any, Any],
    answer: Any,
    *,
    config: RunnableConfig,
) -> Any:
    return await agent.ainvoke(Command(resume=answer), config=config)


class ChildRunGate:
    """Deterministic hard cap used ahead of child graph execution."""

    def __init__(self, max_children: int = 3) -> None:
        if not 1 <= max_children <= 3:
            raise ValueError("max_children must be between 1 and 3")
        self._semaphore = asyncio.Semaphore(max_children)
        self._active = 0
        self.peak_active = 0
        self.completed: dict[str, Any] = {}
        self._completion_changed = asyncio.Event()
        self.child_first_start: float | None = None
        self.child_last_end: float | None = None
        self.child_total_seconds: float = 0.0

    @property
    def active(self) -> int:
        return self._active

    @property
    def child_wall_seconds(self) -> float:
        """Wall-clock span from first gate entry to last gate exit."""
        if self.child_first_start is None or self.child_last_end is None:
            return 0.0
        return self.child_last_end - self.child_first_start

    async def run[T](self, task_id: str, operation: Callable[[], Awaitable[T]]) -> T:
        queued_at = time.perf_counter()
        if self.child_first_start is None:
            self.child_first_start = queued_at
        async with self._semaphore:
            self._active += 1
            self.peak_active = max(self.peak_active, self._active)
            try:
                value = await operation()
                self.completed[task_id] = value
                self._completion_changed.set()
                return value
            finally:
                end = time.perf_counter()
                self.child_last_end = end
                self.child_total_seconds += end - queued_at
                self._active -= 1

    async def wait_for_completed(self, count: int) -> None:
        while len(self.completed) < count:
            self._completion_changed.clear()
            if len(self.completed) < count:
                await self._completion_changed.wait()


async def run_task_batch[T](
    operations: Mapping[str, Callable[[], Awaitable[T]]],
    *,
    gate: ChildRunGate,
) -> dict[str, T | BaseException]:
    task_ids = tuple(operations)
    tasks = [
        asyncio.create_task(gate.run(task_id, operations[task_id]), name=f"skail-child-{task_id}")
        for task_id in task_ids
    ]
    values = await asyncio.gather(*tasks, return_exceptions=True)
    return dict(zip(task_ids, values, strict=True))


def _find_task_id(payload: Any) -> str | None:
    pending = [payload]
    visited = 0
    while pending and visited < 256:
        value = pending.pop()
        visited += 1
        if isinstance(value, Mapping):
            task_id = value.get("skail_task_id")
            if isinstance(task_id, str) and task_id:
                return task_id
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    return None
