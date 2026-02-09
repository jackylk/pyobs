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

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pyobsfs import OBSFileSystem
from pyobsfs.utils import get_parent_path, join_path

# Import shared benchmark infrastructure from conftest
from .conftest import BenchmarkConfig, BenchmarkResult, BenchmarkRunner


# ============================================================================
# Fixtures
# ============================================================================


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
            "path/join",
            "Join paths",
            "local",
            op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_path_parent(self, benchmark_runner: BenchmarkRunner):
        """Benchmark get parent path operation."""

        def op():
            get_parent_path("bucket/dir1/dir2/file.txt")

        result = benchmark_runner.run_benchmark(
            "path/parent",
            "Get parent path",
            "local",
            op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_path_filename(self, benchmark_runner: BenchmarkRunner):
        """Benchmark get filename operation."""

        def op():
            path = "bucket/dir1/dir2/file.txt"
            path.rsplit("/", 1)[-1]

        result = benchmark_runner.run_benchmark(
            "path/filename",
            "Get filename",
            "local",
            op,
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

    def test_obs_write_1kb(
        self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix
    ):
        """Benchmark 1KB file write."""
        data = b"x" * 1024
        counter = [0]

        def op():
            counter[0] += 1
            path = f"{obs_bucket}/{test_prefix}/write_1kb_{counter[0]}.bin"
            obs_fs.pipe_file(path, data)

        result = benchmark_runner.run_timed_benchmark(
            "obs/write_1KB",
            "Write 1KB file",
            "obs",
            op,
            data_size=1024,
        )
        print(f"\n  Write 1KB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_write_1mb(
        self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix
    ):
        """Benchmark 1MB file write."""
        data = b"x" * (1024 * 1024)
        counter = [0]

        def op():
            counter[0] += 1
            path = f"{obs_bucket}/{test_prefix}/write_1mb_{counter[0]}.bin"
            obs_fs.pipe_file(path, data)

        result = benchmark_runner.run_timed_benchmark(
            "obs/write_1MB",
            "Write 1MB file",
            "obs",
            op,
            data_size=1024 * 1024,
        )
        print(f"\n  Write 1MB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_write_100mb(
        self,
        benchmark_runner: BenchmarkRunner,
        obs_fs,
        obs_bucket,
        test_prefix,
        benchmark_config,
    ):
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
            "obs/write_100MB",
            "Write 100MB file",
            "obs",
            op,
            data_size=100 * 1024 * 1024,
        )
        print(
            f"\n  Write 100MB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)"
        )

    def test_obs_read_1kb(
        self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix
    ):
        """Benchmark 1KB file read."""
        # Setup: create file to read
        data = b"x" * 1024
        path = f"{obs_bucket}/{test_prefix}/read_1kb.bin"
        obs_fs.pipe_file(path, data)

        def op():
            obs_fs.cat_file(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/read_1KB",
            "Read 1KB file",
            "obs",
            op,
            data_size=1024,
        )
        print(f"\n  Read 1KB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_read_1mb(
        self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix
    ):
        """Benchmark 1MB file read."""
        # Setup: create file to read
        data = b"x" * (1024 * 1024)
        path = f"{obs_bucket}/{test_prefix}/read_1mb.bin"
        obs_fs.pipe_file(path, data)

        def op():
            obs_fs.cat_file(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/read_1MB",
            "Read 1MB file",
            "obs",
            op,
            data_size=1024 * 1024,
        )
        print(f"\n  Read 1MB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)")

    def test_obs_read_100mb(
        self,
        benchmark_runner: BenchmarkRunner,
        obs_fs,
        obs_bucket,
        test_prefix,
        benchmark_config,
    ):
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
            "obs/read_100MB",
            "Read 100MB file",
            "obs",
            op,
            data_size=100 * 1024 * 1024,
        )
        print(
            f"\n  Read 100MB: {result.mean:.2f} ms (throughput: {result.throughput_mbps:.2f} MB/s)"
        )

    def test_obs_stat(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark stat operation."""
        # Setup: create file
        path = f"{obs_bucket}/{test_prefix}/stat_test.bin"
        obs_fs.pipe_file(path, b"test")

        def op():
            obs_fs.info(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/stat",
            "Get file stat",
            "obs",
            op,
        )
        print(f"\n  Stat: {result.mean:.2f} ms")

    def test_obs_exists(self, benchmark_runner: BenchmarkRunner, obs_fs, obs_bucket, test_prefix):
        """Benchmark exists check."""
        path = f"{obs_bucket}/{test_prefix}/exists_test.bin"
        obs_fs.pipe_file(path, b"test")

        def op():
            obs_fs.exists(path)

        result = benchmark_runner.run_timed_benchmark(
            "obs/exists",
            "Check exists",
            "obs",
            op,
        )
        print(f"\n  Exists: {result.mean:.2f} ms")

    def test_obs_list_100(
        self,
        benchmark_runner: BenchmarkRunner,
        obs_fs,
        obs_bucket,
        test_prefix,
        benchmark_config,
    ):
        """Benchmark listing 100 files."""
        # Setup: create 100 files
        list_dir = f"{obs_bucket}/{test_prefix}/list_100/"
        for i in range(100):
            obs_fs.pipe_file(f"{list_dir}file_{i:03d}.txt", b"x")

        def op():
            list(obs_fs.ls(list_dir, detail=False))

        result = benchmark_runner.run_timed_benchmark(
            "obs/list_100",
            "List 100 files",
            "obs",
            op,
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
            "obs/delete",
            "Delete file",
            "obs",
            op,
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
            "obs/copy",
            "Copy 1MB file",
            "obs",
            op,
            data_size=1024 * 1024,
        )
        print(f"\n  Copy 1MB: {result.mean:.2f} ms")


# ============================================================================
# OBS REST API Benchmarks
# ============================================================================


@pytest.mark.obs
class TestOBSRestBenchmarks:
    """OBS REST API benchmarks - measures raw HTTP overhead without fsspec."""

    @pytest.fixture(autouse=True)
    def check_obs(self, request):
        """Skip if OBS benchmarks not enabled."""
        if not request.config.getoption("--with-obs", False):
            pytest.skip("OBS benchmarks not enabled (use --with-obs)")

    def test_obs_rest_write_1kb(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark 1KB file write via REST API."""
        data = b"x" * 1024
        counter = [0]

        def op():
            counter[0] += 1
            obs_rest_client.put_object(obs_bucket, f"{test_prefix}/rest_write_1kb_{counter[0]}.bin", data)

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/write_1KB", "REST Write 1KB", "obs_rest", op, data_size=1024,
        )
        print(f"\n  REST Write 1KB: {result.mean:.2f} ms")

    def test_obs_rest_write_1mb(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark 1MB file write via REST API."""
        data = b"x" * (1024 * 1024)
        counter = [0]

        def op():
            counter[0] += 1
            obs_rest_client.put_object(obs_bucket, f"{test_prefix}/rest_write_1mb_{counter[0]}.bin", data)

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/write_1MB", "REST Write 1MB", "obs_rest", op, data_size=1024 * 1024,
        )
        print(f"\n  REST Write 1MB: {result.mean:.2f} ms")

    def test_obs_rest_read_1kb(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark 1KB file read via REST API."""
        data = b"x" * 1024
        key = f"{test_prefix}/rest_read_1kb.bin"
        obs_rest_client.put_object(obs_bucket, key, data)

        def op():
            obs_rest_client.get_object(obs_bucket, key)

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/read_1KB", "REST Read 1KB", "obs_rest", op, data_size=1024,
        )
        print(f"\n  REST Read 1KB: {result.mean:.2f} ms")

    def test_obs_rest_read_1mb(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark 1MB file read via REST API."""
        data = b"x" * (1024 * 1024)
        key = f"{test_prefix}/rest_read_1mb.bin"
        obs_rest_client.put_object(obs_bucket, key, data)

        def op():
            obs_rest_client.get_object(obs_bucket, key)

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/read_1MB", "REST Read 1MB", "obs_rest", op, data_size=1024 * 1024,
        )
        print(f"\n  REST Read 1MB: {result.mean:.2f} ms")

    def test_obs_rest_stat(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark HEAD (stat) via REST API."""
        key = f"{test_prefix}/rest_stat_test.bin"
        obs_rest_client.put_object(obs_bucket, key, b"test")

        def op():
            obs_rest_client.head_object(obs_bucket, key)

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/stat", "REST Stat (HEAD)", "obs_rest", op,
        )
        print(f"\n  REST Stat: {result.mean:.2f} ms")

    def test_obs_rest_exists(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark exists check via REST API."""
        key = f"{test_prefix}/rest_exists_test.bin"
        obs_rest_client.put_object(obs_bucket, key, b"test")

        def op():
            obs_rest_client.exists(obs_bucket, key)

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/exists", "REST Exists (HEAD)", "obs_rest", op,
        )
        print(f"\n  REST Exists: {result.mean:.2f} ms")

    def test_obs_rest_list_100(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark listing 100 files via REST API."""
        list_prefix = f"{test_prefix}/rest_list_100/"
        for i in range(100):
            obs_rest_client.put_object(obs_bucket, f"{list_prefix}file_{i:03d}.txt", b"x")

        def op():
            obs_rest_client.list_objects(obs_bucket, prefix=list_prefix)

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/list_100", "REST List 100 files", "obs_rest", op,
        )
        print(f"\n  REST List 100: {result.mean:.2f} ms")

    def test_obs_rest_delete(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark delete via REST API."""
        counter = [0]

        for i in range(60):
            obs_rest_client.put_object(obs_bucket, f"{test_prefix}/rest_delete_{i}.bin", b"x")

        def op():
            counter[0] += 1
            obs_rest_client.delete_object(obs_bucket, f"{test_prefix}/rest_delete_{counter[0]}.bin")

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/delete", "REST Delete", "obs_rest", op,
        )
        print(f"\n  REST Delete: {result.mean:.2f} ms")

    def test_obs_rest_copy(
        self, benchmark_runner: BenchmarkRunner, obs_rest_client, obs_bucket, test_prefix
    ):
        """Benchmark copy via REST API."""
        src_key = f"{test_prefix}/rest_copy_src.bin"
        obs_rest_client.put_object(obs_bucket, src_key, b"x" * (1024 * 1024))
        counter = [0]

        def op():
            counter[0] += 1
            obs_rest_client.copy_object(obs_bucket, src_key, f"{test_prefix}/rest_copy_dst_{counter[0]}.bin")

        result = benchmark_runner.run_timed_benchmark(
            "obs_rest/copy", "REST Copy 1MB", "obs_rest", op, data_size=1024 * 1024,
        )
        print(f"\n  REST Copy 1MB: {result.mean:.2f} ms")


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
    def test_obs_concurrent_read(
        self,
        benchmark_runner: BenchmarkRunner,
        obs_fs,
        obs_bucket,
        test_prefix,
        num_threads,
        benchmark_config,
    ):
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
                futures = [
                    executor.submit(read_file, paths[i % len(paths)]) for i in range(num_threads)
                ]
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
    def test_obs_concurrent_write(
        self,
        benchmark_runner: BenchmarkRunner,
        obs_fs,
        obs_bucket,
        test_prefix,
        num_threads,
        benchmark_config,
    ):
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
