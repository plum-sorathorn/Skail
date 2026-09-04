from __future__ import annotations

import json
from pathlib import Path

from evals.schema import EvaluationFixture


def load_fixtures(path: Path | None = None) -> list[EvaluationFixture]:
    if path is None:
        path = Path(__file__).resolve().parent / "fixtures"

    if path.is_file():
        if path.suffix == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [EvaluationFixture.model_validate(item) for item in raw]
            return [EvaluationFixture.model_validate(raw)]
        elif path.suffix in (".toml", ".manifest"):
            import tomllib
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            fixtures = []
            for item in data.get("fixtures", []):
                fixtures.append(EvaluationFixture.model_validate(item))
            for rel_file in data.get("sources", {}).get("files", []):
                target = (
                    (path.parent / rel_file)
                    if not Path(rel_file).is_absolute()
                    else Path(rel_file)
                )
                if not target.exists():
                    # Check relative to root
                    target = Path(rel_file)
                if target.exists():
                    fixtures.extend(load_fixtures(target))
            return fixtures

    fixtures: list[EvaluationFixture] = []
    if path.is_dir():
        for json_file in sorted(path.glob("*.json")):
            raw = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                fixtures.extend(EvaluationFixture.model_validate(item) for item in raw)
            else:
                fixtures.append(EvaluationFixture.model_validate(raw))

    return fixtures
