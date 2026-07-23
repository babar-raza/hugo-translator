"""HT-QUALITY-GATES-001 Phase 8 (Tier B #6): tests for
audit_cross_locale_duplication.py's extension to body paragraphs (previously
frontmatter-field-only) -- closes the Phase 7 reconnaissance's "clean
two-locale proof of shared batch/template corruption" gap for body prose.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_QUALITY_DIR = _PROJECT_ROOT / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

import audit_cross_locale_duplication as acld  # noqa: E402


class TestExtractBodyParagraphs:
    def test_extracts_paragraphs_above_min_length(self):
        content = (
            "---\ntitle: Test\n---\n"
            "This is a real paragraph with enough characters to pass the length floor.\n\n"
            "Short.\n\n"
            "Another real paragraph here that also has enough characters to pass the floor.\n"
        )
        paras = acld.extract_body_paragraphs(content)
        assert len(paras) == 2
        assert "Short." not in paras

    def test_excludes_fenced_code_block_content(self):
        content = (
            "---\ntitle: Test\n---\n"
            "A real paragraph with enough characters to pass the length floor here.\n\n"
            "```python\nsame_code_in_every_locale_should_not_be_flagged()\n```\n"
        )
        paras = acld.extract_body_paragraphs(content)
        assert not any("same_code_in_every_locale" in p for p in paras)

    def test_no_frontmatter_still_scans_body(self):
        content = "This is a real paragraph with enough characters to pass the length floor here."
        paras = acld.extract_body_paragraphs(content)
        assert len(paras) == 1


class TestFindCrossLocaleDuplicates:
    def test_two_distinct_locales_sharing_a_value_is_flagged(self):
        field_values = {
            "title": [("es", "Titulo Unico"), ("fr", "Titre Unique")],
            "body_paragraph": [
                ("es", "shared corrupted paragraph text"),
                ("fr", "shared corrupted paragraph text"),
            ],
        }
        findings = acld.find_cross_locale_duplicates(field_values)
        assert ("body_paragraph", "shared corrupted paragraph text", ["es", "fr"]) in findings

    def test_single_locale_internal_repetition_is_not_flagged(self):
        """The dedup fix (Phase 8, Tier B #6): a paragraph repeated TWICE
        within one locale's own file must not be misread as 2 locales
        sharing content -- that's a different, already-covered bug
        (write_gate.py Gate 16 / duplicate_content)."""
        field_values = {
            "body_paragraph": [
                ("es", "repeated within this file only"),
                ("es", "repeated within this file only"),
            ],
        }
        findings = acld.find_cross_locale_duplicates(field_values)
        assert findings == []

    def test_three_locales_sharing_reports_all_three(self):
        field_values = {
            "body_paragraph": [
                ("es", "shared text"), ("fr", "shared text"), ("de", "shared text"),
            ],
        }
        findings = acld.find_cross_locale_duplicates(field_values)
        assert len(findings) == 1
        assert findings[0][2] == ["de", "es", "fr"]

    def test_no_sharing_produces_no_findings(self):
        field_values = {
            "body_paragraph": [("es", "texto en espanol"), ("fr", "texte en francais")],
        }
        findings = acld.find_cross_locale_duplicates(field_values)
        assert findings == []
