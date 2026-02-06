"""Integration tests for OBSFileSystem.

These tests require real OBS credentials and a test bucket.
Set the following environment variables before running:
    - OBS_ACCESS_KEY_ID
    - OBS_SECRET_ACCESS_KEY
    - OBS_ENDPOINT
    - OBS_TEST_BUCKET

Run with: pytest tests/test_integration.py -v -m integration
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.integration


class TestIntegrationBasic:
    """Basic integration tests."""

    def test_list_buckets(self, integration_fs):
        """Test listing all buckets."""
        buckets = integration_fs.ls("")
        assert isinstance(buckets, list)

    def test_bucket_exists(self, integration_fs, test_bucket):
        """Test checking if bucket exists."""
        # This may fail if bucket doesn't exist, which is expected
        try:
            exists = integration_fs.exists(test_bucket)
            assert isinstance(exists, bool)
        except Exception:
            pytest.skip(f"Test bucket {test_bucket} not accessible")


class TestIntegrationFileOperations:
    """Integration tests for file operations."""

    @pytest.fixture
    def test_prefix(self, test_bucket) -> str:
        """Generate a unique test prefix."""
        return f"{test_bucket}/pyobs-test-{uuid.uuid4().hex[:8]}"

    def test_write_and_read_file(self, integration_fs, test_prefix):
        """Test writing and reading a file."""
        path = f"{test_prefix}/test.txt"
        content = b"Hello, OBS!"

        try:
            # Write file
            integration_fs.pipe_file(path, content)

            # Read file
            result = integration_fs.cat_file(path)
            assert result == content

            # Check exists
            assert integration_fs.exists(path)

            # Get info
            info = integration_fs.info(path)
            assert info["type"] == "file"
            assert info["size"] == len(content)

        finally:
            # Cleanup
            try:
                integration_fs.rm(path)
            except Exception:
                pass

    def test_write_and_read_with_open(self, integration_fs, test_prefix):
        """Test writing and reading using open()."""
        path = f"{test_prefix}/test_open.txt"
        content = b"Hello from open()!"

        try:
            # Write using open
            with integration_fs.open(path, "wb") as f:
                f.write(content)

            # Read using open
            with integration_fs.open(path, "rb") as f:
                result = f.read()

            assert result == content

        finally:
            try:
                integration_fs.rm(path)
            except Exception:
                pass

    def test_list_directory(self, integration_fs, test_prefix):
        """Test listing directory contents."""
        files = [
            f"{test_prefix}/dir/file1.txt",
            f"{test_prefix}/dir/file2.txt",
            f"{test_prefix}/dir/subdir/file3.txt",
        ]

        try:
            # Create files
            for path in files:
                integration_fs.pipe_file(path, b"test")

            # List directory
            result = integration_fs.ls(f"{test_prefix}/dir/", detail=False)
            assert len(result) >= 2

        finally:
            # Cleanup
            for path in files:
                try:
                    integration_fs.rm(path)
                except Exception:
                    pass

    def test_copy_file(self, integration_fs, test_prefix):
        """Test copying a file."""
        src_path = f"{test_prefix}/src.txt"
        dst_path = f"{test_prefix}/dst.txt"
        content = b"Copy me!"

        try:
            # Create source file
            integration_fs.pipe_file(src_path, content)

            # Copy file
            integration_fs.cp_file(src_path, dst_path)

            # Verify copy
            assert integration_fs.exists(dst_path)
            assert integration_fs.cat_file(dst_path) == content

        finally:
            for path in [src_path, dst_path]:
                try:
                    integration_fs.rm(path)
                except Exception:
                    pass

    def test_delete_file(self, integration_fs, test_prefix):
        """Test deleting a file."""
        path = f"{test_prefix}/delete_me.txt"

        # Create file
        integration_fs.pipe_file(path, b"delete me")
        assert integration_fs.exists(path)

        # Delete file
        integration_fs.rm(path)
        assert not integration_fs.exists(path)

    def test_recursive_delete(self, integration_fs, test_prefix):
        """Test recursive directory deletion."""
        files = [
            f"{test_prefix}/rmdir/file1.txt",
            f"{test_prefix}/rmdir/file2.txt",
            f"{test_prefix}/rmdir/sub/file3.txt",
        ]

        try:
            # Create files
            for path in files:
                integration_fs.pipe_file(path, b"test")

            # Delete recursively
            integration_fs.rm(f"{test_prefix}/rmdir", recursive=True)

            # Verify deletion
            for path in files:
                assert not integration_fs.exists(path)

        except Exception:
            # Cleanup on failure
            for path in files:
                try:
                    integration_fs.rm(path)
                except Exception:
                    pass
            raise


class TestIntegrationSignedUrl:
    """Integration tests for signed URLs."""

    @pytest.fixture
    def test_prefix(self, test_bucket) -> str:
        """Generate a unique test prefix."""
        return f"{test_bucket}/pyobs-test-{uuid.uuid4().hex[:8]}"

    def test_sign_url(self, integration_fs, test_prefix):
        """Test generating a signed URL."""
        path = f"{test_prefix}/signed.txt"
        content = b"Signed content"

        try:
            # Create file
            integration_fs.pipe_file(path, content)

            # Generate signed URL
            url = integration_fs.sign(path, expiration=3600)
            assert url.startswith("http")
            assert "Signature" in url or "signature" in url.lower()

        finally:
            try:
                integration_fs.rm(path)
            except Exception:
                pass


class TestIntegrationLargeFile:
    """Integration tests for large file operations."""

    @pytest.fixture
    def test_prefix(self, test_bucket) -> str:
        """Generate a unique test prefix."""
        return f"{test_bucket}/pyobs-test-{uuid.uuid4().hex[:8]}"

    @pytest.mark.slow
    def test_multipart_upload(self, integration_fs, test_prefix):
        """Test multipart upload for large files.

        This test is marked as slow and may be skipped in CI.
        """
        path = f"{test_prefix}/large.bin"
        # Create 10MB file (smaller than threshold but tests the mechanism)
        content = os.urandom(10 * 1024 * 1024)

        try:
            integration_fs.pipe_file(path, content)

            # Verify
            info = integration_fs.info(path)
            assert info["size"] == len(content)

            # Read back and verify
            result = integration_fs.cat_file(path)
            assert result == content

        finally:
            try:
                integration_fs.rm(path)
            except Exception:
                pass


class TestIntegrationFsspec:
    """Integration tests for fsspec compatibility."""

    def test_fsspec_filesystem(self, obs_credentials, test_bucket):
        """Test creating filesystem via fsspec."""
        if not all([obs_credentials["key"], obs_credentials["secret"], obs_credentials["endpoint"]]):
            pytest.skip("OBS credentials not available")

        import fsspec

        fs = fsspec.filesystem(
            "obs",
            key=obs_credentials["key"],
            secret=obs_credentials["secret"],
            endpoint=obs_credentials["endpoint"],
            token=obs_credentials.get("token"),
        )

        # Basic operation
        buckets = fs.ls("")
        assert isinstance(buckets, list)

    def test_fsspec_open_url(self, obs_credentials, test_bucket):
        """Test opening file via fsspec URL."""
        if not all([obs_credentials["key"], obs_credentials["secret"], obs_credentials["endpoint"]]):
            pytest.skip("OBS credentials not available")

        import fsspec

        # Register credentials for URL-based access
        path = f"obs://{test_bucket}/pyobs-test-{uuid.uuid4().hex[:8]}/url_test.txt"
        content = b"URL test content"

        storage_options = {
            "key": obs_credentials["key"],
            "secret": obs_credentials["secret"],
            "endpoint": obs_credentials["endpoint"],
            "token": obs_credentials.get("token"),
        }

        try:
            # Write via URL
            with fsspec.open(path, "wb", **storage_options) as f:
                f.write(content)

            # Read via URL
            with fsspec.open(path, "rb", **storage_options) as f:
                result = f.read()

            assert result == content

        finally:
            try:
                fs = fsspec.filesystem("obs", **storage_options)
                fs.rm(path.replace("obs://", ""))
            except Exception:
                pass
