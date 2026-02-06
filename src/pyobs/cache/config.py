"""Configuration dataclasses for cache components."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MetadataCacheConfig:
    """Configuration for metadata cache.

    Attributes:
        attr_ttl_sec: TTL for file attributes in seconds.
        dir_ttl_sec: TTL for directory listings in seconds.
        negative_ttl_sec: TTL for negative cache entries in seconds.
        max_attrs: Maximum number of cached file attributes.
        max_dirs: Maximum number of cached directory listings.
        max_negative: Maximum number of negative cache entries.
    """

    attr_ttl_sec: float = 60.0
    dir_ttl_sec: float = 60.0
    negative_ttl_sec: float = 5.0
    max_attrs: int = 10000
    max_dirs: int = 1000
    max_negative: int = 1000


@dataclass
class DataCacheConfig:
    """Configuration for data cache.

    Attributes:
        block_size: Size of each cache block in bytes.
        max_memory_bytes: Maximum memory cache size in bytes.
        max_disk_bytes: Maximum disk cache size in bytes (0 to disable).
        disk_cache_dir: Directory for disk cache (None to disable).
        write_through: Whether to write through to disk cache immediately.
    """

    block_size: int = 64 * 1024  # 64KB
    max_memory_bytes: int = 256 * 1024 * 1024  # 256MB
    max_disk_bytes: int = 0  # Disabled by default
    disk_cache_dir: Optional[Path] = None
    write_through: bool = False


@dataclass
class ReadaheadConfig:
    """Configuration for readahead manager.

    Attributes:
        min_sequential_reads: Minimum sequential reads to trigger readahead.
        readahead_blocks: Number of blocks to prefetch.
        max_prefetch_bytes: Maximum bytes to prefetch per file.
        max_concurrent_prefetch: Maximum concurrent prefetch operations.
        sequential_threshold: Maximum gap between reads to consider sequential.
        prefetch_ttl_sec: TTL for prefetched data in seconds.
        max_prefetched_blocks: Maximum number of prefetched blocks to keep.
    """

    min_sequential_reads: int = 2
    readahead_blocks: int = 4
    max_prefetch_bytes: int = 4 * 1024 * 1024  # 4MB
    max_concurrent_prefetch: int = 4
    sequential_threshold: int = 64 * 1024  # 64KB
    prefetch_ttl_sec: float = 30.0
    max_prefetched_blocks: int = 64


@dataclass
class CacheConfig:
    """Combined configuration for all cache components.

    Attributes:
        metadata: Metadata cache configuration.
        data: Data cache configuration.
        readahead: Readahead configuration.
        enabled: Whether caching is enabled.
    """

    metadata: MetadataCacheConfig = field(default_factory=MetadataCacheConfig)
    data: DataCacheConfig = field(default_factory=DataCacheConfig)
    readahead: ReadaheadConfig = field(default_factory=ReadaheadConfig)
    enabled: bool = True
