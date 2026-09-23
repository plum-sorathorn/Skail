from __future__ import annotations

from skail.cli.main import build_parser


def main() -> int:
    help_text = build_parser().format_help()
    if "Skail" not in help_text or "--fake-provider" in help_text:
        raise RuntimeError("Skail CLI smoke contract failed")
    print("Skail offline smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
