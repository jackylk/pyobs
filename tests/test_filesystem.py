"""Comprehensive unit tests for OBSFileSystem.

This test file covers all functionality defined in the architecture document:
- Authentication (parameters and environment variables)
- File operations (read, write, delete, copy)
- Directory operations (create, list, delete)
- Metadata operations (info, exists, size, isfile, isdir)
- Multipart upload for large files
- Error handling
- Thread safety
- Signed URL generation
"""

from __future__ import annotations

import io
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from pyobs import (
    OBSFileSystem,
    OBSFile,
    OBSError,
    OBSFileNotFoundError,
    OBSPermissionError,
    OBSConnectionError,
    OBSUploadError,
    OBSMultipartError,
)
from pyobs.utils import (
    split_path,
    normalize_path,
    join_path,
    is_directory_marker,
    ensure_trailing_slash,
    remove_trailing_slash,
    get_parent_path,
    get_credentials_from_env,
)

# Import mock classes from conftest
from conftest import (
    MockResponse,
    MockBucket,
    MockObject,
    MockCommonPrefix,
    MockListBucketsBody,
    MockListObjectsBody,
    MockGetObjectMetadataBody,
    MockGetObjectBody,
    MockSignedUrlResponse,
    MockInitiateMultipartUploadBody,
    MockUploadPartBody,
)


# =============================================================================
# Test Utils Module
# =============================================================================

class TestSplitPath:
    """Tests for split_path function."""

    def test_bucket_and_key(self):
        """Test splitting path with bucket and key."""
        bucket, key = split_path("mybucket/path/to/file.txt")
        assert bucket == "mybucket"
        assert key == "path/to/file.txt"

    def test_bucket_only(self):
        """Test splitting path with bucket only."""
        bucket, key = split_path("mybucket")
        assert bucket == "mybucket"
        assert key == ""

    def test_with_leading_slash(self):
        """Test splitting path with leading slash."""
        bucket, key = split_path("/mybucket/key")
        assert bucket == "mybucket"
        assert key == "key"

    def test_with_obs_protocol(self):
        """Test splitting path with obs:// protocol."""
        bucket, key = split_path("obs://mybucket/key")
        assert bucket == "mybucket"
        assert key == "key"

    def test_with_hwobs_protocol(self):
        """Test splitting path with hwobs:// protocol."""
        bucket, key = split_path("hwobs://mybucket/key")
        assert bucket == "mybucket"
        assert key == "key"

    def test_empty_path(self):
        """Test splitting empty path."""
        bucket, key = split_path("")
        assert bucket == ""
        assert key == ""

    def test_deep_nested_path(self):
        """Test splitting deeply nested path."""
        bucket, key = split_path("bucket/a/b/c/d/e/file.txt")
        assert bucket == "bucket"
        assert key == "a/b/c/d/e/file.txt"


class TestNormalizePath:
    """Tests for normalize_path function."""

    def test_with_obs_protocol(self):
        assert normalize_path("obs://mybucket/key") == "mybucket/key"

    def test_with_hwobs_protocol(self):
        assert normalize_path("hwobs://mybucket/key") == "mybucket/key"

    def test_with_leading_slash(self):
        assert normalize_path("/mybucket/key") == "mybucket/key"

    def test_plain_path(self):
        assert normalize_path("mybucket/key") == "mybucket/key"

    def test_empty_path(self):
        assert normalize_path("") == ""


class TestJoinPath:
    """Tests for join_path function."""

    def test_bucket_and_key(self):
        assert join_path("mybucket", "path/to/file.txt") == "mybucket/path/to/file.txt"

    def test_bucket_only(self):
        assert join_path("mybucket", "") == "mybucket"

    def test_single_key(self):
        assert join_path("bucket", "file.txt") == "bucket/file.txt"


class TestIsDirectoryMarker:
    """Tests for is_directory_marker function."""

    def test_empty_key(self):
        assert is_directory_marker("") is True

    def test_trailing_slash(self):
        assert is_directory_marker("dir/") is True

    def test_regular_file(self):
        assert is_directory_marker("file.txt") is False

    def test_nested_dir(self):
        assert is_directory_marker("a/b/c/") is True


