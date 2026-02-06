"""Readahead manager for sequential read detection and prefetching."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from .config import ReadaheadConfig


@dataclass
class ReadPattern:
    """Tracks read pattern for a file.

    Attributes:
        last_offset: Last read offset.
        last_size: Last read size.
        sequential_count: Number of sequential reads detected.
        last_read_time: Time of last read.
        is_sequential: Whether pattern is currently sequential.
    """

    last_offset: int = 0
    last_size: int = 0
    sequential_count: int = 0
    last_read_time: float = field(default_factory=time.time)
    is_sequential: bool = False


@dataclass
class PrefetchedBlock:
    """A prefetched data block.

    Attributes:
        data: Prefetched data.
        expires_at: Expiration timestamp.
    """

    data: bytes
    expires_at: float

    def is_expired(self) -> bool:
        """Check if this block has expired."""
        return time.time() > self.expires_at


class ReadaheadManager:
    """Manages sequential read detection and prefetching.

    Detects sequential read patterns and prefetches upcoming blocks
    to reduce latency for sequential workloads.

    Thread-safe with configurable prefetch parameters.
    """

    def __init__(
        self,
        config: Optional[ReadaheadConfig] = None,
        fetch_func: Optional[Callable[[int, int, int], bytes]] = None,
    ):
        """Initialize the readahead manager.

        Args:
            config: Readahead configuration. Uses defaults if not provided.
            fetch_func: Function to fetch data: (inode, offset, size) -> bytes.
                       If not provided, prefetching is disabled.
        """
        self._config = config or ReadaheadConfig()
        self._fetch_func = fetch_func
        self._lock = threading.RLock()

        # Read patterns per inode
        self._patterns: Dict[int, ReadPattern] = {}

        # Prefetched blocks: (inode, offset) -> PrefetchedBlock
        self._prefetched: OrderedDict[Tuple[int, int], PrefetchedBlock] = OrderedDict()

        # Thread pool for async prefetching
        self._executor: Optional[ThreadPoolExecutor] = None
        if fetch_func:
            self._executor = ThreadPoolExecutor(
                max_workers=self._config.max_concurrent_prefetch,
                thread_name_prefix="readahead",
            )

        # Track pending prefetch operations
        self._pending_prefetch: set[Tuple[int, int]] = set()

    def record_read(self, inode: int, offset: int, size: int) -> bool:
        """Record a read operation and detect sequential pattern.

        Args:
            inode: Inode number.
            offset: Read offset.
            size: Read size.

        Returns:
            True if sequential pattern detected, False otherwise.
        """
        with self._lock:
            pattern = self._patterns.get(inode)

            if pattern is None:
                # First read for this inode
                self._patterns[inode] = ReadPattern(
                    last_offset=offset,
                    last_size=size,
                    sequential_count=1,
                    last_read_time=time.time(),
                    is_sequential=False,
                )
                return False

            # Check if this read is sequential
            expected_offset = pattern.last_offset + pattern.last_size
            gap = abs(offset - expected_offset)

            if gap <= self._config.sequential_threshold:
                # Sequential read
                pattern.sequential_count += 1
                pattern.is_sequential = pattern.sequential_count >= self._config.min_sequential_reads

                # Trigger prefetch if sequential
                if pattern.is_sequential and self._fetch_func:
                    self._trigger_prefetch(inode, offset + size)
            else:
                # Non-sequential read, reset pattern
                pattern.sequential_count = 1
                pattern.is_sequential = False

            pattern.last_offset = offset
            pattern.last_size = size
            pattern.last_read_time = time.time()

            return pattern.is_sequential

    def _trigger_prefetch(self, inode: int, start_offset: int) -> None:
        """Trigger prefetch for upcoming blocks (internal, assumes lock held)."""
        if not self._executor or not self._fetch_func:
            return

        # Calculate blocks to prefetch
        block_size = 64 * 1024  # Default block size
        for i in range(self._config.readahead_blocks):
            offset = start_offset + (i * block_size)
            key = (inode, offset)

            # Skip if already prefetched or pending
            if key in self._prefetched or key in self._pending_prefetch:
                continue

            # Check capacity
            if len(self._prefetched) >= self._config.max_prefetched_blocks:
                # Evict oldest
                self._prefetched.popitem(last=False)

            # Submit prefetch task
            self._pending_prefetch.add(key)
            self._executor.submit(self._do_prefetch, inode, offset, block_size)

    def _do_prefetch(self, inode: int, offset: int, size: int) -> None:
        """Execute prefetch operation (runs in thread pool)."""
        key = (inode, offset)
        try:
            if self._fetch_func:
                data = self._fetch_func(inode, offset, size)
                with self._lock:
                    self._prefetched[key] = PrefetchedBlock(
                        data=data,
                        expires_at=time.time() + self._config.prefetch_ttl_sec,
                    )
                    self._prefetched.move_to_end(key)
        except Exception:
            pass  # Silently ignore prefetch failures
        finally:
            with self._lock:
                self._pending_prefetch.discard(key)

    def get_prefetched(self, inode: int, offset: int) -> Optional[bytes]:
        """Get prefetched data if available.

        Args:
            inode: Inode number.
            offset: Read offset.

        Returns:
            Prefetched data or None if not available.
        """
        key = (inode, offset)

        with self._lock:
            block = self._prefetched.get(key)
            if block is None:
                return None

            if block.is_expired():
                del self._prefetched[key]
                return None

            # Remove from prefetch cache (consumed)
            del self._prefetched[key]
            return block.data

    def store_prefetched(self, inode: int, offset: int, data: bytes) -> None:
        """Store data in prefetch cache.

        Args:
            inode: Inode number.
            offset: Data offset.
            data: Data to store.
        """
        key = (inode, offset)

        with self._lock:
            # Check capacity
            while len(self._prefetched) >= self._config.max_prefetched_blocks:
                self._prefetched.popitem(last=False)

            self._prefetched[key] = PrefetchedBlock(
                data=data,
                expires_at=time.time() + self._config.prefetch_ttl_sec,
            )
            self._prefetched.move_to_end(key)

    def is_sequential(self, inode: int) -> bool:
        """Check if an inode has sequential read pattern.

        Args:
            inode: Inode number.

        Returns:
            True if sequential pattern detected.
        """
        with self._lock:
            pattern = self._patterns.get(inode)
            return pattern.is_sequential if pattern else False

    def get_pattern(self, inode: int) -> Optional[ReadPattern]:
        """Get read pattern for an inode.

        Args:
            inode: Inode number.

        Returns:
            ReadPattern or None if not tracked.
        """
        with self._lock:
            return self._patterns.get(inode)

    def invalidate(self, inode: int) -> int:
        """Invalidate pattern and prefetched data for an inode.

        Args:
            inode: Inode number.

        Returns:
            Number of prefetched blocks invalidated.
        """
        count = 0

        with self._lock:
            # Remove pattern
            self._patterns.pop(inode, None)

            # Remove prefetched blocks
            to_remove = [k for k in self._prefetched if k[0] == inode]
            for key in to_remove:
                del self._prefetched[key]
                count += 1

            # Remove pending prefetch
            self._pending_prefetch = {k for k in self._pending_prefetch if k[0] != inode}

        return count

    def clear(self) -> None:
        """Clear all patterns and prefetched data."""
        with self._lock:
            self._patterns.clear()
            self._prefetched.clear()
            self._pending_prefetch.clear()

    def cleanup_expired(self) -> int:
        """Remove expired prefetched blocks.

        Returns:
            Number of blocks removed.
        """
        count = 0

        with self._lock:
            expired = [k for k, v in self._prefetched.items() if v.is_expired()]
            for key in expired:
                del self._prefetched[key]
                count += 1

        return count

    @property
    def pattern_count(self) -> int:
        """Return number of tracked patterns."""
        with self._lock:
            return len(self._patterns)

    @property
    def prefetched_count(self) -> int:
        """Return number of prefetched blocks."""
        with self._lock:
            return len(self._prefetched)

    def stats(self) -> Dict[str, int]:
        """Return readahead statistics.

        Returns:
            Dictionary with pattern_count, prefetched_count, pending_count.
        """
        with self._lock:
            return {
                "pattern_count": len(self._patterns),
                "prefetched_count": len(self._prefetched),
                "pending_count": len(self._pending_prefetch),
            }

    def shutdown(self) -> None:
        """Shutdown the executor and cleanup resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self.clear()

    def __del__(self):
        """Cleanup on deletion."""
        self.shutdown()
