"""
Integration tests for write gate 45 (ASPOSE-BLOG-DEPLOY-ALIAS-RECURRENCE-001,
2026-09-17): IGNORE-mode frontmatter field leak.

Real confirmed repro: aspose.org's blog.aspose.org.yaml (and the other 3
aspose.org site profiles) set `aliases` and `url` to `mode: ignore` --
reconstruct_frontmatter() already drops both correctly, and
FrontmatterProtectionValidator already has a matching check
(_check_ignore_fields) -- but neither the reconstructor step nor that
validator ran on the stale, pre-2026-09-01 cached translation output that
got adopted wholesale into aspose.org content on 2026-09-15, reintroducing
byte-identical aliases: values across every locale copy of 3 blog posts.
Hugo collapses same-value, unprefixed aliases: across locale copies onto one
output path ("Duplicate target paths"), which broke the blog.aspose.org
deploy workflow 3 days running. This gate is the production-write-path
backstop: it fires regardless of which upstream step (or bypass) produced
the candidate content, as long as a site_profile is supplied.

Ships "warn" per this registry's established rollout convention.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult
from src.utils.models import FrontmatterMode


def _rule(mode):
    return SimpleNamespace(mode=mode)


def _site_profile():
    return SimpleNamespace(
        frontmatter={
            "title": _rule(FrontmatterMode.TRANSLATE),
            "draft": _rule(FrontmatterMode.PASSTHROUGH),
            "aliases": _rule(FrontmatterMode.IGNORE),
            "url": _rule(FrontmatterMode.IGNORE),
        }
    )


def _make_gate() -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    return WriteGateEvaluator(
        detector=None, similarity_tracker=None, config=config, force_accept=True,
    )


class TestGateIgnoreModeFieldLeak:
    def test_leaked_aliases_field_is_flagged(self):
        """The exact real-world repro: aliases: copied verbatim into a
        non-English locale file that should never have carried it."""
        translated = """---
title: Test
aliases: [/slides/cpp/slides-key-features-cpp/]
draft: false
---
Body.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_ignore_mode_field_leak(
            translated, Path("index.ja.md"), result, _site_profile()
        )

        assert result.passed is False
        assert "aliases" in result.error
        assert "GATE45" in result.error

    def test_leaked_url_field_is_flagged(self):
        translated = """---
title: Test
url: /pdf/go/introducing-pdf-foss-go/
draft: false
---
Body.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_ignore_mode_field_leak(
            translated, Path("index.de.md"), result, _site_profile()
        )

        assert result.passed is False
        assert "url" in result.error

    def test_both_ignore_fields_leaking_are_both_named(self):
        translated = """---
title: Test
aliases: [/old/]
url: /old/
draft: false
---
Body.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_ignore_mode_field_leak(
            translated, Path("index.fr.md"), result, _site_profile()
        )

        assert result.passed is False
        assert "aliases" in result.error
        assert "url" in result.error

    def test_correctly_stripped_output_is_silent(self):
        """The correct shape: reconstruct_frontmatter() already removed
        both IGNORE-mode fields -- this is what a healthy translated file
        looks like."""
        translated = """---
title: Test
draft: false
---
Body.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_ignore_mode_field_leak(
            translated, Path("index.ja.md"), result, _site_profile()
        )

        assert result.passed is True
        assert result.error is None

    def test_no_site_profile_is_a_no_op(self):
        """Backward compatible: callers that do not pass a site_profile
        (the gate's only source of which fields are mode: ignore) get no
        finding at all, never a crash."""
        translated = """---
title: Test
aliases: [/old/]
---
Body.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_ignore_mode_field_leak(translated, Path("index.ja.md"), result, None)

        assert result.passed is True

    def test_no_ignore_rules_in_profile_is_silent(self):
        profile = SimpleNamespace(
            frontmatter={"title": _rule(FrontmatterMode.TRANSLATE)}
        )
        translated = """---
title: Test
aliases: [/old/]
---
Body.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_ignore_mode_field_leak(translated, Path("index.ja.md"), result, profile)

        assert result.passed is True

    def test_registered_in_gate_registry_as_warn(self):
        """Ships warn-tier per this file's own documented rollout
        convention (gates 31-44); promotion to block needs a clean-sample
        false-positive check against real content first."""
        entries = [e for e in WriteGateEvaluator.GATE_REGISTRY if e[0] == 45]
        assert len(entries) == 1
        gate_id, method_name, category, action = entries[0]
        assert method_name == "_gate_ignore_mode_field_leak"
        assert action == "warn"
