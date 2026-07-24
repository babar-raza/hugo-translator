"""TC-P7-06 acceptance: unit tests for scripts/quality/triage_newline_explosion.py."""
from __future__ import annotations

import sys
from pathlib import Path

_QUALITY_DIR = Path(__file__).resolve().parents[3] / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

from triage_newline_explosion import classify, collapse_blank_lines, process_file  # noqa: E402


def test_classify_apis_overlap_matching_is_mechanical():
    en_text = "---\nevidence:\n  apis:\n  - Material.get_texture\n  - Material.name\n---\nbody\n"
    tr_text = "---\nevidence:\n  apis:\n  - Material.get_texture\n  - Material.name\n---\nkoerper\n"
    result = classify(en_text, tr_text)
    assert result.verdict == "mechanical"
    assert result.signal_used == "apis_overlap"


def test_classify_apis_overlap_diverging_is_stale():
    # This mirrors the confirmed real-world case: TR documents a removed
    # API surface (LambertMaterial/PhongMaterial) EN no longer has.
    en_text = "---\nevidence:\n  apis:\n  - Material.get_texture\n  - Material.name\n---\nbody\n"
    tr_text = "---\nevidence:\n  apis:\n  - LambertMaterial.ambient_color\n  - PhongMaterial.shininess\n---\nkoerper\n"
    result = classify(en_text, tr_text)
    assert result.verdict == "stale"


def test_classify_falls_back_to_heading_overlap_when_no_apis():
    en_text = "---\ntitle: X\n---\n## Overview\nbody\n## See Also\nmore\n"
    tr_text = "---\ntitle: X\n---\n## Ubersicht\nkoerper\n## Siehe auch\nmehr\n"
    result = classify(en_text, tr_text)
    assert result.verdict == "mechanical"
    assert result.signal_used == "heading_overlap"


def test_classify_falls_back_to_line_ratio_when_no_apis_or_headings():
    en_text = "---\ntitle: X\n---\n" + "\n".join(f"line{i}" for i in range(10))
    tr_text = "---\ntitle: X\n---\n" + "\n".join(f"Zeile{i}" for i in range(11))
    result = classify(en_text, tr_text)
    assert result.verdict == "mechanical"
    assert result.signal_used == "line_ratio"


def test_collapse_blank_lines_collapses_runs_of_three_or_more():
    text = "---\ntitle: X\n---\nline1\n\n\n\n\nline2\n"
    new_text, changed = collapse_blank_lines(text)
    assert changed is True
    assert "line1\n\nline2\n" in new_text


def test_collapse_blank_lines_leaves_normal_paragraph_breaks_alone():
    text = "---\ntitle: X\n---\nline1\n\nline2\n"
    new_text, changed = collapse_blank_lines(text)
    assert changed is False
    assert new_text == text


def test_process_file_stale_case_is_never_written(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\nevidence:\n  apis:\n  - Material.get_texture\n---\nbody\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    original = "---\nevidence:\n  apis:\n  - LambertMaterial.ambient_color\n---\nkoerper\n\n\n\n\nmehr text\n"
    tr.write_text(original, encoding="utf-8")

    outcome = process_file(tr, en, write=True)

    assert outcome.verdict == "stale"
    assert outcome.changed is False
    assert tr.read_text(encoding="utf-8") == original  # untouched -- stale content is never mechanically patched
