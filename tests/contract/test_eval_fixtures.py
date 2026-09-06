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


def test_eval_fixtures_all_have_independent_execution_scripts_and_approvals() -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    fixtures = load_fixtures(fixtures_dir)

    for f in fixtures:
        assert f.execution is not None, f"Fixture {f.id} is missing an execution script"
        assert f.execution.final_response is not None, f"Fixture {f.id} missing final response"
        # Verify metadata approval and evidence class
        assert f.metadata.get("approved") is True, f"Fixture {f.id} not marked approved"
        assert (
            f.metadata.get("evidence_class") == "synthetic_offline"
        ), f"Fixture {f.id} missing explicit synthetic_offline evidence class"
        assert f.metadata.get("intended_work"), f"Fixture {f.id} missing intended_work description"
        assert (
            f.metadata.get("scoring_meaning")
        ), f"Fixture {f.id} missing scoring_meaning description"


def test_eval_fixtures_workload_diversity() -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    fixtures = load_fixtures(fixtures_dir)

    # 1. Direct edits
    edit_fixtures = [
        f
        for f in fixtures
        if f.execution
        and any(
            call.name == "edit_file"
            for resp in f.execution.responses
            for call in resp.tool_calls
        )
    ]
    assert len(edit_fixtures) >= 5, f"Expected >= 5 direct edit fixtures, got {len(edit_fixtures)}"

    # 2. Read-only analysis
    readonly_fixtures = [
        f
        for f in fixtures
        if f.metadata.get("workload_type") == "read_only_analysis"
        or f.role in ("reviewer", "explorer", "researcher")
    ]
    assert (
        len(readonly_fixtures) >= 5
    ), f"Expected >= 5 read-only analysis fixtures, got {len(readonly_fixtures)}"

    # 3. Dependent discovery (multiple responses)
    discovery_fixtures = [
        f
        for f in fixtures
        if f.execution and len(f.execution.responses) >= 2
    ]
    assert (
        len(discovery_fixtures) >= 5
    ), f"Expected >= 5 multi-step discovery fixtures, got {len(discovery_fixtures)}"

    # 4. Parallel exploration plus serialized writes
    parallel_fixtures = [
        f
        for f in fixtures
        if f.category == "parallel"
        and f.execution
        and any(
            call.name == "task"
            for resp in f.execution.responses
            for call in resp.tool_calls
        )
    ]
    assert (
        len(parallel_fixtures) >= 5
    ), f"Expected >= 5 parallel exploration fixtures, got {len(parallel_fixtures)}"

    # 5. Windows paths
    windows_fixtures = [
        f
        for f in fixtures
        if f.metadata.get("platform") == "windows"
        or "win" in f.id
        or "win" in f.prompt.lower()
    ]
    assert (
        len(windows_fixtures) >= 2
    ), f"Expected >= 2 Windows path fixtures, got {len(windows_fixtures)}"

    # 6. Non-code answers
    non_code_extensions = (".md", ".txt", ".json", ".gitignore", ".log")
    non_code_fixtures = [
        f
        for f in fixtures
        if f.metadata.get("workload_type") == "non_code_answer"
        or (f.oracle.target and f.oracle.target.endswith(non_code_extensions))
    ]
    assert (
        len(non_code_fixtures) >= 5
    ), f"Expected >= 5 non-code fixtures, got {len(non_code_fixtures)}"

    # 7. Failure contract checks separated from policy comparisons
    failure_fixtures = [f for f in fixtures if f.category == "failure"]
    assert len(failure_fixtures) >= 6
    assert all("failure_mode" in f.metadata for f in failure_fixtures)


