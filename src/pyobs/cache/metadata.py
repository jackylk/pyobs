"""Metadata cache for file attributes and directory listings."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import MetadataCacheConfig


@dataclass
class CachedAttr:
    """Cached file attribute entry.

    Attributes:
        size: File size in bytes.
        is_dir: Whether this is a directory.
        mtime: Modification time (Unix timestamp).
        etag: ETag for cache validation.
        expires_at: Expiration timestamp.
    """

    size: int
    is_dir: bool
    mtime: float
    etag: Optional[str] = None
    expires_at: float = field(default_factory=lambda: time.time() + 60.0)

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        return time.time() > self.expires_at


@dataclass
class CachedDir:
    """Cached directory listing entry.

    Attributes:
        entries: List of (name, is_dir, size) tuples.
        expires_at: Expiration timestamp.
    """

    entries: List[Tuple[str, bool, int]]
    expires_at: float = field(default_factory=lambda: time.time() + 60.0)

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        return time.time() > self.expires_at


class MetadataCache:
    """LRU cache for file metadata with TTL expiration.

    Provides caching for:
    - File attributes (size, mtime, is_dir)
    - Directory listings
    - Negative cache (non-existent paths)

    Thread-safe with configurable TTL and size limits.
    """

    def __init__(self, config: Optional[MetadataCacheConfig] = None):
        """Initialize the metadata cache.

        Args:
            config: Cache configuration. Uses defaults if not provided.
        """
        self._config = config or MetadataCacheConfig()
        self._lock = threading.RLock()

        # LRU caches using OrderedDict
        self._attrs: OrderedDict[str, CachedAttr] = OrderedDict()
        self._dirs: OrderedDict[str, CachedDir] = OrderedDict()
        self._negative: OrderedDict[str, float] = OrderedDict()  # path -> expires_at

    def _normalize_path(self, path: str) -> str:
        """Normalize path by removing leading/trailing slashes."""
        return path.strip("/")

    # -------------------------------------------------------------------------
    # Attribute cache
    # -------------------------------------------------------------------------

    def get_attr(self, path: str) -> Optional[CachedAttr]:
        """Get cached file attributes.

        Args:
            path: File path.

        Returns:
            CachedAttr if found and not expired, None otherwise.
        """
        path = self._normalize_path(path)

        with self._lock:
            attr = self._attrs.get(path)
            if attr is None:
                return None

            if attr.is_expired():
                del self._attrs[path]
                return None

            # Move to end for LRU
            self._attrs.move_to_end(path)
            return attr

    def put_attr(
        self,
        path: str,
        size: int,
        is_dir: bool,
        mtime: float,
        etag: Optional[str] = None,
        ttl: Optional[float] = None,
    ) -> None:
        """Cache file attributes.

        Args:
            path: File path.
            size: File size in bytes.
            is_dir: Whether this is a directory.
            mtime: Modification time.
            etag: Optional ETag for validation.
            ttl: Optional TTL override in seconds.
        """
        path = self._normalize_path(path)
        ttl = ttl if ttl is not None else self._config.attr_ttl_sec

        with self._lock:
            # Evict if at capacity
            while len(self._attrs) >= self._config.max_attrs:
                self._attrs.popitem(last=False)

            self._attrs[path] = CachedAttr(
                size=size,
                is_dir=is_dir,
                mtime=mtime,
                etag=etag,
                expires_at=time.time() + ttl,
            )
            self._attrs.move_to_end(path)

            # Remove from negative cache if present
            self._negative.pop(path, None)

    def invalidate_attr(self, path: str) -> bool:
        """Invalidate cached attributes for a path.

        Args:
            path: File path.

        Returns:
            True if entry was removed, False if not found.
        """
        path = self._normalize_path(path)

        with self._lock:
            if path in self._attrs:
                del self._attrs[path]
                return True
            return False

    def evict_oldest_attrs(self, count: int) -> int:
        """Evict oldest attribute entries.

        Args:
            count: Number of entries to evict.

        Returns:
            Number of entries actually evicted.
        """
        with self._lock:
            evicted = 0
            for _ in range(min(count, len(self._attrs))):
                self._attrs.popitem(last=False)
                evicted += 1
            return evicted

    # -------------------------------------------------------------------------
    # Directory cache
    # -------------------------------------------------------------------------

    def get_dir(self, path: str) -> Optional[List[Tuple[str, bool, int]]]:
        """Get cached directory listing.

        Args:
            path: Directory path.

        Returns:
            List of (name, is_dir, size) tuples if found and not expired.
        """
        path = self._normalize_path(path)

        with self._lock:
            cached = self._dirs.get(path)
            if cached is None:
                return None

            if cached.is_expired():
                del self._dirs[path]
                return None

            # Move to end for LRU
            self._dirs.move_to_end(path)
            return cached.entries

    def put_dir(
        self,
        path: str,
        entries: List[Tuple[str, bool, int]],
        ttl: Optional[float] = None,
    ) -> None:
        """Cache directory listing.

        Args:
            path: Directory path.
            entries: List of (name, is_dir, size) tuples.
            ttl: Optional TTL override in seconds.
        """
        path = self._normalize_path(path)
        ttl = ttl if ttl is not None else self._config.dir_ttl_sec

        with self._lock:
            # Evict if at capacity
            while len(self._dirs) >= self._config.max_dirs:
                self._dirs.popitem(last=False)

            self._dirs[path] = CachedDir(
                entries=entries,
                expires_at=time.time() + ttl,
            )
            self._dirs.move_to_end(path)

    def invalidate_dir(self, path: str) -> bool:
        """Invalidate cached directory listing.

        Args:
            path: Directory path.

        Returns:
            True if entry was removed, False if not found.
        """
        path = self._normalize_path(path)

        with self._lock:
            if path in self._dirs:
                del self._dirs[path]
                return True
            return False

    def invalidate_dir_tree(self, path: str) -> int:
        """Invalidate directory and all parent directories.

        Args:
            path: Starting path.

        Returns:
            Number of entries invalidated.
        """
        path = self._normalize_path(path)
        count = 0

        with self._lock:
            # Invalidate the path itself
            if path in self._dirs:
                del self._dirs[path]
                count += 1

            # Invalidate all parent directories
            while "/" in path:
                path = path.rsplit("/", 1)[0]
                if path in self._dirs:
                    del self._dirs[path]
                    count += 1

            # Invalidate root
            if "" in self._dirs:
                del self._dirs[""]
                count += 1

        return count

    # -------------------------------------------------------------------------
    # Negative cache
    # -------------------------------------------------------------------------

    def is_negative(self, path: str) -> bool:
        """Check if path is in negative cache (known not to exist).

        Args:
            path: File path.

        Returns:
            True if path is in negative cache and not expired.
        """
        path = self._normalize_path(path)

        with self._lock:
            expires_at = self._negative.get(path)
            if expires_at is None:
                return False

            if time.time() > expires_at:
                del self._negative[path]
                return False

            # Move to end for LRU
            self._negative.move_to_end(path)
            return True

    def put_negative(self, path: str, ttl: Optional[float] = None) -> None:
        """Add path to negative cache.

        Args:
            path: File path that doesn't exist.
            ttl: Optional TTL override in seconds.
        """
        path = self._normalize_path(path)
        ttl = ttl if ttl is not None else self._config.negative_ttl_sec

        with self._lock:
            # Evict if at capacity
            while len(self._negative) >= self._config.max_negative:
                self._negative.popitem(last=False)

            self._negative[path] = time.time() + ttl
            self._negative.move_to_end(path)

            # Remove from attr cache if present
            self._attrs.pop(path, None)

    def invalidate_negative(self, path: str) -> bool:
        """Remove path from negative cache.

        Args:
            path: File path.

        Returns:
            True if entry was removed, False if not found.
        """
        path = self._normalize_path(path)

        with self._lock:
            if path in self._negative:
                del self._negative[path]
                return True
            return False

    # -------------------------------------------------------------------------
    # General operations
    # -------------------------------------------------------------------------

    def invalidate_path(self, path: str) -> int:
        """Invalidate all caches for a path.

        Args:
            path: File path.

        Returns:
            Number of entries invalidated.
        """
        path = self._normalize_path(path)
        count = 0

        with self._lock:
            if path in self._attrs:
                del self._attrs[path]
                count += 1
            if path in self._dirs:
                del self._dirs[path]
                count += 1
            if path in self._negative:
                del self._negative[path]
                count += 1

        return count

    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all entries with a given prefix.

        Args:
            prefix: Path prefix.

        Returns:
            Number of entries invalidated.
        """
        prefix = self._normalize_path(prefix)
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        count = 0

        with self._lock:
            # Invalidate attrs
            to_remove = [p for p in self._attrs if p.startswith(prefix) or p == prefix.rstrip("/")]
            for p in to_remove:
                del self._attrs[p]
                count += 1

            # Invalidate dirs
            to_remove = [p for p in self._dirs if p.startswith(prefix) or p == prefix.rstrip("/")]
            for p in to_remove:
                del self._dirs[p]
                count += 1

            # Invalidate negative
            to_remove = [p for p in self._negative if p.startswith(prefix) or p == prefix.rstrip("/")]
            for p in to_remove:
                del self._negative[p]
                count += 1

        return count

    def clear(self) -> None:
        """Clear all caches."""
        with self._lock:
            self._attrs.clear()
            self._dirs.clear()
            self._negative.clear()

    def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed.
        """
        now = time.time()
        count = 0

        with self._lock:
            # Cleanup attrs
            expired = [p for p, a in self._attrs.items() if a.is_expired()]
            for p in expired:
                del self._attrs[p]
                count += 1

            # Cleanup dirs
            expired = [p for p, d in self._dirs.items() if d.is_expired()]
            for p in expired:
                del self._dirs[p]
                count += 1

            # Cleanup negative
            expired = [p for p, exp in self._negative.items() if now > exp]
            for p in expired:
                del self._negative[p]
                count += 1

        return count

    @property
    def attr_count(self) -> int:
        """Return number of cached attributes."""
        with self._lock:
            return len(self._attrs)

    @property
    def dir_count(self) -> int:
        """Return number of cached directories."""
        with self._lock:
            return len(self._dirs)

    @property
    def negative_count(self) -> int:
        """Return number of negative cache entries."""
        with self._lock:
            return len(self._negative)

    def stats(self) -> Dict[str, int]:
        """Return cache statistics.

        Returns:
            Dictionary with attr_count, dir_count, negative_count.
        """
        with self._lock:
            return {
                "attr_count": len(self._attrs),
                "dir_count": len(self._dirs),
                "negative_count": len(self._negative),
            }