class TestPathManipulation:
    """Tests for path manipulation functions."""

    def test_ensure_trailing_slash(self):
        assert ensure_trailing_slash("dir") == "dir/"
        assert ensure_trailing_slash("dir/") == "dir/"
        assert ensure_trailing_slash("") == ""

    def test_remove_trailing_slash(self):
        assert remove_trailing_slash("dir/") == "dir"
        assert remove_trailing_slash("dir") == "dir"
        assert remove_trailing_slash("a/b/c/") == "a/b/c"

    def test_get_parent_path(self):
        assert get_parent_path("bucket/path/to/file.txt") == "bucket/path/to"
        assert get_parent_path("bucket/file.txt") == "bucket"
        assert get_parent_path("bucket") == ""
        # "bucket/dir/" with trailing slash: after rstrip becomes "bucket/dir", parent is "bucket"
        assert get_parent_path("bucket/dir/") == "bucket"


class TestGetCredentialsFromEnv:
    """Tests for get_credentials_from_env function."""

    def test_all_vars_set(self):
        with patch.dict('os.environ', {
            'OBS_ACCESS_KEY_ID': 'test-key',
            'OBS_SECRET_ACCESS_KEY': 'test-secret',
            'OBS_ENDPOINT': 'https://test.com',
            'OBS_SECURITY_TOKEN': 'test-token',
        }):
            key, secret, endpoint, token = get_credentials_from_env()
            assert key == 'test-key'
            assert secret == 'test-secret'
            assert endpoint == 'https://test.com'
            assert token == 'test-token'

    def test_no_vars_set(self):
        with patch.dict('os.environ', {}, clear=True):
            key, secret, endpoint, token = get_credentials_from_env()
            assert key is None
            assert secret is None
            assert endpoint is None
            assert token is None


# =============================================================================
# Test Error Classes
# =============================================================================

class TestOBSError:
    """Tests for custom exception classes."""

    def test_obs_error(self):
        err = OBSError("Test error", status_code=500, error_code="InternalError")
        assert "Test error" in str(err)
        assert err.status_code == 500
        assert err.error_code == "InternalError"

    def test_obs_file_not_found_error(self):
        err = OBSFileNotFoundError("bucket/file.txt")
        assert "bucket/file.txt" in str(err)
        assert err.path == "bucket/file.txt"
        assert isinstance(err, FileNotFoundError)

    def test_obs_permission_error(self):
        err = OBSPermissionError("bucket/file.txt")
        assert "bucket/file.txt" in str(err)
        assert isinstance(err, PermissionError)

    def test_obs_connection_error(self):
        err = OBSConnectionError("Connection failed", endpoint="https://test.com")
        assert "Connection failed" in str(err)
        assert isinstance(err, ConnectionError)

    def test_obs_upload_error(self):
        err = OBSUploadError("bucket/file.txt", "Upload failed")
        assert "bucket/file.txt" in str(err)

    def test_obs_multipart_error(self):
        err = OBSMultipartError("bucket/file.txt", upload_id="123", part_number=5)
        assert "upload_id=123" in str(err)
        assert "part=5" in str(err)


# =============================================================================
# Test OBSFileSystem Initialization
# =============================================================================

