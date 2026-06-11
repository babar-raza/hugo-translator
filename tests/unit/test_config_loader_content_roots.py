"""
Unit tests for content-root path resolution in ConfigService.
"""

from src.utils.config_loader import ConfigService


def test_resolve_content_root_prefers_cwd_for_relative_path(tmp_path, monkeypatch):
    """Relative paths should resolve against cwd when that target exists."""
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    (config_root / "site_profiles").mkdir(parents=True)
    (project_root / "content" / "site").mkdir(parents=True)

    monkeypatch.chdir(project_root)
    service = ConfigService(config_root)

    resolved = service.resolve_content_root("content/site")
    assert resolved == (project_root / "content" / "site").resolve()
    assert resolved.exists()


def test_resolve_content_root_falls_back_to_project_root(tmp_path, monkeypatch):
    """When cwd-relative path is missing, config_root.parent fallback should be used."""
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    (config_root / "site_profiles").mkdir(parents=True)
    (project_root / "repo-content").mkdir(parents=True)

    monkeypatch.chdir(tmp_path)
    service = ConfigService(config_root)

    resolved = service.resolve_content_root("repo-content")
    assert resolved == (project_root / "repo-content").resolve()
    assert resolved.exists()


def test_resolve_content_root_missing_is_deterministic_absolute(tmp_path, monkeypatch):
    """Missing relative paths should still resolve deterministically to an absolute path."""
    project_root = tmp_path / "project"
    config_root = project_root / "config"
    (config_root / "site_profiles").mkdir(parents=True)

    monkeypatch.chdir(project_root)
    service = ConfigService(config_root)

    resolved = service.resolve_content_root("missing/content")
    assert resolved == (project_root / "missing" / "content").resolve()
    assert not resolved.exists()


def test_ws5_content_root_resolves_in_repo():
    """ws5-test profile should resolve to an existing in-repo content root."""
    service = ConfigService("config")
    profile = service.get_site_profile("ws5-test")
    resolved = service.resolve_content_root(profile.content_roots[0])
    assert resolved.exists()
