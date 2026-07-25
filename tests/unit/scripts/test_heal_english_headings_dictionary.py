"""Unit tests for heal_english_headings_dictionary.py's `_patch_headings`
core function -- both modes (mission reference-i18n-hardening-20260725,
plan item C1). No prior automated coverage existed for this script.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from scripts.quality.heal_english_headings_dictionary import _patch_headings
from src.translation_engine.terminology.classification import TemplateStringRegistry


def _make_registry(tmp_path) -> TemplateStringRegistry:
    d = tmp_path / "template_strings"
    d.mkdir()
    (d / "_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "id": "heading.overview",
                        "en": "Overview",
                        "category": "section_heading",
                        "status": "approved",
                    },
                    {
                        "id": "heading.see_also",
                        "en": "See Also",
                        "category": "section_heading",
                        "status": "approved",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (d / "ja.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "locale": "ja",
                "translations": {
                    "heading.overview": {"value": "概要", "reviewed_by": "t"},
                    "heading.see_also": {
                        "value": "関連情報",
                        "reviewed_by": "t",
                        "rejected_variants": ["參照"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return TemplateStringRegistry(d)


class TestNormalizeMode:
    def test_replaces_any_matched_heading_with_current_approved_value(self, tmp_path):
        registry = _make_registry(tmp_path)
        body = "## Overview\n\ntext\n\n## 見出し\n\nother text\n"
        new_body, n, reasons = _patch_headings(body, "ja", registry, mode="normalize")
        assert "## 概要" in new_body
        assert n == 1
        assert reasons["normalize"] == 1

    def test_no_op_when_already_the_approved_value(self, tmp_path):
        registry = _make_registry(tmp_path)
        body = "## 概要\n\ntext\n"
        new_body, n, reasons = _patch_headings(body, "ja", registry, mode="normalize")
        assert new_body == body
        assert n == 0


class TestTargetedModeLeakage:
    def test_english_leakage_is_fixed(self, tmp_path):
        registry = _make_registry(tmp_path)
        body = "## Overview\n\ntext\n"
        new_body, n, reasons = _patch_headings(body, "ja", registry, mode="targeted")
        assert "## 概要" in new_body
        assert n == 1
        assert reasons["leakage"] == 1
        assert reasons["normalize"] == 0

    def test_acceptable_variant_is_left_untouched(self, tmp_path):
        """A DIFFERENT-but-not-flagged translation (not the EN term, not in
        rejected_variants) must be left alone in targeted mode -- this is
        the core behavioral difference from normalize mode."""
        registry = _make_registry(tmp_path)
        body = "## 概観\n\ntext\n"  # a plausible-but-different ja rendering
        new_body, n, reasons = _patch_headings(body, "ja", registry, mode="targeted")
        assert new_body == body
        assert n == 0


class TestTargetedModeRejectedVariant:
    def test_adjudicated_wrong_form_is_corrected(self, tmp_path):
        registry = _make_registry(tmp_path)
        en_body = "## Overview\n\ntext\n\n## See Also\n\nmore\n"
        body = "## 概要\n\ntext\n\n## 參照\n\nmore\n"  # 參照 is a rejected_variant for See Also
        new_body, n, reasons = _patch_headings(
            body, "ja", registry, mode="targeted", en_body=en_body
        )
        assert "## 関連情報" in new_body
        assert n == 1
        assert reasons["rejected_variant"] == 1

    def test_rejected_variant_not_fixed_without_en_alignment(self, tmp_path):
        """Without the EN counterpart (or with a heading-count mismatch),
        rejected_variants cannot be safely attributed to an entry -- must
        not guess."""
        registry = _make_registry(tmp_path)
        body = "## 參照\n\nmore\n"
        new_body, n, reasons = _patch_headings(body, "ja", registry, mode="targeted", en_body=None)
        assert new_body == body
        assert n == 0

    def test_mismatched_heading_counts_skip_rejected_variant_check(self, tmp_path):
        registry = _make_registry(tmp_path)
        en_body = "## Overview\n\ntext\n\n## See Also\n\nmore\n\n## Extra\n\nsection\n"
        body = "## 概要\n\ntext\n\n## 參照\n\nmore\n"  # locale is missing a section -> count mismatch
        new_body, n, reasons = _patch_headings(
            body, "ja", registry, mode="targeted", en_body=en_body
        )
        # Leakage fix still applies (doesn't need alignment); rejected_variant does not.
        assert reasons["rejected_variant"] == 0
        assert "參照" in new_body  # left untouched, not guessed


class TestTargetedModeIdentifierRestoration:
    def test_multi_hump_identifier_mistranslation_is_restored(self, tmp_path):
        registry = _make_registry(tmp_path)
        en_body = "## Overview\n\ntext\n\n## ImageRenderOptions\n\nmore\n"
        body = "## 概要\n\ntext\n\n## 画像レンダリングオプション\n\nmore\n"
        new_body, n, reasons = _patch_headings(
            body, "ja", registry, mode="targeted", en_body=en_body
        )
        assert "## ImageRenderOptions" in new_body
        assert reasons["identifier_restore"] == 1

    def test_correctly_untranslated_identifier_is_not_touched(self, tmp_path):
        registry = _make_registry(tmp_path)
        en_body = "## Overview\n\ntext\n\n## ImageRenderOptions\n\nmore\n"
        body = "## 概要\n\ntext\n\n## ImageRenderOptions\n\nmore\n"
        new_body, n, reasons = _patch_headings(
            body, "ja", registry, mode="targeted", en_body=en_body
        )
        assert new_body == body
        assert reasons["identifier_restore"] == 0

    def test_single_hump_word_is_never_force_restored_by_shape(self, tmp_path):
        """Single-hump words (e.g. a real class named "Body") are
        deliberately NOT covered by identifier restoration -- shape alone
        can't tell a heading word from a class name (the same ambiguity
        classification.py's design already avoids)."""
        registry = _make_registry(tmp_path)
        en_body = "## Overview\n\ntext\n\n## Body\n\nmore\n"
        body = "## 概要\n\ntext\n\n## ボディ\n\nmore\n"
        new_body, n, reasons = _patch_headings(
            body, "ja", registry, mode="targeted", en_body=en_body
        )
        assert reasons["identifier_restore"] == 0
        assert "## ボディ" in new_body


class TestIdempotency:
    def test_targeted_second_pass_makes_zero_changes(self, tmp_path):
        registry = _make_registry(tmp_path)
        en_body = "## Overview\n\ntext\n\n## See Also\n\nmore\n"
        body = "## Overview\n\ntext\n\n## 參照\n\nmore\n"
        first_body, n1, _ = _patch_headings(body, "ja", registry, mode="targeted", en_body=en_body)
        assert n1 == 2
        second_body, n2, _ = _patch_headings(
            first_body, "ja", registry, mode="targeted", en_body=en_body
        )
        assert n2 == 0
        assert second_body == first_body
