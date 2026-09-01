"""TC-P7-03 acceptance: unit tests for scripts/content/fix_title_identity.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_CONTENT_DIR = Path(__file__).resolve().parents[3] / "scripts" / "content"
if str(_SCRIPTS_CONTENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_CONTENT_DIR))

from fix_title_identity import fix_file, get_field_value  # noqa: E402


def test_fix_title_mismatch_dry_run_does_not_write(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: Cells\nlinkTitle: Cells\n---\nbody\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    original = "---\ntitle: Zellen\nlinkTitle: Zellen\n---\nkoerper\n"
    tr.write_text(original, encoding="utf-8")

    outcome = fix_file(tr, en, ["title", "linkTitle"], write=False)

    assert outcome.changed is True
    assert outcome.fields_changed == ["title", "linkTitle"]
    assert tr.read_text(encoding="utf-8") == original  # dry-run: file untouched


def test_fix_title_mismatch_write_applies_and_is_idempotent(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: Cells\nlinkTitle: Cells\n---\nbody\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: Zellen\nlinkTitle: Zellen\n---\nkoerper\n", encoding="utf-8")

    outcome1 = fix_file(tr, en, ["title", "linkTitle"], write=True)
    assert outcome1.changed is True
    fixed_text = tr.read_text(encoding="utf-8")
    assert get_field_value(fixed_text, "title") == "Cells"
    assert get_field_value(fixed_text, "linkTitle") == "Cells"
    assert "koerper" in fixed_text  # body untouched -- blast radius

    # Idempotent: re-running on the already-fixed file is a clean no-op
    outcome2 = fix_file(tr, en, ["title", "linkTitle"], write=True)
    assert outcome2.changed is False
    assert outcome2.skipped_reason == "already matches EN (idempotent no-op)"
    assert tr.read_text(encoding="utf-8") == fixed_text  # unchanged by the no-op


def test_fix_title_preserves_yaml_quoting_from_en(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: 'Cell: value, formula, and style'\n---\nbody\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: Cell\n---\nkoerper\n", encoding="utf-8")

    outcome = fix_file(tr, en, ["title"], write=True)

    assert outcome.changed is True
    fixed_text = tr.read_text(encoding="utf-8")
    assert "title: 'Cell: value, formula, and style'" in fixed_text
    assert get_field_value(fixed_text, "title") == "Cell: value, formula, and style"


def test_fix_title_skips_when_en_has_no_linktitle(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: Cells\n---\nbody\n", encoding="utf-8")  # no linkTitle field
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: Zellen\nlinkTitle: Zellen\n---\nkoerper\n", encoding="utf-8")

    outcome = fix_file(tr, en, ["title", "linkTitle"], write=True)

    assert outcome.fields_changed == ["title"]  # linkTitle left alone, EN doesn't have it
    fixed_text = tr.read_text(encoding="utf-8")
    assert "linkTitle: Zellen" in fixed_text  # untouched


def test_fix_title_only_touches_frontmatter_lines_not_body(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: Cells\n---\ntitle: this word appears in the body too\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: Zellen\n---\ntitle: this word appears in the body too\n", encoding="utf-8")

    outcome = fix_file(tr, en, ["title"], write=True)

    assert outcome.changed is True
    fixed_text = tr.read_text(encoding="utf-8")
    # Only the frontmatter line (first match) changed; body's literal "title:" text untouched.
    assert fixed_text.count("title: this word appears in the body too") == 1
    assert fixed_text.startswith("---\ntitle: Cells\n")
