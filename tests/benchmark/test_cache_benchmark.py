"""Cache component performance benchmark tests.

Benchmarks matching obsfuse format for direct comparison:
- Inode operations
- Cache operations (metadata, data)
- Path operations
- Readahead operations
- Concurrent operations

Run with:
    pytest tests/benchmark/test_cache_benchmark.py -v              # All benchmarks
    pytest tests/benchmark/test_cache_benchmark.py -v --quick      # Quick mode
    pytest tests/benchmark/test_cache_benchmark.py -v -k "inode"   # Inode only
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pyobs.cache import (
    DataCache,
    DataCacheConfig,
    InodeManager,
    MetadataCache,
    MetadataCacheConfig,
    ReadaheadConfig,
    ReadaheadManager,
)
from pyobs.utils import get_parent_path, join_path

from .conftest import BenchmarkConfig, BenchmarkResult, BenchmarkRunner


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def inode_manager():
    """Create a fresh InodeManager for each test."""
    return InodeManager()


@pytest.fixture
def metadata_cache():
    """Create a fresh MetadataCache for each test."""
    return MetadataCache(MetadataCacheConfig(max_attrs=100000, max_dirs=10000))


@pytest.fixture
def data_cache():
    """Create a fresh DataCache for each test."""
    return DataCache(DataCacheConfig(max_memory_bytes=512 * 1024 * 1024))


@pytest.fixture
def data_cache_with_disk(tmp_path):
    """Create a DataCache with disk backing."""
    return DataCache(
        DataCacheConfig(
            max_memory_bytes=64 * 1024 * 1024,
            max_disk_bytes=256 * 1024 * 1024,
            disk_cache_dir=tmp_path / "cache",
        )
    )


@pytest.fixture
def readahead_manager():
    """Create a fresh ReadaheadManager for each test."""
    return ReadaheadManager(ReadaheadConfig())


# ============================================================================
# Inode Operation Benchmarks
# ============================================================================


class TestInodeBenchmarks:
    """Inode operation benchmarks."""

    def test_inode_create(self, benchmark_runner: BenchmarkRunner, inode_manager: InodeManager):
        """Benchmark inode creation."""
        counter = [0]

        def op():
            counter[0] += 1
            inode_manager.get_or_create_inode(f"bucket/dir/file_{counter[0]}.txt")

        result = benchmark_runner.run_benchmark(
            "inode/create",
            "Create inode",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 10000, f"Expected >10K ops/sec, got {result.ops_per_sec:.0f}"

    def test_inode_lookup_existing(
        self, benchmark_runner: BenchmarkRunner, inode_manager: InodeManager
    ):
        """Benchmark looking up existing inodes."""
        # Pre-populate
        paths = [f"bucket/dir/file_{i}.txt" for i in range(1000)]
        for path in paths:
            inode_manager.get_or_create_inode(path)

        counter = [0]

        def op():
            counter[0] = (counter[0] + 1) % len(paths)
            inode_manager.get_inode(paths[counter[0]])

        result = benchmark_runner.run_benchmark(
            "inode/lookup_existing",
            "Lookup existing inode",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_inode_get_path(self, benchmark_runner: BenchmarkRunner, inode_manager: InodeManager):
        """Benchmark inode to path lookup."""
        # Pre-populate
        inodes = []
        for i in range(1000):
            inode = inode_manager.get_or_create_inode(f"bucket/dir/file_{i}.txt")
            inodes.append(inode)

        counter = [0]

        def op():
            counter[0] = (counter[0] + 1) % len(inodes)
            inode_manager.get_path(inodes[counter[0]])

        result = benchmark_runner.run_benchmark(
            "inode/get_path",
            "Get path from inode",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_inode_update_size(
        self, benchmark_runner: BenchmarkRunner, inode_manager: InodeManager
    ):
        """Benchmark updating inode size."""
        # Pre-populate
        inodes = []
        for i in range(1000):
            inode = inode_manager.get_or_create_inode(f"bucket/dir/file_{i}.txt")
            inodes.append(inode)

        counter = [0]

        def op():
            counter[0] = (counter[0] + 1) % len(inodes)
            inode_manager.update_size(inodes[counter[0]], counter[0] * 1024)

        result = benchmark_runner.run_benchmark(
            "inode/update_size",
            "Update inode size",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_inode_rename(self, benchmark_runner: BenchmarkRunner, inode_manager: InodeManager):
        """Benchmark inode rename."""
        # Pre-populate
        for i in range(10000):
            inode_manager.get_or_create_inode(f"bucket/dir/file_{i}.txt")

        counter = [0]

        def op():
            old_path = f"bucket/dir/file_{counter[0]}.txt"
            new_path = f"bucket/dir/renamed_{counter[0]}.txt"
            inode_manager.rename(old_path, new_path)
            # Rename back for next iteration
            inode_manager.rename(new_path, old_path)
            counter[0] = (counter[0] + 1) % 10000

        result = benchmark_runner.run_benchmark(
            "inode/rename",
            "Rename inode",
            "cache",
            op,
            iterations_per_sample=50,
        )
        assert result.ops_per_sec > 10000, f"Expected >10K ops/sec, got {result.ops_per_sec:.0f}"


# ============================================================================
# Metadata Cache Benchmarks
# ============================================================================


class TestMetadataCacheBenchmarks:
    """Metadata cache benchmarks."""

    def test_cache_metadata_put(
        self, benchmark_runner: BenchmarkRunner, metadata_cache: MetadataCache
    ):
        """Benchmark metadata cache put."""
        counter = [0]

        def op():
            counter[0] += 1
            metadata_cache.put_attr(
                f"bucket/dir/file_{counter[0]}.txt",
                size=counter[0] * 1024,
                is_dir=False,
                mtime=time.time(),
            )

        result = benchmark_runner.run_benchmark(
            "cache/metadata_put",
            "Put metadata",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 50000, f"Expected >50K ops/sec, got {result.ops_per_sec:.0f}"

    def test_cache_metadata_get_hit(
        self, benchmark_runner: BenchmarkRunner, metadata_cache: MetadataCache
    ):
        """Benchmark metadata cache hit."""
        # Pre-populate
        paths = [f"bucket/dir/file_{i}.txt" for i in range(1000)]
        for i, path in enumerate(paths):
            metadata_cache.put_attr(path, size=i * 1024, is_dir=False, mtime=time.time())

        counter = [0]

        def op():
            counter[0] = (counter[0] + 1) % len(paths)
            metadata_cache.get_attr(paths[counter[0]])

        result = benchmark_runner.run_benchmark(
            "cache/metadata_get_hit",
            "Get metadata (hit)",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_cache_metadata_get_miss(
        self, benchmark_runner: BenchmarkRunner, metadata_cache: MetadataCache
    ):
        """Benchmark metadata cache miss."""
        counter = [0]

        def op():
            counter[0] += 1
            metadata_cache.get_attr(f"bucket/nonexistent/file_{counter[0]}.txt")

        result = benchmark_runner.run_benchmark(
            "cache/metadata_get_miss",
            "Get metadata (miss)",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 100000, f"Expected >100K ops/sec, got {result.ops_per_sec:.0f}"

    def test_cache_dir_put(
        self, benchmark_runner: BenchmarkRunner, metadata_cache: MetadataCache
    ):
        """Benchmark directory cache put."""
        entries = [(f"file_{i}.txt", False, i * 1024) for i in range(100)]
        counter = [0]

        def op():
            counter[0] += 1
            metadata_cache.put_dir(f"bucket/dir_{counter[0]}", entries)

        result = benchmark_runner.run_benchmark(
            "cache/dir_put",
            "Put directory listing",
            "cache",
            op,
            iterations_per_sample=50,
        )
        assert result.ops_per_sec > 10000, f"Expected >10K ops/sec, got {result.ops_per_sec:.0f}"

    def test_cache_dir_get_hit(
        self, benchmark_runner: BenchmarkRunner, metadata_cache: MetadataCache
    ):
        """Benchmark directory cache hit."""
        # Pre-populate
        entries = [(f"file_{i}.txt", False, i * 1024) for i in range(100)]
        dirs = [f"bucket/dir_{i}" for i in range(100)]
        for d in dirs:
            metadata_cache.put_dir(d, entries)

        counter = [0]

        def op():
            counter[0] = (counter[0] + 1) % len(dirs)
            metadata_cache.get_dir(dirs[counter[0]])

        result = benchmark_runner.run_benchmark(
            "cache/dir_get_hit",
            "Get directory (hit)",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 50000, f"Expected >50K ops/sec, got {result.ops_per_sec:.0f}"


# ============================================================================
# Data Cache Benchmarks
# ============================================================================


class TestDataCacheBenchmarks:
    """Data cache benchmarks."""

    def test_cache_data_put_4kb(self, benchmark_runner: BenchmarkRunner, data_cache: DataCache):
        """Benchmark 4KB data cache put."""
        data = b"x" * 4096
        counter = [0]

        def op():
            counter[0] += 1
            data_cache.put(counter[0] % 1000, counter[0] * 4096, data)

        result = benchmark_runner.run_benchmark(
            "cache/data_put/4KB",
            "Put 4KB block",
            "cache",
            op,
            iterations_per_sample=100,
            data_size=4096,
        )
        assert result.ops_per_sec > 10000, f"Expected >10K ops/sec, got {result.ops_per_sec:.0f}"

    def test_cache_data_put_64kb(self, benchmark_runner: BenchmarkRunner, data_cache: DataCache):
        """Benchmark 64KB data cache put."""
        data = b"x" * 65536
        counter = [0]

        def op():
            counter[0] += 1
            data_cache.put(counter[0] % 1000, counter[0] * 65536, data)

        result = benchmark_runner.run_benchmark(
            "cache/data_put/64KB",
            "Put 64KB block",
            "cache",
            op,
            iterations_per_sample=50,
            data_size=65536,
        )
        assert result.ops_per_sec > 5000, f"Expected >5K ops/sec, got {result.ops_per_sec:.0f}"

    def test_cache_data_get_hit_4kb(
        self, benchmark_runner: BenchmarkRunner, data_cache: DataCache
    ):
        """Benchmark 4KB data cache hit."""
        # Pre-populate
        data = b"x" * 4096
        for i in range(1000):
            data_cache.put(i, 0, data)

        counter = [0]

        def op():
            counter[0] = (counter[0] + 1) % 1000
            data_cache.get(counter[0], 0)

        result = benchmark_runner.run_benchmark(
            "cache/data_get_hit/4KB",
            "Get 4KB block (hit)",
            "cache",
            op,
            iterations_per_sample=100,
            data_size=4096,
        )
        assert result.ops_per_sec > 50000, f"Expected >50K ops/sec, got {result.ops_per_sec:.0f}"

    def test_cache_data_get_hit_64kb(
        self, benchmark_runner: BenchmarkRunner, data_cache: DataCache
    ):
        """Benchmark 64KB data cache hit."""
        # Pre-populate
        data = b"x" * 65536
        for i in range(500):
            data_cache.put(i, 0, data)

        counter = [0]

        def op():
            counter[0] = (counter[0] + 1) % 500
            data_cache.get(counter[0], 0)

        result = benchmark_runner.run_benchmark(
            "cache/data_get_hit/64KB",
            "Get 64KB block (hit)",
            "cache",
            op,
            iterations_per_sample=100,
            data_size=65536,
        )
        assert result.ops_per_sec > 50000, f"Expected >50K ops/sec, got {result.ops_per_sec:.0f}"

    def test_cache_data_invalidate(
        self, benchmark_runner: BenchmarkRunner, data_cache: DataCache
    ):
        """Benchmark data cache invalidation."""
        # Pre-populate
        data = b"x" * 4096
        for i in range(1000):
            for j in range(10):
                data_cache.put(i, j * 4096, data)

        counter = [0]

        def op():
            inode = counter[0] % 1000
            data_cache.invalidate(inode)
            # Re-populate for next iteration
            for j in range(10):
                data_cache.put(inode, j * 4096, data)
            counter[0] += 1

        result = benchmark_runner.run_benchmark(
            "cache/data_invalidate",
            "Invalidate inode cache",
            "cache",
            op,
            iterations_per_sample=20,
        )
        assert result.ops_per_sec > 1000, f"Expected >1K ops/sec, got {result.ops_per_sec:.0f}"


# ============================================================================
# Path Operation Benchmarks
# ============================================================================


class TestPathBenchmarks:
    """Path operation benchmarks."""

    def test_path_join(self, benchmark_runner: BenchmarkRunner):
        """Benchmark path join."""

        def op():
            join_path("bucket/dir1/dir2", "file.txt")

        result = benchmark_runner.run_benchmark(
            "path/join",
            "Join paths",
            "cache",
            op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 500000, f"Expected >500K ops/sec, got {result.ops_per_sec:.0f}"

    def test_path_parent(self, benchmark_runner: BenchmarkRunner):
        """Benchmark get parent path."""

        def op():
            get_parent_path("bucket/dir1/dir2/file.txt")

        result = benchmark_runner.run_benchmark(
            "path/parent",
            "Get parent path",
            "cache",
            op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 500000, f"Expected >500K ops/sec, got {result.ops_per_sec:.0f}"

    def test_path_file_name(self, benchmark_runner: BenchmarkRunner):
        """Benchmark get file name."""

        def op():
            path = "bucket/dir1/dir2/file.txt"
            path.rsplit("/", 1)[-1]

        result = benchmark_runner.run_benchmark(
            "path/file_name",
            "Get file name",
            "cache",
            op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 500000, f"Expected >500K ops/sec, got {result.ops_per_sec:.0f}"

    def test_path_join_deep(self, benchmark_runner: BenchmarkRunner):
        """Benchmark deep path join."""

        def op():
            join_path("bucket/a/b/c/d/e/f/g/h/i/j", "file.txt")

        result = benchmark_runner.run_benchmark(
            "path/join_deep",
            "Join deep paths",
            "cache",
            op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 500000, f"Expected >500K ops/sec, got {result.ops_per_sec:.0f}"

    def test_path_parent_deep(self, benchmark_runner: BenchmarkRunner):
        """Benchmark deep parent path."""

        def op():
            get_parent_path("bucket/a/b/c/d/e/f/g/h/i/j/file.txt")

        result = benchmark_runner.run_benchmark(
            "path/parent_deep",
            "Get deep parent path",
            "cache",
            op,
            iterations_per_sample=1000,
        )
        assert result.ops_per_sec > 500000, f"Expected >500K ops/sec, got {result.ops_per_sec:.0f}"


# ============================================================================
# Readahead Benchmarks
# ============================================================================


class TestReadaheadBenchmarks:
    """Readahead operation benchmarks."""

    def test_readahead_record_read(
        self, benchmark_runner: BenchmarkRunner, readahead_manager: ReadaheadManager
    ):
        """Benchmark recording reads."""
        counter = [0]

        def op():
            counter[0] += 1
            readahead_manager.record_read(counter[0] % 100, counter[0] * 4096, 4096)

        result = benchmark_runner.run_benchmark(
            "readahead/record_read",
            "Record read",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 50000, f"Expected >50K ops/sec, got {result.ops_per_sec:.0f}"

    def test_readahead_sequential_detection(
        self, benchmark_runner: BenchmarkRunner, readahead_manager: ReadaheadManager
    ):
        """Benchmark sequential read detection."""
        # Simulate sequential reads
        inode = 1
        offset = [0]

        def op():
            readahead_manager.record_read(inode, offset[0], 4096)
            offset[0] += 4096
            if offset[0] > 1024 * 1024:
                offset[0] = 0

        result = benchmark_runner.run_benchmark(
            "readahead/sequential_detection",
            "Sequential detection",
            "cache",
            op,
            iterations_per_sample=100,
        )
        assert result.ops_per_sec > 50000, f"Expected >50K ops/sec, got {result.ops_per_sec:.0f}"

    def test_readahead_store_prefetch(
        self, benchmark_runner: BenchmarkRunner, readahead_manager: ReadaheadManager
    ):
        """Benchmark storing prefetched data."""
        data = b"x" * 65536
        counter = [0]

        def op():
            counter[0] += 1
            readahead_manager.store_prefetched(counter[0] % 100, counter[0] * 65536, data)

        result = benchmark_runner.run_benchmark(
            "readahead/store_prefetch",
            "Store prefetch",
            "cache",
            op,
            iterations_per_sample=50,
        )
        assert result.ops_per_sec > 10000, f"Expected >10K ops/sec, got {result.ops_per_sec:.0f}"

    def test_readahead_get_prefetch_hit(
        self, benchmark_runner: BenchmarkRunner, readahead_manager: ReadaheadManager
    ):
        """Benchmark getting prefetched data (hit)."""
        # Pre-populate
        data = b"x" * 65536
        keys = []
        for i in range(100):
            for j in range(10):
                readahead_manager.store_prefetched(i, j * 65536, data)
                keys.append((i, j * 65536))

        counter = [0]

        def op():
            inode, offset = keys[counter[0] % len(keys)]
            result = readahead_manager.get_prefetched(inode, offset)
            # Re-store for next iteration
            if result is None:
                readahead_manager.store_prefetched(inode, offset, data)
            counter[0] += 1

        result = benchmark_runner.run_benchmark(
            "readahead/get_prefetch_hit",
            "Get prefetch (hit)",
            "cache",
            op,
            iterations_per_sample=50,
        )
        assert result.ops_per_sec > 10000, f"Expected >10K ops/sec, got {result.ops_per_sec:.0f}"


# ============================================================================
# Concurrent Operation Benchmarks
# ============================================================================


class TestConcurrentBenchmarks:
    """Concurrent operation benchmarks."""

    @pytest.mark.parametrize("num_threads", [1, 2, 4, 8, 16, 32])
    def test_concurrent_inode_create(
        self,
        benchmark_runner: BenchmarkRunner,
        benchmark_config: BenchmarkConfig,
        num_threads: int,
    ):
        """Benchmark concurrent inode creation."""
        if benchmark_config.mode == "quick" and num_threads > 8:
            pytest.skip("Skipping high concurrency in quick mode")

        inode_manager = InodeManager()
        counter = [0]
        lock = threading.Lock()

        def create_inode():
            with lock:
                idx = counter[0]
                counter[0] += 1
            tid = threading.current_thread().ident
            inode_manager.get_or_create_inode(f"bucket/dir/file_{tid}_{idx}.txt")

        samples = []
        for _ in range(benchmark_config.sample_size // 5 or 1):
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(create_inode) for _ in range(num_threads * 10)]
                for f in as_completed(futures):
                    f.result()
            elapsed = time.perf_counter() - start
            ops = (num_threads * 10) / elapsed
            samples.append(ops)

        result = BenchmarkResult(
            benchmark_id=f"concurrent/inode_create/{num_threads}",
            name=f"Concurrent inode create ({num_threads} threads)",
            category="concurrent",
            unit="ops/sec",
            concurrent_level=num_threads,
        )
        result.samples = samples
        benchmark_runner.results.append(result)

        print(f"\n  Concurrent inode create ({num_threads} threads): {result.mean:.0f} ops/sec")

    @pytest.mark.parametrize("num_threads", [1, 2, 4, 8, 16, 32])
    def test_concurrent_inode_lookup(
        self,
        benchmark_runner: BenchmarkRunner,
        benchmark_config: BenchmarkConfig,
        num_threads: int,
    ):
        """Benchmark concurrent inode lookup."""
        if benchmark_config.mode == "quick" and num_threads > 8:
            pytest.skip("Skipping high concurrency in quick mode")

        inode_manager = InodeManager()
        # Pre-populate
        paths = [f"bucket/dir/file_{i}.txt" for i in range(10000)]
        for path in paths:
            inode_manager.get_or_create_inode(path)

        counter = [0]
        lock = threading.Lock()

        def lookup_inode():
            with lock:
                idx = counter[0] % len(paths)
                counter[0] += 1
            inode_manager.get_inode(paths[idx])

        samples = []
        for _ in range(benchmark_config.sample_size // 5 or 1):
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(lookup_inode) for _ in range(num_threads * 100)]
                for f in as_completed(futures):
                    f.result()
            elapsed = time.perf_counter() - start
            ops = (num_threads * 100) / elapsed
            samples.append(ops)

        result = BenchmarkResult(
            benchmark_id=f"concurrent/inode_lookup/{num_threads}",
            name=f"Concurrent inode lookup ({num_threads} threads)",
            category="concurrent",
            unit="ops/sec",
            concurrent_level=num_threads,
        )
        result.samples = samples
        benchmark_runner.results.append(result)

        print(f"\n  Concurrent inode lookup ({num_threads} threads): {result.mean:.0f} ops/sec")

    @pytest.mark.parametrize("num_threads", [1, 2, 4, 8, 16, 32])
    def test_concurrent_cache_data_get(
        self,
        benchmark_runner: BenchmarkRunner,
        benchmark_config: BenchmarkConfig,
        num_threads: int,
    ):
        """Benchmark concurrent data cache reads."""
        if benchmark_config.mode == "quick" and num_threads > 8:
            pytest.skip("Skipping high concurrency in quick mode")

        data_cache = DataCache(DataCacheConfig(max_memory_bytes=256 * 1024 * 1024))
        # Pre-populate
        data = b"x" * 4096
        for i in range(1000):
            data_cache.put(i, 0, data)

        counter = [0]
        lock = threading.Lock()

        def get_data():
            with lock:
                idx = counter[0] % 1000
                counter[0] += 1
            data_cache.get(idx, 0)

        samples = []
        for _ in range(benchmark_config.sample_size // 5 or 1):
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(get_data) for _ in range(num_threads * 100)]
                for f in as_completed(futures):
                    f.result()
            elapsed = time.perf_counter() - start
            ops = (num_threads * 100) / elapsed
            samples.append(ops)

        result = BenchmarkResult(
            benchmark_id=f"concurrent/cache_data_get/{num_threads}",
            name=f"Concurrent cache get ({num_threads} threads)",
            category="concurrent",
            unit="ops/sec",
            concurrent_level=num_threads,
        )
        result.samples = samples
        benchmark_runner.results.append(result)

        print(f"\n  Concurrent cache get ({num_threads} threads): {result.mean:.0f} ops/sec")

    @pytest.mark.parametrize("num_threads", [1, 2, 4, 8, 16, 32])
    def test_concurrent_cache_data_put(
        self,
        benchmark_runner: BenchmarkRunner,
        benchmark_config: BenchmarkConfig,
        num_threads: int,
    ):
        """Benchmark concurrent data cache writes."""
        if benchmark_config.mode == "quick" and num_threads > 8:
            pytest.skip("Skipping high concurrency in quick mode")

        data_cache = DataCache(DataCacheConfig(max_memory_bytes=256 * 1024 * 1024))
        data = b"x" * 4096
        counter = [0]
        lock = threading.Lock()

        def put_data():
            with lock:
                idx = counter[0]
                counter[0] += 1
            tid = threading.current_thread().ident
            data_cache.put(tid % 1000, idx * 4096, data)

        samples = []
        for _ in range(benchmark_config.sample_size // 5 or 1):
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(put_data) for _ in range(num_threads * 100)]
                for f in as_completed(futures):
                    f.result()
            elapsed = time.perf_counter() - start
            ops = (num_threads * 100) / elapsed
            samples.append(ops)

        result = BenchmarkResult(
            benchmark_id=f"concurrent/cache_data_put/{num_threads}",
            name=f"Concurrent cache put ({num_threads} threads)",
            category="concurrent",
            unit="ops/sec",
            concurrent_level=num_threads,
        )
        result.samples = samples
        benchmark_runner.results.append(result)

        print(f"\n  Concurrent cache put ({num_threads} threads): {result.mean:.0f} ops/sec")
