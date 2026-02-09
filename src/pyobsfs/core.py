"""OBSFileSystem - fsspec implementation for Huawei Cloud OBS."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

from fsspec import AbstractFileSystem
from fsspec.utils import stringify_path
from obs import ObsClient
from obs.model import (
    CompleteMultipartUploadRequest,
    CompletePart,
    GetObjectHeader,
    GetObjectRequest,
    PutObjectHeader,
)

from .errors import (
    OBSConnectionError,
    OBSError,
    OBSFileNotFoundError,
    OBSMultipartError,
    OBSPermissionError,
    OBSUploadError,
)
from .utils import (
    get_credentials_from_env,
    is_directory_marker,
    normalize_path,
    split_path,
)

logger = logging.getLogger(__name__)

# Default block size: 5MB
DEFAULT_BLOCK_SIZE = 5 * 1024 * 1024

# Multipart upload threshold: 100MB
MULTIPART_THRESHOLD = 100 * 1024 * 1024

# Maximum number of parts for multipart upload
MAX_PARTS = 10000


class OBSFileSystem(AbstractFileSystem):
    """Huawei Cloud OBS filesystem implementation for fsspec.

    This filesystem allows you to interact with Huawei Cloud Object Storage Service (OBS)
    using the fsspec interface. It supports both the 'obs' and 'hwobs' protocols.

    Parameters
    ----------
    key : str, optional
        OBS access key ID. Can also be set via OBS_ACCESS_KEY_ID environment variable.
    secret : str, optional
        OBS secret access key. Can also be set via OBS_SECRET_ACCESS_KEY environment variable.
    endpoint : str, optional
        OBS endpoint URL. Can also be set via OBS_ENDPOINT environment variable.
    token : str, optional
        Security token for temporary credentials. Can also be set via OBS_SECURITY_TOKEN.
    default_block_size : int, optional
        Default block size for file operations. Default is 5MB.
    **kwargs
        Additional arguments passed to AbstractFileSystem.

    Examples
    --------
    >>> import fsspec
    >>> fs = fsspec.filesystem('obs',
    ...     key='your-access-key',
    ...     secret='your-secret-key',
    ...     endpoint='https://obs.cn-north-4.myhuaweicloud.com')
    >>> fs.ls('mybucket/')
    >>> data = fs.cat_file('mybucket/file.txt')
    """

    protocol = ("obs", "hwobs")
    _extra_tokenize_attributes = ("key", "secret", "endpoint")

    def __init__(
        self,
        key: str | None = None,
        secret: str | None = None,
        endpoint: str | None = None,
        token: str | None = None,
        default_block_size: int = DEFAULT_BLOCK_SIZE,
        **kwargs,
    ):
        super().__init__(**kwargs)

        # Get credentials from environment if not provided
        env_key, env_secret, env_endpoint, env_token = get_credentials_from_env()

        self.key = key or env_key
        self.secret = secret or env_secret
        self.endpoint = endpoint or env_endpoint
        self.token = token or env_token
        self.default_block_size = default_block_size

        # Validate required credentials
        if not self.key:
            raise ValueError(
                "OBS access key is required. "
                "Provide 'key' parameter or set OBS_ACCESS_KEY_ID environment variable."
            )
        if not self.secret:
            raise ValueError(
                "OBS secret key is required. "
                "Provide 'secret' parameter or set OBS_SECRET_ACCESS_KEY environment variable."
            )
        if not self.endpoint:
            raise ValueError(
                "OBS endpoint is required. "
                "Provide 'endpoint' parameter or set OBS_ENDPOINT environment variable."
            )

        # Thread-local storage for ObsClient instances
        self._local = threading.local()

    @property
    def client(self) -> ObsClient:
        """Get thread-local ObsClient instance.

        Creates a new client for each thread to ensure thread safety.
        """
        if not hasattr(self._local, "client") or self._local.client is None:
            self._local.client = ObsClient(
                access_key_id=self.key,
                secret_access_key=self.secret,
                server=self.endpoint,
                security_token=self.token,
            )
        return self._local.client

    def _call_obs(self, method: str, *args, **kwargs) -> Any:
        """Call an OBS client method and handle errors.

        Parameters
        ----------
        method : str
            Name of the ObsClient method to call.
        *args, **kwargs
            Arguments to pass to the method.

        Returns
        -------
        Any
            The response from the OBS API.

        Raises
        ------
        OBSFileNotFoundError
            If the object or bucket is not found (404).
        OBSPermissionError
            If access is denied (403).
        OBSConnectionError
            If connection fails.
        OBSError
            For other OBS errors.
        """
        try:
            func = getattr(self.client, method)
            resp = func(*args, **kwargs)

            # Check response status
            if resp.status >= 300:
                path = args[0] if args else kwargs.get("bucketName", "")
                if len(args) > 1:
                    path = f"{args[0]}/{args[1]}"
                elif "objectKey" in kwargs:
                    path = f"{kwargs.get('bucketName', '')}/{kwargs['objectKey']}"

                if resp.status == 404:
                    raise OBSFileNotFoundError(path, resp.errorMessage)
                elif resp.status == 403:
                    raise OBSPermissionError(path, resp.errorMessage)
                else:
                    raise OBSError(
                        resp.errorMessage or f"OBS error: {method}",
                        status_code=resp.status,
                        error_code=resp.errorCode,
                    )

            return resp

        except (OBSError, OBSFileNotFoundError, OBSPermissionError):
            raise
        except Exception as e:
            raise OBSConnectionError(str(e), self.endpoint) from e

    def _split_path(self, path: str) -> Tuple[str, str]:
        """Split path into bucket and key."""
        return split_path(path)

    def ls(
        self,
        path: str,
        detail: bool = True,
        refresh: bool = False,
        **kwargs,
    ) -> List[Union[str, Dict[str, Any]]]:
        """List objects in a bucket or prefix.

        Parameters
        ----------
        path : str
            Path to list (bucket or bucket/prefix).
        detail : bool, optional
            If True, return list of dicts with file info. If False, return list of paths.
        refresh : bool, optional
            If True, bypass cache.
        **kwargs
            Additional arguments (unused).

        Returns
        -------
        list
            List of file paths (if detail=False) or list of dicts with file info.
        """
        path = stringify_path(path)
        path = normalize_path(path)
        bucket, prefix = self._split_path(path)

        if not bucket:
            # List all buckets
            resp = self._call_obs("listBuckets")
            buckets = []
            for b in resp.body.buckets:
                if detail:
                    buckets.append(
                        {
                            "name": b.name,
                            "type": "directory",
                            "size": 0,
                            "created": b.create_date,
                        }
                    )
                else:
                    buckets.append(b.name)
            return buckets

        # List objects in bucket
        results = []
        marker = None
        prefix_with_slash = prefix + "/" if prefix and not prefix.endswith("/") else prefix

        while True:
            resp = self._call_obs(
                "listObjects",
                bucketName=bucket,
                prefix=prefix_with_slash if prefix else "",
                delimiter="/",
                marker=marker,
                max_keys=1000,
            )

            # Add common prefixes (directories)
            if resp.body.commonPrefixs:
                for cp in resp.body.commonPrefixs:
                    dir_path = f"{bucket}/{cp.prefix}".rstrip("/")
                    if detail:
                        results.append(
                            {
                                "name": dir_path,
                                "type": "directory",
                                "size": 0,
                            }
                        )
                    else:
                        results.append(dir_path)

            # Add objects (files)
            if resp.body.contents:
                for obj in resp.body.contents:
                    # Skip the prefix itself if it's a directory marker
                    if obj.key == prefix_with_slash:
                        continue

                    obj_path = f"{bucket}/{obj.key}"
                    if is_directory_marker(obj.key):
                        if detail:
                            results.append(
                                {
                                    "name": obj_path.rstrip("/"),
                                    "type": "directory",
                                    "size": 0,
                                }
                            )
                        else:
                            results.append(obj_path.rstrip("/"))
                    else:
                        if detail:
                            results.append(
                                {
                                    "name": obj_path,
                                    "type": "file",
                                    "size": obj.size,
                                    "LastModified": obj.lastModified,
                                    "ETag": obj.etag,
                                    "StorageClass": obj.storageClass,
                                }
                            )
                        else:
                            results.append(obj_path)

            # Check if there are more results
            if resp.body.is_truncated:
                marker = resp.body.next_marker
            else:
                break

        return results

    def info(self, path: str, **kwargs) -> Dict[str, Any]:
        """Get info about a file or directory.

        Parameters
        ----------
        path : str
            Path to get info for.
        **kwargs
            Additional arguments (unused).

        Returns
        -------
        dict
            Dictionary with file/directory information.
        """
        path = stringify_path(path)
        path = normalize_path(path)
        bucket, key = self._split_path(path)

        if not bucket:
            raise ValueError("Path must include bucket name")

        if not key:
            # Check if bucket exists
            resp = self._call_obs("headBucket", bucketName=bucket)
            return {
                "name": bucket,
                "type": "directory",
                "size": 0,
            }

        # Try to get object metadata
        try:
            resp = self._call_obs(
                "getObjectMetadata",
                bucketName=bucket,
                objectKey=key,
            )
            return {
                "name": path,
                "type": "file",
                "size": int(resp.body.contentLength),
                "LastModified": resp.body.lastModified,
                "ETag": resp.body.etag,
                "ContentType": resp.body.contentType,
            }
        except OBSFileNotFoundError:
            # Check if it's a directory (prefix with objects under it)
            resp = self._call_obs(
                "listObjects",
                bucketName=bucket,
                prefix=key.rstrip("/") + "/",
                max_keys=1,
            )
            if resp.body.contents or resp.body.commonPrefixs:
                return {
                    "name": path,
                    "type": "directory",
                    "size": 0,
                }
            raise OBSFileNotFoundError(path)

    def exists(self, path: str, **kwargs) -> bool:
        """Check if a path exists.

        Parameters
        ----------
        path : str
            Path to check.
        **kwargs
            Additional arguments (unused).

        Returns
        -------
        bool
            True if path exists, False otherwise.
        """
        try:
            self.info(path)
            return True
        except (OBSFileNotFoundError, FileNotFoundError):
            return False

    def cat_file(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
        **kwargs,
    ) -> bytes:
        """Read contents of a file.

        Parameters
        ----------
        path : str
            Path to the file.
        start : int, optional
            Start byte position for range read.
        end : int, optional
            End byte position for range read (exclusive).
        **kwargs
            Additional arguments (unused).

        Returns
        -------
        bytes
            File contents.
        """
        path = stringify_path(path)
        path = normalize_path(path)
        bucket, key = self._split_path(path)

        if not bucket or not key:
            raise ValueError("Path must include bucket and key")

        # Build range header if needed
        headers = GetObjectHeader()
        if start is not None or end is not None:
            range_str = f"bytes={start or 0}-{end - 1 if end else ''}"
            headers.range = range_str

        resp = self._call_obs(
            "getObject",
            bucketName=bucket,
            objectKey=key,
            headers=headers,
        )

        # Read response body
        return resp.body.response.read()

    def _upload_simple(self, bucket: str, key: str, data: bytes) -> None:
        """Upload data using simple PUT.

        Parameters
        ----------
        bucket : str
            Bucket name.
        key : str
            Object key.
        data : bytes
            Data to upload.
        """
        self._call_obs(
            "putContent",
            bucketName=bucket,
            objectKey=key,
            content=data,
        )

    def _upload_multipart(
        self,
        bucket: str,
        key: str,
        data: bytes,
        part_size: int | None = None,
    ) -> None:
        """Upload data using multipart upload.

        Parameters
        ----------
        bucket : str
            Bucket name.
        key : str
            Object key.
        data : bytes
            Data to upload.
        part_size : int, optional
            Size of each part. Default is default_block_size.
        """
        part_size = part_size or self.default_block_size
        path = f"{bucket}/{key}"

        # Initiate multipart upload
        resp = self._call_obs(
            "initiateMultipartUpload",
            bucketName=bucket,
            objectKey=key,
        )
        upload_id = resp.body.uploadId

        try:
            parts = []
            part_number = 1
            offset = 0

            while offset < len(data):
                chunk = data[offset : offset + part_size]
                offset += part_size

                # Upload part
                resp = self._call_obs(
                    "uploadPart",
                    bucketName=bucket,
                    objectKey=key,
                    partNumber=part_number,
                    uploadId=upload_id,
                    content=chunk,
                )

                parts.append(CompletePart(partNum=part_number, etag=resp.body.etag))
                part_number += 1

                if part_number > MAX_PARTS:
                    raise OBSMultipartError(
                        path,
                        upload_id,
                        message=f"Exceeded maximum number of parts ({MAX_PARTS})",
                    )

            # Complete multipart upload
            complete_req = CompleteMultipartUploadRequest(parts=parts)
            self._call_obs(
                "completeMultipartUpload",
                bucketName=bucket,
                objectKey=key,
                uploadId=upload_id,
                completeMultipartUploadRequest=complete_req,
            )

        except Exception as e:
            # Abort multipart upload on failure
            try:
                self._call_obs(
                    "abortMultipartUpload",
                    bucketName=bucket,
                    objectKey=key,
                    uploadId=upload_id,
                )
            except Exception:
                logger.warning(f"Failed to abort multipart upload: {upload_id}")

            if isinstance(e, OBSError):
                raise
            raise OBSMultipartError(path, upload_id, message=str(e)) from e

    def pipe_file(self, path: str, value: bytes, **kwargs) -> None:
        """Write data to a file.

        Parameters
        ----------
        path : str
            Path to the file.
        value : bytes
            Data to write.
        **kwargs
            Additional arguments (unused).
        """
        path = stringify_path(path)
        path = normalize_path(path)
        bucket, key = self._split_path(path)

        if not bucket or not key:
            raise ValueError("Path must include bucket and key")

        # Use multipart upload for large files
        if len(value) > MULTIPART_THRESHOLD:
            self._upload_multipart(bucket, key, value)
        else:
            self._upload_simple(bucket, key, value)

    def _open(
        self,
        path: str,
        mode: str = "rb",
        block_size: int | None = None,
        autocommit: bool = True,
        cache_options: dict | None = None,
        **kwargs,
    ):
        """Open a file for reading or writing.

        Parameters
        ----------
        path : str
            Path to the file.
        mode : str, optional
            File mode ('rb', 'wb', 'ab').
        block_size : int, optional
            Block size for buffered operations.
        autocommit : bool, optional
            If True, commit writes automatically on close.
        cache_options : dict, optional
            Options for caching.
        **kwargs
            Additional arguments passed to OBSFile.

        Returns
        -------
        OBSFile
            File object.
        """
        from .file import OBSFile

        return OBSFile(
            self,
            path,
            mode=mode,
            block_size=block_size or self.default_block_size,
            autocommit=autocommit,
            cache_options=cache_options,
            **kwargs,
        )

    def rm(self, path: str, recursive: bool = False, **kwargs) -> None:
        """Delete a file or directory.

        Parameters
        ----------
        path : str
            Path to delete.
        recursive : bool, optional
            If True, delete directory contents recursively.
        **kwargs
            Additional arguments (unused).
        """
        path = stringify_path(path)
        path = normalize_path(path)
        bucket, key = self._split_path(path)

        if not bucket:
            raise ValueError("Path must include bucket name")

        if not key:
            # Delete bucket (must be empty)
            self._call_obs("deleteBucket", bucketName=bucket)
            return

        if recursive:
            # List and delete all objects with prefix
            objects_to_delete = []
            marker = None

            while True:
                resp = self._call_obs(
                    "listObjects",
                    bucketName=bucket,
                    prefix=key if key.endswith("/") else key + "/",
                    marker=marker,
                    max_keys=1000,
                )

                if resp.body.contents:
                    for obj in resp.body.contents:
                        objects_to_delete.append({"key": obj.key})

                if resp.body.is_truncated:
                    marker = resp.body.next_marker
                else:
                    break

            # Also try to delete the path itself
            objects_to_delete.append({"key": key})

            # Delete objects in batches
            if objects_to_delete:
                # OBS supports batch delete of up to 1000 objects
                for i in range(0, len(objects_to_delete), 1000):
                    batch = objects_to_delete[i : i + 1000]
                    self._call_obs(
                        "deleteObjects",
                        bucketName=bucket,
                        deleteObjectsRequest={"objects": batch, "quiet": True},
                    )
        else:
            # Delete single object
            self._call_obs(
                "deleteObject",
                bucketName=bucket,
                objectKey=key,
            )

    def rm_file(self, path: str) -> None:
        """Delete a single file.

        Parameters
        ----------
        path : str
            Path to the file to delete.
        """
        self.rm(path, recursive=False)

    def mkdir(self, path: str, create_parents: bool = True, **kwargs) -> None:
        """Create a directory.

        In OBS, directories are represented as empty objects with trailing slash.

        Parameters
        ----------
        path : str
            Path to create.
        create_parents : bool, optional
            If True, create parent directories as needed.
        **kwargs
            Additional arguments (unused).
        """
        path = stringify_path(path)
        path = normalize_path(path)
        bucket, key = self._split_path(path)

        if not bucket:
            raise ValueError("Path must include bucket name")

        # Check if bucket exists, create if needed
        try:
            self._call_obs("headBucket", bucketName=bucket)
        except OBSFileNotFoundError:
            if create_parents:
                self._call_obs("createBucket", bucketName=bucket)
            else:
                raise

        if key:
            # Create directory marker (empty object with trailing slash)
            dir_key = key.rstrip("/") + "/"
            self._call_obs(
                "putContent",
                bucketName=bucket,
                objectKey=dir_key,
                content="",
            )

    def makedirs(self, path: str, exist_ok: bool = True) -> None:
        """Create a directory and all parent directories.

        Parameters
        ----------
        path : str
            Path to create.
        exist_ok : bool, optional
            If True, don't raise error if directory exists.
        """
        if not exist_ok and self.exists(path):
            raise FileExistsError(f"Directory already exists: {path}")
        self.mkdir(path, create_parents=True)

    def rmdir(self, path: str) -> None:
        """Remove an empty directory.

        Parameters
        ----------
        path : str
            Path to the directory to remove.
        """
        path = stringify_path(path)
        path = normalize_path(path)
        bucket, key = self._split_path(path)

        if not bucket:
            raise ValueError("Path must include bucket name")

        if not key:
            # Delete bucket
            self._call_obs("deleteBucket", bucketName=bucket)
        else:
            # Delete directory marker
            dir_key = key.rstrip("/") + "/"
            try:
                self._call_obs(
                    "deleteObject",
                    bucketName=bucket,
                    objectKey=dir_key,
                )
            except OBSFileNotFoundError:
                # Try without trailing slash
                self._call_obs(
                    "deleteObject",
                    bucketName=bucket,
                    objectKey=key,
                )

    def cp_file(self, path1: str, path2: str, **kwargs) -> None:
        """Copy a file from one location to another.

        Parameters
        ----------
        path1 : str
            Source path.
        path2 : str
            Destination path.
        **kwargs
            Additional arguments (unused).
        """
        path1 = stringify_path(path1)
        path2 = stringify_path(path2)
        path1 = normalize_path(path1)
        path2 = normalize_path(path2)

        src_bucket, src_key = self._split_path(path1)
        dst_bucket, dst_key = self._split_path(path2)

        if not src_bucket or not src_key:
            raise ValueError("Source path must include bucket and key")
        if not dst_bucket or not dst_key:
            raise ValueError("Destination path must include bucket and key")

        self._call_obs(
            "copyObject",
            sourceBucketName=src_bucket,
            sourceObjectKey=src_key,
            destBucketName=dst_bucket,
            destObjectKey=dst_key,
        )

    def sign(
        self,
        path: str,
        expiration: int = 3600,
        method: str = "GET",
        **kwargs,
    ) -> str:
        """Generate a pre-signed URL for a file.

        Parameters
        ----------
        path : str
            Path to the file.
        expiration : int, optional
            URL expiration time in seconds. Default is 3600 (1 hour).
        method : str, optional
            HTTP method for the URL ('GET' or 'PUT'). Default is 'GET'.
        **kwargs
            Additional arguments (unused).

        Returns
        -------
        str
            Pre-signed URL.
        """
        path = stringify_path(path)
        path = normalize_path(path)
        bucket, key = self._split_path(path)

        if not bucket or not key:
            raise ValueError("Path must include bucket and key")

        resp = self.client.createSignedUrl(
            method=method,
            bucketName=bucket,
            objectKey=key,
            expires=expiration,
        )

        return resp.signedUrl

    def created(self, path: str) -> str | None:
        """Get creation time of a file.

        Note: OBS doesn't store creation time, returns last modified instead.

        Parameters
        ----------
        path : str
            Path to the file.

        Returns
        -------
        str or None
            Last modified timestamp.
        """
        info = self.info(path)
        return info.get("LastModified")

    def modified(self, path: str) -> str | None:
        """Get last modified time of a file.

        Parameters
        ----------
        path : str
            Path to the file.

        Returns
        -------
        str or None
            Last modified timestamp.
        """
        info = self.info(path)
        return info.get("LastModified")

    def size(self, path: str) -> int:
        """Get size of a file.

        Parameters
        ----------
        path : str
            Path to the file.

        Returns
        -------
        int
            File size in bytes.
        """
        info = self.info(path)
        return info.get("size", 0)

    def isfile(self, path: str) -> bool:
        """Check if path is a file.

        Parameters
        ----------
        path : str
            Path to check.

        Returns
        -------
        bool
            True if path is a file.
        """
        try:
            info = self.info(path)
            return info.get("type") == "file"
        except (OBSFileNotFoundError, FileNotFoundError):
            return False

    def isdir(self, path: str) -> bool:
        """Check if path is a directory.

        Parameters
        ----------
        path : str
            Path to check.

        Returns
        -------
        bool
            True if path is a directory.
        """
        try:
            info = self.info(path)
            return info.get("type") == "directory"
        except (OBSFileNotFoundError, FileNotFoundError):
            return False

    def __del__(self):
        """Clean up ObsClient on deletion."""
        if hasattr(self, "_local") and hasattr(self._local, "client"):
            try:
                self._local.client.close()
            except Exception:
                pass
