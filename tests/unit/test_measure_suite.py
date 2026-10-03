from scripts.measure_suite import _elapsed_seconds, measured_pair_order, node_ids_from_collection


def test_node_id_collection_ignores_summary_lines_and_sorts_ids() -> None:
    output = """
tests/unit/test_second.py::test_second
tests/unit/test_first.py::test_first
2 tests collected in 0.01s
"""

    assert node_ids_from_collection(output) == (
        "tests/unit/test_first.py::test_first",
        "tests/unit/test_second.py::test_second",
    )


def test_measured_pairs_alternate_the_first_tree() -> None:
    assert measured_pair_order(0) == ("baseline", "candidate")
    assert measured_pair_order(1) == ("candidate", "baseline")
    assert measured_pair_order(2) == ("baseline", "candidate")


def test_pytest_elapsed_time_uses_the_final_summary() -> None:
    output = "first passed in 9.5s\n10 passed, 2 skipped in 12.34s\n"

    assert _elapsed_seconds(output) == 12.34
