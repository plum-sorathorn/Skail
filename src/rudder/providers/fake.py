from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable


class DeterministicFakeChatModel(BaseChatModel):
    """Deterministic offline fake chat model supporting tool binding."""

    model_name: str = "fake:model"
    response_text: str = "Task completed successfully by Rudder fake provider."

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_content = ""
        for m in reversed(messages):
            if m.type == "human" and m.content:
                last_content = str(m.content)
                break
        content = self.response_text or f"Rudder executed: {last_content}"
        generation = ChatGeneration(message=AIMessage(content=content))
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return "rudder-deterministic-fake"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        return self
