"""pyobs - Huawei Cloud OBS filesystem implementation for fsspec.

This package provides a fsspec-compatible filesystem interface for
Huawei Cloud Object Storage Service (OBS).

Example usage:
    >>> import fsspec
    >>> fs = fsspec.filesystem('obs',
    ...     key='your-access-key',
    ...     secret='your-secret-key',
    ...     endpoint='https://obs.cn-north-4.myhuaweicloud.com')
    >>> fs.ls('mybucket/')
    >>> data = fs.cat_file('mybucket/file.txt')
"""

from ._version import __version__
from .core import OBSFileSystem
from .errors import (
    OBSConnectionError,
    OBSError,
    OBSFileNotFoundError,
    OBSMultipartError,
    OBSPermissionError,
    OBSUploadError,
)
from .file import OBSFile

__all__ = [
    "__version__",
    "OBSFileSystem",
    "OBSFile",
    "OBSError",
    "OBSFileNotFoundError",
    "OBSPermissionError",
    "OBSConnectionError",
    "OBSUploadError",
    "OBSMultipartError",
]
