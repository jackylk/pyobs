#!/usr/bin/env python3
"""Comprehensive benchmark tests for pyobs.

Run with:
    python -m benchmarks.benchmark                    # All benchmarks
    python -m benchmarks.benchmark --local-only       # Local components only
    python -m benchmarks.benchmark --obs-only         # OBS integration only

Generate reports:
    python -m benchmarks.benchmark --report
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@dataclass
class BenchmarkResult:
    """Result of a single benchmark."""
    name: str
    category: str
    iterations: int
    total_time_sec: float
    mean_time_sec: float
    median_time_sec: float
    std_dev_sec: float
    min_time_sec: float
    max_time_sec: float
    p50_sec: float
    p95_sec: float
    p99_sec: float
    ops_per_sec: float
    throughput_mb_sec: Optional[float] = None
    data_size_bytes: Optional[int] = None
    concurrency: Optional[int] = None


@dataclass
class BenchmarkReport:
    """Complete benchmark report."""
    timestamp: str
    environment: Dict[str, Any]
    results: List[BenchmarkResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


def get_environment_info() -> Dict[str, Any]:
    """Collect environment information."""
    return {
        "os": platform.system(),
        "os_version": platform.release(),
        "python_version": platform.python_version(),
        "cpu": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "machine": platform.machine(),
    }


class BenchmarkRunner:
    """Run and collect benchmark results."""

    def __init__(self, warmup: int = 5, iterations: int = 100):
        self.warmup = warmup
        self.iterations = iterations
        self.results: List[BenchmarkResult] = []

    def bench(
        self,
        name: str,
        category: str,
        func: Callable,
        iterations: Optional[int] = None,
        warmup: Optional[int] = None,
        data_size: Optional[int] = None,
        concurrency: Optional[int] = None,
    ) -> BenchmarkResult:
        """Run a benchmark and record results."""
        iters = iterations or self.iterations
        warm = warmup or self.warmup

        # Warmup
        for _ in range(warm):
            func()

        # Measure
        times = []
        for _ in range(iters):
            start = time.perf_counter()
            func()
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        times.sort()
        total = sum(times)
        mean = statistics.mean(times)
        median = statistics.median(times)
        std_dev = statistics.stdev(times) if len(times) > 1 else 0

        # Percentiles
        p50_idx = int(len(times) * 0.50)
        p95_idx = int(len(times) * 0.95)
        p99_idx = int(len(times) * 0.99)

        ops_per_sec = iters / total if total > 0 else 0
        throughput = None
        if data_size:
            throughput = (data_size * iters) / total / (1024 * 1024)  # MB/s

        result = BenchmarkResult(
            name=name,
            category=category,
            iterations=iters,
            total_time_sec=total,
            mean_time_sec=mean,
            median_time_sec=median,
            std_dev_sec=std_dev,
            min_time_sec=min(times),
            max_time_sec=max(times),
            p50_sec=times[p50_idx],
            p95_sec=times[p95_idx],
            p99_sec=times[p99_idx],
            ops_per_sec=ops_per_sec,
            throughput_mb_sec=throughput,
            data_size_bytes=data_size,
            concurrency=concurrency,
        )

        self.results.append(result)
        return result


# ============================================================================
# Local Component Benchmarks
# ============================================================================

def run_local_benchmarks(runner: BenchmarkRunner) -> None:
    """Run local component benchmarks (no network)."""
    from pyobs.utils import (
        split_path, normalize_path, join_path,
        get_parent_path, is_directory_marker,
        ensure_trailing_slash, remove_trailing_slash,
    )

    print("\n=== Local Component Benchmarks ===\n")

    # Path operations
    print("Running path operation benchmarks...")

    test_paths = [
        "bucket/path/to/file.txt",
        "bucket/deeply/nested/directory/structure/file.txt",
        "obs://bucket/key",
        "hwobs://bucket/path/to/object",
    ]

    runner.bench(
        "split_path",
        "path_operations",
        lambda: [split_path(p) for p in test_paths],
        iterations=10000,
    )

    runner.bench(
        "normalize_path",
        "path_operations",
        lambda: [normalize_path(p) for p in test_paths],
        iterations=10000,
    )

    runner.bench(
        "join_path",
        "path_operations",
        lambda: [join_path("bucket", f"key_{i}") for i in range(10)],
        iterations=10000,
    )

    runner.bench(
        "get_parent_path",
        "path_operations",
        lambda: [get_parent_path(p) for p in test_paths],
        iterations=10000,
    )

    runner.bench(
        "is_directory_marker",
        "path_operations",
        lambda: [is_directory_marker(k) for k in ["", "dir/", "file.txt", "a/b/"]],
        iterations=10000,
    )

    runner.bench(
        "ensure_trailing_slash",
        "path_operations",
        lambda: [ensure_trailing_slash(p) for p in ["dir", "dir/", "a/b"]],
        iterations=10000,
    )

    runner.bench(
        "remove_trailing_slash",
        "path_operations",
        lambda: [remove_trailing_slash(p) for p in ["dir/", "dir", "a/b/c/"]],
        iterations=10000,
    )

    # Mock OBS client for filesystem tests
    print("Running filesystem operation benchmarks (mocked)...")

    with patch("pyobs.core.ObsClient") as mock_class:
        mock_client = MagicMock()
        mock_class.return_value = mock_client

        # Setup mock responses
        from tests.conftest import (
            MockResponse, MockListBucketsBody, MockBucket,
            MockListObjectsBody, MockObject, MockGetObjectMetadataBody,
        )

        mock_client.listBuckets.return_value = MockResponse(
            body=MockListBucketsBody([MockBucket(f"bucket-{i}") for i in range(10)])
        )
        mock_client.headBucket.return_value = MockResponse()
        mock_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody(
                contents=[MockObject(f"file_{i}.txt", size=1024) for i in range(100)]
            )
        )
        mock_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(content_length=1024)
        )
        mock_client.putContent.return_value = MockResponse()
        mock_client.deleteObject.return_value = MockResponse()

        from pyobs import OBSFileSystem

        fs = OBSFileSystem(
            key="test-key",
            secret="test-secret",
            endpoint="https://obs.cn-north-4.myhuaweicloud.com",
            skip_instance_cache=True,
        )

        runner.bench(
            "ls_buckets",
            "filesystem_mock",
            lambda: fs.ls(""),
            iterations=1000,
        )

        runner.bench(
            "ls_bucket_contents",
            "filesystem_mock",
            lambda: fs.ls("bucket/"),
            iterations=1000,
        )

        runner.bench(
            "info",
            "filesystem_mock",
            lambda: fs.info("bucket/file.txt"),
            iterations=1000,
        )

        runner.bench(
            "exists",
            "filesystem_mock",
            lambda: fs.exists("bucket/file.txt"),
            iterations=1000,
        )


# ============================================================================
# OBS Integration Benchmarks
# ============================================================================

def run_obs_benchmarks(runner: BenchmarkRunner) -> None:
    """Run OBS integration benchmarks (requires credentials)."""
    from pyobs import OBSFileSystem
    from pyobs.utils import get_credentials_from_env

    key, secret, endpoint, token = get_credentials_from_env()
    test_bucket = os.environ.get("OBS_TEST_BUCKET", "obs-fs-test-jska")

    if not all([key, secret, endpoint]):
        print("Skipping OBS benchmarks: credentials not set")
        return

    print("\n=== OBS Integration Benchmarks ===\n")

    fs = OBSFileSystem(key=key, secret=secret, endpoint=endpoint, token=token)
    test_prefix = f"{test_bucket}/pyobs-bench-{uuid.uuid4().hex[:8]}"

    try:
        # Cleanup old test files
        try:
            fs.rm(test_prefix, recursive=True)
        except Exception:
            pass

        # File sizes for testing
        sizes = [
            (1024, "1KB"),
            (64 * 1024, "64KB"),
            (1024 * 1024, "1MB"),
            (10 * 1024 * 1024, "10MB"),
        ]

        # Write benchmarks
        print("Running write benchmarks...")
        for size, label in sizes:
            data = b"x" * size
            counter = [0]

            def write_func():
                path = f"{test_prefix}/write_{label}_{counter[0]}"
                counter[0] += 1
                fs.pipe_file(path, data)

            result = runner.bench(
                f"write_{label}",
                "obs_write",
                write_func,
                iterations=20 if size >= 10 * 1024 * 1024 else 50,
                warmup=2,
                data_size=size,
            )
            print(f"  write_{label}: {result.throughput_mb_sec:.2f} MB/s")

        # Prepare files for read benchmarks
        print("Preparing files for read benchmarks...")
        for size, label in sizes:
            data = b"y" * size
            fs.pipe_file(f"{test_prefix}/read_{label}", data)

        # Read benchmarks
        print("Running read benchmarks...")
        for size, label in sizes:
            path = f"{test_prefix}/read_{label}"

            result = runner.bench(
                f"read_{label}",
                "obs_read",
                lambda p=path: fs.cat_file(p),
                iterations=20 if size >= 10 * 1024 * 1024 else 50,
                warmup=2,
                data_size=size,
            )
            print(f"  read_{label}: {result.throughput_mb_sec:.2f} MB/s")

        # Range read benchmark
        print("Running range read benchmark...")
        large_path = f"{test_prefix}/read_10MB"
        offset = [0]

        def range_read():
            start = offset[0]
            offset[0] = (offset[0] + 65536) % (9 * 1024 * 1024)
            return fs.cat_file(large_path, start=start, end=start + 65536)

        result = runner.bench(
            "read_range_64KB",
            "obs_read",
            range_read,
            iterations=50,
            warmup=5,
            data_size=65536,
        )
        print(f"  read_range_64KB: {result.throughput_mb_sec:.2f} MB/s")

        # Metadata operations
        print("Running metadata operation benchmarks...")

        runner.bench(
            "stat",
            "obs_metadata",
            lambda: fs.info(f"{test_prefix}/read_1MB"),
            iterations=50,
            warmup=5,
        )

        runner.bench(
            "exists",
            "obs_metadata",
            lambda: fs.exists(f"{test_prefix}/read_1MB"),
            iterations=50,
            warmup=5,
        )

        # Mkdir benchmark
        print("Running mkdir benchmark...")
        mkdir_counter = [0]

        def mkdir_bench():
            path = f"{test_prefix}/mkdir_bench_{mkdir_counter[0]}/"
            mkdir_counter[0] += 1
            fs.mkdir(path)

        runner.bench(
            "mkdir",
            "obs_operations",
            mkdir_bench,
            iterations=30,
            warmup=3,
        )

        # List benchmarks
        print("Preparing files for list benchmark...")
        for i in range(100):
            fs.pipe_file(f"{test_prefix}/list_dir/file_{i:03d}.txt", b"test")

        runner.bench(
            "list_100",
            "obs_metadata",
            lambda: fs.ls(f"{test_prefix}/list_dir/"),
            iterations=30,
            warmup=3,
        )

        # Delete benchmark
        print("Running delete benchmark...")
        delete_counter = [0]

        def delete_bench():
            path = f"{test_prefix}/delete_{delete_counter[0]}"
            delete_counter[0] += 1
            fs.pipe_file(path, b"to delete")
            fs.rm(path)

        runner.bench(
            "delete",
            "obs_operations",
            delete_bench,
            iterations=30,
            warmup=3,
        )

        # Copy benchmark
        print("Running copy benchmark...")
        copy_counter = [0]

        def copy_bench():
            dst = f"{test_prefix}/copy_dst_{copy_counter[0]}"
            copy_counter[0] += 1
            fs.cp_file(f"{test_prefix}/read_1MB", dst)

        runner.bench(
            "copy",
            "obs_operations",
            copy_bench,
            iterations=20,
            warmup=2,
        )

    finally:
        # Cleanup
        print("\nCleaning up test files...")
        try:
            fs.rm(test_prefix, recursive=True)
        except Exception as e:
            print(f"Cleanup warning: {e}")


# ============================================================================
# Concurrent Benchmarks
# ============================================================================

def run_concurrent_benchmarks(runner: BenchmarkRunner) -> None:
    """Run concurrent OBS benchmarks."""
    from pyobs import OBSFileSystem
    from pyobs.utils import get_credentials_from_env

    key, secret, endpoint, token = get_credentials_from_env()
    test_bucket = os.environ.get("OBS_TEST_BUCKET", "obs-fs-test-jska")

    if not all([key, secret, endpoint]):
        print("Skipping concurrent benchmarks: credentials not set")
        return

    print("\n=== Concurrent Benchmarks ===\n")

    fs = OBSFileSystem(key=key, secret=secret, endpoint=endpoint, token=token)
    test_prefix = f"{test_bucket}/pyobs-concurrent-{uuid.uuid4().hex[:8]}"

    concurrent_levels = [1, 2, 4, 8, 16]

    try:
        # Prepare test files
        print("Preparing files for concurrent benchmarks...")
        data_1mb = b"z" * (1024 * 1024)
        for i in range(32):
            fs.pipe_file(f"{test_prefix}/concurrent_read_{i}", data_1mb)

        # Concurrent read benchmarks
        print("Running concurrent read benchmarks...")
        for num_threads in concurrent_levels:
            def concurrent_read():
                def read_file(idx):
                    path = f"{test_prefix}/concurrent_read_{idx % 32}"
                    return fs.cat_file(path)

                with ThreadPoolExecutor(max_workers=num_threads) as executor:
                    futures = [executor.submit(read_file, i) for i in range(num_threads)]
                    for f in as_completed(futures):
                        f.result()

            result = runner.bench(
                f"concurrent_read_{num_threads}t",
                "obs_concurrent",
                concurrent_read,
                iterations=10,
                warmup=2,
                data_size=1024 * 1024 * num_threads,
                concurrency=num_threads,
            )
            print(f"  concurrent_read ({num_threads} threads): {result.throughput_mb_sec:.2f} MB/s")

        # Concurrent write benchmarks
        print("Running concurrent write benchmarks...")
        write_counter = [0]

        for num_threads in concurrent_levels:
            def concurrent_write():
                def write_file(idx):
                    path = f"{test_prefix}/concurrent_write_{write_counter[0]}_{idx}"
                    write_counter[0] += 1
                    fs.pipe_file(path, data_1mb)

                with ThreadPoolExecutor(max_workers=num_threads) as executor:
                    futures = [executor.submit(write_file, i) for i in range(num_threads)]
                    for f in as_completed(futures):
                        f.result()

            result = runner.bench(
                f"concurrent_write_{num_threads}t",
                "obs_concurrent",
                concurrent_write,
                iterations=10,
                warmup=2,
                data_size=1024 * 1024 * num_threads,
                concurrency=num_threads,
            )
            print(f"  concurrent_write ({num_threads} threads): {result.throughput_mb_sec:.2f} MB/s")

        # Mixed read/write workload
        print("Running mixed read/write benchmarks...")
        mixed_counter = [0]

        for num_threads in concurrent_levels:
            def mixed_workload():
                def work(idx):
                    if idx % 5 == 0:  # 20% write
                        path = f"{test_prefix}/mixed_write_{mixed_counter[0]}_{idx}"
                        mixed_counter[0] += 1
                        fs.pipe_file(path, b"x" * 65536)
                    else:  # 80% read
                        path = f"{test_prefix}/concurrent_read_{idx % 32}"
                        fs.cat_file(path)

                with ThreadPoolExecutor(max_workers=num_threads) as executor:
                    futures = [executor.submit(work, i) for i in range(num_threads * 5)]
                    for f in as_completed(futures):
                        f.result()

            runner.bench(
                f"mixed_rw_{num_threads}t",
                "obs_concurrent",
                mixed_workload,
                iterations=5,
                warmup=1,
                concurrency=num_threads,
            )
            print(f"  mixed_rw ({num_threads} threads): done")

    finally:
        # Cleanup
        print("\nCleaning up test files...")
        try:
            fs.rm(test_prefix, recursive=True)
        except Exception as e:
            print(f"Cleanup warning: {e}")


# ============================================================================
# Report Generation
# ============================================================================

def generate_report(report: BenchmarkReport, output_dir: Path) -> None:
    """Generate benchmark reports in multiple formats."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON report (full)
    json_path = output_dir / "benchmark-data.json"
    with open(json_path, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)
    print(f"JSON report: {json_path}")

    # Simplified JSON (compatible with obsfuse format for comparison site)
    simple_path = output_dir / "benchmark-simple.json"
    benchmarks = {}
    for r in report.results:
        benchmarks[r.name] = {
            "mean_ns": r.mean_time_sec * 1e9,
            "std_dev_ns": r.std_dev_sec * 1e9,
            "median_ns": r.median_time_sec * 1e9,
        }
    with open(simple_path, "w") as f:
        json.dump({"timestamp": report.timestamp, "benchmarks": benchmarks}, f, indent=2)
    print(f"Simple JSON report: {simple_path}")

    # Markdown report
    md_path = output_dir / "benchmark-report.md"
    with open(md_path, "w") as f:
        f.write("# PyOBS Performance Benchmark Report\n\n")
        f.write(f"**Generated:** {report.timestamp}\n\n")

        f.write("## Test Environment\n\n")
        f.write("| Property | Value |\n")
        f.write("|----------|-------|\n")
        for key, value in report.environment.items():
            f.write(f"| {key} | {value} |\n")
        f.write("\n")

        f.write("## Summary\n\n")
        categories = {}
        for r in report.results:
            if r.category not in categories:
                categories[r.category] = []
            categories[r.category].append(r)

        f.write(f"- Total benchmarks: {len(report.results)}\n")
        f.write(f"- Categories: {', '.join(categories.keys())}\n\n")

        for category, results in categories.items():
            f.write(f"## {category.replace('_', ' ').title()}\n\n")

            has_throughput = any(r.throughput_mb_sec for r in results)
            has_concurrency = any(r.concurrency for r in results)

            if has_throughput:
                f.write("| Benchmark | Mean | P50 | P99 | ops/sec | MB/s |\n")
                f.write("|-----------|------|-----|-----|---------|------|\n")
                for r in results:
                    throughput = f"{r.throughput_mb_sec:.2f}" if r.throughput_mb_sec else "-"
                    f.write(f"| {r.name} | {r.mean_time_sec*1000:.3f}ms | "
                           f"{r.p50_sec*1000:.3f}ms | {r.p99_sec*1000:.3f}ms | "
                           f"{r.ops_per_sec:.1f} | {throughput} |\n")
            else:
                f.write("| Benchmark | Mean | P50 | P99 | ops/sec |\n")
                f.write("|-----------|------|-----|-----|--------|\n")
                for r in results:
                    f.write(f"| {r.name} | {r.mean_time_sec*1000:.3f}ms | "
                           f"{r.p50_sec*1000:.3f}ms | {r.p99_sec*1000:.3f}ms | "
                           f"{r.ops_per_sec:.1f} |\n")
            f.write("\n")

        # Concurrent scaling analysis
        concurrent_results = [r for r in report.results if r.concurrency]
        if concurrent_results:
            f.write("## Concurrent Scaling Analysis\n\n")

            # Group by operation type
            read_results = [r for r in concurrent_results if "read" in r.name and "mixed" not in r.name]
            write_results = [r for r in concurrent_results if "write" in r.name and "mixed" not in r.name]

            if read_results:
                base = next((r for r in read_results if r.concurrency == 1), None)
                if base and base.throughput_mb_sec:
                    f.write("### Read Scaling\n\n")
                    f.write("| Threads | Throughput (MB/s) | Scaling Efficiency |\n")
                    f.write("|---------|-------------------|--------------------|\n")
                    for r in sorted(read_results, key=lambda x: x.concurrency or 0):
                        if r.throughput_mb_sec:
                            efficiency = (r.throughput_mb_sec / (base.throughput_mb_sec * r.concurrency)) * 100
                            f.write(f"| {r.concurrency} | {r.throughput_mb_sec:.2f} | {efficiency:.1f}% |\n")
                    f.write("\n")

            if write_results:
                base = next((r for r in write_results if r.concurrency == 1), None)
                if base and base.throughput_mb_sec:
                    f.write("### Write Scaling\n\n")
                    f.write("| Threads | Throughput (MB/s) | Scaling Efficiency |\n")
                    f.write("|---------|-------------------|--------------------|\n")
                    for r in sorted(write_results, key=lambda x: x.concurrency or 0):
                        if r.throughput_mb_sec:
                            efficiency = (r.throughput_mb_sec / (base.throughput_mb_sec * r.concurrency)) * 100
                            f.write(f"| {r.concurrency} | {r.throughput_mb_sec:.2f} | {efficiency:.1f}% |\n")
                    f.write("\n")

    print(f"Markdown report: {md_path}")


