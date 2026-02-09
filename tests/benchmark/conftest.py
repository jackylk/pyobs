"""Pytest configuration for benchmark tests."""

from __future__ import annotations

import json
import os
import platform
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest


# ============================================================================
# Configuration
# ============================================================================

SPEC_PATH = Path(__file__).parent.parent / "spec" / "benchmark-spec.json"


def load_spec() -> Dict[str, Any]:
    """Load benchmark specification."""
    with open(SPEC_PATH) as f:
        return json.load(f)


SPEC = load_spec()


@dataclass
class BenchmarkConfig:
    """Benchmark configuration based on mode."""

    mode: str = "normal"
    sample_size: int = 50
    measurement_time_sec: int = 5
    warmup_time_sec: int = 3

    @classmethod
    def from_mode(cls, mode: str) -> "BenchmarkConfig":
        modes = SPEC["config"]["modes"]
        if mode not in modes:
            mode = "normal"
        cfg = modes[mode]
        return cls(
            mode=mode,
            sample_size=cfg["sample_size"],
            measurement_time_sec=cfg["measurement_time_sec"],
            warmup_time_sec=cfg["warmup_time_sec"],
        )


@dataclass
class BenchmarkResult:
    """Result of a single benchmark."""

    benchmark_id: str
    name: str
    category: str
    samples: List[float] = field(default_factory=list)
    unit: str = "ops/sec"
    data_size: Optional[int] = None
    concurrent_level: Optional[int] = None

    @property
    def mean(self) -> float:
        return statistics.mean(self.samples) if self.samples else 0

    @property
    def std_dev(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) > 1 else 0

    @property
    def median(self) -> float:
        return statistics.median(self.samples) if self.samples else 0

    @property
    def p99(self) -> float:
        if not self.samples:
            return 0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.99)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    @property
    def ops_per_sec(self) -> float:
        if self.unit == "ops/sec":
            return self.mean
        elif self.unit == "ms":
            return 1000 / self.mean if self.mean > 0 else 0
        elif self.unit in ("MB/s", "GB/s"):
            return self.mean
        return self.mean

    @property
    def throughput_mbps(self) -> Optional[float]:
        if self.data_size and self.unit == "ms":
            return (self.data_size / (1024 * 1024)) / (self.mean / 1000) if self.mean > 0 else None
        elif self.unit == "MB/s":
            return self.mean
        elif self.unit == "GB/s":
            return self.mean * 1024
        return None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "benchmark_id": self.benchmark_id,
            "name": self.name,
            "category": self.category,
            "mean": self.mean,
            "std_dev": self.std_dev,
            "median": self.median,
            "p99": self.p99,
            "unit": self.unit,
            "sample_count": len(self.samples),
        }
        if self.ops_per_sec:
            result["ops_per_sec"] = self.ops_per_sec
        if self.throughput_mbps:
            result["throughput_mbps"] = self.throughput_mbps
        if self.data_size:
            result["data_size"] = self.data_size
        if self.concurrent_level:
            result["concurrent_level"] = self.concurrent_level
        return result


class BenchmarkRunner:
    """Runs benchmarks and collects results."""

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.results: List[BenchmarkResult] = []

    def run_benchmark(
        self,
        benchmark_id: str,
        name: str,
        category: str,
        func: Callable[[], Any],
        unit: str = "ops/sec",
        data_size: Optional[int] = None,
        concurrent_level: Optional[int] = None,
        iterations_per_sample: int = 1,
    ) -> BenchmarkResult:
        """Run a benchmark and return results."""
        result = BenchmarkResult(
            benchmark_id=benchmark_id,
            name=name,
            category=category,
            unit=unit,
            data_size=data_size,
            concurrent_level=concurrent_level,
        )

        # Warmup
        warmup_end = time.time() + self.config.warmup_time_sec
        while time.time() < warmup_end:
            func()

        # Measurement
        for _ in range(self.config.sample_size):
            start = time.perf_counter()
            for _ in range(iterations_per_sample):
                func()
            elapsed = time.perf_counter() - start

            if unit == "ops/sec":
                ops = iterations_per_sample / elapsed
                result.samples.append(ops)
            elif unit == "ms":
                ms = (elapsed / iterations_per_sample) * 1000
                result.samples.append(ms)
            elif unit == "MB/s" and data_size:
                mbps = (data_size * iterations_per_sample / (1024 * 1024)) / elapsed
                result.samples.append(mbps)
            elif unit == "GB/s" and data_size:
                gbps = (data_size * iterations_per_sample / (1024 * 1024 * 1024)) / elapsed
                result.samples.append(gbps)
            else:
                result.samples.append(elapsed)

        self.results.append(result)
        return result

    def run_timed_benchmark(
        self,
        benchmark_id: str,
        name: str,
        category: str,
        func: Callable[[], Any],
        unit: str = "ms",
        data_size: Optional[int] = None,
    ) -> BenchmarkResult:
        """Run a benchmark measuring time per operation."""
        result = BenchmarkResult(
            benchmark_id=benchmark_id,
            name=name,
            category=category,
            unit=unit,
            data_size=data_size,
        )

        # Warmup (fewer iterations for network operations)
        for _ in range(min(3, self.config.warmup_time_sec)):
            func()

        # Measurement
        for _ in range(self.config.sample_size):
            start = time.perf_counter()
            func()
            elapsed = time.perf_counter() - start
            result.samples.append(elapsed * 1000)  # Convert to ms

        self.results.append(result)
        return result


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "obs: marks tests as requiring OBS credentials")
    config.addinivalue_line("markers", "slow: marks tests as slow running")


