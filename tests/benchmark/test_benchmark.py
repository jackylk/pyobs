"""Performance benchmark tests for pyobs based on shared specification.

Run with:
    pytest tests/benchmark/ -v                     # All benchmarks
    pytest tests/benchmark/ -v --quick             # Quick mode
    pytest tests/benchmark/ -v --full              # Full mode
    pytest tests/benchmark/ -v -k "path"           # Path operations only
    pytest tests/benchmark/ -v -k "obs"            # OBS integration only

Generate reports:
    python scripts/run_benchmark.py --report
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pyobs import OBSFileSystem
from pyobs.utils import get_parent_path, join_path


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
# Fixtures
# ============================================================================

def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption("--quick", action="store_true", help="Run quick benchmarks")
    parser.addoption("--full", action="store_true", help="Run full benchmarks")
    parser.addoption("--with-obs", action="store_true", help="Include OBS benchmarks")
    parser.addoption("--report", action="store_true", help="Generate reports")


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
def obs_bucket():
    """Get OBS bucket name."""
    bucket = os.environ.get("OBS_TEST_BUCKET")
    if not bucket:
        pytest.skip("OBS_TEST_BUCKET not configured")
    return bucket


@pytest.fixture(scope="session")
def obs_fs():
    """Create OBS filesystem for benchmarks."""
    ak = os.environ.get("OBS_ACCESS_KEY_ID")
    sk = os.environ.get("OBS_SECRET_ACCESS_KEY")
    endpoint = os.environ.get("OBS_ENDPOINT")
    bucket = os.environ.get("OBS_TEST_BUCKET")

    if not all([ak, sk, endpoint, bucket]):
        pytest.skip("OBS credentials not configured")

    return OBSFileSystem(
        key=ak,
        secret=sk,
        endpoint=endpoint,
        bucket=bucket,
    )


@pytest.fixture(scope="session")
def test_prefix():
    """Generate unique test prefix."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"pyobs-bench-{timestamp}"


# ============================================================================
# Path Operation Benchmarks (Local)
# ============================================================================