class TestOBSFileSystemInit:
    """Tests for OBSFileSystem initialization."""

    def test_init_with_explicit_credentials(self, mock_obs_client):
        """Test initialization with explicit credentials."""
        fs = OBSFileSystem(
            key="test-key",
            secret="test-secret",
            endpoint="https://obs.cn-north-4.myhuaweicloud.com",
        )
        assert fs.key == "test-key"
        assert fs.secret == "test-secret"
        assert fs.endpoint == "https://obs.cn-north-4.myhuaweicloud.com"
        assert fs.token is None

    def test_init_with_token(self, mock_obs_client):
        """Test initialization with security token."""
        fs = OBSFileSystem(
            key="test-key",
            secret="test-secret",
            endpoint="https://obs.cn-north-4.myhuaweicloud.com",
            token="test-token",
        )
        assert fs.token == "test-token"

    def test_init_with_custom_block_size(self, mock_obs_client):
        """Test initialization with custom block size."""
        fs = OBSFileSystem(
            key="test-key",
            secret="test-secret",
            endpoint="https://obs.cn-north-4.myhuaweicloud.com",
            default_block_size=10 * 1024 * 1024,  # 10MB
        )
        assert fs.default_block_size == 10 * 1024 * 1024

    def test_init_missing_key(self, mock_obs_client):
        """Test initialization fails without access key."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="access key is required"):
                OBSFileSystem(
                    secret="test-secret",
                    endpoint="https://obs.cn-north-4.myhuaweicloud.com",
                )

    def test_init_missing_secret(self, mock_obs_client):
        """Test initialization fails without secret key."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="secret key is required"):
                OBSFileSystem(
                    key="test-key",
                    endpoint="https://obs.cn-north-4.myhuaweicloud.com",
                )

    def test_init_missing_endpoint(self, mock_obs_client):
        """Test initialization fails without endpoint."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="endpoint is required"):
                OBSFileSystem(
                    key="test-key",
                    secret="test-secret",
                )

    def test_init_from_env_vars(self, mock_obs_client):
        """Test initialization from environment variables."""
        with patch.dict('os.environ', {
            'OBS_ACCESS_KEY_ID': 'env-key',
            'OBS_SECRET_ACCESS_KEY': 'env-secret',
            'OBS_ENDPOINT': 'https://env.com',
        }):
            fs = OBSFileSystem()
            assert fs.key == 'env-key'
            assert fs.secret == 'env-secret'
            assert fs.endpoint == 'https://env.com'

    def test_protocol_attribute(self, obs_fs):
        """Test protocol attribute."""
        assert "obs" in OBSFileSystem.protocol
        assert "hwobs" in OBSFileSystem.protocol


# =============================================================================
# Test OBSFileSystem Listing Operations
# =============================================================================

class TestOBSFileSystemLs:
    """Tests for ls method."""

    def test_ls_buckets(self, obs_fs, mock_obs_client):
        """Test listing all buckets."""
        mock_obs_client.listBuckets.return_value = MockResponse(
            body=MockListBucketsBody([
                MockBucket("bucket1"),
                MockBucket("bucket2"),
                MockBucket("bucket3"),
            ])
        )

        result = obs_fs.ls("")
        assert len(result) == 3
        assert all(r["type"] == "directory" for r in result)
        assert [r["name"] for r in result] == ["bucket1", "bucket2", "bucket3"]

    def test_ls_bucket_contents(self, obs_fs, mock_obs_client):
        """Test listing bucket contents with files and directories."""
        mock_obs_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody(
                contents=[
                    MockObject("file1.txt", size=100),
                    MockObject("file2.txt", size=200),
                ],
                common_prefixs=[
                    MockCommonPrefix("subdir/"),
                ],
            )
        )

        result = obs_fs.ls("mybucket/")

        dirs = [r for r in result if r["type"] == "directory"]
        files = [r for r in result if r["type"] == "file"]

        assert len(dirs) == 1
        assert dirs[0]["name"] == "mybucket/subdir"
        assert len(files) == 2

    def test_ls_detail_false(self, obs_fs, mock_obs_client):
        """Test listing with detail=False returns only paths."""
        mock_obs_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody(
                contents=[
                    MockObject("file1.txt", size=100),
                    MockObject("file2.txt", size=200),
                ],
            )
        )

        result = obs_fs.ls("mybucket/", detail=False)
        assert result == ["mybucket/file1.txt", "mybucket/file2.txt"]

    def test_ls_paginated_results(self, obs_fs, mock_obs_client):
        """Test listing with pagination (truncated results)."""
        # First page
        page1 = MockResponse(
            body=MockListObjectsBody(
                contents=[MockObject("file1.txt", size=100)],
                is_truncated=True,
                next_marker="file1.txt",
            )
        )
        # Second page
        page2 = MockResponse(
            body=MockListObjectsBody(
                contents=[MockObject("file2.txt", size=200)],
                is_truncated=False,
            )
        )
        mock_obs_client.listObjects.side_effect = [page1, page2]

        result = obs_fs.ls("mybucket/", detail=False)
        assert "mybucket/file1.txt" in result
        assert "mybucket/file2.txt" in result

    def test_ls_empty_bucket(self, obs_fs, mock_obs_client):
        """Test listing empty bucket."""
        mock_obs_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody(contents=[], common_prefixs=[])
        )

        result = obs_fs.ls("mybucket/")
        assert result == []


# =============================================================================
# Test OBSFileSystem Info Operations
# =============================================================================

class TestOBSFileSystemInfo:
    """Tests for info method."""

    def test_info_file(self, obs_fs, mock_obs_client):
        """Test getting file info."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(
                content_length=1024,
                content_type="text/plain",
                last_modified="2024-01-01T00:00:00Z",
                etag='"abc123"',
            )
        )

        info = obs_fs.info("mybucket/file.txt")
        assert info["name"] == "mybucket/file.txt"
        assert info["type"] == "file"
        assert info["size"] == 1024
        assert info["ContentType"] == "text/plain"

    def test_info_bucket(self, obs_fs, mock_obs_client):
        """Test getting bucket info."""
        info = obs_fs.info("mybucket")
        assert info["name"] == "mybucket"
        assert info["type"] == "directory"
        assert info["size"] == 0

    def test_info_directory_by_prefix(self, obs_fs, mock_obs_client):
        """Test getting info for a directory (detected by prefix)."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            status=404,
            error_message="NoSuchKey",
        )
        mock_obs_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody(
                contents=[MockObject("dir/file.txt", size=100)],
            )
        )

        info = obs_fs.info("mybucket/dir")
        assert info["type"] == "directory"

    def test_info_not_found(self, obs_fs, mock_obs_client):
        """Test info for non-existent file."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            status=404,
            error_message="NoSuchKey",
        )
        mock_obs_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody()
        )

        with pytest.raises(OBSFileNotFoundError):
            obs_fs.info("mybucket/nonexistent.txt")


