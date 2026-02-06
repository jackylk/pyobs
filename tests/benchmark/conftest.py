"""Pytest configuration for benchmark tests."""

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "obs: marks tests as requiring OBS credentials")
    config.addinivalue_line("markers", "slow: marks tests as slow running")


def pytest_addoption(parser):
    """Add benchmark-specific command line options."""
    parser.addoption(
        "--quick",
        action="store_true",
        default=False,
        help="Run benchmarks in quick mode (fewer iterations)",
    )
    parser.addoption(
        "--full",
        action="store_true",
        default=False,
        help="Run benchmarks in full mode (more iterations)",
    )
    parser.addoption(
        "--with-obs",
        action="store_true",
        default=False,
        help="Include OBS integration benchmarks",
    )


@pytest.fixture
def benchmark_mode(request):
    """Get the current benchmark mode."""
    if request.config.getoption("--quick"):
        return "quick"
    elif request.config.getoption("--full"):
        return "full"
    return "normal"


@pytest.fixture
def with_obs(request):
    """Check if OBS benchmarks should run."""
    return request.config.getoption("--with-obs")
