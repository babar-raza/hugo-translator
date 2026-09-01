"""TC-P7-07 acceptance: unit tests for scripts/content/fix_dropped_code_fences.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_CONTENT_DIR = Path(__file__).resolve().parents[3] / "scripts" / "content"
if str(_SCRIPTS_CONTENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_CONTENT_DIR))

from fix_dropped_code_fences import fix_file  # noqa: E402


def _fenced_block(n: int) -> str:
    return f"```python\ncode_block_{n} = True\n```"


def test_fix_file_reinserts_dropped_fence_in_aligned_section(tmp_path):
    en = tmp_path / "en.md"
    en.write_text(
        "---\ntitle: X\n---\n"
        f"## Installation\ntext before.\n{_fenced_block(1)}\nmore text.\n{_fenced_block(2)}\n"
        "## See Also\nlink text\n",
        encoding="utf-8",
    )
    tr = tmp_path / "tr.md"
    tr.write_text(
        "---\ntitle: X\n---\n"
        "## Installation\ntext before uebersetzt.\nmore text uebersetzt.\n"  # both fences dropped
        "## See Also\nlink text uebersetzt\n",
        encoding="utf-8",
    )

    outcome = fix_file(tr, en, write=True)

    assert outcome.changed is True
    fixed_text = tr.read_text(encoding="utf-8")
    assert "code_block_1 = True" in fixed_text
    assert "code_block_2 = True" in fixed_text
    assert "text before uebersetzt." in fixed_text  # translated prose preserved


def test_fix_file_aligns_by_heading_level_not_exact_translated_text(tmp_path):
    # Regression guard for the real bug found mid-mission: headings are
    # legitimately translated ("## Installation" -> "## Installazione"),
    # so comparing raw heading TEXT for alignment rejected nearly every
    # real file (75/351 code_fence_dropped files had matching structure
    # but different heading text and were incorrectly routed to backlog).
    # Alignment must key on heading LEVEL sequence (## vs ###), not text.
    en = tmp_path / "en.md"
    en.write_text(
        f"---\ntitle: X\n---\n## Installation\ntext\n{_fenced_block(1)}\n{_fenced_block(2)}\n## See Also\nlink\n",
        encoding="utf-8",
    )
    tr = tmp_path / "tr.md"
    tr.write_text(
        "---\ntitle: X\n---\n## Installazione\ntesto tradotto\n## Vedi anche\ncollegamento tradotto\n",
        encoding="utf-8",
    )

    outcome = fix_file(tr, en, write=True)

    assert outcome.changed is True
    fixed_text = tr.read_text(encoding="utf-8")
    assert "## Installazione" in fixed_text  # translated heading preserved
    assert "code_block_1 = True" in fixed_text
    assert "code_block_2 = True" in fixed_text


def test_fix_file_skips_when_heading_structure_mismatches(tmp_path):
    en = tmp_path / "en.md"
    en.write_text(f"---\ntitle: X\n---\n## A\n{_fenced_block(1)}\n{_fenced_block(2)}\n## B\ntext\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    original = "---\ntitle: X\n---\n## A\nno fences here\n"  # missing "## B" entirely -- ambiguous alignment
    tr.write_text(original, encoding="utf-8")

    outcome = fix_file(tr, en, write=True)

    assert outcome.changed is False
    assert "ambiguous alignment" in outcome.skipped_reason
    assert tr.read_text(encoding="utf-8") == original  # untouched, routed to backlog not force-fixed


def test_fix_file_is_idempotent(tmp_path):
    en = tmp_path / "en.md"
    en.write_text(f"---\ntitle: X\n---\n## A\ntext\n{_fenced_block(1)}\n{_fenced_block(2)}\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: X\n---\n## A\ntext uebersetzt\n", encoding="utf-8")

    outcome1 = fix_file(tr, en, write=True)
    assert outcome1.changed is True
    fixed = tr.read_text(encoding="utf-8")

    outcome2 = fix_file(tr, en, write=True)
    assert outcome2.changed is False
    assert tr.read_text(encoding="utf-8") == fixed


def test_fix_file_dry_run_does_not_write(tmp_path):
    en = tmp_path / "en.md"
    en.write_text(f"---\ntitle: X\n---\n## A\ntext\n{_fenced_block(1)}\n{_fenced_block(2)}\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    original = "---\ntitle: X\n---\n## A\ntext uebersetzt\n"
    tr.write_text(original, encoding="utf-8")

    outcome = fix_file(tr, en, write=False)

    assert outcome.changed is True
    assert tr.read_text(encoding="utf-8") == original
