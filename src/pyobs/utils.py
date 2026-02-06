"""Utility functions for pyobs."""

from __future__ import annotations

import os
from typing import Tuple


def split_path(path: str) -> Tuple[str, str]:
    """Split an OBS path into bucket and key.

    Args:
        path: Path in format "bucket/key" or "bucket" or "/bucket/key"

    Returns:
        Tuple of (bucket, key). Key may be empty string.

    Examples:
        >>> split_path("mybucket/path/to/file.txt")
        ('mybucket', 'path/to/file.txt')
        >>> split_path("mybucket")
        ('mybucket', '')
        >>> split_path("/mybucket/key")
        ('mybucket', 'key')
        >>> split_path("obs://mybucket/key")
        ('mybucket', 'key')
    """
    # Remove protocol prefix if present
    for prefix in ("obs://", "hwobs://"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
            break

    # Remove leading slash
    path = path.lstrip("/")

    if not path:
        return "", ""

    # Split on first slash
    if "/" in path:
        bucket, key = path.split("/", 1)
        return bucket, key
    else:
        return path, ""


def normalize_path(path: str) -> str:
    """Normalize an OBS path by removing protocol and leading slashes.

    Args:
        path: Path that may include protocol prefix

    Returns:
        Normalized path without protocol or leading slashes

    Examples:
        >>> normalize_path("obs://mybucket/key")
        'mybucket/key'
        >>> normalize_path("/mybucket/key")
        'mybucket/key'
    """
    # Remove protocol prefix if present
    for prefix in ("obs://", "hwobs://"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
            break

    return path.lstrip("/")


def join_path(bucket: str, key: str) -> str:
    """Join bucket and key into a path.

    Args:
        bucket: Bucket name
        key: Object key (may be empty)

    Returns:
        Combined path

    Examples:
        >>> join_path("mybucket", "path/to/file.txt")
        'mybucket/path/to/file.txt'
        >>> join_path("mybucket", "")
        'mybucket'
    """
    if key:
        return f"{bucket}/{key}"
    return bucket


def is_directory_marker(key: str) -> bool:
    """Check if a key represents a directory marker.

    Args:
        key: Object key

    Returns:
        True if the key ends with '/' or is empty
    """
    return key == "" or key.endswith("/")


def ensure_trailing_slash(path: str) -> str:
    """Ensure path ends with a trailing slash.

    Args:
        path: Path to modify

    Returns:
        Path with trailing slash
    """
    if path and not path.endswith("/"):
        return path + "/"
    return path


def remove_trailing_slash(path: str) -> str:
    """Remove trailing slash from path.

    Args:
        path: Path to modify

    Returns:
        Path without trailing slash
    """
    return path.rstrip("/")


def get_parent_path(path: str) -> str:
    """Get the parent directory of a path.

    Args:
        path: Path to get parent of

    Returns:
        Parent path, or empty string if no parent

    Examples:
        >>> get_parent_path("bucket/path/to/file.txt")
        'bucket/path/to'
        >>> get_parent_path("bucket/file.txt")
        'bucket'
        >>> get_parent_path("bucket")
        ''
    """
    path = remove_trailing_slash(path)
    if "/" in path:
        return path.rsplit("/", 1)[0]
    return ""


def get_credentials_from_env() -> Tuple[str | None, str | None, str | None, str | None]:
    """Get OBS credentials from environment variables.

    Returns:
        Tuple of (access_key, secret_key, endpoint, security_token)
    """
    return (
        os.environ.get("OBS_ACCESS_KEY_ID"),
        os.environ.get("OBS_SECRET_ACCESS_KEY"),
        os.environ.get("OBS_ENDPOINT"),
        os.environ.get("OBS_SECURITY_TOKEN"),
    )
