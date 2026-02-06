"""Pytest fixtures for pyobs tests."""

from __future__ import annotations

import os
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

import pytest


class MockResponse:
    """Mock OBS API response."""

    def __init__(
        self,
        status: int = 200,
        body: Any = None,
        error_message: str | None = None,
        error_code: str | None = None,
    ):
        self.status = status
        self.body = body or MagicMock()
        self.errorMessage = error_message
        self.errorCode = error_code


class MockBucket:
    """Mock bucket object."""

    def __init__(self, name: str, create_date: str = "2024-01-01T00:00:00Z"):
        self.name = name
        self.create_date = create_date


class MockObject:
    """Mock object in bucket."""

    def __init__(
        self,
        key: str,
        size: int = 0,
        last_modified: str = "2024-01-01T00:00:00Z",
        etag: str = '"abc123"',
        storage_class: str = "STANDARD",
    ):
        self.key = key
        self.size = size
        self.lastModified = last_modified
        self.etag = etag
        self.storageClass = storage_class


class MockCommonPrefix:
    """Mock common prefix (directory)."""

    def __init__(self, prefix: str):
        self.prefix = prefix


class MockListBucketsBody:
    """Mock body for listBuckets response."""

    def __init__(self, buckets: list | None = None):
        self.buckets = buckets or []


class MockListObjectsBody:
    """Mock body for listObjects response."""

    def __init__(
        self,
        contents: list | None = None,
        common_prefixs: list | None = None,
        is_truncated: bool = False,
        next_marker: str | None = None,
    ):
        self.contents = contents or []
        self.commonPrefixs = common_prefixs or []
        self.is_truncated = is_truncated
        self.next_marker = next_marker


class MockGetObjectMetadataBody:
    """Mock body for getObjectMetadata response."""

    def __init__(
        self,
        content_length: int = 0,
        last_modified: str = "2024-01-01T00:00:00Z",
        etag: str = '"abc123"',
        content_type: str = "application/octet-stream",
    ):
        self.contentLength = content_length
        self.lastModified = last_modified
        self.etag = etag
        self.contentType = content_type


class MockGetObjectBody:
    """Mock body for getObject response."""

    def __init__(self, content: bytes = b""):
        self.response = MagicMock()
        self.response.read.return_value = content


class MockInitiateMultipartUploadBody:
    """Mock body for initiateMultipartUpload response."""

    def __init__(self, upload_id: str = "test-upload-id"):
        self.uploadId = upload_id


class MockUploadPartBody:
    """Mock body for uploadPart response."""

    def __init__(self, etag: str = '"part-etag"'):
        self.etag = etag


class MockSignedUrlResponse:
    """Mock response for createSignedUrl."""

    def __init__(self, signed_url: str = "https://example.com/signed"):
        self.signedUrl = signed_url


@pytest.fixture(autouse=True)
def clear_fsspec_cache():
    """Clear fsspec cache before each test."""
    from fsspec import AbstractFileSystem
    AbstractFileSystem._cache.clear()
    yield
    AbstractFileSystem._cache.clear()


@pytest.fixture
def mock_obs_client() -> Generator[MagicMock, None, None]:
    """Create a mock ObsClient."""
    with patch("pyobs.core.ObsClient") as mock_class:
        mock_client = MagicMock()
        mock_class.return_value = mock_client

        # Default responses
        mock_client.listBuckets.return_value = MockResponse(
            body=MockListBucketsBody([MockBucket("test-bucket")])
        )
        mock_client.headBucket.return_value = MockResponse()
        mock_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody()
        )
        mock_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(content_length=100)
        )
        mock_client.getObject.return_value = MockResponse(
            body=MockGetObjectBody(b"test content")
        )
        mock_client.putContent.return_value = MockResponse()
        mock_client.deleteObject.return_value = MockResponse()
        mock_client.deleteObjects.return_value = MockResponse()
        mock_client.copyObject.return_value = MockResponse()
        mock_client.createBucket.return_value = MockResponse()
        mock_client.deleteBucket.return_value = MockResponse()
        mock_client.initiateMultipartUpload.return_value = MockResponse(
            body=MockInitiateMultipartUploadBody()
        )
        mock_client.uploadPart.return_value = MockResponse(
            body=MockUploadPartBody()
        )
        mock_client.completeMultipartUpload.return_value = MockResponse()
        mock_client.abortMultipartUpload.return_value = MockResponse()
        mock_client.createSignedUrl.return_value = MockSignedUrlResponse()

        yield mock_client


@pytest.fixture
def obs_fs(mock_obs_client: MagicMock):
    """Create an OBSFileSystem instance with mocked client."""
    from pyobs import OBSFileSystem

    # Use skip_instance_cache to avoid caching issues in tests
    fs = OBSFileSystem(
        key="test-key",
        secret="test-secret",
        endpoint="https://obs.cn-north-4.myhuaweicloud.com",
        skip_instance_cache=True,
    )
    return fs


@pytest.fixture
def obs_credentials() -> Dict[str, str]:
    """Get OBS credentials from environment variables for integration tests."""
    return {
        "key": os.environ.get("OBS_ACCESS_KEY_ID", ""),
        "secret": os.environ.get("OBS_SECRET_ACCESS_KEY", ""),
        "endpoint": os.environ.get("OBS_ENDPOINT", ""),
        "token": os.environ.get("OBS_SECURITY_TOKEN"),
    }


@pytest.fixture
def test_bucket() -> str:
    """Get test bucket name from environment variable."""
    return os.environ.get("OBS_TEST_BUCKET", "pyobs-test-bucket")


@pytest.fixture
def integration_fs(obs_credentials: Dict[str, str]):
    """Create an OBSFileSystem for integration tests.

    Skips if credentials are not available.
    """
    if not all([obs_credentials["key"], obs_credentials["secret"], obs_credentials["endpoint"]]):
        pytest.skip("OBS credentials not available")

    from pyobs import OBSFileSystem

    return OBSFileSystem(**obs_credentials)
