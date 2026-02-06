"""Inode manager for path-to-inode mapping and attribute management."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class FileAttr:
    """File attributes similar to FUSE file attributes.

    Attributes:
        ino: Inode number.
        size: File size in bytes.
        is_dir: Whether this is a directory.
        mtime: Modification time (Unix timestamp).
        ctime: Creation time (Unix timestamp).
        atime: Access time (Unix timestamp).
        mode: File mode/permissions.
        nlink: Number of hard links.
        uid: User ID.
        gid: Group ID.
    """

    ino: int
    size: int = 0
    is_dir: bool = False
    mtime: float = field(default_factory=time.time)
    ctime: float = field(default_factory=time.time)
    atime: float = field(default_factory=time.time)
    mode: int = 0o644
    nlink: int = 1
    uid: int = 0
    gid: int = 0

    def __post_init__(self):
        """Set directory mode if is_dir is True."""
        if self.is_dir and self.mode == 0o644:
            self.mode = 0o755


class InodeManager:
    """Manages path-to-inode mapping and file attributes.

    Thread-safe inode allocation and lookup for filesystem operations.
    Provides bidirectional mapping between paths and inodes.
    """

    # Reserved inodes
    ROOT_INODE = 1

    def __init__(self):
        """Initialize the inode manager."""
        self._lock = threading.RLock()
        self._next_inode = 2  # Start after root inode
        self._path_to_inode: Dict[str, int] = {}
        self._inode_to_path: Dict[int, str] = {}
        self._inode_to_attr: Dict[int, FileAttr] = {}

        # Initialize root inode
        self._path_to_inode[""] = self.ROOT_INODE
        self._inode_to_path[self.ROOT_INODE] = ""
        self._inode_to_attr[self.ROOT_INODE] = FileAttr(
            ino=self.ROOT_INODE,
            is_dir=True,
            mode=0o755,
        )

    def _normalize_path(self, path: str) -> str:
        """Normalize path by removing leading/trailing slashes."""
        return path.strip("/")

    def get_or_create_inode(
        self,
        path: str,
        is_dir: bool = False,
        size: int = 0,
        mtime: Optional[float] = None,
    ) -> int:
        """Get existing inode or create a new one for the path.

        Args:
            path: File path.
            is_dir: Whether this is a directory.
            size: File size in bytes.
            mtime: Modification time (defaults to current time).

        Returns:
            Inode number for the path.
        """
        path = self._normalize_path(path)

        with self._lock:
            if path in self._path_to_inode:
                inode = self._path_to_inode[path]
                # Update attributes if provided
                if inode in self._inode_to_attr:
                    attr = self._inode_to_attr[inode]
                    attr.size = size
                    if mtime is not None:
                        attr.mtime = mtime
                return inode

            # Allocate new inode
            inode = self._next_inode
            self._next_inode += 1

            self._path_to_inode[path] = inode
            self._inode_to_path[inode] = path
            self._inode_to_attr[inode] = FileAttr(
                ino=inode,
                size=size,
                is_dir=is_dir,
                mtime=mtime if mtime is not None else time.time(),
            )

            return inode

    def get_inode(self, path: str) -> Optional[int]:
        """Get inode for a path if it exists.

        Args:
            path: File path.

        Returns:
            Inode number or None if not found.
        """
        path = self._normalize_path(path)
        with self._lock:
            return self._path_to_inode.get(path)

    def get_path(self, inode: int) -> Optional[str]:
        """Get path for an inode.

        Args:
            inode: Inode number.

        Returns:
            Path or None if not found.
        """
        with self._lock:
            return self._inode_to_path.get(inode)

    def get_attr(self, inode: int) -> Optional[FileAttr]:
        """Get file attributes for an inode.

        Args:
            inode: Inode number.

        Returns:
            FileAttr or None if not found.
        """
        with self._lock:
            return self._inode_to_attr.get(inode)

    def get_attr_by_path(self, path: str) -> Optional[FileAttr]:
        """Get file attributes for a path.

        Args:
            path: File path.

        Returns:
            FileAttr or None if not found.
        """
        path = self._normalize_path(path)
        with self._lock:
            inode = self._path_to_inode.get(path)
            if inode is not None:
                return self._inode_to_attr.get(inode)
            return None

    def update_size(self, inode: int, size: int) -> bool:
        """Update file size for an inode.

        Args:
            inode: Inode number.
            size: New file size.

        Returns:
            True if updated, False if inode not found.
        """
        with self._lock:
            attr = self._inode_to_attr.get(inode)
            if attr is not None:
                attr.size = size
                attr.mtime = time.time()
                return True
            return False

    def update_attr(
        self,
        inode: int,
        size: Optional[int] = None,
        mtime: Optional[float] = None,
        atime: Optional[float] = None,
    ) -> bool:
        """Update file attributes for an inode.

        Args:
            inode: Inode number.
            size: New file size (optional).
            mtime: New modification time (optional).
            atime: New access time (optional).

        Returns:
            True if updated, False if inode not found.
        """
        with self._lock:
            attr = self._inode_to_attr.get(inode)
            if attr is None:
                return False

            if size is not None:
                attr.size = size
            if mtime is not None:
                attr.mtime = mtime
            if atime is not None:
                attr.atime = atime

            return True

    def rename(self, old_path: str, new_path: str) -> bool:
        """Rename a path (move inode to new path).

        Args:
            old_path: Current path.
            new_path: New path.

        Returns:
            True if renamed, False if old path not found.
        """
        old_path = self._normalize_path(old_path)
        new_path = self._normalize_path(new_path)

        with self._lock:
            inode = self._path_to_inode.get(old_path)
            if inode is None:
                return False

            # Remove old mapping
            del self._path_to_inode[old_path]

            # Add new mapping
            self._path_to_inode[new_path] = inode
            self._inode_to_path[inode] = new_path

            return True

    def remove(self, path: str) -> bool:
        """Remove a path and its inode mapping.

        Args:
            path: Path to remove.

        Returns:
            True if removed, False if not found.
        """
        path = self._normalize_path(path)

        with self._lock:
            inode = self._path_to_inode.get(path)
            if inode is None:
                return False

            # Don't allow removing root
            if inode == self.ROOT_INODE:
                return False

            del self._path_to_inode[path]
            del self._inode_to_path[inode]
            del self._inode_to_attr[inode]

            return True

    def remove_by_inode(self, inode: int) -> bool:
        """Remove an inode and its path mapping.

        Args:
            inode: Inode to remove.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            path = self._inode_to_path.get(inode)
            if path is None:
                return False

            # Don't allow removing root
            if inode == self.ROOT_INODE:
                return False

            del self._path_to_inode[path]
            del self._inode_to_path[inode]
            del self._inode_to_attr[inode]

            return True

    def clear(self) -> None:
        """Clear all mappings except root."""
        with self._lock:
            self._path_to_inode = {"": self.ROOT_INODE}
            self._inode_to_path = {self.ROOT_INODE: ""}
            root_attr = FileAttr(ino=self.ROOT_INODE, is_dir=True, mode=0o755)
            self._inode_to_attr = {self.ROOT_INODE: root_attr}
            self._next_inode = 2

    def __len__(self) -> int:
        """Return number of inodes (including root)."""
        with self._lock:
            return len(self._inode_to_path)

    @property
    def inode_count(self) -> int:
        """Return number of inodes (including root)."""
        return len(self)