def pytest_addoption(parser):
    """Add benchmark-specific command line options."""
    try:
        parser.addoption(
            "--quick",
            action="store_true",
            default=False,
            help="Run benchmarks in quick mode (fewer iterations)",
        )
    except ValueError:
        pass  # Option already added

    try:
        parser.addoption(
            "--full",
            action="store_true",
            default=False,
            help="Run benchmarks in full mode (more iterations)",
        )
    except ValueError:
        pass

    try:
        parser.addoption(
            "--with-obs",
            action="store_true",
            default=False,
            help="Include OBS integration benchmarks",
        )
    except ValueError:
        pass

    try:
        parser.addoption(
            "--report",
            action="store_true",
            default=False,
            help="Generate reports",
        )
    except ValueError:
        pass


@pytest.fixture
def benchmark_mode(request):
    """Get the current benchmark mode."""
    if request.config.getoption("--quick"):
        return "quick"
    elif request.config.getoption("--full"):
        return "full"
    return "normal"


@pytest.fixture
def with_obs(request):
    """Check if OBS benchmarks should run."""
    return request.config.getoption("--with-obs")


@pytest.fixture(scope="session")
def benchmark_config(request) -> BenchmarkConfig:
    """Get benchmark configuration based on command line options."""
    if request.config.getoption("--quick", False):
        return BenchmarkConfig.from_mode("quick")
    elif request.config.getoption("--full", False):
        return BenchmarkConfig.from_mode("full")
    return BenchmarkConfig.from_mode("normal")


@pytest.fixture(scope="session")
def benchmark_runner(benchmark_config) -> BenchmarkRunner:
    """Create benchmark runner."""
    return BenchmarkRunner(benchmark_config)


@pytest.fixture(scope="session")
def obs_rest_client():
    """Create OBS REST API client for benchmarks."""
    from benchmarks.obs_rest_client import OBSRestClient

    ak = os.environ.get("OBS_ACCESS_KEY_ID")
    sk = os.environ.get("OBS_SECRET_ACCESS_KEY")
    endpoint = os.environ.get("OBS_ENDPOINT")

    if not all([ak, sk, endpoint]):
        pytest.skip("OBS credentials not configured")

    return OBSRestClient(access_key=ak, secret_key=sk, endpoint=endpoint)


# ============================================================================
# Report Generation
# ============================================================================


def _format_time_unit(ns: float) -> Tuple[str, str]:
    """Format nanoseconds into appropriate unit."""
    if ns >= 1_000_000:
        return f"{ns / 1_000_000:.2f}", "ms"
    elif ns >= 1_000:
        return f"{ns / 1_000:.2f}", "µs"
    else:
        return f"{ns:.2f}", "ns"


def _format_throughput(ops_per_sec: float) -> str:
    """Format throughput with appropriate formatting."""
    if ops_per_sec >= 1_000_000:
        return f"{ops_per_sec:,.0f}"
    elif ops_per_sec >= 1_000:
        return f"{ops_per_sec:,.0f}"
    else:
        return f"{ops_per_sec:.0f}"