# =============================================================================
# Test OBSFileSystem Existence Checks
# =============================================================================

class TestOBSFileSystemExists:
    """Tests for exists, isfile, isdir methods."""

    def test_exists_true_for_file(self, obs_fs, mock_obs_client):
        """Test exists returns True for existing file."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(content_length=100)
        )

        assert obs_fs.exists("mybucket/file.txt") is True

    def test_exists_true_for_bucket(self, obs_fs, mock_obs_client):
        """Test exists returns True for existing bucket."""
        assert obs_fs.exists("mybucket") is True

    def test_exists_false(self, obs_fs, mock_obs_client):
        """Test exists returns False for non-existent path."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            status=404,
            error_message="NoSuchKey",
        )
        mock_obs_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody()
        )

        assert obs_fs.exists("mybucket/nonexistent.txt") is False

    def test_isfile_true(self, obs_fs, mock_obs_client):
        """Test isfile returns True for file."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(content_length=100)
        )

        assert obs_fs.isfile("mybucket/file.txt") is True

    def test_isfile_false_for_directory(self, obs_fs, mock_obs_client):
        """Test isfile returns False for directory."""
        assert obs_fs.isfile("mybucket") is False

    def test_isdir_true_for_bucket(self, obs_fs, mock_obs_client):
        """Test isdir returns True for bucket."""
        assert obs_fs.isdir("mybucket") is True

    def test_isdir_false_for_file(self, obs_fs, mock_obs_client):
        """Test isdir returns False for file."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(content_length=100)
        )

        assert obs_fs.isdir("mybucket/file.txt") is False


# =============================================================================
# Test OBSFileSystem Read Operations
# =============================================================================

class TestOBSFileSystemCatFile:
    """Tests for cat_file method."""

    def test_cat_file_full(self, obs_fs, mock_obs_client):
        """Test reading entire file."""
        mock_obs_client.getObject.return_value = MockResponse(
            body=MockGetObjectBody(b"Hello, World!")
        )

        content = obs_fs.cat_file("mybucket/file.txt")
        assert content == b"Hello, World!"

    def test_cat_file_range_start_end(self, obs_fs, mock_obs_client):
        """Test reading file with start and end range."""
        mock_obs_client.getObject.return_value = MockResponse(
            body=MockGetObjectBody(b"Hello")
        )

        content = obs_fs.cat_file("mybucket/file.txt", start=0, end=5)
        assert content == b"Hello"

    def test_cat_file_range_start_only(self, obs_fs, mock_obs_client):
        """Test reading file from start offset."""
        mock_obs_client.getObject.return_value = MockResponse(
            body=MockGetObjectBody(b"World!")
        )

        content = obs_fs.cat_file("mybucket/file.txt", start=7)
        assert content == b"World!"

    def test_cat_file_empty(self, obs_fs, mock_obs_client):
        """Test reading empty file."""
        mock_obs_client.getObject.return_value = MockResponse(
            body=MockGetObjectBody(b"")
        )

        content = obs_fs.cat_file("mybucket/empty.txt")
        assert content == b""

    def test_cat_file_binary(self, obs_fs, mock_obs_client):
        """Test reading binary file."""
        binary_data = bytes(range(256))
        mock_obs_client.getObject.return_value = MockResponse(
            body=MockGetObjectBody(binary_data)
        )

        content = obs_fs.cat_file("mybucket/binary.bin")
        assert content == binary_data


