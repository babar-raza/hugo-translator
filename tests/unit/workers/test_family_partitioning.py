"""Unit tests for family-aware content_root partitioning in the autonomous worker.

Tests _expand_family_content_roots() and verify:
- Multi-family content roots are expanded into per-family sub-roots
- Each sub-root path includes the family token (enabling correct scope resolution)
- Single-family profiles are not expanded
- family_scope=single/total bypasses expansion
- No regression for existing single-family profiles
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_worker():
    """Create a minimal worker instance with mocked config_service."""
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
    )

    config = SimpleNamespace(
        site=None,
        max_sites_per_run=None,
        file_timeout_seconds=60,
        max_seconds_per_run=None,
        daemon_mode=False,
    )
    config_service = MagicMock()
    # suppress config_service.get_config so it returns empty dict
    config_service.get_config.return_value = {}

    with patch.object(AutonomousContentTranslationWorker, "__init__", lambda *a, **k: None):
        worker = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
    worker.config = config
    worker.config_service = config_service
    worker.invocation_id = "test-inv-001"
    worker._site_profile_cache = {}
    worker._site_profile_errors = {}
    return worker


def _fake_profile(family_scope=None, content_roots=None):
    """Build a minimal site profile stub."""
    p = SimpleNamespace(
        site_id="products.aspose.org",
        display_name="Landing Pages",
        family_scope=family_scope,
        content_roots=content_roots or ["${ASPOSE_ORG_CONTENT}/products.aspose.org"],
        target_langs=["de", "fr"],
    )
    return p


class TestExpandFamilyContentRoots:
    """_expand_family_content_roots behaviour."""

    def test_multi_family_org_style_expands(self, tmp_path):
        """Org-style multi-family root (en/{family}/) is expanded per family."""
        en = tmp_path / "en"
        en.mkdir()
        (en / "words").mkdir()
        (en / "cells").mkdir()
        (en / "font").mkdir()

        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path

        profile = _fake_profile(family_scope="multi")
        result = worker._expand_family_content_roots(profile, str(tmp_path))

        assert len(result) == 3
        tokens = set()
        for p in result:
            tokens.add(Path(p).name)
        assert tokens == {"words", "cells", "font"}

    def test_multi_family_net_style_expands(self, tmp_path):
        """Net-style multi-family root ({family}/) is expanded per family."""
        (tmp_path / "words").mkdir()
        (tmp_path / "barcode").mkdir()
        (tmp_path / "home").mkdir()   # non-family dir — must be ignored
        (tmp_path / "ar").mkdir()     # lang dir — must be ignored

        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path

        profile = _fake_profile(family_scope="multi")
        result = worker._expand_family_content_roots(profile, str(tmp_path))

        assert len(result) == 2
        tokens = {Path(p).name for p in result}
        assert tokens == {"words", "barcode"}

    def test_single_family_profile_not_expanded(self, tmp_path):
        """family_scope=single returns content_root unchanged."""
        (tmp_path / "words").mkdir()
        (tmp_path / "cells").mkdir()  # even if dirs exist, no expansion

        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path

        content_root = str(tmp_path)
        profile = _fake_profile(family_scope="single")
        result = worker._expand_family_content_roots(profile, content_root)

        assert result == [content_root]

    def test_explicit_total_not_expanded(self, tmp_path):
        """family_scope=total is never expanded (Total pages translate as one batch)."""
        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path

        content_root = str(tmp_path)
        profile = _fake_profile(family_scope="total")
        result = worker._expand_family_content_roots(profile, content_root)

        assert result == [content_root]

    def test_no_family_dirs_not_expanded(self, tmp_path):
        """Content root with no recognised family subdirs is returned unchanged."""
        (tmp_path / "home").mkdir()
        (tmp_path / "archive").mkdir()

        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path

        content_root = str(tmp_path)
        profile = _fake_profile(family_scope=None)
        result = worker._expand_family_content_roots(profile, content_root)

        assert result == [content_root]

    def test_single_family_dir_not_expanded(self, tmp_path):
        """Single family dir → no expansion (not multi-family)."""
        (tmp_path / "words").mkdir()

        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path

        content_root = str(tmp_path)
        profile = _fake_profile(family_scope=None)
        result = worker._expand_family_content_roots(profile, content_root)

        assert result == [content_root]

    def test_nonexistent_dir_returns_unchanged(self, tmp_path):
        """If resolved dir doesn't exist, return content_root unchanged."""
        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path / "does_not_exist"

        content_root = "whatever"
        profile = _fake_profile(family_scope=None)
        result = worker._expand_family_content_roots(profile, content_root)

        assert result == [content_root]

    def test_resolve_exception_returns_unchanged(self):
        """If resolve_content_root raises, return original content_root."""
        worker = _make_worker()
        worker.config_service.resolve_content_root.side_effect = RuntimeError("no resolver")

        content_root = "whatever"
        profile = _fake_profile(family_scope=None)
        result = worker._expand_family_content_roots(profile, content_root)

        assert result == [content_root]

    def test_auto_detect_multi_family_without_explicit_scope(self, tmp_path):
        """Without family_scope, multi-family auto-detection must also fire."""
        en = tmp_path / "en"
        en.mkdir()
        (en / "pdf").mkdir()
        (en / "slides").mkdir()

        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path

        profile = _fake_profile(family_scope=None)  # no explicit declaration
        result = worker._expand_family_content_roots(profile, str(tmp_path))

        assert len(result) == 2
        assert {Path(p).name for p in result} == {"pdf", "slides"}

    def test_expanded_paths_contain_family_token_for_scope_resolution(self, tmp_path):
        """Expanded paths must end with the family token so scope resolver finds it."""
        en = tmp_path / "en"
        en.mkdir()
        (en / "cells").mkdir()
        (en / "words").mkdir()

        worker = _make_worker()
        worker.config_service.resolve_content_root.return_value = tmp_path

        profile = _fake_profile(family_scope="multi")
        result = worker._expand_family_content_roots(profile, str(tmp_path))

        for r in result:
            p = Path(r)
            from src.observability.metrics_scope import DEFAULT_KNOWN_FAMILIES
            assert p.name in DEFAULT_KNOWN_FAMILIES, (
                f"Expanded path {r!r} must end with a known family token "
                "so MetricsRunContext can resolve scope."
            )