def _result_to_ns_entry(result: BenchmarkResult) -> Dict[str, Any]:
    """Convert a BenchmarkResult to a benchmark JSON entry with ns + ms metrics."""
    if result.unit == "ops/sec":
        mean_ns = 1_000_000_000 / result.mean if result.mean > 0 else 0
        std_dev_ns = (
            (1_000_000_000 / (result.mean - result.std_dev) - mean_ns)
            if result.mean > result.std_dev
            else 0
        )
        median_ns = 1_000_000_000 / result.median if result.median > 0 else 0
        p99_ns = 1_000_000_000 / result.p99 if result.p99 > 0 else 0
    elif result.unit == "ms":
        mean_ns = result.mean * 1_000_000
        std_dev_ns = result.std_dev * 1_000_000
        median_ns = result.median * 1_000_000
        p99_ns = result.p99 * 1_000_000
    else:
        mean_ns = result.mean
        std_dev_ns = result.std_dev
        median_ns = result.median
        p99_ns = result.p99

    entry: Dict[str, Any] = {
        "mean_ns": mean_ns,
        "std_dev_ns": abs(std_dev_ns),
        "median_ns": median_ns,
        "p99_ns": p99_ns,
        "mean_ms": mean_ns / 1_000_000,
        "p50_ms": median_ns / 1_000_000,
        "p99_ms": p99_ns / 1_000_000,
    }
    if result.throughput_mbps is not None:
        entry["throughput_mb_sec"] = result.throughput_mbps
    if result.data_size is not None:
        entry["data_size_bytes"] = result.data_size
    return entry


