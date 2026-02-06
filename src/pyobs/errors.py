"""Custom exceptions for pyobs."""


class OBSError(Exception):
    """Base exception for OBS operations."""

    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(self.message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"status_code={self.status_code}")
        if self.error_code:
            parts.append(f"error_code={self.error_code}")
        return " ".join(parts)


class OBSFileNotFoundError(OBSError, FileNotFoundError):
    """Raised when a file or bucket is not found (404)."""

    def __init__(self, path: str, message: str | None = None):
        self.path = path
        msg = message or f"File not found: {path}"
        super().__init__(msg, status_code=404, error_code="NoSuchKey")


class OBSPermissionError(OBSError, PermissionError):
    """Raised when access is denied (403)."""

    def __init__(self, path: str, message: str | None = None):
        self.path = path
        msg = message or f"Permission denied: {path}"
        super().__init__(msg, status_code=403, error_code="AccessDenied")


class OBSConnectionError(OBSError, ConnectionError):
    """Raised when connection to OBS fails."""

    def __init__(self, message: str | None = None, endpoint: str | None = None):
        self.endpoint = endpoint
        msg = message or f"Failed to connect to OBS"
        if endpoint:
            msg = f"{msg}: {endpoint}"
        super().__init__(msg)


class OBSUploadError(OBSError):
    """Raised when upload operation fails."""

    def __init__(self, path: str, message: str | None = None):
        self.path = path
        if message:
            msg = f"{message}: {path}"
        else:
            msg = f"Upload failed: {path}"
        super().__init__(msg)


class OBSMultipartError(OBSUploadError):
    """Raised when multipart upload fails."""

    def __init__(
        self,
        path: str,
        upload_id: str | None = None,
        part_number: int | None = None,
        message: str | None = None,
    ):
        self.upload_id = upload_id
        self.part_number = part_number
        msg = message or f"Multipart upload failed: {path}"
        if upload_id:
            msg = f"{msg} (upload_id={upload_id})"
        if part_number is not None:
            msg = f"{msg} (part={part_number})"
        super().__init__(path, msg)
