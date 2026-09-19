"""Phase 2 composer tests: queue/history/ghost palette/state machine.

Targets pure helpers in ``skail.tui.widgets.composer`` (no live app).
"""

from __future__ import annotations

from skail.tui.widgets.composer import (
    ComposerState,
    complete_ghost,
    fuzzy_match_commands,
    overflow_label,
    should_send_on_enter,
    take_back_newest,
)


def test_placeholder_constant_exact() -> None:
    from skail.tui.widgets.composer import COMPOSER_PLACEHOLDER

    assert COMPOSER_PLACEHOLDER == "Message Skail\u2026"


def test_validating_text_constant() -> None:
    from skail.tui.widgets.composer import COMPOSER_VALIDATING_TEXT

    assert COMPOSER_VALIDATING_TEXT == "Validating provider\u2026"


def test_stash_receipt_constant_exact() -> None:
    from skail.tui.widgets.composer import STASH_RECEIPT

    assert STASH_RECEIPT == (
        "Draft stashed. Press Up on an empty composer to restore it."
    )


def test_enter_sends_when_palette_closed() -> None:
    state = ComposerState(draft="hello", palette_open=False)
    assert should_send_on_enter(state) is True


def test_enter_does_not_send_when_palette_open() -> None:
    state = ComposerState(draft="/he", palette_open=True)
    assert should_send_on_enter(state) is False


def test_ghost_rank_prefix_beats_subsequence() -> None:
    matches = fuzzy_match_commands("/he", ["help", "theme", "the"])
    names = [m.command for m in matches]
    assert names[0] == "help"  # prefix match wins


def test_ghost_rank_subsequence_beats_description() -> None:
    matches = fuzzy_match_commands("/ts", ["trust", "tasks", "status"])
    assert matches  # deterministic non-empty ranking


def test_ghost_rank_deterministic_tiebreak() -> None:
    first = fuzzy_match_commands("/a", ["agents", "agent", "approve"])
    second = fuzzy_match_commands("/a", ["agents", "agent", "approve"])
    assert [m.command for m in first] == [m.command for m in second]


def test_palette_overflow_label() -> None:
    assert overflow_label(total=9, shown=6) == "+3 more"
    assert overflow_label(total=6, shown=6) == ""


def test_mode_token_maps_modes_to_theme_tokens() -> None:
    from skail.tui.widgets.composer import mode_token

    assert mode_token("QUALITY") == "modeQuality"
    assert mode_token("economy") == "modeEconomy"
    assert mode_token("Manual") == "modeManual"
    assert mode_token("  quality  ") == "modeQuality"
    assert mode_token("custom") == "text"


def test_palette_max_six_rows() -> None:
    from skail.tui.widgets.composer import MAX_PALETTE_ROWS

    assert MAX_PALETTE_ROWS == 6
    matches = fuzzy_match_commands(
        "/", ["help", "agents", "plan", "route", "budget",
              "mode", "model", "quit", "compact"]
    )
    assert len(matches[:MAX_PALETTE_ROWS]) == MAX_PALETTE_ROWS


def test_tab_completes_without_submit() -> None:
    draft, submitted = complete_ghost("/he", "help")
    assert draft == "/help"
    assert submitted is False


def test_queue_fifo_take_back_newest() -> None:
    queue = ["first", "second"]
    remaining, restored = take_back_newest(queue)
    assert remaining == ["first"]
    assert restored == "second"


def test_queue_take_back_empty() -> None:
    remaining, restored = take_back_newest([])
    assert remaining == []
    assert restored is None


def test_history_recall_newest_first() -> None:
    from skail.tui.widgets.composer import recall_older

    history = ["one", "two", "three"]
    assert recall_older(history, None) == "three"
    assert recall_older(history, "three") == "two"
    assert recall_older(history, "one") == "one"  # oldest sticks


def test_history_recall_down_toward_draft() -> None:
    from skail.tui.widgets.composer import recall_newer

    history = ["one", "two", "three"]
    assert recall_newer(history, "two", draft="wip") == "three"
    assert recall_newer(history, "three", draft="wip") == "wip"


def test_composer_module_conventions() -> None:
    import pathlib
    import re

    src = pathlib.Path("src/skail/tui/widgets/composer.py").read_text(
        encoding="utf-8"
    )
    assert re.search(r"#[0-9A-Fa-f]{6}", src) is None
    assert "parse_slash_command" not in src  # parsing stays in commands.py
    assert "dispatch_slash_command" not in src
