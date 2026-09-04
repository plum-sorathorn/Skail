from __future__ import annotations

from pathlib import Path

from evals.fixtures_loader import load_fixtures
from evals.runner import evaluate_oracle
from evals.schema import OracleType


def test_eval_fixtures_loaded_from_directory_and_manifest() -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    manifest_path = Path(__file__).resolve().parents[2] / "evals" / "manifest.toml"

    dir_fixtures = load_fixtures(fixtures_dir)
    manifest_fixtures = load_fixtures(manifest_path)

    # Both should find the curated suite
    assert len(dir_fixtures) >= 50
    assert len(manifest_fixtures) >= 50
    assert len(dir_fixtures) == len(manifest_fixtures)


def test_eval_fixtures_category_balance() -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    fixtures = load_fixtures(fixtures_dir)

    categories = {f.category for f in fixtures}
    expected_categories = {
        "trivial",
        "routine",
        "bounded",
        "complex",
        "high_risk",
        "parallel",
        "failure",
    }
    assert expected_categories.issubset(categories)

    # Check minimum balance
    by_category: dict[str, int] = {}
    for f in fixtures:
        by_category[f.category] = by_category.get(f.category, 0) + 1

    for cat in expected_categories:
        assert by_category[cat] >= 5, f"Category {cat} has only {by_category[cat]} fixtures"


def test_eval_fixtures_role_and_platform_coverage() -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    fixtures = load_fixtures(fixtures_dir)

    roles = {f.role for f in fixtures}
    assert "implementer" in roles
    assert "tester" in roles
    assert "reviewer" in roles
    assert "explorer" in roles
    assert "lead" in roles

    # Parallel fixtures have parallel_eligible=True
    parallel_fixtures = [f for f in fixtures if f.category == "parallel"]
    assert len(parallel_fixtures) >= 5
    assert all(f.parallel_eligible for f in parallel_fixtures)


def test_eval_fixtures_oracle_integrity_and_mutation(tmp_path: Path) -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    fixtures = load_fixtures(fixtures_dir)

    for f in fixtures:
        assert f.id
        assert f.prompt
        file_types = (
            OracleType.FILE_EXISTS,
            OracleType.FILE_CONTAINS,
            OracleType.FILE_CONTENT,
        )
        if f.oracle.type in file_types:
            assert f.oracle.target

    # Oracle mutation test: verify expectation mismatch causes failure
    sample = next(f for f in fixtures if f.oracle.type == OracleType.FILE_CONTAINS)
    target_file = tmp_path / sample.oracle.target
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("unrelated garbage content", encoding="utf-8")

    passed, err = evaluate_oracle(tmp_path, sample.oracle)
    assert not passed
    assert err is not None
