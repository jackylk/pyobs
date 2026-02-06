"""Data cache for file content blocks."""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from .config import DataCacheConfig


@dataclass(frozen=True)
class CacheKey:
    """Key for data cache entries.

    Attributes:
        inode: Inode number.
        offset: Block offset (aligned to block_size).
    """

    inode: int
    offset: int

    def __hash__(self) -> int:
        return hash((self.inode, self.offset))


class DataCache:
    """LRU cache for file data blocks with optional disk backing.

    Provides two-tier caching:
    - Memory cache: Fast access, limited size
    - Disk cache: Larger capacity, persistent (optional)

    Thread-safe with configurable block size and capacity limits.
    """

    def __init__(self, config: Optional[DataCacheConfig] = None):
        """Initialize the data cache.

        Args:
            config: Cache configuration. Uses defaults if not provided.
        """
        self._config = config or DataCacheConfig()
        self._lock = threading.RLock()

        # Memory cache: LRU using OrderedDict
        self._memory_cache: OrderedDict[CacheKey, bytes] = OrderedDict()
        self._memory_bytes: int = 0

        # Disk cache setup
        self._disk_cache_dir: Optional[Path] = None
        self._disk_bytes: int = 0

        if self._config.disk_cache_dir and self._config.max_disk_bytes > 0:
            self._disk_cache_dir = Path(self._config.disk_cache_dir)
            self._disk_cache_dir.mkdir(parents=True, exist_ok=True)
            self._scan_disk_cache()

    def _scan_disk_cache(self) -> None:
        """Scan disk cache directory and calculate size."""
        if not self._disk_cache_dir:
            return

        self._disk_bytes = 0
        for f in self._disk_cache_dir.iterdir():
            if f.is_file():
                self._disk_bytes += f.stat().st_size

    def _disk_path(self, key: CacheKey) -> Path:
        """Get disk cache path for a key."""
        # Use hash to distribute files
        key_str = f"{key.inode}_{key.offset}"
        hash_prefix = hashlib.md5(key_str.encode()).hexdigest()[:4]
        return self._disk_cache_dir / hash_prefix / f"{key.inode}_{key.offset}.bin"

    def _align_offset(self, offset: int) -> int:
        """Align offset to block boundary."""
        return (offset // self._config.block_size) * self._config.block_size

    def get(self, inode: int, offset: int) -> Optional[bytes]:
        """Get cached data block.

        Args:
            inode: Inode number.
            offset: Byte offset (will be aligned to block boundary).

        Returns:
            Cached data or None if not found.
        """
        aligned_offset = self._align_offset(offset)
        key = CacheKey(inode, aligned_offset)

        with self._lock:
            # Check memory cache first
            data = self._memory_cache.get(key)
            if data is not None:
                # Move to end for LRU
                self._memory_cache.move_to_end(key)
                return data

            # Check disk cache
            if self._disk_cache_dir:
                disk_path = self._disk_path(key)
                if disk_path.exists():
                    try:
                        data = disk_path.read_bytes()
                        # Promote to memory cache
                        self._put_memory(key, data)
                        return data
                    except OSError:
                        pass

            return None

    def _put_memory(self, key: CacheKey, data: bytes) -> None:
        """Put data in memory cache (internal, assumes lock held)."""
        data_size = len(data)

        # Evict if needed
        while (
            self._memory_bytes + data_size > self._config.max_memory_bytes
            and self._memory_cache
        ):
            evicted_key, evicted_data = self._memory_cache.popitem(last=False)
            self._memory_bytes -= len(evicted_data)

            # Optionally write to disk cache
            if self._disk_cache_dir and self._config.write_through:
                self._put_disk(evicted_key, evicted_data)

        # Add to cache
        if key in self._memory_cache:
            self._memory_bytes -= len(self._memory_cache[key])

        self._memory_cache[key] = data
        self._memory_bytes += data_size
        self._memory_cache.move_to_end(key)

    def _put_disk(self, key: CacheKey, data: bytes) -> bool:
        """Put data in disk cache (internal)."""
        if not self._disk_cache_dir:
            return False

        data_size = len(data)

        # Check capacity
        if self._disk_bytes + data_size > self._config.max_disk_bytes:
            # Simple eviction: remove oldest files
            self._evict_disk(data_size)

        disk_path = self._disk_path(key)
        try:
            disk_path.parent.mkdir(parents=True, exist_ok=True)
            disk_path.write_bytes(data)
            self._disk_bytes += data_size
            return True
        except OSError:
            return False

    def _evict_disk(self, needed_bytes: int) -> None:
        """Evict disk cache entries to free space."""
        if not self._disk_cache_dir:
            return

        # Get all cache files sorted by mtime
        files = []
        for subdir in self._disk_cache_dir.iterdir():
            if subdir.is_dir():
                for f in subdir.iterdir():
                    if f.is_file():
                        files.append((f.stat().st_mtime, f.stat().st_size, f))

        files.sort()  # Oldest first

        freed = 0
        for _, size, path in files:
            if self._disk_bytes - freed + needed_bytes <= self._config.max_disk_bytes:
                break
            try:
                path.unlink()
                freed += size
            except OSError:
                pass

        self._disk_bytes -= freed

    def put(self, inode: int, offset: int, data: bytes) -> None:
        """Cache a data block.

        Args:
            inode: Inode number.
            offset: Byte offset (will be aligned to block boundary).
            data: Data to cache.
        """
        aligned_offset = self._align_offset(offset)
        key = CacheKey(inode, aligned_offset)

        with self._lock:
            self._put_memory(key, data)

            # Write through to disk if configured
            if self._disk_cache_dir and self._config.write_through:
                self._put_disk(key, data)

    def invalidate(self, inode: int) -> int:
        """Invalidate all cached blocks for an inode.

        Args:
            inode: Inode number.

        Returns:
            Number of blocks invalidated.
        """
        count = 0

        with self._lock:
            # Invalidate memory cache
            to_remove = [k for k in self._memory_cache if k.inode == inode]
            for key in to_remove:
                self._memory_bytes -= len(self._memory_cache[key])
                del self._memory_cache[key]
                count += 1

            # Invalidate disk cache
            if self._disk_cache_dir:
                for subdir in self._disk_cache_dir.iterdir():
                    if subdir.is_dir():
                        for f in subdir.iterdir():
                            if f.is_file() and f.name.startswith(f"{inode}_"):
                                try:
                                    size = f.stat().st_size
                                    f.unlink()
                                    self._disk_bytes -= size
                                    count += 1
                                except OSError:
                                    pass

        return count

    def invalidate_range(self, inode: int, start: int, end: int) -> int:
        """Invalidate cached blocks in a byte range.

        Args:
            inode: Inode number.
            start: Start offset (inclusive).
            end: End offset (exclusive).

        Returns:
            Number of blocks invalidated.
        """
        start_aligned = self._align_offset(start)
        # End needs to include the block containing end-1
        end_aligned = self._align_offset(end - 1) + self._config.block_size if end > 0 else 0

        count = 0

        with self._lock:
            # Invalidate memory cache
            to_remove = [
                k
                for k in self._memory_cache
                if k.inode == inode and start_aligned <= k.offset < end_aligned
            ]
            for key in to_remove:
                self._memory_bytes -= len(self._memory_cache[key])
                del self._memory_cache[key]
                count += 1

            # Invalidate disk cache
            if self._disk_cache_dir:
                for offset in range(start_aligned, end_aligned, self._config.block_size):
                    key = CacheKey(inode, offset)
                    disk_path = self._disk_path(key)
                    if disk_path.exists():
                        try:
                            size = disk_path.stat().st_size
                            disk_path.unlink()
                            self._disk_bytes -= size
                            count += 1
                        except OSError:
                            pass

        return count

    def clear(self) -> None:
        """Clear all caches."""
        with self._lock:
            self._memory_cache.clear()
            self._memory_bytes = 0

            if self._disk_cache_dir:
                try:
                    shutil.rmtree(self._disk_cache_dir)
                    self._disk_cache_dir.mkdir(parents=True, exist_ok=True)
                    self._disk_bytes = 0
                except OSError:
                    pass

    @property
    def memory_bytes(self) -> int:
        """Return current memory cache size in bytes."""
        with self._lock:
            return self._memory_bytes

    @property
    def disk_bytes(self) -> int:
        """Return current disk cache size in bytes."""
        with self._lock:
            return self._disk_bytes

    @property
    def block_count(self) -> int:
        """Return number of blocks in memory cache."""
        with self._lock:
            return len(self._memory_cache)

    @property
    def block_size(self) -> int:
        """Return configured block size."""
        return self._config.block_size

    def stats(self) -> Dict[str, int]:
        """Return cache statistics.

        Returns:
            Dictionary with memory_bytes, disk_bytes, block_count.
        """
        with self._lock:
            return {
                "memory_bytes": self._memory_bytes,
                "disk_bytes": self._disk_bytes,
                "block_count": len(self._memory_cache),
                "block_size": self._config.block_size,
            }
