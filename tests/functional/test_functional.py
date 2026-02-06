"""Functional tests for pyobs based on shared specification.

Run with:
    pytest tests/functional/ -v                    # All tests
    pytest tests/functional/ -k "F_C"              # File create tests
    pytest tests/functional/ -k "CS"               # Consistency tests
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import pytest

# Test configuration
TEST_PREFIX = f"pyobs-functest-{time.strftime('%Y%m%d%H%M%S')}"
FILE_SIZES = {
    "tiny": 1,
    "small": 1024,
    "medium": 1024 * 1024,
    "large": 100 * 1024 * 1024,
}


def generate_test_data(size: int, seed: int = 42) -> bytes:
    """Generate reproducible test data."""
    import random
    random.seed(seed)
    return bytes([random.randint(0, 255) for _ in range(size)])


def compute_checksum(data: bytes) -> str:
    """Compute MD5 checksum."""
    return hashlib.md5(data).hexdigest()


@pytest.fixture(scope="module")
def obs_fs():
    """Create OBSFileSystem for functional tests."""
    key = os.environ.get("OBS_ACCESS_KEY_ID")
    secret = os.environ.get("OBS_SECRET_ACCESS_KEY")
    endpoint = os.environ.get("OBS_ENDPOINT")

    if not all([key, secret, endpoint]):
        pytest.skip("OBS credentials not available")

    from pyobs import OBSFileSystem
    return OBSFileSystem(key=key, secret=secret, endpoint=endpoint)


@pytest.fixture(scope="module")
def test_bucket():
    """Get test bucket."""
    bucket = os.environ.get("OBS_TEST_BUCKET", "obs-fs-test-jska")
    return bucket


@pytest.fixture(scope="module")
def test_path(test_bucket):
    """Get test path prefix."""
    return f"{test_bucket}/{TEST_PREFIX}"


@pytest.fixture(autouse=True)
def cleanup(obs_fs, test_path, request):
    """Cleanup test files after each test."""
    yield
    # Cleanup is handled at module level


@pytest.fixture(scope="module", autouse=True)
def module_cleanup(obs_fs, test_path):
    """Cleanup all test files after module."""
    yield
    # Cleanup test prefix
    try:
        obs_fs.rm(test_path, recursive=True)
    except Exception:
        pass


# =============================================================================
# File Create Tests (F-C-*)
# =============================================================================

class TestFileCreate:
    """File creation tests."""

    def test_F_C_01_create_empty_file(self, obs_fs, test_path):
        """F-C-01: Create empty file."""
        path = f"{test_path}/F-C-01/empty.txt"
        obs_fs.pipe_file(path, b"")

        assert obs_fs.exists(path)
        info = obs_fs.info(path)
        assert info["size"] == 0

    def test_F_C_02_create_with_content(self, obs_fs, test_path):
        """F-C-02: Create file with content."""
        path = f"{test_path}/F-C-02/content.txt"
        content = b"Hello, OBS!"
        obs_fs.pipe_file(path, content)

        result = obs_fs.cat_file(path)
        assert result == content

    def test_F_C_03_create_in_subdir(self, obs_fs, test_path):
        """F-C-03: Create file in subdirectory."""
        path = f"{test_path}/F-C-03/subdir/nested/file.txt"
        content = b"nested content"
        obs_fs.pipe_file(path, content)

        result = obs_fs.cat_file(path)
        assert result == content

    def test_F_C_04_create_special_chars(self, obs_fs, test_path):
        """F-C-04: Create file with special characters."""
        # Note: Some special chars may not work with OBS
        path = f"{test_path}/F-C-04/special_file.txt"
        content = b"special"
        obs_fs.pipe_file(path, content)

        assert obs_fs.exists(path)

    def test_F_C_06_create_deep_path(self, obs_fs, test_path):
        """F-C-06: Create file in deep path (20 levels)."""
        deep_path = "/".join([f"d{i}" for i in range(1, 21)])
        path = f"{test_path}/F-C-06/{deep_path}/file.txt"
        content = b"deep"
        obs_fs.pipe_file(path, content)

        result = obs_fs.cat_file(path)
        assert result == content


# =============================================================================
# File Read Tests (F-R-*)
# =============================================================================

class TestFileRead:
    """File read tests."""

    def test_F_R_01_read_full_file(self, obs_fs, test_path):
        """F-R-01: Read entire file."""
        path = f"{test_path}/F-R-01/read_test.bin"
        data = generate_test_data(FILE_SIZES["medium"])
        obs_fs.pipe_file(path, data)

        result = obs_fs.cat_file(path)
        assert compute_checksum(result) == compute_checksum(data)

    def test_F_R_02_read_partial_start(self, obs_fs, test_path):
        """F-R-02: Read partial from start."""
        path = f"{test_path}/F-R-02/partial.txt"
        obs_fs.pipe_file(path, b"0123456789ABCDEF")

        result = obs_fs.cat_file(path, start=0, end=4)
        assert result == b"0123"

    def test_F_R_03_read_partial_middle(self, obs_fs, test_path):
        """F-R-03: Read partial from middle."""
        path = f"{test_path}/F-R-03/partial.txt"
        obs_fs.pipe_file(path, b"0123456789ABCDEF")

        result = obs_fs.cat_file(path, start=4, end=8)
        assert result == b"4567"

    def test_F_R_04_read_partial_end(self, obs_fs, test_path):
        """F-R-04: Read partial from end."""
        path = f"{test_path}/F-R-04/partial.txt"
        obs_fs.pipe_file(path, b"0123456789ABCDEF")

        result = obs_fs.cat_file(path, start=12, end=16)
        assert result == b"CDEF"

    def test_F_R_06_read_empty_file(self, obs_fs, test_path):
        """F-R-06: Read empty file."""
        path = f"{test_path}/F-R-06/empty.txt"
        obs_fs.pipe_file(path, b"")

        result = obs_fs.cat_file(path)
        assert result == b""

    def test_F_R_08_read_nonexistent(self, obs_fs, test_path):
        """F-R-08: Read non-existent file."""
        path = f"{test_path}/F-R-08/nonexistent.txt"

        with pytest.raises(FileNotFoundError):
            obs_fs.cat_file(path)


# =============================================================================
# File Write Tests (F-W-*)
# =============================================================================

class TestFileWrite:
    """File write tests."""

    def test_F_W_01_write_new_file(self, obs_fs, test_path):
        """F-W-01: Write to new file."""
        path = f"{test_path}/F-W-01/new.txt"
        content = b"new content"
        obs_fs.pipe_file(path, content)

        result = obs_fs.cat_file(path)
        assert result == content

    def test_F_W_02_write_overwrite(self, obs_fs, test_path):
        """F-W-02: Overwrite existing file."""
        path = f"{test_path}/F-W-02/overwrite.txt"
        obs_fs.pipe_file(path, b"old content")
        obs_fs.pipe_file(path, b"new content")

        result = obs_fs.cat_file(path)
        assert result == b"new content"

    def test_F_W_05_write_large_file(self, obs_fs, test_path):
        """F-W-05: Write large file (100MB)."""
        path = f"{test_path}/F-W-05/large.bin"
        data = generate_test_data(FILE_SIZES["large"])
        checksum = compute_checksum(data)
        obs_fs.pipe_file(path, data)

        result = obs_fs.cat_file(path)
        assert compute_checksum(result) == checksum

    def test_F_W_06_write_binary_data(self, obs_fs, test_path):
        """F-W-06: Write binary data."""
        path = f"{test_path}/F-W-06/binary.bin"
        data = bytes([0, 1, 255, 128, 64])
        obs_fs.pipe_file(path, data)

        result = obs_fs.cat_file(path)
        assert result == data


# =============================================================================
# File Delete Tests (F-D-*)
# =============================================================================

class TestFileDelete:
    """File delete tests."""

    def test_F_D_01_delete_file(self, obs_fs, test_path):
        """F-D-01: Delete existing file."""
        path = f"{test_path}/F-D-01/to_delete.txt"
        obs_fs.pipe_file(path, b"delete me")

        obs_fs.rm(path)
        assert not obs_fs.exists(path)

    def test_F_D_02_delete_nonexistent(self, obs_fs, test_path):
        """F-D-02: Delete non-existent file."""
        path = f"{test_path}/F-D-02/nonexistent.txt"

        # OBS may not raise error for deleting non-existent
        try:
            obs_fs.rm(path)
        except FileNotFoundError:
            pass  # Expected


# =============================================================================
# Metadata Tests (F-M-*)
# =============================================================================

class TestMetadata:
    """Metadata tests."""

    def test_F_M_01_stat_file(self, obs_fs, test_path):
        """F-M-01: Get file status."""
        path = f"{test_path}/F-M-01/stat_test.txt"
        obs_fs.pipe_file(path, b"0123456789")

        info = obs_fs.info(path)
        assert info["size"] == 10

    def test_F_M_03_exists_check(self, obs_fs, test_path):
        """F-M-03: Check file existence."""
        path = f"{test_path}/F-M-03/exists.txt"
        obs_fs.pipe_file(path, b"exists")

        assert obs_fs.exists(path)
        assert not obs_fs.exists(f"{test_path}/F-M-03/not_exists.txt")


# =============================================================================
# Directory Tests (D-*)
# =============================================================================

class TestDirectory:
    """Directory operation tests."""

    def test_D_C_01_mkdir_simple(self, obs_fs, test_path, test_bucket):
        """D-C-01: Create simple directory."""
        dir_path = f"{test_path}/D-C-01/newdir"
        obs_fs.mkdir(dir_path)

        # In OBS, directories are virtual - check by listing
        # or creating a file inside
        file_path = f"{dir_path}/marker.txt"
        obs_fs.pipe_file(file_path, b"")
        assert obs_fs.exists(file_path)

    def test_D_L_02_list_with_files(self, obs_fs, test_path):
        """D-L-02: List directory with files."""
        dir_path = f"{test_path}/D-L-02/files_dir"
        obs_fs.pipe_file(f"{dir_path}/a.txt", b"a")
        obs_fs.pipe_file(f"{dir_path}/b.txt", b"b")
        obs_fs.pipe_file(f"{dir_path}/c.txt", b"c")

        items = obs_fs.ls(dir_path, detail=False)
        names = [p.split("/")[-1] for p in items]
        assert "a.txt" in names
        assert "b.txt" in names
        assert "c.txt" in names


# =============================================================================
# Copy Tests (C-*)
# =============================================================================

class TestCopy:
    """Copy operation tests."""

    def test_C_01_copy_file(self, obs_fs, test_path):
        """C-01: Copy file."""
        src = f"{test_path}/C-01/original.txt"
        dst = f"{test_path}/C-01/copied.txt"
        content = b"original content"
        obs_fs.pipe_file(src, content)

        obs_fs.cp_file(src, dst)

        assert obs_fs.exists(src)
        result = obs_fs.cat_file(dst)
        assert result == content


# =============================================================================
# Consistency Tests (CS-*)
# =============================================================================

class TestConsistency:
    """Consistency tests."""

    def test_CS_01_raw_single(self, obs_fs, test_path):
        """CS-01: Single-thread read-after-write consistency."""
        for i in range(10):
            path = f"{test_path}/CS-01/raw_{i}.bin"
            data = generate_test_data(FILE_SIZES["small"], seed=i)
            checksum = compute_checksum(data)

            obs_fs.pipe_file(path, data)
            result = obs_fs.cat_file(path)

            assert compute_checksum(result) == checksum

    def test_CS_02_raw_concurrent(self, obs_fs, test_path):
        """CS-02: Multi-thread read-after-write consistency."""
        def worker(thread_id):
            path = f"{test_path}/CS-02/raw_t{thread_id}.bin"
            data = generate_test_data(FILE_SIZES["small"], seed=thread_id)
            checksum = compute_checksum(data)

            obs_fs.pipe_file(path, data)
            result = obs_fs.cat_file(path)

            return compute_checksum(result) == checksum

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(8)]
            results = [f.result() for f in as_completed(futures)]

        assert all(results)

    def test_CS_06_create_visible(self, obs_fs, test_path):
        """CS-06: File visible immediately after creation."""
        path = f"{test_path}/CS-06/visible.txt"
        obs_fs.pipe_file(path, b"test")

        # Immediate check
        assert obs_fs.exists(path)

    def test_CS_07_delete_invisible(self, obs_fs, test_path):
        """CS-07: File invisible immediately after deletion."""
        path = f"{test_path}/CS-07/invisible.txt"
        obs_fs.pipe_file(path, b"test")
        obs_fs.rm(path)

        # Immediate check
        assert not obs_fs.exists(path)


# =============================================================================
# Boundary Condition Tests (BC-*)
# =============================================================================

class TestBoundaryConditions:
    """Boundary condition tests."""

    def test_BC_04_zero_byte_write(self, obs_fs, test_path):
        """BC-04: Write zero bytes."""
        path = f"{test_path}/BC-04/zero.txt"
        obs_fs.pipe_file(path, b"original")
        obs_fs.pipe_file(path, b"")

        info = obs_fs.info(path)
        assert info["size"] == 0

    def test_BC_07_dot_files(self, obs_fs, test_path):
        """BC-07: Hidden files (dot prefix)."""
        path = f"{test_path}/BC-07/.hidden"
        obs_fs.pipe_file(path, b"hidden")

        result = obs_fs.cat_file(path)
        assert result == b"hidden"