class TestPathBenchmarks:
    """Path operation benchmarks - no network required."""

    def test_path_join(self, benchmark_runner: BenchmarkRunner):
        """Benchmark path join operation."""
        def op():
            join_path("bucket/dir1/dir2", "file.txt")

        result = benchmark_runner.run_benchmark(
            "path/join", "Join paths", "local", op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_path_parent(self, benchmark_runner: BenchmarkRunner):
        """Benchmark get parent path operation."""
        def op():
            get_parent_path("bucket/dir1/dir2/file.txt")

        result = benchmark_runner.run_benchmark(
            "path/parent", "Get parent path", "local", op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_path_filename(self, benchmark_runner: BenchmarkRunner):
        """Benchmark get filename operation."""
        def op():
            path = "bucket/dir1/dir2/file.txt"
            path.rsplit("/", 1)[-1]

        result = benchmark_runner.run_benchmark(
            "path/filename", "Get filename", "local", op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"


# ============================================================================
# OBS Integration Benchmarks
# ============================================================================

@pytest.mark.obs
class TestOBSBenchmarks:
    """OBS integration benchmarks - requires network and credentials."""

    @pytest.fixture(autouse=True)
    def check_obs(self, request):
        """Skip if OBS benchmarks not enabled."""
        if not request.config.getoption("--with-obs", False):
            pytest.skip("OBS benchmarks not enabled (use --with-obs)")

    def test_obs_write_1kb(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark 1KB file write."""
        data = b"x" * 1024
        counter = [0]

        def op():
            counter[0] += 1
            path = f"{obs_bucket}/{test_prefix}/write_1kb_{counter[0]}.bin"
            obs_fs.pipe_file(path, data)

        result = benchmark_runner.run_timed_benchmark(
            "obs/write_1KB", "Write 1KB file", "obs", op,
            data_size=1024,
        )
        print(f"\n  Write 1KB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_write_1mb(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark 1MB file write."""
        data = b"x" * (1024 * 1024)
        counter = [0]

        def op():
            counter[0] += 1
            path = f"{obs_bucket}/{test_prefix}/write_1mb_{counter[0]}.bin"
            obs_fs.pipe_file(path, data)

        result = benchmark_runner.run_timed_benchmark(
            "obs/write_1MB", "Write 1MB file", "obs", op,
            data_size=1024 * 1024,
        )
        print(f"\n  Write 1MB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_write_100mb(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix, benchmark_config):
        """Benchmark 100MB file write."""
        if benchmark_config.mode == "quick":
            pytest.skip("Skipping large file test in quick mode")

        data = b"x" * (100 * 1024 * 1024)
        counter = [0]

        def op():
            counter[0] += 1
            path = f"{obs_bucket}/{test_prefix}/write_100mb_{counter[0]}.bin"
            obs_fs.pipe_file(path, data)

        result = benchmark_runner.run_timed_benchmark(
            "obs/write_100MB", "Write 100MB file", "obs", op,
            data_size=100 * 1024 * 1024,
        )
        print(f"\n  Write 100MB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_read_1kb(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark 1KB file read."""
        # Setup: create file to read
        data = b"x" * 1024
        path = f"{obs_bucket}/{test_prefix}/read_1kb.bin"
        obs_fs.pipe_file(path, data)

        def op():
            obs_fs.cat_file(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/read_1KB", "Read 1KB file", "obs", op,
            data_size=1024,
        )
        print(f"\n  Read 1KB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_read_1mb(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark 1MB file read."""
        # Setup: create file to read
        data = b"x" * (1024 * 1024)
        path = f"{obs_bucket}/{test_prefix}/read_1mb.bin"
        obs_fs.pipe_file(path, data)

        def op():
            obs_fs.cat_file(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/read_1MB", "Read 1MB file", "obs", op,
            data_size=1024 * 1024,
        )
        print(f"\n  Read 1MB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_read_100mb(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix, benchmark_config):
        """Benchmark 100MB file read."""
        if benchmark_config.mode == "quick":
            pytest.skip("Skipping large file test in quick mode")

        # Setup: create file to read
        data = b"x" * (100 * 1024 * 1024)
        path = f"{obs_bucket}/{test_prefix}/read_100mb.bin"
        obs_fs.pipe_file(path, data)

        def op():
            obs_fs.cat_file(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/read_100MB", "Read 100MB file", "obs", op,
            data_size=100 * 1024 * 1024,
        )
        print(f"\n  Read 100MB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_stat(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark stat operation."""
        # Setup: create file
        path = f"{obs_bucket}/{test_prefix}/stat_test.bin"
        obs_fs.pipe_file(path, b"test")

        def op():
            obs_fs.info(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/stat", "Get file stat", "obs", op,
        )
        print(f"\n  Stat: {result.mean:.2f} ms")

    def test_obs_exists(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark exists check."""
        path = f"{obs_bucket}/{test_prefix}/exists_test.bin"
        obs_fs.pipe_file(path, b"test")

        def op():
            obs_fs.exists(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/exists", "Check exists", "obs", op,
        )
        print(f"\n  Exists: {result.mean:.2f} ms")

    def test_obs_list_100(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix, benchmark_config):
        """Benchmark listing 100 files."""
        # Setup: create 100 files
        list_dir = f"{obs_bucket}/{test_prefix}/list_100/"
        for i in range(100):
            obs_fs.pipe_file(f"{list_dir}file_{i:03d}.txt", b"x")

        def op():
            list(obs_fs.ls(list_dir, detail=False))

        result = benchmark_runner.run_timed_benchmark(
            "obs/list_100", "List 100 files", "obs", op,
        )
        print(f"\n  List 100 files: {result.mean:.2f} ms")

    def test_obs_delete(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark delete operation."""
        counter = [0]

        # Pre-create files to delete
        for i in range(benchmark_runner.config.sample_size + 10):
            obs_fs.pipe_file(f"{obs_bucket}/{test_prefix}/delete_{i}.bin", b"x")

        def op():
            counter[0] += 1
            path = f"{obs_bucket}/{test_prefix}/delete_{counter[0]}.bin"
            obs_fs.rm(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/delete", "Delete file", "obs", op,
        )
        print(f"\n  Delete: {result.mean:.2f} ms")

    def test_obs_copy(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark copy operation."""
        # Setup: create source file
        src_path = f"{obs_bucket}/{test_prefix}/copy_src.bin"
        obs_fs.pipe_file(src_path, b"x" * (1024 * 1024))  # 1MB
        counter = [0]

        def op():
            counter[0] += 1
            dst_path = f"{obs_bucket}/{test_prefix}/copy_dst_{counter[0]}.bin"
            obs_fs.copy(src_path, dst_path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/copy", "Copy 1MB file", "obs", op,
            data_size=1024 * 1024,
        )
        print(f"\n  Copy 1MB: {result.mean:.2f} ms")


# ============================================================================
# OBS Concurrent Benchmarks
# ============================================================================

@pytest.mark.obs
class TestOBSConcurrentBenchmarks:
    """OBS concurrent operation benchmarks."""

    @pytest.fixture(autouse=True)
    def check_obs(self, request):
        """Skip if OBS benchmarks not enabled."""
        if not request.config.getoption("--with-obs", False):
            pytest.skip("OBS benchmarks not enabled (use --with-obs)")

    @pytest.mark.parametrize("num_threads", [1, 4, 8, 16])
    def test_obs_concurrent_read(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix, num_threads, benchmark_config):
        """Benchmark concurrent reads."""
        if benchmark_config.mode == "quick" and num_threads > 4:
            pytest.skip("Skipping high concurrency in quick mode")

        # Setup: create files to read
        data = b"x" * (1024 * 1024)  # 1MB
        paths = []
        for i in range(num_threads):
            path = f"{obs_bucket}/{test_prefix}/concurrent_read_{i}.bin"
            obs_fs.pipe_file(path, data)
            paths.append(path)

        def read_file(path):
            obs_fs.cat_file(path)

        samples = []
        for _ in range(benchmark_config.sample_size // 5 or 1):
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(read_file, paths[i % len(paths)]) for i in range(num_threads)]
                for f in as_completed(futures):
                    f.result()
            elapsed = time.perf_counter() - start
            # Throughput: num_threads * 1MB / elapsed
            throughput = (num_threads * 1024 * 1024 / (1024 * 1024)) / elapsed  # MB/s
            samples.append(throughput)

        result = BenchmarkResult(
            benchmark_id=f"obs_concurrent/read_1MB_{num_threads}",
            name=f"Concurrent read 1MB ({num_threads} threads)",
            category="obs_concurrent",
            unit="MB/s",
            data_size=1024 * 1024,
            concurrent_level=num_threads,
        )
        result.samples = samples
        benchmark_runner.results.append(result)

        print(f"\n  Concurrent read ({num_threads} threads): {result.mean:.2f} MB/s")

    @pytest.mark.parametrize("num_threads", [1, 4, 8, 16])
    def test_obs_concurrent_write(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix, num_threads, benchmark_config):
        """Benchmark concurrent writes."""
        if benchmark_config.mode == "quick" and num_threads > 4:
            pytest.skip("Skipping high concurrency in quick mode")

        data = b"x" * (1024 * 1024)  # 1MB
        counter = [0]

        def write_file():
            import threading
            tid = threading.current_thread().ident
            idx = counter[0]
            counter[0] += 1
            path = f"{obs_bucket}/{test_prefix}/concurrent_write_{tid}_{idx}.bin"
            obs_fs.pipe_file(path, data)

        samples = []
        for _ in range(benchmark_config.sample_size // 5 or 1):
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(write_file) for _ in range(num_threads)]
                for f in as_completed(futures):
                    f.result()
            elapsed = time.perf_counter() - start
            throughput = (num_threads * 1024 * 1024 / (1024 * 1024)) / elapsed  # MB/s
            samples.append(throughput)

        result = BenchmarkResult(
            benchmark_id=f"obs_concurrent/write_1MB_{num_threads}",
            name=f"Concurrent write 1MB ({num_threads} threads)",
            category="obs_concurrent",
            unit="MB/s",
            data_size=1024 * 1024,
            concurrent_level=num_threads,
        )
        result.samples = samples
        benchmark_runner.results.append(result)

        print(f"\n  Concurrent write ({num_threads} threads): {result.mean:.2f} MB/s")


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


@pytest.fixture(scope="session", autouse=True)
def generate_report(request, benchmark_runner: BenchmarkRunner):
    """Generate benchmark report after all tests.

    Generates reports in obsfuse-compatible format for project comparison.
    """
    yield

    if not benchmark_runner.results:
        return

    timestamp = datetime.now()
    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

    # Create test-reports directory
    reports_dir = Path(__file__).parent.parent.parent / "test-reports"
    reports_dir.mkdir(exist_ok=True)

    # Generate obsfuse-compatible JSON data (benchmark-data.json)
    # Format: {"timestamp": "...", "benchmarks": {"name": {"mean_ns": ..., "std_dev_ns": ..., "median_ns": ...}}}
    obsfuse_json = {
        "timestamp": timestamp_str,
        "benchmarks": {},
    }

    for result in benchmark_runner.results:
        # Convert to nanoseconds based on unit
        if result.unit == "ops/sec":
            # ops/sec -> ns/op
            mean_ns = 1_000_000_000 / result.mean if result.mean > 0 else 0
            std_dev_ns = (1_000_000_000 / (result.mean - result.std_dev) - mean_ns) if result.mean > result.std_dev else 0
            median_ns = 1_000_000_000 / result.median if result.median > 0 else 0
        elif result.unit == "ms":
            # ms -> ns
            mean_ns = result.mean * 1_000_000
            std_dev_ns = result.std_dev * 1_000_000
            median_ns = result.median * 1_000_000
        else:
            mean_ns = result.mean
            std_dev_ns = result.std_dev
            median_ns = result.median

        # Use benchmark_id with underscores for obsfuse compatibility
        key = result.benchmark_id.replace("/", "_")
        obsfuse_json["benchmarks"][key] = {
            "mean_ns": mean_ns,
            "std_dev_ns": abs(std_dev_ns),
            "median_ns": median_ns,
        }

    json_path = reports_dir / "benchmark-data.json"
    with open(json_path, "w") as f:
        json.dump(obsfuse_json, f, indent=4)

    # Generate obsfuse-compatible Markdown report (benchmark-report.md)
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
                # Convert to nanoseconds for display
                if r.unit == "ops/sec":
                    mean_ns = 1_000_000_000 / r.mean if r.mean > 0 else 0
                    std_ns = (1_000_000_000 / (r.mean - r.std_dev) - mean_ns) if r.mean > r.std_dev else 0
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

        f.write("## Notes\n\n")
        f.write("- All times are in nanoseconds unless otherwise specified\n")
        f.write("- Throughput calculated as operations per second\n")
        f.write("- OBS integration tests require network access and valid credentials\n\n")
        f.write("---\n\n")
        f.write("*Report generated by PyOBS benchmark suite*\n")

    print(f"\n\nBenchmark reports generated:")
    print(f"  - JSON: {json_path}")
    print(f"  - Markdown: {md_path}")
