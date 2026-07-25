"""
Integration tests for write gate 40 (HT-QUALITY-GATES-001 Phase 8, Tier A
#10): SEO metadata field corruption -- dropped head_title/seoTitle
separator, and a ballooning keywords list (structural proxy for fabricated
entries). No check read either shape anywhere in this codebase before this
gate.

Ships "warn" per this registry's established rollout convention.
"""
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


def _make_gate() -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    return WriteGateEvaluator(
        detector=None, similarity_tracker=None, config=config, force_accept=True,
    )


_EN = (
    "---\ntitle: Test\nhead_title: \"Getting Started - Aspose.PDF for Java\"\n"
    "keywords: [pdf, java, sdk]\n---\nBody.\n"
)


class TestGateSeoMetadataCorruption:
    def test_dropped_separator_is_flagged(self):
        tr = (
            "---\ntitle: Test\nhead_title: \"Empezando Aspose.PDF para Java\"\n"
            "keywords: [pdf, java, sdk]\n---\nCuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(_EN, tr, Path("test.md"), result)

        assert result.passed is False
        assert "head_title" in result.error

    def test_preserved_separator_is_silent(self):
        tr = (
            "---\ntitle: Test\nhead_title: \"Empezando - Aspose.PDF para Java\"\n"
            "keywords: [pdf, java, sdk]\n---\nCuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(_EN, tr, Path("test.md"), result)

        assert result.passed is True

    def test_pipe_separator_variant_is_recognized(self):
        en = (
            "---\ntitle: Test\nhead_title: \"Getting Started | Aspose.PDF for Java\"\n---\n"
            "Body.\n"
        )
        tr = "---\ntitle: Test\nhead_title: \"Empezando Aspose.PDF para Java\"\n---\nCuerpo.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(en, tr, Path("test.md"), result)

        assert result.passed is False

    def test_ballooning_keywords_list_is_flagged(self):
        tr = (
            "---\ntitle: Test\nhead_title: \"Empezando - Aspose.PDF para Java\"\n"
            "keywords: [pdf, java, sdk, extra1, extra2, extra3]\n---\nCuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(_EN, tr, Path("test.md"), result)

        assert result.passed is False
        assert "keywords" in result.error

    def test_keywords_list_same_length_is_silent(self):
        tr = (
            "---\ntitle: Test\nhead_title: \"Empezando - Aspose.PDF para Java\"\n"
            "keywords: [pdf, java, sdk]\n---\nCuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(_EN, tr, Path("test.md"), result)

        assert result.passed is True

    def test_one_extra_keyword_is_below_the_fabrication_threshold(self):
        """A single extra entry could legitimately be a locale-specific
        synonym addition -- only a real ballooning (>= +2 and >= 1.5x)
        should flag, to keep this low-false-positive."""
        tr = (
            "---\ntitle: Test\nhead_title: \"Empezando - Aspose.PDF para Java\"\n"
            "keywords: [pdf, java, sdk, extra1]\n---\nCuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(_EN, tr, Path("test.md"), result)

        assert result.passed is True

    def test_no_separator_in_source_is_a_no_op(self):
        en = "---\ntitle: Test\nhead_title: \"Simple Title\"\n---\nBody.\n"
        tr = "---\ntitle: Test\nhead_title: \"Titulo Simple\"\n---\nCuerpo.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_empty_translated_field_is_a_different_gates_concern(self):
        """An empty/missing field is Gate 20 (empty_body) or a frontmatter
        key-drop concern, not this gate's -- must not double-report."""
        tr = "---\ntitle: Test\nhead_title: \"\"\n---\nCuerpo.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(_EN, tr, Path("test.md"), result)

        assert result.passed is True

    def test_seotitle_dropped_separator_is_flagged(self):
        """Independent-verification test-gap finding: every existing test in
        this file exercised head_title only, even though the gate iterates
        BOTH ("head_title", "seoTitle") -- seoTitle was never actually
        exercised."""
        en = (
            "---\ntitle: Test\nseoTitle: \"Getting Started - Aspose.PDF for Java\"\n---\n"
            "Body.\n"
        )
        tr = (
            "---\ntitle: Test\nseoTitle: \"Empezando Aspose.PDF para Java\"\n---\n"
            "Cuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(en, tr, Path("test.md"), result)

        assert result.passed is False
        assert "seoTitle" in result.error

    def test_seotitle_preserved_separator_is_silent(self):
        en = (
            "---\ntitle: Test\nseoTitle: \"Getting Started - Aspose.PDF for Java\"\n---\n"
            "Body.\n"
        )
        tr = (
            "---\ntitle: Test\nseoTitle: \"Empezando - Aspose.PDF para Java\"\n---\n"
            "Cuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_fullwidth_pipe_separator_variant_is_recognized(self):
        """Conservative regex expansion (Part B): fullwidth pipe (｜) is a
        direct CJK-locale analog of the already-recognized ASCII pipe."""
        en = (
            "---\ntitle: Test\nhead_title: \"Getting Started | Aspose.PDF for Java\"\n---\n"
            "Body.\n"
        )
        tr = (
            "---\ntitle: Test\nhead_title: \"入門｜Aspose.PDF for Java\"\n---\n"
            "本文.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_fullwidth_hyphen_separator_variant_is_recognized(self):
        """Conservative regex expansion (Part B): fullwidth hyphen-minus
        (－) is a direct CJK-locale analog of the already-recognized
        ASCII hyphen."""
        en = (
            "---\ntitle: Test\nhead_title: \"Getting Started - Aspose.PDF for Java\"\n---\n"
            "Body.\n"
        )
        tr = (
            "---\ntitle: Test\nhead_title: \"入門－Aspose.PDF for Java\"\n---\n"
            "本文.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_metadata_corruption(en, tr, Path("test.md"), result)

        assert result.passed is True