def load_obsfuse_results(obsfuse_perf_dir: Path) -> Optional[Dict[str, Any]]:
    """Load obsfuse benchmark results for comparison."""
    json_path = obsfuse_perf_dir / "benchmark-data.json"
    if json_path.exists():
        with open(json_path) as f:
            return json.load(f)
    return None


def generate_comparison_report(
    pyobs_report: BenchmarkReport,
    obsfuse_results: Optional[Dict[str, Any]],
    output_dir: Path
) -> None:
    """Generate comparison report between pyobs and obsfuse."""
    md_path = output_dir / "comparison-report.md"

    with open(md_path, "w") as f:
        f.write("# PyOBS vs OBSFuse Performance Comparison\n\n")
        f.write(f"**Generated:** {pyobs_report.timestamp}\n\n")

        f.write("## Overview\n\n")
        f.write("This report compares the performance of:\n")
        f.write("- **PyOBS**: Python fsspec implementation for Huawei OBS\n")
        f.write("- **OBSFuse**: Rust FUSE implementation for Huawei OBS\n\n")

        f.write("## Architecture Differences\n\n")
        f.write("| Aspect | PyOBS | OBSFuse |\n")
        f.write("|--------|-------|--------|\n")
        f.write("| Language | Python | Rust |\n")
        f.write("| Interface | fsspec API | FUSE filesystem |\n")
        f.write("| Concurrency | Thread-based | Async (tokio) |\n")
        f.write("| OBS SDK | esdk-obs-python | opendal |\n")
        f.write("| Use Case | Data science, ETL | System-level mount |\n\n")

        f.write("## Performance Summary\n\n")

        # PyOBS results summary
        f.write("### PyOBS Results\n\n")

        obs_results = [r for r in pyobs_report.results if r.category.startswith("obs_")]
        if obs_results:
            f.write("| Operation | Mean Latency | Throughput |\n")
            f.write("|-----------|--------------|------------|\n")
            for r in obs_results:
                throughput = f"{r.throughput_mb_sec:.2f} MB/s" if r.throughput_mb_sec else "-"
                f.write(f"| {r.name} | {r.mean_time_sec*1000:.1f}ms | {throughput} |\n")
            f.write("\n")

        # Comparison notes
        f.write("### Expected Differences\n\n")
        f.write("1. **Raw Throughput**: OBSFuse (Rust) typically achieves higher raw throughput due to:\n")
        f.write("   - Zero-copy operations\n")
        f.write("   - Native async I/O\n")
        f.write("   - Lower memory overhead\n\n")
        f.write("2. **Latency**: PyOBS may have higher per-operation latency due to:\n")
        f.write("   - Python interpreter overhead\n")
        f.write("   - GIL contention in concurrent scenarios\n")
        f.write("   - SDK abstraction layers\n\n")
        f.write("3. **Concurrent Scaling**: OBSFuse scales better with thread count due to:\n")
        f.write("   - True parallel execution (no GIL)\n")
        f.write("   - Efficient async task scheduling\n\n")

        f.write("### When to Use Each\n\n")
        f.write("| Scenario | Recommended |\n")
        f.write("|----------|-------------|\n")
        f.write("| Data science workflows | PyOBS |\n")
        f.write("| Pandas/Dask integration | PyOBS |\n")
        f.write("| System-level file access | OBSFuse |\n")
        f.write("| High-throughput streaming | OBSFuse |\n")
        f.write("| Quick prototyping | PyOBS |\n")
        f.write("| Production data pipelines | Either (depends on stack) |\n\n")

        if obsfuse_results:
            f.write("### Direct Comparison (if data available)\n\n")
            f.write("*OBSFuse benchmark data loaded from previous run.*\n\n")
            # Add detailed comparison if obsfuse data is available
        else:
            f.write("### Direct Comparison\n\n")
            f.write("*Run OBSFuse benchmarks to enable direct comparison.*\n\n")
            f.write("```bash\n")
            f.write("cd /Users/jacky/code/obsfuse\n")
            f.write("cargo bench --features obs-bench\n")
            f.write("```\n\n")

    print(f"Comparison report: {md_path}")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="PyOBS Benchmark Suite")
    parser.add_argument("--local-only", action="store_true", help="Run only local benchmarks")
    parser.add_argument("--obs-only", action="store_true", help="Run only OBS integration benchmarks")
    parser.add_argument("--concurrent-only", action="store_true", help="Run only concurrent benchmarks")
    parser.add_argument("--report", action="store_true", help="Generate reports")
    parser.add_argument("--output", type=str, default="perf", help="Output directory for reports")
    parser.add_argument("--compare", action="store_true", help="Generate comparison with obsfuse")
    args = parser.parse_args()

    print("=" * 60)
    print("PyOBS Benchmark Suite")
    print("=" * 60)

    runner = BenchmarkRunner(warmup=5, iterations=100)

    run_local = not args.obs_only and not args.concurrent_only
    run_obs = not args.local_only and not args.concurrent_only
    run_concurrent = not args.local_only and not args.obs_only or args.concurrent_only

    if run_local:
        run_local_benchmarks(runner)

    if run_obs:
        run_obs_benchmarks(runner)

    if run_concurrent:
        run_concurrent_benchmarks(runner)

    # Generate report
    report = BenchmarkReport(
        timestamp=datetime.now().isoformat(),
        environment=get_environment_info(),
        results=runner.results,
    )

    output_dir = Path(args.output)

    if args.report or True:  # Always generate report
        generate_report(report, output_dir)

    if args.compare:
        obsfuse_results = load_obsfuse_results(Path("/Users/jacky/code/obsfuse/perf"))
        generate_comparison_report(report, obsfuse_results, output_dir)

    print("\n" + "=" * 60)
    print("Benchmark complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