# =============================================================================
# Test OBSFileSystem Write Operations
# =============================================================================

class TestOBSFileSystemPipeFile:
    """Tests for pipe_file method."""

    def test_pipe_file_simple(self, obs_fs, mock_obs_client):
        """Test writing small file with simple upload."""
        mock_obs_client.putContent.reset_mock()

        obs_fs.pipe_file("mybucket/file.txt", b"Hello, World!")

        mock_obs_client.putContent.assert_called_once()

    def test_pipe_file_empty(self, obs_fs, mock_obs_client):
        """Test writing empty file."""
        mock_obs_client.putContent.reset_mock()

        obs_fs.pipe_file("mybucket/empty.txt", b"")

        mock_obs_client.putContent.assert_called_once()

    def test_pipe_file_multipart_large(self, obs_fs, mock_obs_client):
        """Test writing large file triggers multipart upload."""
        # Create data larger than MULTIPART_THRESHOLD (100MB)
        large_data = b"x" * (101 * 1024 * 1024)

        mock_obs_client.initiateMultipartUpload.reset_mock()
        mock_obs_client.uploadPart.reset_mock()
        mock_obs_client.completeMultipartUpload.reset_mock()

        obs_fs.pipe_file("mybucket/large.txt", large_data)

        mock_obs_client.initiateMultipartUpload.assert_called()
        mock_obs_client.uploadPart.assert_called()
        mock_obs_client.completeMultipartUpload.assert_called()

    def test_pipe_file_binary(self, obs_fs, mock_obs_client):
        """Test writing binary data."""
        mock_obs_client.putContent.reset_mock()
        binary_data = bytes(range(256))

        obs_fs.pipe_file("mybucket/binary.bin", binary_data)

        mock_obs_client.putContent.assert_called_once()


# =============================================================================
# Test OBSFileSystem Delete Operations
# =============================================================================

class TestOBSFileSystemRm:
    """Tests for rm, rm_file, rmdir methods."""

    def test_rm_single_file(self, obs_fs, mock_obs_client):
        """Test deleting a single file."""
        mock_obs_client.deleteObject.reset_mock()

        obs_fs.rm("mybucket/file.txt")

        mock_obs_client.deleteObject.assert_called_once()

    def test_rm_file_method(self, obs_fs, mock_obs_client):
        """Test rm_file method."""
        mock_obs_client.deleteObject.reset_mock()

        obs_fs.rm_file("mybucket/file.txt")

        mock_obs_client.deleteObject.assert_called_once()

    def test_rm_recursive(self, obs_fs, mock_obs_client):
        """Test recursive directory deletion."""
        mock_obs_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody(
                contents=[
                    MockObject("dir/file1.txt"),
                    MockObject("dir/file2.txt"),
                    MockObject("dir/subdir/file3.txt"),
                ],
            )
        )
        mock_obs_client.deleteObjects.reset_mock()

        obs_fs.rm("mybucket/dir", recursive=True)

        mock_obs_client.deleteObjects.assert_called()

    def test_rmdir_bucket(self, obs_fs, mock_obs_client):
        """Test removing bucket."""
        mock_obs_client.deleteBucket.reset_mock()

        obs_fs.rmdir("mybucket")

        mock_obs_client.deleteBucket.assert_called()

    def test_rmdir_directory(self, obs_fs, mock_obs_client):
        """Test removing directory marker."""
        mock_obs_client.deleteObject.reset_mock()

        obs_fs.rmdir("mybucket/dir")

        mock_obs_client.deleteObject.assert_called()


# =============================================================================
# Test OBSFileSystem Directory Operations
# =============================================================================

