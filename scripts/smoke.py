from __future__ import annotations

import argparse

from rudder.smoke import run_fake_provider_smoke


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Rudder's offline smoke check.")
    parser.add_argument("--fake-provider", action="store_true", required=True)
    parser.parse_args()
    print(run_fake_provider_smoke())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
