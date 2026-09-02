from __future__ import annotations

from importlib.metadata import version


def test_framework_versions_match_the_accepted_contract() -> None:
    assert {
        distribution: version(distribution)
        for distribution in (
            "deepagents",
            "langchain",
            "langchain-core",
            "langgraph",
            "langgraph-checkpoint",
            "langgraph-checkpoint-sqlite",
        )
    } == {
        "deepagents": "0.7.13",
        "langchain": "1.3.18",
        "langchain-core": "1.6.1",
        "langgraph": "1.2.11",
        "langgraph-checkpoint": "4.2.0",
        "langgraph-checkpoint-sqlite": "3.1.1",
    }