@pytest.fixture(scope="session", autouse=True)
def generate_report(request, benchmark_runner: BenchmarkRunner):
    """Generate benchmark report after all tests.

    Outputs to test-reports/:
      - benchmark-data.json        — all results
      - rest-benchmark-data.json   — REST API results only (keys match fsspec names)
      - fs-vs-rest-comparison.json — side-by-side comparison
      - benchmark-report.md        — human-readable markdown
    """
    yield

    if not benchmark_runner.results:
        return

    timestamp = datetime.now()
    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

    reports_dir = Path(__file__).parent.parent.parent / "test-reports"
    reports_dir.mkdir(exist_ok=True)

    # ----------------------------------------------------------------
    # 1. Full JSON (benchmark-data.json)
    # ----------------------------------------------------------------
    full_json: Dict[str, Any] = {
        "timestamp": timestamp_str,
        "benchmarks": {},
    }
    for result in benchmark_runner.results:
        key = result.benchmark_id.replace("/", "_")
        entry = _result_to_ns_entry(result)
        entry["category"] = result.category
        full_json["benchmarks"][key] = entry

    json_path = reports_dir / "benchmark-data.json"
    with open(json_path, "w") as f:
        json.dump(full_json, f, indent=4)

    # ----------------------------------------------------------------
    # 2. REST-only JSON (rest-benchmark-data.json)
    #    Keys strip "obs_rest/" prefix so they match fsspec keys for
    #    1:1 comparison.  e.g. obs_rest/write_1KB -> write_1KB
    # ----------------------------------------------------------------
    rest_results_list = [
        r for r in benchmark_runner.results if r.category == "obs_rest"
    ]
    if rest_results_list:
        rest_json: Dict[str, Any] = {
            "timestamp": timestamp_str,
            "benchmarks": {},
        }
        for r in rest_results_list:
            # obs_rest/write_1KB -> write_1KB
            canonical = r.benchmark_id.replace("obs_rest/", "")
            rest_json["benchmarks"][canonical] = _result_to_ns_entry(r)
        rest_path = reports_dir / "rest-benchmark-data.json"
        with open(rest_path, "w") as f:
            json.dump(rest_json, f, indent=4)
        print(f"  - REST JSON: {rest_path}")

    # ----------------------------------------------------------------
    # 3. fsspec vs REST comparison JSON
    # ----------------------------------------------------------------
    obs_map = {
        r.benchmark_id.replace("obs/", ""): r
        for r in benchmark_runner.results
        if r.category == "obs" and r.unit == "ms"
    }
    rest_map = {
        r.benchmark_id.replace("obs_rest/", ""): r
        for r in benchmark_runner.results
        if r.category == "obs_rest" and r.unit == "ms"
    }
    common_ops = sorted(set(obs_map.keys()) & set(rest_map.keys()))
    comparisons: list = []
    if common_ops:
        for op in common_ops:
            fs_r = obs_map[op]
            rest_r = rest_map[op]
            fs_mean = fs_r.mean
            rest_mean = rest_r.mean
            overhead = (
                (fs_mean - rest_mean) / rest_mean * 100
                if rest_mean > 0 else 0
            )
            comp_entry: Dict[str, Any] = {
                "operation": op,
                "fs_api": {
                    "mean_ms": round(fs_mean, 4),
                    "p50_ms": round(fs_r.median, 4),
                    "p99_ms": round(fs_r.p99, 4),
                },
                "rest_api": {
                    "mean_ms": round(rest_mean, 4),
                    "p50_ms": round(rest_r.median, 4),
                    "p99_ms": round(rest_r.p99, 4),
                },
                "overhead_pct": round(overhead, 2),
            }
            if fs_r.throughput_mbps is not None:
                comp_entry["fs_api"]["throughput_mb_sec"] = round(fs_r.throughput_mbps, 4)
            if rest_r.throughput_mbps is not None:
                comp_entry["rest_api"]["throughput_mb_sec"] = round(rest_r.throughput_mbps, 4)
            comparisons.append(comp_entry)

        comp_path = reports_dir / "fs-vs-rest-comparison.json"
        with open(comp_path, "w") as f:
            json.dump({"timestamp": timestamp_str, "comparisons": comparisons}, f, indent=2)
        print(f"  - Comparison JSON: {comp_path}")

    # ----------------------------------------------------------------
    # 4. Markdown report
    # ----------------------------------------------------------------
    md_path = reports_dir / "benchmark-report.md"
    with open(md_path, "w") as f:
        f.write("# PyOBS Performance Benchmark Report\n\n")
        f.write(f"**Generated:** {timestamp_str}\n\n")

        f.write("## Test Environment\n\n")
        f.write("| Property | Value |\n")
        f.write("|----------|-------|\n")
        f.write(f"| Platform | {platform.platform()} |\n")
        f.write(f"| Python | {platform.python_version()} |\n")
        f.write(f"| CPU Count | {os.cpu_count()} |\n")
        f.write(f"| Mode | {benchmark_runner.config.mode} |\n\n")

        f.write("## Summary\n\n")
        f.write("All benchmarks measure the time taken for individual operations. Lower is better.\n\n")
        f.write("## Benchmark Results\n\n")

        # Group by category
        categories: Dict[str, List[BenchmarkResult]] = {}
        for result in benchmark_runner.results:
            cat = result.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(result)

        for cat, results in categories.items():
            f.write(f"### {cat.title()} Operations\n\n")
            f.write("| Benchmark | Mean | Std Dev | Throughput |\n")
            f.write("|-----------|------|---------|------------|\n")

            for r in results:
                if r.unit == "ops/sec":
                    mean_ns = 1_000_000_000 / r.mean if r.mean > 0 else 0
                    std_ns = (
                        (1_000_000_000 / (r.mean - r.std_dev) - mean_ns)
                        if r.mean > r.std_dev
                        else 0
                    )
                    mean_val, mean_unit = _format_time_unit(mean_ns)
                    std_val, _ = _format_time_unit(abs(std_ns))
                    throughput = f"{_format_throughput(r.mean)} ops/s"
                elif r.unit == "ms":
                    mean_ns = r.mean * 1_000_000
                    std_ns = r.std_dev * 1_000_000
                    mean_val, mean_unit = _format_time_unit(mean_ns)
                    std_val, _ = _format_time_unit(std_ns)
                    if r.throughput_mbps:
                        throughput = f"{r.throughput_mbps:.2f} MB/s"
                    else:
                        throughput = f"{1000 / r.mean:.0f} ops/s" if r.mean > 0 else "-"
                else:
                    mean_val = f"{r.mean:.2f}"
                    mean_unit = r.unit
                    std_val = f"{r.std_dev:.2f}"
                    throughput = "-"

                f.write(f"| {r.name} | {mean_val} {mean_unit} | ±{std_val} {mean_unit} | {throughput} |\n")

            f.write("\n")

        # fsspec vs REST comparison table
        if comparisons:
            f.write("## PyOBS fsspec vs OBS REST API\n\n")
            f.write("| Operation | fsspec Mean | REST Mean | Overhead |\n")
            f.write("|-----------|------------|-----------|----------|\n")
            for c in comparisons:
                overhead_str = f"{c['overhead_pct']:+.1f}%"
                f.write(f"| {c['operation']} | {c['fs_api']['mean_ms']:.2f} ms "
                        f"| {c['rest_api']['mean_ms']:.2f} ms | {overhead_str} |\n")
            f.write("\n")

        f.write("## Notes\n\n")
        f.write("- All times are in nanoseconds unless otherwise specified\n")
        f.write("- Throughput calculated as operations per second\n")
        f.write("- OBS integration tests require network access and valid credentials\n\n")
        f.write("---\n\n")
        f.write("*Report generated by PyOBS benchmark suite*\n")

    print(f"\n\nBenchmark reports generated:")
    print(f"  - JSON: {json_path}")
    print(f"  - Markdown: {md_path}")
