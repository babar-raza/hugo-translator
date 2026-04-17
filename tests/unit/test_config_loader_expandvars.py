"""Test env-var expansion in ConfigService.resolve_content_root."""
import os
from unittest.mock import patch

import pytest

from src.utils.config_loader import ConfigService


@pytest.fixture
def config_service():
    return ConfigService("config/")


def test_expandvars_resolves_env_var(config_service, tmp_path):
    """${MY_VAR}/sub expands to the env var value."""
    target = tmp_path / "sub"
    target.mkdir()
    with patch.dict(os.environ, {"MY_TEST_ROOT": str(tmp_path)}):
        result = config_service.resolve_content_root("${MY_TEST_ROOT}/sub")
    assert result == target


def test_expandvars_unset_var_returns_literal(config_service):
    """Unset env var returns the literal string (expandvars passthrough)."""
    env_key = "HUGO_TRANSLATOR_TEST_NONEXISTENT_VAR_12345"
    os.environ.pop(env_key, None)
    result = config_service.resolve_content_root(f"${{{env_key}}}/subdir")
    # os.path.expandvars returns literal ${VAR} when unset on Unix,
    # but %VAR% on Windows. Either way, the path should contain the var name.
    assert env_key in str(result)


def test_plain_path_unchanged(config_service, tmp_path):
    """Path without ${} is not affected by expandvars."""
    target = tmp_path / "plain"
    target.mkdir()
    result = config_service.resolve_content_root(str(target))
    assert result == target


def test_dotenv_loaded_at_init(tmp_path):
    """ConfigService.__init__ loads .env so env vars are available without shell export."""
    env_file = tmp_path / ".env"
    env_file.write_text("HUGO_TEST_DOTENV_VAR=resolved_from_dotenv\n")

    # Ensure the var is NOT in the environment before init
    os.environ.pop("HUGO_TEST_DOTENV_VAR", None)

    # ConfigService expects config_root; point it at the real one but .env at tmp_path
    # We monkey-patch the _env_file resolution by creating a minimal config root
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "site_profiles").mkdir()
    (config_root / "global.yaml").write_text("{}\n")

    ConfigService(str(config_root))

    assert os.environ.get("HUGO_TEST_DOTENV_VAR") == "resolved_from_dotenv"

    # Cleanup
    os.environ.pop("HUGO_TEST_DOTENV_VAR", None)
