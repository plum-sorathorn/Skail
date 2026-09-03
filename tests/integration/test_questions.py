from __future__ import annotations

from pathlib import Path

import pytest
from fakes.models import ScriptedChatModel, tool_call_message
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from rudder.runtime.interrupts import QuestionStore, StaleAnswerError
from rudder.tools.assembly import build_default_agent


def test_question_resume_targets_only_waiting_graph_and_survives_reload(tmp_path: Path) -> None:
    path = tmp_path / "questions.sqlite3"
    store = QuestionStore(path)
    question = store.ask(
        graph_id="child-graph",
        task_id="task-1",
        prompt="Choose",
        options=("a", "b"),
        reason="missing input",
        blocking_scope="task",
        idempotency_key="q-key",
    )
    reloaded = QuestionStore(path)
    assert reloaded.pending("child-graph") == (question,)
    assert reloaded.pending("lead-graph") == ()
    answered = reloaded.answer(question.question_id, "a", graph_id="child-graph")
    assert answered.answer == "a"
    with pytest.raises(StaleAnswerError):
        reloaded.answer(question.question_id, "b", graph_id="child-graph")


def test_question_cancel_is_explicit(tmp_path: Path) -> None:
    store = QuestionStore(tmp_path / "q.sqlite3")
    question = store.ask(
        graph_id="g",
        task_id=None,
        prompt="Proceed?",
        reason="blocked",
        blocking_scope="run",
        idempotency_key="k",
    )
    assert store.cancel(question.question_id, graph_id="g").status == "cancelled"


def test_ask_user_interrupt_resumes_only_its_durable_question(tmp_path: Path) -> None:
    store = QuestionStore(tmp_path / "questions.sqlite3")
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "ask_user",
                {"prompt": "Choose", "options": ["a", "b"], "reason": "missing"},
                call_id="question-1",
            ),
            AIMessage(content="done"),
        ]
    )
    agent = build_default_agent(
        model,
        workspace=tmp_path,
        profile="lead",
        question_store=store,
        graph_id="lead-graph",
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "thread-1"}}
    interrupted = agent.invoke(
        {"messages": [{"role": "user", "content": "Need input"}]}, config=config
    )
    assert interrupted["__interrupt__"]
    question = store.pending("lead-graph")[0]
    resumed = agent.invoke(Command(resume="a"), config=config)
    assert resumed["messages"][-1].content == "done"
    assert store.pending("lead-graph") == ()
    with pytest.raises(StaleAnswerError):
        store.answer(question.question_id, "b", graph_id="lead-graph")
