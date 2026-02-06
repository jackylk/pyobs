#!/usr/bin/env python3
"""Compare benchmark results between pyobs and obsfuse.

Usage:
    python scripts/compare_benchmarks.py [--obsfuse-path PATH]
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


def load_benchmark_data(path: Path) -> Dict[str, Any]:
    """Load benchmark data from JSON file."""
    with open(path) as f:
        return json.load(f)


def format_time(ns: float) -> str:
    """Format nanoseconds into appropriate unit."""
    if ns >= 1_000_000:
        return f"{ns / 1_000_000:.2f} ms"
    elif ns >= 1_000:
        return f"{ns / 1_000:.2f} µs"
    else:
        return f"{ns:.2f} ns"


def format_ops(ns: float) -> str:
    """Format nanoseconds as ops/sec."""
    if ns <= 0:
        return "-"
    ops = 1_000_000_000 / ns
    if ops >= 1_000_000:
        return f"{ops / 1_000_000:.2f}M ops/s"
    elif ops >= 1_000:
        return f"{ops / 1_000:.1f}K ops/s"
    else:
        return f"{ops:.0f} ops/s"


def calculate_ratio(pyobs_ns: float, obsfuse_ns: float) -> Tuple[str, str]:
    """Calculate performance ratio and format it."""
    if obsfuse_ns <= 0 or pyobs_ns <= 0:
        return "-", ""

    ratio = pyobs_ns / obsfuse_ns
    if ratio > 1:
        # pyobs is slower
        return f"{ratio:.1f}x", "slower"
    else:
        # pyobs is faster
        return f"{1/ratio:.1f}x", "faster"


def compare_benchmarks(pyobs_path: Path, obsfuse_path: Path) -> None:
    """Compare benchmark results and print report."""
    pyobs_data = load_benchmark_data(pyobs_path)
    obsfuse_data = load_benchmark_data(obsfuse_path)

    pyobs_benchmarks = pyobs_data.get("benchmarks", {})
    obsfuse_benchmarks = obsfuse_data.get("benchmarks", {})

    # Find common benchmarks
    common_keys = set(pyobs_benchmarks.keys()) & set(obsfuse_benchmarks.keys())

    # Group by category
    categories = {
        "Inode Operations": ["inode_create", "inode_lookup_existing", "inode_get_path",
                            "inode_update_size", "inode_rename"],
        "Cache Operations": ["cache_metadata_put", "cache_metadata_get_hit", "cache_metadata_get_miss",
                            "cache_data_put_4KB", "cache_data_put_64KB",
                            "cache_data_get_hit_4KB", "cache_data_get_hit_64KB",
                            "cache_data_invalidate"],
        "Path Operations": ["path_join", "path_parent", "path_file_name",
                           "path_join_deep", "path_parent_deep"],
        "Readahead Operations": ["readahead_record_read", "readahead_sequential_detection",
                                 "readahead_store_prefetch", "readahead_get_prefetch_hit"],
    }

    # Add concurrent operations
    for prefix in ["concurrent_inode_create", "concurrent_inode_lookup",
                   "concurrent_cache_data_get", "concurrent_cache_data_put"]:
        for n in [1, 2, 4, 8, 16, 32]:
            key = f"{prefix}_{n}"
            if key in common_keys:
                cat = "Concurrent Operations"
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(key)

    print("=" * 80)
    print("PyOBS vs OBS FUSE Performance Comparison")
    print("=" * 80)
    print()
    print(f"PyOBS timestamp: {pyobs_data.get('timestamp', 'N/A')}")
    print(f"OBS FUSE timestamp: {obsfuse_data.get('timestamp', 'N/A')}")
    print()

    for category, keys in categories.items():
        available_keys = [k for k in keys if k in common_keys]
        if not available_keys:
            continue

        print(f"\n### {category}\n")
        print(f"{'Benchmark':<35} {'PyOBS':<15} {'OBS FUSE':<15} {'Ratio':<15}")
        print("-" * 80)

        for key in available_keys:
            pyobs_mean = pyobs_benchmarks[key].get("mean_ns", 0)
            obsfuse_mean = obsfuse_benchmarks[key].get("mean_ns", 0)

            ratio, direction = calculate_ratio(pyobs_mean, obsfuse_mean)
            ratio_str = f"{ratio} {direction}" if direction else ratio

            # Format benchmark name
            name = key.replace("_", " ").replace("cache ", "").replace("inode ", "")

            print(f"{name:<35} {format_time(pyobs_mean):<15} {format_time(obsfuse_mean):<15} {ratio_str:<15}")

    # Summary statistics
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)

    faster_count = 0
    slower_count = 0
    total_ratio = 0.0

    for key in common_keys:
        pyobs_mean = pyobs_benchmarks[key].get("mean_ns", 0)
        obsfuse_mean = obsfuse_benchmarks[key].get("mean_ns", 0)
        if pyobs_mean > 0 and obsfuse_mean > 0:
            ratio = pyobs_mean / obsfuse_mean
            total_ratio += ratio
            if ratio > 1:
                slower_count += 1
            else:
                faster_count += 1

    total_compared = faster_count + slower_count
    if total_compared > 0:
        avg_ratio = total_ratio / total_compared
        print(f"\nTotal benchmarks compared: {total_compared}")
        print(f"PyOBS faster: {faster_count}")
        print(f"PyOBS slower: {slower_count}")
        print(f"Average ratio: {avg_ratio:.2f}x (>1 means PyOBS slower)")
        print()
        print("Note: Rust (OBS FUSE) is expected to be faster than Python (PyOBS)")
        print("      for CPU-bound operations. Network I/O should be comparable.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Compare benchmark results")
    parser.add_argument("--obsfuse-path", type=Path,
                       default=Path(__file__).parent.parent.parent / "obsfuse" / "test-reports" / "benchmark-data.json",
                       help="Path to obsfuse benchmark-data.json")
    parser.add_argument("--pyobs-path", type=Path,
                       default=Path(__file__).parent.parent / "test-reports" / "benchmark-data.json",
                       help="Path to pyobs benchmark-data.json")
    args = parser.parse_args()

    if not args.pyobs_path.exists():
        print(f"Error: PyOBS benchmark data not found: {args.pyobs_path}")
        print("Run: pytest tests/benchmark/test_cache_benchmark.py -v --quick")
        sys.exit(1)

    if not args.obsfuse_path.exists():
        print(f"Error: OBS FUSE benchmark data not found: {args.obsfuse_path}")
        sys.exit(1)

    compare_benchmarks(args.pyobs_path, args.obsfuse_path)


if __name__ == "__main__":
    main()
