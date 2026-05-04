"""
Pytest configuration and shared fixtures for the translation system tests.
"""
import os
import shutil
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml

# Add src to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Standalone scripts that match test_*.py naming but are not pytest tests.
# Importing them during collection causes StopIteration (module-level execution).
collect_ignore = [
    str(Path(__file__).parent / "regression" / "test_reconstruction_fix.py"),
]


# Pytest command-line options
def pytest_addoption(parser):
    """Add custom command-line options for pytest."""
    parser.addoption(
        "--test-model",
        action="store",
        default="m2m100_418m",
        help="Model ID to use for tests (default: m2m100_418m)",
    )
    parser.addoption(
        "--test-models",
        action="store",
        help="Comma-separated list of model IDs to parameterize tests with",
    )


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


# Model-related fixtures for BM-05: Parameterized Model Testing
@pytest.fixture(scope="session")
def available_models(config_dir: Path) -> list[str]:
    """
    Load list of available models from model registry.

    Returns:
        List of model IDs available for testing
    """
    registry_path = config_dir / "model_registry.yaml"
    if not registry_path.exists():
        return ["m2m100_418m"]  # Fallback default

    with open(registry_path) as f:
        registry_data = yaml.safe_load(f)

    models = registry_data.get("models", [])
    return [model["model_id"] for model in models]


@pytest.fixture(scope="session")
def test_model(request) -> str:
    """
    Get the model ID to use for testing.

    Can be overridden via pytest command-line option:
        pytest --test-model=opus_en_fr

    Returns:
        Model ID string (e.g., "m2m100_418m")
    """
    return request.config.getoption("--test-model")


@pytest.fixture(scope="session")
def test_models(request, available_models: list[str]) -> list[str]:
    """
    Get list of model IDs for parameterized testing.

    Can be overridden via pytest command-line option:
        pytest --test-models=m2m100_418m,opus_en_fr,nllb_200_600m

    If not specified, uses all available models from registry.

    Returns:
        List of model ID strings
    """
    models_arg = request.config.getoption("--test-models")
    if models_arg:
        return [m.strip() for m in models_arg.split(",")]
    return available_models


@pytest.fixture(scope="session")
def small_test_models(available_models: list[str]) -> list[str]:
    """
    Get list of small/fast models suitable for quick testing.

    Returns:
        List of smaller model IDs (418M and under)
    """
    # Heuristic: filter to smaller models based on naming
    small_keywords = ["418m", "small", "base", "opus"]
    return [
        model_id
        for model_id in available_models
        if any(keyword in model_id.lower() for keyword in small_keywords)
    ]


# ---------------------------------------------------------------------------
# LMDB cleanup helpers (Windows-safe)
# ---------------------------------------------------------------------------

TEST_L2_MAX_SIZE_MB: int = 20


def _force_delete_lmdb_dir(path: Path, retries: int = 5, delay: float = 0.2) -> bool:
    """Delete an LMDB directory with retry logic for Windows file-lock issues."""
    for attempt in range(retries):
        try:
            shutil.rmtree(path)
            return True
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(delay)
    return False


def _find_lmdb_dirs_in(root: Path) -> list[Path]:
    """Find LMDB directories under *root* by presence of data.mdb + lock.mdb."""
    results = []
    if not root.exists():
        return results
    for data_mdb in root.rglob("data.mdb"):
        lmdb_dir = data_mdb.parent
        if (lmdb_dir / "lock.mdb").exists() and not lmdb_dir.is_symlink():
            results.append(lmdb_dir)
    return results


@pytest.fixture(autouse=True)
def _cleanup_test_lmdb(tmp_path: Path) -> Generator[None, None, None]:
    """Per-test autouse fixture: clean up LMDB dirs inside tmp_path on Windows."""
    yield
    if os.name != "nt":
        return
    for lmdb_dir in _find_lmdb_dirs_in(tmp_path):
        _force_delete_lmdb_dir(lmdb_dir)