def test_eval_fixtures_adversarial_oracle_mutations(tmp_path: Path) -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    fixtures = load_fixtures(fixtures_dir)

    # 1. FILE_CONTENT mismatch
    content_fixture = next(f for f in fixtures if f.oracle.type == OracleType.FILE_CONTENT)
    fpath = tmp_path / content_fixture.oracle.target
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text("corrupted content", encoding="utf-8")
    passed, err = evaluate_oracle(tmp_path, content_fixture.oracle)
    assert not passed
    assert err is not None

    # 2. FILE_EXISTS missing
    exists_fixture = next(f for f in fixtures if f.oracle.type == OracleType.FILE_EXISTS)
    nonexistent = tmp_path / "does_not_exist"
    nonexistent.mkdir(parents=True, exist_ok=True)
    passed, err = evaluate_oracle(nonexistent, exists_fixture.oracle)
    assert not passed
    assert err is not None

    # 3. MULTI_ASSERT failure on sub-assertion
    multi_fixture = next(f for f in fixtures if f.oracle.type == OracleType.MULTI_ASSERT)
    partial_dir = tmp_path / "partial"
    partial_dir.mkdir(parents=True, exist_ok=True)
    # create only the first target, leaving others missing
    first_target = multi_fixture.oracle.assertions[0].get("target", "")
    if first_target:
        (partial_dir / first_target).write_text("ok", encoding="utf-8")
    passed, err = evaluate_oracle(partial_dir, multi_fixture.oracle)
    assert not passed
    assert err is not None


def test_eval_fixtures_workspace_reset_and_boundary(tmp_path: Path) -> None:
    from rudder.tools.filesystem import FilesystemBoundary, PathBoundaryError

    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    fixtures = load_fixtures(fixtures_dir)

    for f in fixtures:
        ws = tmp_path / f.id
        ws.mkdir(parents=True, exist_ok=True)
        # Reset workspace from initial_files
        for rel_path, content in f.initial_files.items():
            p = ws / rel_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            assert p.exists()

        # Validate filesystem boundary
        boundary = FilesystemBoundary(ws)
        for rel_path in f.initial_files:
            resolved = boundary.resolve(rel_path)
            assert resolved.is_relative_to(ws.resolve())

        # Validate traversal outside workspace raises PathBoundaryError
        import pytest
        with pytest.raises(PathBoundaryError):
            boundary.resolve("../../escape.txt", for_write=True)


def test_eval_fixtures_file_write_suppression_causes_mutation_failure(tmp_path: Path) -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
    fixtures = load_fixtures(fixtures_dir)

    # Pick a fixture requiring a new file or modified file
    file_oracle_types = (
        OracleType.FILE_EXISTS,
        OracleType.FILE_CONTENT,
        OracleType.FILE_CONTAINS,
    )
    write_fixtures = [
        f
        for f in fixtures
        if f.oracle.type in file_oracle_types
        and (
            f.oracle.target not in f.initial_files
            or (
                bool(f.oracle.expected)
                and f.oracle.expected not in f.initial_files.get(f.oracle.target, "")
            )
        )
    ]
    assert len(write_fixtures) >= 5

    # With writes suppressed (workspace only has initial_files and no agent writes take place)
    for sample in write_fixtures[:5]:
        ws = tmp_path / f"suppressed_{sample.id}"
        ws.mkdir(parents=True, exist_ok=True)
        for rel_path, content in sample.initial_files.items():
            p = ws / rel_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        passed, err = evaluate_oracle(ws, sample.oracle)
        assert not passed, f"Fixture {sample.id} should fail when writes are suppressed"
        assert err is not None


def test_eval_fixtures_manifest_freeze_and_digests() -> None:
    import hashlib
    import tomllib

    manifest_path = Path(__file__).resolve().parents[2] / "evals" / "manifest.toml"
    assert manifest_path.exists()

    data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sec = data.get("manifest", {})
    assert manifest_sec.get("version")
    assert manifest_sec.get("date")
    assert manifest_sec.get("approved") is True
    assert manifest_sec.get("fixture_count") >= 50

    digests = data.get("digests", {})
    assert digests, "Manifest missing [digests] section"

    sources = data.get("sources", {}).get("files", [])
    assert len(sources) >= 7

    for rel_file in sources:
        target = manifest_path.parent / Path(rel_file).name
        if not target.exists():
            target = manifest_path.parent / "fixtures" / Path(rel_file).name
        if not target.exists():
            target = manifest_path.parent.parent / rel_file
        assert target.exists(), f"Source file {rel_file} does not exist"

        content = target.read_bytes()
        computed_digest = hashlib.sha256(content).hexdigest()
        stored_digest = digests.get(Path(rel_file).name) or digests.get(rel_file)
        assert (
            stored_digest == computed_digest
        ), f"Digest mismatch for {rel_file}: expected {stored_digest}, computed {computed_digest}"
