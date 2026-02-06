#!/usr/bin/env python3
"""Run benchmarks and generate reports.

Usage:
    python scripts/run_benchmark.py                 # Normal mode
    python scripts/run_benchmark.py --quick         # Quick mode
    python scripts/run_benchmark.py --full          # Full mode
    python scripts/run_benchmark.py --with-obs      # Include OBS tests
    python scripts/run_benchmark.py --report        # Generate report only
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
PERF_DIR = PROJECT_ROOT / "perf"
SPEC_FILE = PROJECT_ROOT / "tests" / "spec" / "benchmark-spec.json"


def load_spec() -> Dict[str, Any]:
    """Load benchmark specification."""
    with open(SPEC_FILE) as f:
        return json.load(f)


def get_system_info() -> Dict[str, Any]:
    """Collect system information."""
    import psutil

    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "arch": platform.machine(),
        "cpu": platform.processor() or "Unknown",
        "cpu_count": os.cpu_count(),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "python_version": platform.python_version(),
    }


def run_pytest_benchmark(
    mode: str = "normal",
    with_obs: bool = False,
    filter_pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """Run pytest benchmarks and collect results."""
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/benchmark/",
        "-v",
        f"--{mode}",
        "--tb=short",
    ]

    if not with_obs:
        cmd.extend(["-k", "not obs"])

    if filter_pattern:
        if "-k" in cmd:
            idx = cmd.index("-k")
            cmd[idx + 1] = f"({cmd[idx + 1]}) and ({filter_pattern})"
        else:
            cmd.extend(["-k", filter_pattern])

    # Run benchmarks
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    return {
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def parse_benchmark_output(output: str) -> Dict[str, Dict[str, Any]]:
    """Parse pytest output to extract benchmark results."""
    results = {}

    # Parse lines like: test_path_join - 1234567.89 ops/sec (mean: 0.81 µs)
    import re

    pattern = r"(\w+)\s*-\s*([\d.]+)\s*(ops/sec|MB/s|GB/s|ms|µs|ns)"
    for match in re.finditer(pattern, output):
        name = match.group(1)
        value = float(match.group(2))
        unit = match.group(3)
        results[name] = {
            "value": value,
            "unit": unit,
        }

    return results


def generate_markdown_report(
    results: Dict[str, Any],
    output_path: Path,
) -> None:
    """Generate markdown report."""
    timestamp = results.get("timestamp", datetime.now().isoformat())
    system = results.get("system_info", {})
    mode = results.get("mode", "normal")
    benchmarks = results.get("benchmarks", {})

    lines = [
        "# PyOBS Performance Benchmark Report",
        "",
        f"Generated: {timestamp}",
        f"Mode: {mode}",
        "",
        "## System Information",
        "",
        f"- OS: {system.get('os', 'Unknown')} {system.get('os_version', '')}",
        f"- CPU: {system.get('cpu', 'Unknown')} ({system.get('cpu_count', '?')} cores)",
        f"- Memory: {system.get('memory_gb', '?')} GB",
        f"- Python: {system.get('python_version', 'Unknown')}",
        "",
        "## Summary",
        "",
        f"- Total benchmarks: {len(benchmarks)}",
        "",
        "## Results",
        "",
    ]

    # Group by category
    categories: Dict[str, List[tuple]] = {}
    for name, data in benchmarks.items():
        category = name.split("/")[0] if "/" in name else "other"
        if category not in categories:
            categories[category] = []
        categories[category].append((name, data))

    for category, items in sorted(categories.items()):
        lines.append(f"### {category.title()}")
        lines.append("")
        lines.append("| Benchmark | Value | Unit |")
        lines.append("|-----------|-------|------|")

        for name, data in sorted(items):
            value = data.get("value", 0)
            unit = data.get("unit", "")
            if isinstance(value, float):
                if value > 1000000:
                    value_str = f"{value/1000000:.2f}M"
                elif value > 1000:
                    value_str = f"{value/1000:.2f}K"
                else:
                    value_str = f"{value:.2f}"
            else:
                value_str = str(value)
            lines.append(f"| {name} | {value_str} | {unit} |")

        lines.append("")

    output_path.write_text("\n".join(lines))
    print(f"Report saved to: {output_path}")


def generate_json_report(
    results: Dict[str, Any],
    output_path: Path,
) -> None:
    """Generate JSON report."""
    output_path.write_text(json.dumps(results, indent=2))
    print(f"JSON data saved to: {output_path}")


def check_regression(
    current: Dict[str, Any],
    baseline_path: Path,
    warning_threshold: float = 0.1,
    failure_threshold: float = 0.2,
) -> List[Dict[str, Any]]:
    """Check for performance regression against baseline."""
    if not baseline_path.exists():
        print(f"No baseline found at {baseline_path}, skipping regression check")
        return []

    with open(baseline_path) as f:
        baseline = json.load(f)

    regressions = []
    current_benchmarks = current.get("benchmarks", {})
    baseline_benchmarks = baseline.get("benchmarks", {})

    for name, current_data in current_benchmarks.items():
        if name not in baseline_benchmarks:
            continue

        current_value = current_data.get("value", 0)
        baseline_value = baseline_benchmarks[name].get("value", 0)

        if baseline_value == 0:
            continue

        # For latency metrics (ms, µs, ns), higher is worse
        # For throughput metrics (ops/sec, MB/s), lower is worse
        unit = current_data.get("unit", "")
        if unit in ("ms", "µs", "ns"):
            change = (current_value - baseline_value) / baseline_value
        else:
            change = (baseline_value - current_value) / baseline_value

        if change > failure_threshold:
            regressions.append({
                "name": name,
                "baseline": baseline_value,
                "current": current_value,
                "change_percent": change * 100,
                "severity": "failure",
            })
        elif change > warning_threshold:
            regressions.append({
                "name": name,
                "baseline": baseline_value,
                "current": current_value,
                "change_percent": change * 100,
                "severity": "warning",
            })

    return regressions


def main():
    parser = argparse.ArgumentParser(description="Run pyobs benchmarks")
    parser.add_argument("--quick", action="store_true", help="Quick mode (fewer samples)")
    parser.add_argument("--full", action="store_true", help="Full mode (more samples)")
    parser.add_argument("--with-obs", action="store_true", help="Include OBS integration tests")
    parser.add_argument("--report", action="store_true", help="Generate report from existing data")
    parser.add_argument("--filter", "-k", type=str, help="Filter benchmarks by pattern")
    parser.add_argument("--baseline", action="store_true", help="Save as baseline")
    parser.add_argument("--check-regression", action="store_true", help="Check regression against baseline")
    args = parser.parse_args()

    # Ensure perf directory exists
    PERF_DIR.mkdir(exist_ok=True)

    # Determine mode
    if args.quick:
        mode = "quick"
    elif args.full:
        mode = "full"
    else:
        mode = "normal"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.report:
        # Generate report from existing data
        data_file = PERF_DIR / "benchmark-data.json"
        if not data_file.exists():
            print(f"No data file found at {data_file}")
            sys.exit(1)

        with open(data_file) as f:
            results = json.load(f)
    else:
        # Run benchmarks
        print(f"Running benchmarks in {mode} mode...")
        if args.with_obs:
            print("Including OBS integration tests")

        run_result = run_pytest_benchmark(
            mode=mode,
            with_obs=args.with_obs,
            filter_pattern=args.filter,
        )

        print(run_result["stdout"])
        if run_result["stderr"]:
            print(run_result["stderr"], file=sys.stderr)

        # Parse results
        benchmarks = parse_benchmark_output(run_result["stdout"])

        results = {
            "project": "pyobs",
            "version": "0.1.0",
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "system_info": get_system_info(),
            "benchmarks": benchmarks,
        }

        # Save JSON data
        generate_json_report(results, PERF_DIR / "benchmark-data.json")

        # Save to history
        history_dir = PERF_DIR / "history"
        history_dir.mkdir(exist_ok=True)
        generate_json_report(results, history_dir / f"benchmark-{timestamp}.json")

    # Generate markdown report
    generate_markdown_report(results, PERF_DIR / "benchmark-report.md")

    # Save as baseline if requested
    if args.baseline:
        generate_json_report(results, PERF_DIR / "baseline.json")
        print("Saved as baseline")

    # Check regression if requested
    if args.check_regression:
        spec = load_spec()
        thresholds = spec.get("config", {}).get("regression_thresholds", {})

        regressions = check_regression(
            results,
            PERF_DIR / "baseline.json",
            warning_threshold=thresholds.get("warning_percent", 10) / 100,
            failure_threshold=thresholds.get("failure_percent", 20) / 100,
        )

        if regressions:
            print("\n=== Regression Report ===")
            has_failure = False
            for reg in regressions:
                severity = reg["severity"].upper()
                if severity == "FAILURE":
                    has_failure = True
                print(f"[{severity}] {reg['name']}: {reg['change_percent']:.1f}% regression")
                print(f"  Baseline: {reg['baseline']}, Current: {reg['current']}")

            if has_failure:
                sys.exit(1)
        else:
            print("\nNo performance regression detected")


if __name__ == "__main__":
    main()
