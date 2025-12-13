"""
Pytest configuration and shared fixtures for the translation system tests.
"""
import os
import sys
from pathlib import Path
from typing import Generator

import pytest

# Add src to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


@pytest.fixture(scope="session")
def project_root_dir() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def config_dir(project_root_dir: Path) -> Path:
    """Return the config directory."""
    return project_root_dir / "config"


@pytest.fixture(scope="session")
def test_data_dir(project_root_dir: Path) -> Path:
    """Return the test data directory."""
    return project_root_dir / "tests" / "fixtures"


@pytest.fixture(scope="session")
def legacy_dir(project_root_dir: Path) -> Path:
    """Return the legacy code directory."""
    return project_root_dir / "legacy"


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary config directory for testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "site_profiles").mkdir()
    (config_dir / "schemas").mkdir()
    yield config_dir


@pytest.fixture
def temp_tm_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary TM directory for testing."""
    tm_dir = tmp_path / "tm"
    tm_dir.mkdir()
    yield tm_dir


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setup test environment variables."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