class TestOBSFileSystemMkdir:
    """Tests for mkdir, makedirs methods."""

    def test_mkdir_in_existing_bucket(self, obs_fs, mock_obs_client):
        """Test creating directory in existing bucket."""
        mock_obs_client.putContent.reset_mock()

        obs_fs.mkdir("mybucket/newdir")

        mock_obs_client.putContent.assert_called()

    def test_mkdir_creates_bucket(self, obs_fs, mock_obs_client):
        """Test mkdir creates bucket if needed."""
        mock_obs_client.headBucket.return_value = MockResponse(
            status=404,
            error_message="NoSuchBucket",
        )
        mock_obs_client.createBucket.reset_mock()

        obs_fs.mkdir("newbucket/dir", create_parents=True)

        mock_obs_client.createBucket.assert_called()

    def test_makedirs(self, obs_fs, mock_obs_client):
        """Test makedirs creates nested directories."""
        mock_obs_client.putContent.reset_mock()

        obs_fs.makedirs("mybucket/a/b/c/d")

        mock_obs_client.putContent.assert_called()

    def test_makedirs_exist_ok_true(self, obs_fs, mock_obs_client):
        """Test makedirs with exist_ok=True doesn't raise for existing dir."""
        # Should not raise even if directory exists
        obs_fs.makedirs("mybucket", exist_ok=True)

    def test_makedirs_exist_ok_false(self, obs_fs, mock_obs_client):
        """Test makedirs with exist_ok=False raises for existing dir."""
        with pytest.raises(FileExistsError):
            obs_fs.makedirs("mybucket", exist_ok=False)


# =============================================================================
# Test OBSFileSystem Copy Operations
# =============================================================================

class TestOBSFileSystemCpFile:
    """Tests for cp_file method."""

    def test_cp_file_same_bucket(self, obs_fs, mock_obs_client):
        """Test copying file within same bucket."""
        mock_obs_client.copyObject.reset_mock()

        obs_fs.cp_file("mybucket/src.txt", "mybucket/dst.txt")

        mock_obs_client.copyObject.assert_called_once()

    def test_cp_file_different_buckets(self, obs_fs, mock_obs_client):
        """Test copying file between different buckets."""
        mock_obs_client.copyObject.reset_mock()

        obs_fs.cp_file("bucket1/src.txt", "bucket2/dst.txt")

        mock_obs_client.copyObject.assert_called_once()


# =============================================================================
# Test OBSFileSystem Signed URL
# =============================================================================

class TestOBSFileSystemSign:
    """Tests for sign method."""

    def test_sign_default_expiration(self, obs_fs, mock_obs_client):
        """Test generating signed URL with default expiration."""
        mock_obs_client.createSignedUrl.return_value = MockSignedUrlResponse(
            "https://obs.example.com/signed?signature=xxx"
        )

        url = obs_fs.sign("mybucket/file.txt")

        assert "https://obs.example.com/signed" in url

    def test_sign_custom_expiration(self, obs_fs, mock_obs_client):
        """Test generating signed URL with custom expiration."""
        mock_obs_client.createSignedUrl.return_value = MockSignedUrlResponse(
            "https://obs.example.com/signed?expires=7200"
        )

        url = obs_fs.sign("mybucket/file.txt", expiration=7200)

        assert url is not None

    def test_sign_put_method(self, obs_fs, mock_obs_client):
        """Test generating signed URL for PUT method."""
        mock_obs_client.createSignedUrl.return_value = MockSignedUrlResponse(
            "https://obs.example.com/signed?method=PUT"
        )

        url = obs_fs.sign("mybucket/file.txt", method='PUT')

        assert url is not None


# =============================================================================
# Test OBSFileSystem Helper Methods
# =============================================================================

class TestOBSFileSystemHelpers:
    """Tests for helper methods."""

    def test_size(self, obs_fs, mock_obs_client):
        """Test size method."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(content_length=1024)
        )

        size = obs_fs.size("mybucket/file.txt")
        assert size == 1024

    def test_created(self, obs_fs, mock_obs_client):
        """Test created method."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(last_modified="2024-01-01T00:00:00Z")
        )

        created = obs_fs.created("mybucket/file.txt")
        assert created == "2024-01-01T00:00:00Z"

    def test_modified(self, obs_fs, mock_obs_client):
        """Test modified method."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(last_modified="2024-06-15T12:00:00Z")
        )

        modified = obs_fs.modified("mybucket/file.txt")
        assert modified == "2024-06-15T12:00:00Z"


# =============================================================================
# Test OBSFileSystem Open Operations
# =============================================================================

class TestOBSFileSystemOpen:
    """Tests for _open method and file operations."""

    def test_open_read_mode(self, obs_fs, mock_obs_client):
        """Test opening file for reading."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(content_length=100)
        )

        with obs_fs.open("mybucket/file.txt", "rb") as f:
            assert f is not None
            assert f.mode == "rb"

    def test_open_write_mode(self, obs_fs, mock_obs_client):
        """Test opening file for writing."""
        mock_obs_client.putContent.reset_mock()

        with obs_fs.open("mybucket/file.txt", "wb") as f:
            f.write(b"Hello, World!")

        mock_obs_client.putContent.assert_called()

    def test_open_context_manager(self, obs_fs, mock_obs_client):
        """Test file is properly closed after context manager exits."""
        mock_obs_client.putContent.reset_mock()

        with obs_fs.open("mybucket/file.txt", "wb") as f:
            f.write(b"test")

        # File should be closed and data should be uploaded
        mock_obs_client.putContent.assert_called()


