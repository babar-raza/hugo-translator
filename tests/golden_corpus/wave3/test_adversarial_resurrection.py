"""
TC-HT-010: adversarial resurrection test.

Reconstructs the OLD, buggy `_fix_description_hallucination` (deleted in
TC-HT-001; pasted here verbatim from git history, not exec'd from a live
`git show` at test time) and proves the new safety net -- Gate 8 (YAML
structural) via the full WriteGateEvaluator pipeline, reached through
safe_io.save() -- blocks its output on the REAL wave-3 golden-corpus pair.

This proves the corruption class is caught by the gates independently of
the TC-HT-001 code-level fix: even if the buggy function were somehow
reintroduced, the write path would refuse to persist its output.

Original source (deleted by TC-HT-001, commit f29c7cc):
    git show f29c7cc^:scripts/quality/surgical_retranslate.py | sed -n '793,800p'
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_CORPUS_DIR = Path(__file__).resolve().parent
_SCRIPTS_QUALITY = str(_CORPUS_DIR.parents[2] / "scripts" / "quality")
if _SCRIPTS_QUALITY not in sys.path:
    sys.path.insert(0, _SCRIPTS_QUALITY)

_DESC_DIR = _CORPUS_DIR / "description_truncation"


def _old_buggy_fix_description_hallucination(en_content: str, tr_content: str) -> str:
    """Verbatim resurrection of the deleted buggy fixer (TC-HT-001).

    Replace tgt frontmatter description with the EN source description
    LINE verbatim -- the exact regex that caused the wave-3 corruption:
    `.+` with `re.MULTILINE` (no DOTALL) captures only the FIRST physical
    line of a multi-line YAML scalar.
    """
    en_m = re.search(r"^(description:\s*.+)$", en_content[:2000], re.MULTILINE)
    if not en_m:
        return tr_content
    en_line = en_m.group(1)  # e.g. 'description: "Learn how to..."'
    new = re.sub(r"^description:\s*.+$", en_line, tr_content, count=1, flags=re.MULTILINE)
    return new


class TestAdversarialResurrection:
    def test_old_buggy_fixer_reproduces_the_real_corruption_signature(self):
        """Sanity check: running the resurrected bug over the TRUE EN
        source and the REAL (good) parent translation reproduces the same
        truncation signature actually observed in the damaged file."""
        en_source = (_DESC_DIR / "en_cells_features_source.md").read_text(encoding="utf-8")
        parent = (_DESC_DIR / "bg_cells_features_parent.md").read_text(encoding="utf-8")
        damaged_real = (_DESC_DIR / "bg_cells_features_damaged.md").read_text(encoding="utf-8")

        resurrected_output = _old_buggy_fix_description_hallucination(en_source, parent)

        # Same truncation point as the real wave-3 damage: cut mid-sentence,
        # quote left open.
        assert "description: 'Overview of all major capabilities in Aspose.Cells FOSS for .NET: workbook" in resurrected_output
        assert "worksheet management" not in resurrected_output.split("---", 2)[1]
        # Matches the real damaged file's frontmatter shape (first two lines identical).
        real_first_lines = damaged_real.split("\n")[:4]
        resurrected_first_lines = resurrected_output.split("\n")[:4]
        assert real_first_lines == resurrected_first_lines

    def test_safe_io_blocks_the_resurrected_corruption(self, tmp_path, monkeypatch):
        """The actual proof: safe_io.save() (TC-HT-002, running the full
        WriteGateEvaluator pipeline including Gate 8) refuses to write the
        resurrected bug's output."""
        import safe_io

        monkeypatch.chdir(tmp_path)
        en_source = (_DESC_DIR / "en_cells_features_source.md").read_text(encoding="utf-8")
        parent = (_DESC_DIR / "bg_cells_features_parent.md").read_text(encoding="utf-8")

        corrupted = _old_buggy_fix_description_hallucination(en_source, parent)

        out_path = tmp_path / "features.bg.md"
        # Simulate: the file already exists with the good parent content
        # (this is a REPAIR run, not a fresh translation).
        out_path.write_text(parent, encoding="utf-8")

        frontmatter, body = safe_io.parse_content(corrupted)
        result = safe_io.save(
            out_path, out_path, frontmatter, body,
            source_content=en_source, target_lang="bg",
        )

        assert result.written is False
        assert result.quarantined is True
        # The good, pre-existing parent content must survive untouched.
        assert out_path.read_text(encoding="utf-8") == parent

    def test_gate27_would_also_block_a_syntactically_valid_truncation(self):
        """Belt-and-braces: even in a hypothetical variant of the bug where
        the truncated value stayed syntactically valid YAML (e.g. properly
        re-quoted rather than left open), Gate 27 (TC-HT-005) independently
        blocks it on length-ratio grounds."""
        from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult

        en_source = (_DESC_DIR / "en_cells_features_source.md").read_text(encoding="utf-8")
        # A syntactically-valid stand-in for "truncated to first line, requoted".
        truncated_but_valid = (
            "---\ntitle: Features\n"
            "description: 'Overview of all major capabilities in Aspose.Cells FOSS for .NET: workbook'\n"
            "weight: 10\ntype: docs\n---\nBody.\n"
        )
        gate = WriteGateEvaluator(detector=None, similarity_tracker=None, config=None, force_accept=False)
        result = WriteGateResult(passed=True)
        gate._gate_multiline_scalar_preservation(
            en_source, truncated_but_valid, "bg", Path("features.bg.md"), result
        )
        assert not result.passed
        assert "Gate 27" in result.error
