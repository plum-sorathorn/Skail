"""Capture reference screenshots of the current Skail TUI main chat page.

Boots SkailApp headless via Textual's ``run_test`` (same pattern as
``tests/integration/test_tui_shell.py``), injects representative traffic
through the seams the integration tests already use, then exports matching
120x40 PNG and SVG files for each maintained theme.

Usage: python scripts/dev_tui_screenshot.py --themes pistachio-night
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from textual.geometry import Size

from skail.domain.events import (
    BudgetPayload,
    EventEnvelope,
    PlanPayload,
    ToolPayload,
)
from skail.domain.ids import new_event_id, new_run_id, new_session_id
from skail.tui.app import SkailApp
from skail.tui.projection import (
    AgentRailItem,
    BudgetViewItem,
    TranscriptItem,
    TuiProjection,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "design" / "tui-themes"
THEME_NAMES = ("pistachio-night", "pistachio-paper", "mint-porcelain")

WIDE_SIZE = (120, 40)
NARROW_SIZE = (80, 40)

# Fixed plan ids so the rendered copy is stable across runs.
PLAN_ID = "00000000-0000-4000-8000-000000000001"
NODE_ID = "00000000-0000-4000-8000-000000000002"


def build_projection() -> TuiProjection:
    """Build a representative, populated main-chat projection.

    Only seams exercised by the existing integration tests are used:
    direct assignment of the public projection dataclasses
    (test_tui_panels.py) and apply_event envelopes before mount
    (test_tui_shell_early_events_before_mount).
    """
    proj = TuiProjection()
    proj.set_future_model("fake:smart-model")
    # Status strip renders "$X / $Y" when the footer knows the limit.
    proj.footer_data.budget_limit_usd = Decimal("15.00")

    # Agent rail: populated through the public projection seams. The rail
    # widget renders rows from children_view() (note_child / mark_child_status
    # -- the same path the live runtime drives), while agent_rail_items feeds
    # the footer's "Active Agents" count and the blocked-child lineage.
    proj.note_child("task-r1", task="Inspect routing failures", model="fake:smart-model")
    proj.note_child("task-r2", task="Patch assignment.py", model="fake:fast-model")
    proj.note_child("task-b1", task="Rerun budget suite", model="fake:fast-model")
    proj.mark_child_status("task-r2", "queued")
    proj.mark_child_status("task-b1", "blocked")
    proj.focus_agent("task-r1")
    proj.agent_rail_items = [
        AgentRailItem(
            task_id="task-r1",
            task_id_suffix="r1",
            parent_task_id=None,
            profile="researcher",
            model="fake:smart-model",
            status="running",
            elapsed_sec=3.4,
            cost_authoritative_usd=Decimal("0.02"),
            cost_estimated_usd=Decimal("0.05"),
        ),
        AgentRailItem(
            task_id="task-r2",
            task_id_suffix="r2",
            parent_task_id=None,
            profile="implementer",
            model="fake:fast-model",
            status="queued",
            elapsed_sec=0.0,
            cost_authoritative_usd=Decimal("0.00"),
            cost_estimated_usd=Decimal("0.04"),
        ),
        AgentRailItem(
            task_id="task-b1",
            task_id_suffix="b1",
            parent_task_id="task-r1",
            profile="implementer",
            model="fake:fast-model",
            status="blocked",
            elapsed_sec=5.0,
            cost_authoritative_usd=Decimal("0.01"),
            cost_estimated_usd=Decimal("0.03"),
        ),
    ]

    # Budget: hard limit comes from the projection; reservations/charges flow
    # through the same budget.* events the runtime emits.
    proj.budget_item = BudgetViewItem(hard_limit_usd=Decimal("15.00"))

    # Transcript: user prompt + lead response. Titles/roles match what
    # SkailApp itself appends (on_prompt_composer_prompt_submitted ->
    # role "user" title "User Prompt"; _apply_run_result -> role "lead"
    # title "Skail Response").
    proj.transcript_items.append(
        TranscriptItem(
            id="tx-user-001",
            role="user",
            title="User Prompt",
            content=(
                "Fix the failing routing tests and tighten the budget warning "
                "threshold to 80%."
            ),
        )
    )
    proj.transcript_items.append(
        TranscriptItem(
            id="tx-lead-001",
            role="lead",
            title="Skail Response",
            content=(
                "Plan: inspect routing failures, patch assignment.py, rerun the "
                "budget suite. Two children delegated; $0.45 charged so far."
            ),
        )
    )

    # Live traffic: plan admitted -> node running -> budget reserved/charged ->
    # tool completed. Envelope shape mirrors test_tui_shell.py exactly.
    sid = new_session_id()
    rid = new_run_id()

    def envelope(sequence: int, ev_type: str, payload: Any) -> EventEnvelope:
        return EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=sequence,
            type=ev_type,
            payload=payload,
        )

    proj.apply_event(
        envelope(
            1,
            "plan.admitted",
            PlanPayload(action="admitted", plan_id=PLAN_ID, revision=1),
        )
    )
    proj.apply_event(
        envelope(
            2,
            "plan.node_running",
            PlanPayload(
                action="node_running", plan_id=PLAN_ID, revision=1, node_id=NODE_ID
            ),
        )
    )
    proj.apply_event(
        envelope(3, "budget.reserved", BudgetPayload(action="reserved", amount_usd=Decimal("1.00")))
    )
    proj.apply_event(
        envelope(4, "budget.charged", BudgetPayload(action="charged", amount_usd=Decimal("0.45")))
    )
    proj.apply_event(
        envelope(
            5,
            "tool.completed",
            ToolPayload(tool="read_file", status="completed"),
        )
    )
    return proj


def frame_text(app: SkailApp, width: int, height: int) -> str:
    """Plain-text copy of the current frame, taken from the live compositor."""
    compositor = app.screen._compositor
    strips = compositor.render_strips(Size(width, height))
    lines = [strip.text.rstrip() for strip in strips]
    if len(lines) > height:
        lines = lines[:height]
    while len(lines) < height:
        lines.append("")
    return "\n".join(lines) + "\n"


async def capture(theme: str, width: int, height: int) -> tuple[str, str, bool]:
    """Boot the app, inject traffic, return (svg, plain-text frame, narrow?)."""
    app = SkailApp(theme_name=theme, projection=build_projection())  # type: ignore[arg-type]
    async with app.run_test(size=(width, height)) as pilot:
        await pilot.pause()
        await pilot.pause()
        narrow = app.query_one("#main-container").has_class("narrow")
        frame = frame_text(app, width, height)
        svg = app.export_screenshot()
    return svg, frame, narrow


def export_png(svg: str, output: Path) -> str:
    """Convert one SVG to PNG; converter absence is a hard failure."""
    try:
        import cairosvg  # type: ignore[import-untyped]

        cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            write_to=str(output),
        )
        return "cairosvg"
    except ImportError:
        pass
    except Exception as exc:  # native cairo deps may be missing on Windows
        print(f"cairosvg failed, trying svglib: {exc}")
    try:
        import cairo

        sys.modules["cairocffi"] = cairo
        import cairosvg

        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(output))
        return "cairosvg+pycairo"
    except ImportError:
        pass
    except Exception as exc:
        print(f"cairosvg+pycairo failed, trying reportlab: {exc}")
    try:
        import cairo

        # rlPyCairo prefers cairocffi, while Windows wheels provide pycairo.
        sys.modules.setdefault("cairocffi", cairo)
        from reportlab.graphics import renderPM  # type: ignore[import-untyped]
        from svglib.svglib import svg2rlg

        drawing = svg2rlg(io.StringIO(svg))
        if drawing is None:
            raise RuntimeError("SVG converter returned no drawing")
        renderPM.drawToFile(drawing, str(output), fmt="PNG")
        return "svglib+reportlab"
    except ImportError:
        raise RuntimeError(
            "PNG conversion requires cairosvg or svglib/reportlab; install a converter"
        )
    except Exception as exc:
        raise RuntimeError(f"PNG conversion failed: {exc}") from exc


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--themes", nargs="+", choices=THEME_NAMES, default=list(THEME_NAMES))
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for theme in args.themes:
        svg, frame, narrow = await capture(theme, *WIDE_SIZE)
        assert not narrow, f"{theme} 120x40 must not carry the .narrow class"
        assert "<svg" in svg[:200], f"{theme} capture is not an SVG"
        svg = "\n".join(line.rstrip() for line in svg.splitlines()) + "\n"
        svg_path = OUT_DIR / f"{theme}.svg"
        png_path = OUT_DIR / f"{theme}.png"
        svg_path.write_text(svg, encoding="utf-8")
        missing = [
            needle for needle in ("YOU", "LEAD", "AGENT", "read_file") if needle not in frame
        ]
        if missing:
            raise AssertionError(f"{theme} screenshot content missing: {missing}")
        converter = export_png(svg, png_path)
        if not png_path.is_file() or png_path.stat().st_size == 0:
            raise RuntimeError(f"{theme} PNG was not produced")
        print(f"{theme}: 120x40, converter={converter}, png={png_path}, svg={svg_path}")


if __name__ == "__main__":
    asyncio.run(main())
