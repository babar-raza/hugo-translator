"""
TC-HT-001: description-truncation bug class removal.

Covers the shared frontmatter_utils.get_frontmatter_field() helper and the
three sibling detectors it replaced (all previously used a first-line regex
that truncated multi-line/folded YAML scalars to their first physical line —
the root cause of the 2026-07-12 wave-3 description-truncation corruption).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_QUALITY = str(Path(__file__).resolve().parents[3] / "scripts" / "quality")
if _SCRIPTS_QUALITY not in sys.path:
    sys.path.insert(0, _SCRIPTS_QUALITY)

import pytest

from frontmatter_utils import get_frontmatter_field

FOLDED_DESC = (
    "---\n"
    "title: Test\n"
    "description: >-\n"
    "  This is a folded description that\n"
    "  continues onto a second physical line.\n"
    "---\n"
    "Body content.\n"
)

LITERAL_MULTILINE_DESC = (
    "---\n"
    "title: Test\n"
    "description: |\n"
    "  Line one of the description.\n"
    "  Line two of the description.\n"
    "---\n"
    "Body content.\n"
)

MULTILINE_SINGLE_QUOTED_DESC = (
    "---\n"
    "title: Test\n"
    "description: 'This is a long\n"
    "  multi-line single-quoted description\n"
    "  that spans physical lines.'\n"
    "---\n"
    "Body content.\n"
)


class TestGetFrontmatterField:
    def test_folded_scalar_returns_full_joined_value(self):
        value = get_frontmatter_field(FOLDED_DESC, "description")
        assert value is not None
        assert "continues onto a second physical line" in value
        # A first-line regex would have stopped at "that" (line one only).
        assert value.strip() != "This is a folded description that"

    def test_literal_multiline_scalar_returns_full_value(self):
        value = get_frontmatter_field(LITERAL_MULTILINE_DESC, "description")
        assert value is not None
        assert "Line one" in value
        assert "Line two" in value

    def test_multiline_single_quoted_scalar_returns_full_value(self):
        value = get_frontmatter_field(MULTILINE_SINGLE_QUOTED_DESC, "description")
        assert value is not None
        assert "multi-line single-quoted description" in value
        assert "spans physical lines" in value

    def test_missing_field_returns_none(self):
        assert get_frontmatter_field(FOLDED_DESC, "summary") is None

    def test_no_frontmatter_returns_none(self):
        assert get_frontmatter_field("Just body text, no frontmatter.\n", "description") is None


class TestSurgicalRetranslateDetector:
    def test_folded_scalar_ratio_computed_on_full_value_not_first_line(self):
        from surgical_retranslate import _detect_description_hallucination

        en = FOLDED_DESC
        # Target description mirrors the full (multi-line) length of the source,
        # so ratio should be ~1.0 and NOT flagged — a first-line-only comparison
        # would see a huge length mismatch and false-positive here.
        tr = (
            "---\n"
            "title: Test\n"
            "description: >-\n"
            "  Esta es una descripcion plegada que\n"
            "  continua en una segunda linea fisica.\n"
            "---\n"
            "Contenido del cuerpo.\n"
        )
        issues = _detect_description_hallucination(en, tr)
        assert issues == []

    def test_genuine_hallucination_still_detected(self):
        from surgical_retranslate import _detect_description_hallucination

        en = "---\ntitle: Test\ndescription: Short desc here for testing purposes ok.\n---\nBody.\n"
        tr = (
            "---\ntitle: Test\n"
            "description: This translation ballooned into a very long explanatory "
            "paragraph with way more text than the source ever had, several times over.\n"
            "---\nBody.\n"
        )
        issues = _detect_description_hallucination(en, tr)
        assert len(issues) == 1
        assert issues[0][3] == "description_hallucination"

    def test_fix_description_hallucination_function_removed(self):
        import surgical_retranslate

        assert not hasattr(surgical_retranslate, "_fix_description_hallucination")


class TestDeleteForRetranslateDetector:
    def test_folded_scalar_not_false_flagged(self):
        from delete_for_retranslate import _detect_description_hallucination

        en = FOLDED_DESC
        tr = (
            "---\n"
            "title: Test\n"
            "description: >-\n"
            "  Esta es una descripcion plegada que\n"
            "  continua en una segunda linea fisica.\n"
            "---\n"
            "Contenido del cuerpo.\n"
        )
        assert _detect_description_hallucination(en, tr) is False

    def test_genuine_hallucination_still_detected(self):
        from delete_for_retranslate import _detect_description_hallucination

        en = "---\ntitle: Test\ndescription: Short desc here for testing purposes ok.\n---\nBody.\n"
        tr = (
            "---\ntitle: Test\n"
            "description: This translation ballooned into a very long explanatory "
            "paragraph with way more text than the source ever had, several times over.\n"
            "---\nBody.\n"
        )
        assert _detect_description_hallucination(en, tr) is True

    def test_extract_fm_field_removed(self):
        import delete_for_retranslate

        assert not hasattr(delete_for_retranslate, "_extract_fm_field")


class TestHealEnglishHeadingsDescriptionCheck:
    def test_folded_scalar_not_false_flagged(self, tmp_path):
        from heal_english_headings import _check_file

        en_path = tmp_path / "en.md"
        en_path.write_text(FOLDED_DESC, encoding="utf-8")
        tr_path = tmp_path / "tr.md"
        tr_path.write_text(
            "---\n"
            "title: Test\n"
            "description: >-\n"
            "  Esta es una descripcion plegada que\n"
            "  continua en una segunda linea fisica.\n"
            "---\n"
            "Contenido del cuerpo suficientemente largo para pasar otras comprobaciones.\n",
            encoding="utf-8",
        )
        issues = _check_file(tr_path, "es", en_path=en_path)
        assert "description_hallucination" not in issues

    def test_genuine_hallucination_still_detected(self, tmp_path):
        from heal_english_headings import _check_file

        en_path = tmp_path / "en.md"
        en_path.write_text(
            "---\ntitle: Test\ndescription: Short desc here for testing purposes ok.\n---\n"
            "Body content long enough to pass the body-identical check here today now.\n",
            encoding="utf-8",
        )
        tr_path = tmp_path / "tr.md"
        tr_path.write_text(
            "---\ntitle: Test\n"
            "description: This translation ballooned into a very long explanatory "
            "paragraph with way more text than the source ever had, several times over.\n"
            "---\n"
            "Contenido del cuerpo suficientemente largo para pasar otras comprobaciones.\n",
            encoding="utf-8",
        )
        issues = _check_file(tr_path, "es", en_path=en_path)
        assert "description_hallucination" in issues


class TestAuditLinguisticDetector:
    """audit_linguistic.py::check_file's description_yaml_reverted detector.

    Discovered during TC-HT-001 (not named in the original brief): this file
    had the same first-line ^description: regex bug as the other sibling
    sites — caught by the lint test below.
    """

    def test_multiline_folded_translated_description_not_false_flagged(self):
        from audit_linguistic import check_file

        en = FOLDED_DESC
        tr = (
            "---\n"
            "title: Test\n"
            "description: >-\n"
            "  هذا وصف مطوي يستمر\n"
            "  على أكثر من سطر واحد.\n"
            "---\n"
            "محتوى النص.\n"
        )
        issues = check_file(en, tr, "ar")
        assert "description_yaml_reverted" not in issues

    def test_english_reverted_description_still_detected(self):
        from audit_linguistic import check_file

        en = FOLDED_DESC
        tr = (
            "---\n"
            "title: Test\n"
            "description: >-\n"
            "  This is a folded description that\n"
            "  continues onto a second physical line.\n"
            "---\n"
            "Body content.\n"
        )
        issues = check_file(en, tr, "ar")
        assert "description_yaml_reverted" in issues


class TestNoRawFrontmatterRegexRemains:
    """Lint guard: no first-line ^description:/^title: MULTILINE regex left."""

    _FORBIDDEN_PATTERNS = (
        r"^\^description:",
        r"^\^title:",
    )

    def test_no_first_line_description_or_title_regex_in_scripts_quality(self):
        import re

        quality_dir = Path(__file__).resolve().parents[3] / "scripts" / "quality"
        offenders = []
        for py_file in quality_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r'r["\'][^"\']*\^(?:description|title):[^"\']*["\']', text):
                offenders.append(f"{py_file.name}: {match.group(0)}")
        assert offenders == [], f"Raw first-line frontmatter regex still present: {offenders}"

    def test_no_first_line_description_regex_in_write_gate(self):
        import re

        write_gate = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "translation_engine"
            / "write_gate.py"
        )
        text = write_gate.read_text(encoding="utf-8", errors="replace")
        matches = list(re.finditer(r'r["\'][^"\']*\^(?:description|title):[^"\']*["\']', text))
        assert matches == [], f"Raw first-line frontmatter regex still present in write_gate.py: {matches}"
