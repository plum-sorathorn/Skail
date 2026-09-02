from __future__ import annotations

import argparse
from collections.abc import Sequence

from rudder import __version__
from rudder.smoke import run_fake_provider_smoke


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rudder",
        description="Rudder - a native budget-aware multi-agent coding harness.",
    )
    parser.add_argument("--version", action="version", version=f"rudder {__version__}")
    subcommands = parser.add_subparsers(dest="command")
    smoke = subcommands.add_parser("smoke", help="run an offline package smoke check")
    smoke.add_argument(
        "--fake-provider",
        action="store_true",
        required=True,
        help="use the deterministic in-process fake provider",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "smoke":
        print(run_fake_provider_smoke())
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