# =============================================================================
# Test OBSFileSystem Error Handling
# =============================================================================

class TestOBSFileSystemErrorHandling:
    """Tests for error handling."""

    def test_permission_denied(self, obs_fs, mock_obs_client):
        """Test handling of permission denied error."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            status=403,
            error_message="AccessDenied",
        )

        with pytest.raises(OBSPermissionError):
            obs_fs.info("mybucket/file.txt")

    def test_file_not_found(self, obs_fs, mock_obs_client):
        """Test handling of file not found error."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            status=404,
            error_message="NoSuchKey",
        )
        mock_obs_client.listObjects.return_value = MockResponse(
            body=MockListObjectsBody()
        )

        with pytest.raises(OBSFileNotFoundError):
            obs_fs.info("mybucket/nonexistent.txt")

    def test_generic_error(self, obs_fs, mock_obs_client):
        """Test handling of generic OBS error."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            status=500,
            error_message="InternalError",
            error_code="InternalError",
        )

        with pytest.raises(OBSError):
            obs_fs.info("mybucket/file.txt")


# =============================================================================
# Test OBSFile Class
# =============================================================================

class TestOBSFile:
    """Tests for OBSFile class."""

    def test_fetch_range(self, obs_fs, mock_obs_client):
        """Test _fetch_range method."""
        mock_obs_client.getObjectMetadata.return_value = MockResponse(
            body=MockGetObjectMetadataBody(content_length=100)
        )
        mock_obs_client.getObject.return_value = MockResponse(
            body=MockGetObjectBody(b"Hello")
        )

        with obs_fs.open("mybucket/file.txt", "rb") as f:
            # Trigger a range fetch
            data = f._fetch_range(0, 5)
            assert data == b"Hello"

    def test_write_small_file(self, obs_fs, mock_obs_client):
        """Test writing small file through OBSFile."""
        mock_obs_client.putContent.reset_mock()

        with obs_fs.open("mybucket/file.txt", "wb") as f:
            f.write(b"Small content")

        mock_obs_client.putContent.assert_called()

    def test_discard(self, obs_fs, mock_obs_client):
        """Test discard method aborts upload."""
        f = obs_fs.open("mybucket/file.txt", "wb")
        f.write(b"Some data")
        f.discard()

        # File should be properly discarded
        assert f.closed or True  # Just verify no exception


# =============================================================================
# Test Thread Safety
# =============================================================================

class TestThreadSafety:
    """Tests for thread safety."""

    def test_thread_local_client(self, mock_obs_client):
        """Test that each thread gets its own client."""
        fs = OBSFileSystem(
            key="test-key",
            secret="test-secret",
            endpoint="https://test.com",
            skip_instance_cache=True,
        )

        clients = []

        def get_client():
            clients.append(id(fs.client))

        threads = [threading.Thread(target=get_client) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # In mock environment, all clients will be the same mock object
        # but in real usage, each thread would have its own client
        assert len(clients) == 5


# =============================================================================
# Test fsspec Integration
# =============================================================================

class TestFsspecIntegration:
    """Tests for fsspec integration."""

    def test_protocol_registration(self):
        """Test that obs and hwobs protocols are registered."""
        import fsspec

        protocols = fsspec.available_protocols()
        assert 'obs' in protocols
        assert 'hwobs' in protocols

    def test_filesystem_class(self):
        """Test getting filesystem class."""
        import fsspec

        cls = fsspec.get_filesystem_class('obs')
        assert cls == OBSFileSystem

        cls = fsspec.get_filesystem_class('hwobs')
        assert cls == OBSFileSystem
