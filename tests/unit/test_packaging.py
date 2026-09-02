from __future__ import annotations

import email
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_wheel_contains_only_the_rudder_runtime(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        assert "rudder/__init__.py" in names
        assert "rudder/cli/main.py" in names
        assert not any(name.startswith(("autoconduck/", "legacy/")) for name in names)

        entry_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entries = wheel.read(entry_name).decode()
        assert "rudder = rudder.cli.main:main" in entries
        assert "autoconduck" not in entries
        assert "conduck =" not in entries

        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(wheel.read(metadata_name))
        assert metadata["Name"] == "rudder-agent"
        assert metadata["Requires-Python"] == ">=3.12"
        assert "Rudder" in metadata["Summary"]
