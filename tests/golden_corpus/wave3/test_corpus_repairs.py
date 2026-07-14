"""
TC-HT-010: golden corpus tests — real wave-3 damaged/parent pairs extracted
from aspose.org git history (see README.md for provenance/commands).

Verifies the TC-HT-001/002/005/007 fixes against REAL corruption data
(not synthetic fixtures): the repaired frontmatter-extraction code
correctly handles the true multi-line EN source, and the new gates /
consumer-intake checks correctly reject the real damaged output.
"""
from __future__ import annotations

import sys
from pathlib import Path

_CORPUS_DIR = Path(__file__).resolve().parent
_SCRIPTS_QUALITY = str(_CORPUS_DIR.parents[2] / "scripts" / "quality")
if _SCRIPTS_QUALITY not in sys.path:
    sys.path.insert(0, _SCRIPTS_QUALITY)

from src.translation_engine.consumer_intake import check_pair
from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult

_DESC_DIR = _CORPUS_DIR / "description_truncation"
_LEAK_DIR = _CORPUS_DIR / "title_prompt_leak"
_FENCE_DIR = _CORPUS_DIR / "fence_strip"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_gate() -> WriteGateEvaluator:
    return WriteGateEvaluator(detector=None, similarity_tracker=None, config=None, force_accept=False)


class TestDescriptionTruncationCorpus:
    """Real wave-3 pair: bg/cells/net/developer-guide/features.md."""

    def test_true_en_source_is_genuinely_multiline(self):
        """Confirms the precondition: the EN source description spans 3
        physical lines as a single-quoted YAML scalar."""
        en_source = _read(_DESC_DIR / "en_cells_features_source.md")
        fm_end = en_source.find("\n---", 3)
        fm_text = en_source[3:fm_end]
        desc_lines = [ln for ln in fm_text.splitlines() if ln.strip()]
        # description spans from its "description:" line through the closing quote line
        start = next(i for i, ln in enumerate(desc_lines) if ln.startswith("description:"))
        end = next(i for i in range(start + 1, len(desc_lines)) if desc_lines[i].startswith("weight:"))
        assert end - start > 1, "EN source description must be genuinely multi-line"

    def test_get_frontmatter_field_extracts_full_value_not_first_line(self):
        """TC-HT-001: the fixed extraction must not truncate to line 1."""
        from frontmatter_utils import get_frontmatter_field

        en_source = _read(_DESC_DIR / "en_cells_features_source.md")
        value = get_frontmatter_field(en_source, "description")
        assert value is not None
        assert "workbook" in value
        assert "worksheet management" in value  # only present if lines 2-3 were captured
        assert not value.rstrip().endswith("workbook")  # old bug's truncation point

    def test_damaged_file_yaml_is_malformed_gate8_blocks(self):
        """The real damaged file's unterminated quote produces a genuine
        YAML parse error (Gate 8 structural gate blocks it)."""
        damaged = _read(_DESC_DIR / "bg_cells_features_damaged.md")
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_yaml_frontmatter(damaged, Path("features.bg.md"), "bg", None, result)
        assert not result.passed
        assert "parsing a block mapping" in result.error or "block mapping" in result.error

    def test_parent_file_yaml_is_well_formed(self):
        """The real parent (good) file parses cleanly."""
        parent = _read(_DESC_DIR / "bg_cells_features_parent.md")
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_yaml_frontmatter(parent, Path("features.bg.md"), "bg", None, result)
        assert result.passed


class TestFenceStripCorpus:
    """Real wave-3 pair: reference.aspose.org/ja/slides/java/presentation.md
    (16 fence lines in parent, 0 in damaged)."""

    def test_gate26_blocks_real_fence_strip(self):
        parent = _read(_FENCE_DIR / "ja_slides_presentation_parent.md")
        damaged = _read(_FENCE_DIR / "ja_slides_presentation_damaged.md")
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_fence_parity(parent, damaged, Path("presentation.ja.md"), result)
        assert not result.passed
        assert "Gate 26" in result.error

    def test_gate26_passes_when_fences_match(self):
        parent = _read(_FENCE_DIR / "ja_slides_presentation_parent.md")
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_fence_parity(parent, parent, Path("presentation.ja.md"), result)
        assert result.passed

    def test_gate19_also_catches_this_real_case(self):
        """Confirms Gate 19's pre-existing threshold-based check also fires
        for this case (large loss) -- Gate 26 is the zero-tolerance backstop
        for smaller losses Gate 19 would miss."""
        parent = _read(_FENCE_DIR / "ja_slides_presentation_parent.md")
        damaged = _read(_FENCE_DIR / "ja_slides_presentation_damaged.md")
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_code_fence_count(parent, damaged, Path("presentation.ja.md"), result)
        assert not result.passed


class TestTitlePromptLeakCorpus:
    """Real wave-3 pair: reference.aspose.org/es/pdf/net/Do.md."""

    def test_consumer_intake_catches_real_prompt_leak(self):
        damaged = _read(_LEAK_DIR / "es_pdf_do_damaged.md")
        parent = _read(_LEAK_DIR / "es_pdf_do_parent.md")
        failures = check_pair(damaged, parent, "es")
        assert "R2" in failures

    def test_consumer_intake_passes_genuinely_clean_content(self):
        """The extracted "parent" revision (2ef1def182^) turns out to
        ALSO carry the leak (linkTitle: 'Reglas:...' -- the leak predates
        this commit; 2ef1def182 only changed which mangled form shipped).
        Use synthetic clean content for the true negative case instead."""
        clean = "---\nlinkTitle: Do\ntitle: Do\n---\nBody content here.\n"
        failures = check_pair(clean, clean, "es")
        assert "R2" not in failures

    def test_parent_revision_already_carried_the_leak(self):
        """Documents the real finding: the leak was already present one
        commit earlier, just in a different mangled form (linkTitle:
        'Reglas:' instead of 'Do')."""
        parent = _read(_LEAK_DIR / "es_pdf_do_parent.md")
        failures = check_pair(parent, None, "es")
        assert "R2" in failures
