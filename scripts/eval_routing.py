#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

# Add project root to sys.path if not present
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.report import render_markdown_report, save_report_json
from evals.runner import EvaluationRunner
from evals.schema import (
    EvaluationFixture,
    EvaluationPolicy,
    ExecutionScript,
    OracleSpec,
    OracleType,
    ScriptedModelResponse,
    ScriptedToolCall,
    ScriptedUsage,
)


def _write_script(target: str, content: str) -> ExecutionScript:
    return ExecutionScript(
        responses=(
            ScriptedModelResponse(
                tool_calls=(
                    ScriptedToolCall(
                        name="write_file",
                        args={"file_path": target, "content": content},
                        id=f"write-{target}",
                    ),
                ),
                usage=ScriptedUsage(
                    input_tokens=10, output_tokens=5, cost_usd=Decimal("0.001")
                ),
            ),
        ),
        final_response=ScriptedModelResponse(
            content="Fixture work completed through Rudder tools.",
            usage=ScriptedUsage(
                input_tokens=10, output_tokens=5, cost_usd=Decimal("0.001")
            ),
        ),
    )


def _sample_fixtures() -> list[EvaluationFixture]:
    return [
        EvaluationFixture(
            id="smoke-trivial-01",
            title="Create hello.txt file",
            category="trivial",
            role="implementer",
            prompt="Create a file hello.txt containing 'Hello World'",
            execution=_write_script("hello.txt", "Hello World"),
            oracle=OracleSpec(
                type=OracleType.FILE_CONTENT,
                target="hello.txt",
                expected="Hello World",
            ),
        ),
        EvaluationFixture(
            id="smoke-parallel-01",
            title="Implement and test math helper",
            category="parallel",
            role="implementer",
            prompt="Implement math helper and verify with tests",
            parallel_eligible=True,
            execution=_write_script("math_helper.py", "def add(a, b): return a + b\n"),
            oracle=OracleSpec(
                type=OracleType.FILE_EXISTS,
                target="math_helper.py",
            ),
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Rudder Routing & Orchestration Evaluation Runner")
    parser.add_argument(
        "--fixtures",
        type=str,
        default=None,
        help="Path to fixture directory, JSON, or TOML manifest",
    )
    parser.add_argument(
        "--policies",
        type=str,
        default="all",
        help=(
            "Comma-separated list of policies to evaluate "
            "(auto,economy,quality,serial,no_delegation) or 'all'"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--paired-runtime",
        action="store_true",
        help="Run the frozen Phase 15 paired-runtime profile (seeds 42,100; five repetitions)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write JSON evaluation report",
    )
    parser.add_argument(
        "--markdown",
        type=str,
        default=None,
        help="Path to write Markdown summary report",
    )

    args = parser.parse_args()

    if args.policies.strip().lower() == "all":
        policies = list(EvaluationPolicy)
    else:
        policies = [EvaluationPolicy(p.strip().lower()) for p in args.policies.split(",")]

    # Load fixtures if provided, or default sample
    fixtures = _sample_fixtures()
    if args.fixtures:
        from evals.fixtures_loader import load_fixtures  # type: ignore[import-not-found]
        fixtures = load_fixtures(Path(args.fixtures))

    if args.paired_runtime:
        if args.policies.strip().lower() != "all":
            parser.error("--paired-runtime fixes the policy matrix; omit --policies")
        if args.seed != 42:
            parser.error("--paired-runtime fixes seeds 42 and 100; omit --seed")
        runner = EvaluationRunner.paired_runtime(fixtures=fixtures, command=tuple(sys.argv))
    else:
        runner = EvaluationRunner(
            fixtures=fixtures,
            policies=policies,
            seed=args.seed,
            command=tuple(sys.argv),
        )

    report = runner.run()
    md = render_markdown_report(report)
    print(md)

    if args.output:
        save_report_json(report, Path(args.output))
        print(f"\nSaved JSON report to: {args.output}")

    if args.markdown:
        out_p = Path(args.markdown)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")
        print(f"Saved Markdown report to: {args.markdown}")

    if report.comparison and not report.comparison.all_gates_passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
