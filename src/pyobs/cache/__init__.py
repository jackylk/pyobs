"""Cache layer components for pyobs.

This module provides caching infrastructure similar to obsfuse:
- InodeManager: Path-to-inode mapping and attribute management
- MetadataCache: File attribute TTL caching with LRU eviction
- DataCache: Data block caching (memory + optional disk)
- ReadaheadManager: Sequential read detection and prefetching
"""

from .config import (
    CacheConfig,
    DataCacheConfig,
    MetadataCacheConfig,
    ReadaheadConfig,
)
from .data import CacheKey, DataCache
from .inode import FileAttr, InodeManager
from .metadata import CachedAttr, CachedDir, MetadataCache
from .readahead import PrefetchedBlock, ReadaheadManager, ReadPattern

__all__ = [
    # Config
    "CacheConfig",
    "DataCacheConfig",
    "MetadataCacheConfig",
    "ReadaheadConfig",
    # Inode
    "InodeManager",
    "FileAttr",
    # Metadata
    "MetadataCache",
    "CachedAttr",
    "CachedDir",
    # Data
    "DataCache",
    "CacheKey",
    # Readahead
    "ReadaheadManager",
    "ReadPattern",
    "PrefetchedBlock",
]
