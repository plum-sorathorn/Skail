"""Phase 3a command registry + projection replay tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from skail.tui.commands import (
    COMMAND_REGISTRY,
    THEME_USAGE,
    dispatch_slash_command,
    parse_slash_command,
    resume_receipt,
    search_commands,
)
from skail.tui.projection import (
    BUDGET_UNAVAILABLE_COPY,
    TranscriptItem,
    TuiProjection,
    budget_meter,
    budget_view_model,
    queue_followup,
    take_back_newest,
)


def test_parse_existing_intact() -> None:
    assert parse_slash_command("not a command") == ("", [])
    assert parse_slash_command("/help") == ("help", [])
    assert parse_slash_command("/mode economy") == ("mode", ["economy"])
    assert parse_slash_command("/steer task-1 please fix formatting") == (
        "steer",
        ["task-1", "please", "fix", "formatting"],
    )
    assert parse_slash_command("/budget") == ("budget", [])
    assert parse_slash_command("/quit") == ("quit", [])


def test_parse_new_commands() -> None:
    assert parse_slash_command("/theme dark") == ("theme", ["dark"])
    assert parse_slash_command("/model foo") == ("model", ["foo"])
    assert parse_slash_command("/missions") == ("missions", [])
    assert parse_slash_command("/children") == ("children", [])
    assert parse_slash_command("/agent task-1") == ("agent", ["task-1"])
    assert parse_slash_command("/tasks") == ("tasks", [])
    assert parse_slash_command("/steer task-1 update") == (
        "steer",
        ["task-1", "update"],
    )


def test_theme_usage_exact() -> None:
    assert THEME_USAGE == "Usage: /theme [dark|light|system]"
    proj = TuiProjection()
    res = dispatch_slash_command("/theme bogus", proj)
    assert res.action == "error"
    assert res.output_message == "Usage: /theme [dark|light|system]"


def test_theme_valid_and_picker() -> None:
    proj = TuiProjection()
    res = dispatch_slash_command("/theme dark", proj)
    assert res.output_message == "Theme changed to Dark."
    assert proj.receipts[-1] == "Theme changed to Dark."
    picker = dispatch_slash_command("/theme", proj)
    assert picker.action == "theme_picker"
    assert picker.payload.get("picker") == "theme"


def test_model_picker_and_receipt() -> None:
    proj = TuiProjection()
    picker = dispatch_slash_command("/model", proj)
    assert picker.action == "model_picker"
    res = dispatch_slash_command("/model fast-1", proj)
    assert res.output_message == (
        "Model set to fast-1 for future attempts. Active attempts are unchanged."
    )
    assert proj.model_for_future() == "fast-1"
    proj.note_attempt_model("attempt-1", "old-model")
    res2 = dispatch_slash_command("/model new-model", proj)
    assert res2.output_message is not None and "new-model" in res2.output_message
    assert proj.model_for_attempt("attempt-1") == "old-model"


def test_missions_and_alias() -> None:
    proj = TuiProjection()
    res = dispatch_slash_command("/missions", proj)
    assert res.action == "missions"
    alias = dispatch_slash_command("/children", proj)
    assert alias.action == "missions"
    assert alias.command == "missions"


def test_resume_receipt_contains_skail_r() -> None:
    assert "skail -r " in resume_receipt("01JABC")
    assert resume_receipt("01JABC") == (
        "Session resumed: 01JABC\nResume later with:\nskail -r 01JABC"
    )
def test_registry_has_required_commands_and_drives_help() -> None:
    assert len(COMMAND_REGISTRY) == 18
    for entry in COMMAND_REGISTRY:
        assert set(entry) >= {
            "command",
            "aliases",
            "synopsis",
            "description",
            "keywords",
            "args_required",
            "category",
        }
    res = dispatch_slash_command("/help", TuiProjection())
    assert res.output_message is not None
    for entry in COMMAND_REGISTRY:
        assert entry["command"] in res.output_message
    assert "/missions" in res.output_message
    missions = next(e for e in COMMAND_REGISTRY if e["command"] == "/missions")
    assert "/children" in missions["aliases"]


def test_search_ranking_deterministic() -> None:
    first = [e["command"] for e in search_commands("the")]
    second = [e["command"] for e in search_commands("the")]
    assert first == second
    assert first[0] == "/theme"
    mods = [e["command"] for e in search_commands("model")]
    assert mods[0] == "/model"
    assert search_commands("") == sorted(
        search_commands(""), key=lambda e: str(e["command"])
    )


def _fake_event(event_id: str, task_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=event_id,
        task_id=task_id,
        type="route.selected",
        payload=SimpleNamespace(action="selected", assignment_id="a1"),
    )


def test_projection_replay_queue_slots_approval_plan_ids() -> None:
    proj = TuiProjection()
    proj.queue_followup("one")
    proj.queue_followup("two")
    assert proj.queue == ["one", "two"]
    assert queue_followup(["a"], "b") == ["a", "b"]
    assert take_back_newest(["a", "b"]) == (["a"], "b")
    assert proj.take_back_newest() == "two"
    assert proj.queue == ["one"]

    s1 = proj.child_slot_for("c1")
    assert proj.child_slot_for("c1") == s1
    proj.child_slot_for("c2")
    proj.child_slot_for("c3")
    assert len(proj.child_slots) <= 3
    assert set(proj.child_slots.values()) <= {1, 2, 3}

    proj.note_plan("proposed")
    assert proj.plan_state == "proposed"
    proj.mark_approval("ap1", "approved")
    assert proj.approvals["ap1"] == "approved"

    proj.note_child("k1", "task one", "m1")
    proj.mark_child_status("k1", "complete")
    view = proj.children_view()
    assert view[0].id == "k1"
    assert view[0].status == "complete"

    assert proj._add_transcript_item(
        TranscriptItem(id="tx1", role="user", title="t", content="c")
    )
    assert not proj._add_transcript_item(
        TranscriptItem(id="tx1", role="user", title="t", content="c")
    )
    before = len(proj.transcript_items)
    proj.apply_event(_fake_event("ev1"))  # type: ignore[arg-type]
    proj.apply_event(_fake_event("ev1"))  # type: ignore[arg-type]
    assert len(proj.transcript_items) == before + 1
    assert len({t.id for t in proj.transcript_items}) == len(proj.transcript_items)


def test_projection_serialized_state_has_no_keys() -> None:
    proj = TuiProjection()
    proj.note_receipt("hello")
    proj.note_child("k1", "t", "m")
    blob = json.dumps(proj.to_dict())
    for secret in ("sk-ant-", "sk-", "api_key", "API_KEY", "secret-key-material"):
        assert secret not in blob
    assert BUDGET_UNAVAILABLE_COPY == (
        "Budget details are unavailable for this provider."
    )


def test_budget_thresholds_and_meter() -> None:
    assert budget_view_model(0.74, 1.0).state == "normal"
    assert budget_view_model(0.75, 1.0).state == "near"
    assert budget_view_model(0.90, 1.0).state == "critical"
    assert budget_view_model(1.0, 1.0).state == "exceeded"
    meter = budget_meter(0.5, 1.0)
    assert len(meter) == 8
    assert meter == "■■■■····"
    assert budget_meter(0.0) == "········"
    assert budget_meter(1.0) == "■■■■■■■■"
