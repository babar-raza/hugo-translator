"""Test env-var expansion in ConfigService.resolve_content_root."""
import os
from pathlib import Path
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
