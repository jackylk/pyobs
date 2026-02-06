#!/usr/bin/env python3
"""Generate test summary report for pyobs.

This script aggregates test results from functional and benchmark tests
and generates a summary report compatible with obsfuse format.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).parent.parent
TEST_REPORTS_DIR = PROJECT_ROOT / "test-reports"


def generate_test_summary(
    mode: str = "normal",
    consistency_status: str = "passed",
    functional_status: str = "passed",
    benchmark_status: str = "completed",
) -> None:
    """Generate test summary files."""
    TEST_REPORTS_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now()

    # Generate JSON summary
    summary_json = {
        "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "results": {
            "consistency": consistency_status,
            "functional": functional_status,
            "benchmark": benchmark_status,
        }
    }

    json_path = TEST_REPORTS_DIR / "test-summary.json"
    with open(json_path, "w") as f:
        json.dump(summary_json, f, indent=4)

    # Generate Markdown summary
    md_path = TEST_REPORTS_DIR / "test-summary.md"
    with open(md_path, "w") as f:
        f.write("# PyOBS Test Summary\n\n")
        f.write(f"**Generated:** {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Mode:** {mode}\n\n")

        f.write("## Test Results\n\n")
        f.write("| Test Suite | Status |\n")
        f.write("|------------|--------|\n")
        f.write(f"| Consistency Tests | {consistency_status} |\n")
        f.write(f"| Functional Tests | {functional_status} |\n")
        f.write(f"| Benchmark Tests | {benchmark_status} |\n\n")

        f.write("## Report Files\n\n")
        f.write("- Consistency: `test-reports/consistency-test.log`\n")
        f.write("- Functional: `test-reports/functional-test.log`\n")
        f.write("- Benchmark Log: `test-reports/benchmark.log`\n")
        f.write("- Benchmark Report: `test-reports/benchmark-report.md`\n")
        f.write("- Benchmark Data: `test-reports/benchmark-data.json`\n")

    print(f"Test summary generated:")
    print(f"  - {json_path}")
    print(f"  - {md_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate test summary")
    parser.add_argument("--mode", default="normal", choices=["quick", "normal", "full"])
    parser.add_argument("--consistency", default="passed")
    parser.add_argument("--functional", default="passed")
    parser.add_argument("--benchmark", default="completed")

    args = parser.parse_args()

    generate_test_summary(
        mode=args.mode,
        consistency_status=args.consistency,
        functional_status=args.functional,
        benchmark_status=args.benchmark,
    )
