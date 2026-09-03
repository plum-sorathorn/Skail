from __future__ import annotations

from rudder.runtime.interrupts import Question, QuestionStore


def ask_user(
    store: QuestionStore,
    *,
    graph_id: str,
    task_id: str | None,
    prompt: str,
    reason: str,
    blocking_scope: str,
    idempotency_key: str,
    options: tuple[str, ...] = (),
) -> Question:
    return store.ask(
        graph_id=graph_id,
        task_id=task_id,
        prompt=prompt,
        options=options,
        reason=reason,
        blocking_scope=blocking_scope,
        idempotency_key=idempotency_key,
    )
