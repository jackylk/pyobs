"""OBSFile - Buffered file implementation for OBS."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fsspec.spec import AbstractBufferedFile
from obs.model import CompleteMultipartUploadRequest, CompletePart

from .errors import OBSMultipartError, OBSUploadError
from .utils import normalize_path, split_path

if TYPE_CHECKING:
    from .core import OBSFileSystem

logger = logging.getLogger(__name__)

# Multipart upload threshold: 100MB
MULTIPART_THRESHOLD = 100 * 1024 * 1024

# Maximum number of parts
MAX_PARTS = 10000


class OBSFile(AbstractBufferedFile):
    """Buffered file implementation for OBS.

    This class provides buffered read and write operations for OBS objects,
    supporting both simple and multipart uploads.

    Parameters
    ----------
    fs : OBSFileSystem
        The filesystem instance.
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
        Additional arguments passed to AbstractBufferedFile.
    """

    def __init__(
        self,
        fs: "OBSFileSystem",
        path: str,
        mode: str = "rb",
        block_size: int | None = None,
        autocommit: bool = True,
        cache_options: dict | None = None,
        **kwargs,
    ):
        path = normalize_path(path)
        self.bucket, self.key = split_path(path)

        if not self.bucket or not self.key:
            raise ValueError("Path must include bucket and key")

        # For write modes, we need to track multipart upload state
        self._upload_id: str | None = None
        self._parts: List[CompletePart] = []
        self._part_number: int = 1

        super().__init__(
            fs,
            path,
            mode=mode,
            block_size=block_size or fs.default_block_size,
            autocommit=autocommit,
            cache_options=cache_options,
            **kwargs,
        )

    def _fetch_range(self, start: int, end: int) -> bytes:
        """Fetch a range of bytes from the file.

        Parameters
        ----------
        start : int
            Start byte position.
        end : int
            End byte position (exclusive).

        Returns
        -------
        bytes
            The requested byte range.
        """
        return self.fs.cat_file(self.path, start=start, end=end)

    def _initiate_upload(self) -> None:
        """Initialize a multipart upload.

        This is called when opening a file for writing.
        """
        if "w" not in self.mode and "a" not in self.mode:
            return

        # For small files, we'll use simple upload in _upload_chunk
        # For large files, we'll initiate multipart upload when needed
        self._upload_id = None
        self._parts = []
        self._part_number = 1

    def _upload_chunk(self, final: bool = False) -> bool:
        """Upload a chunk of data.

        Parameters
        ----------
        final : bool, optional
            If True, this is the final chunk.

        Returns
        -------
        bool
            True if upload was successful.
        """
        if self.buffer is None:
            return True

        data = self.buffer.getvalue()
        if not data and not final:
            return True

        # If this is the final chunk and we haven't started multipart upload,
        # use simple upload for small files
        if final and self._upload_id is None:
            if len(data) <= MULTIPART_THRESHOLD:
                # Simple upload
                self.fs._upload_simple(self.bucket, self.key, data)
                return True
            else:
                # Need to start multipart upload
                self._start_multipart_upload()

        # If we have an upload ID, upload as part
        if self._upload_id is not None:
            if data:
                self._upload_part(data)

            if final:
                self._complete_multipart_upload()

        elif data:
            # Start multipart upload if buffer exceeds threshold
            if len(data) > MULTIPART_THRESHOLD:
                self._start_multipart_upload()
                self._upload_part(data)
                if final:
                    self._complete_multipart_upload()
            elif final:
                # Simple upload for final small chunk
                self.fs._upload_simple(self.bucket, self.key, data)

        return True

    def _start_multipart_upload(self) -> None:
        """Start a multipart upload session."""
        resp = self.fs._call_obs(
            "initiateMultipartUpload",
            bucketName=self.bucket,
            objectKey=self.key,
        )
        self._upload_id = resp.body.uploadId
        self._parts = []
        self._part_number = 1
        logger.debug(f"Started multipart upload: {self._upload_id}")

    def _upload_part(self, data: bytes) -> None:
        """Upload a single part.

        Parameters
        ----------
        data : bytes
            Data to upload.
        """
        if not self._upload_id:
            raise OBSUploadError(
                self.path,
                "Cannot upload part without initiating multipart upload",
            )

        if self._part_number > MAX_PARTS:
            raise OBSMultipartError(
                self.path,
                self._upload_id,
                message=f"Exceeded maximum number of parts ({MAX_PARTS})",
            )

        try:
            resp = self.fs._call_obs(
                "uploadPart",
                bucketName=self.bucket,
                objectKey=self.key,
                partNumber=self._part_number,
                uploadId=self._upload_id,
                content=data,
            )

            self._parts.append(
                CompletePart(partNum=self._part_number, etag=resp.body.etag)
            )
            logger.debug(f"Uploaded part {self._part_number}, etag: {resp.body.etag}")
            self._part_number += 1

        except Exception as e:
            raise OBSMultipartError(
                self.path,
                self._upload_id,
                self._part_number,
                str(e),
            ) from e

    def _complete_multipart_upload(self) -> None:
        """Complete the multipart upload."""
        if not self._upload_id:
            return

        if not self._parts:
            # No parts uploaded, abort
            self._abort_multipart_upload()
            return

        try:
            complete_req = CompleteMultipartUploadRequest(parts=self._parts)
            self.fs._call_obs(
                "completeMultipartUpload",
                bucketName=self.bucket,
                objectKey=self.key,
                uploadId=self._upload_id,
                completeMultipartUploadRequest=complete_req,
            )
            logger.debug(f"Completed multipart upload: {self._upload_id}")

        except Exception as e:
            self._abort_multipart_upload()
            raise OBSMultipartError(
                self.path,
                self._upload_id,
                message=f"Failed to complete multipart upload: {e}",
            ) from e

        finally:
            self._upload_id = None
            self._parts = []
            self._part_number = 1

    def _abort_multipart_upload(self) -> None:
        """Abort the multipart upload."""
        if not self._upload_id:
            return

        try:
            self.fs._call_obs(
                "abortMultipartUpload",
                bucketName=self.bucket,
                objectKey=self.key,
                uploadId=self._upload_id,
            )
            logger.debug(f"Aborted multipart upload: {self._upload_id}")
        except Exception as e:
            logger.warning(f"Failed to abort multipart upload {self._upload_id}: {e}")
        finally:
            self._upload_id = None
            self._parts = []
            self._part_number = 1

    def discard(self) -> None:
        """Discard any buffered data and abort multipart upload."""
        self._abort_multipart_upload()
        super().discard()

    def close(self) -> None:
        """Close the file and complete any pending uploads."""
        if self.closed:
            return

        if "w" in self.mode or "a" in self.mode:
            if self.autocommit:
                self.flush(force=True)
            elif self._upload_id:
                # Abort incomplete upload if not autocommit
                self._abort_multipart_upload()

        super().close()

    def __del__(self):
        """Clean up on deletion."""
        if hasattr(self, "_upload_id") and self._upload_id:
            self._abort_multipart_upload()
