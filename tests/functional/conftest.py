"""Pytest configuration for functional tests."""

import pytest


def pytest_addoption(parser):
    """Add functional test command line options."""
    parser.addoption(
        "--with-obs",
        action="store_true",
        default=False,
        help="Run OBS integration tests (requires credentials)",
    )
    parser.addoption(
        "--huge-files",
        action="store_true",
        default=False,
        help="Run huge file tests (5GB+, slow)",
    )


@pytest.fixture
def with_obs(request):
    """Check if OBS integration tests should run."""
    return request.config.getoption("--with-obs")


@pytest.fixture
def huge_files(request):
    """Check if huge file tests should run."""
    return request.config.getoption("--huge-files")