class TestTranslateContentRootPassthrough:
    """Verify _translate_content_root forwards family_scope/profile_filename/display_name
    into MetricsRunContext.__init__ -- not just that the signature accepts them."""

    def _run_translate_root_and_capture_metrics_init(
        self, tmp_path, family_scope, profile_filename, display_name
    ):
        """
        Call _translate_content_root with the given params and return the list of
        kwargs dicts captured by a MetricsRunContext spy.
        """
        import time
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        # Minimal content file so resolved_content_dir.exists() passes
        (tmp_path / "en").mkdir(parents=True, exist_ok=True)
        (tmp_path / "en" / "index.md").write_text("---\ntitle: T\n---\nBody.\n")

        # Build worker with mocked dependencies
        config = SimpleNamespace(
            site=None,
            max_sites_per_run=None,
            file_timeout_seconds=60,
            max_seconds_per_run=None,
        )
        worker = AutonomousContentTranslationWorker.__new__(
            AutonomousContentTranslationWorker
        )
        worker.config = config
        worker.invocation_id = "test-spy-001"
        worker._run_start = time.time()
        worker._run_deadline = None

        # Config service
        mock_cs = MagicMock()
        mock_cs.resolve_content_root.return_value = tmp_path
        mock_cs.get_config.return_value = {
            "agent_metrics": {"enabled": True, "dry_run": True},
            "git_commit": {"files_per_commit": 0},
            "metrics": {"enabled": False},
            "auto_scan_contamination": False,
        }
        worker.config_service = mock_cs

        # Translation engine — zero result
        mock_te = MagicMock()
        mock_result = SimpleNamespace(
            successful_files=0,
            total_files=0,
            failed_files=0,
            file_results=[],
            aggregate_stats=None,
            completion_filter_skipped=0,
        )
        mock_te.translate_directory.return_value = mock_result
        worker.translation_engine = mock_te

        # Capture MetricsRunContext __init__ kwargs
        captured: list[dict] = []

        from src.observability.agent_metrics_integration import (
            MetricsRunContext as RealMRC,
        )

        class SpyMRC(RealMRC):
            def __init__(self_inner, **kwargs):
                captured.append(dict(kwargs))
                super().__init__(**kwargs)

        with patch(
            "src.observability.agent_metrics_integration.MetricsRunContext",
            new=SpyMRC,
        ):
            with patch.object(
                AutonomousContentTranslationWorker,
                "_run_post_contamination_scan",
                return_value=None,
            ):
                with patch.object(
                    AutonomousContentTranslationWorker,
                    "_write_run_metrics",
                    return_value=None,
                ):
                    worker._translate_content_root(
                        "products.aspose.org",
                        str(tmp_path),
                        ["de"],
                        profile_filename=profile_filename,
                        family_scope=family_scope,
                        display_name=display_name,
                    )

        return captured

    def test_family_scope_forwarded_to_metrics_run_context(self, tmp_path):
        """family_scope is passed from _translate_content_root into MetricsRunContext."""
        captured = self._run_translate_root_and_capture_metrics_init(
            tmp_path,
            family_scope="multi",
            profile_filename="products.aspose.org.yaml",
            display_name="Product Pages",
        )
        assert len(captured) == 1, f"Expected 1 MetricsRunContext call, got {len(captured)}"
        assert captured[0]["family_scope"] == "multi", (
            f"family_scope not forwarded: got {captured[0].get('family_scope')!r}"
        )

    def test_profile_filename_forwarded_to_metrics_run_context(self, tmp_path):
        """profile_filename is passed from _translate_content_root into MetricsRunContext."""
        captured = self._run_translate_root_and_capture_metrics_init(
            tmp_path,
            family_scope="single",
            profile_filename="docs.aspose.net.words.yaml",
            display_name=None,
        )
        assert len(captured) == 1, f"Expected 1 MetricsRunContext call, got {len(captured)}"
        assert captured[0]["profile_filename"] == "docs.aspose.net.words.yaml", (
            f"profile_filename not forwarded: got {captured[0].get('profile_filename')!r}"
        )

    def test_display_name_forwarded_to_metrics_run_context(self, tmp_path):
        """display_name is passed from _translate_content_root into MetricsRunContext."""
        captured = self._run_translate_root_and_capture_metrics_init(
            tmp_path,
            family_scope=None,
            profile_filename="kb.aspose.net.words.yaml",
            display_name="Knowledge Base",
        )
        assert len(captured) == 1, f"Expected 1 MetricsRunContext call, got {len(captured)}"
        assert captured[0]["display_name"] == "Knowledge Base", (
            f"display_name not forwarded: got {captured[0].get('display_name')!r}"
        )


class TestFamilyScopeInSiteProfile:
    """Verify SiteProfile accepts and stores family_scope from YAML."""

    def test_family_scope_field_exists(self):
        from src.utils.models import SiteProfile
        assert hasattr(SiteProfile, "model_fields")
        assert "family_scope" in SiteProfile.model_fields

    def test_family_scope_defaults_to_none(self):
        from src.utils.models import SiteProfile
        field = SiteProfile.model_fields["family_scope"]
        assert field.default is None

    def test_family_scope_multi_accepted(self):
        """SiteProfile can hold family_scope='multi'."""
        from src.utils.models import SiteProfile, BodyRules
        profile = SiteProfile(
            site_id="products.aspose.org",
            content_roots=["/content/products.aspose.org"],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            family_scope="multi",
        )
        assert profile.family_scope == "multi"
