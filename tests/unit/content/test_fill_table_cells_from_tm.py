"""TC-P7-08 acceptance: unit tests for scripts/content/fill_table_cells_from_tm.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_CONTENT_DIR = Path(__file__).resolve().parents[3] / "scripts" / "content"
if str(_SCRIPTS_CONTENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_CONTENT_DIR))
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fill_table_cells_from_tm import looks_like_passthrough_identifier, process_file  # noqa: E402
from src.tm import lmdb_registry  # noqa: E402
from src.tm.l2_persistent import L2PersistentTM  # noqa: E402


def test_looks_like_passthrough_identifier_true_for_bare_type_name():
    assert looks_like_passthrough_identifier("str") is True
    assert looks_like_passthrough_identifier("PropertyCollection") is True
    assert looks_like_passthrough_identifier("`List<int>`") is True


def test_looks_like_passthrough_identifier_false_for_prose():
    assert looks_like_passthrough_identifier("Gets or sets the name of the field") is False


def _make_tm(tmp_path, monkeypatch):
    monkeypatch.setattr(lmdb_registry, "APPROVED_LMDB_RELATIVE_PATHS", frozenset({"test_l2.lmdb"}))
    lmdb_registry.set_project_root(tmp_path)
    return L2PersistentTM(tmp_path / "test_l2.lmdb")


def test_process_file_fills_from_exact_tm_hit(tmp_path, monkeypatch):
    tm = _make_tm(tmp_path, monkeypatch)
    en_desc = "Gets or sets the name of the field in this record"
    tm.store(site_id="docs.aspose.org", src_lang="en", tgt_lang="de", text=en_desc, translation="Ruft den Namen des Feldes in diesem Datensatz ab oder legt ihn fest")

    en = tmp_path / "en.md"
    en.write_text(
        f"---\ntitle: X\n---\n| Name | Type | Description |\n|---|---|---|\n| field | str | {en_desc} |\n",
        encoding="utf-8",
    )
    tr = tmp_path / "tr.md"
    tr.write_text(
        f"---\ntitle: X\n---\n| Name | Typ | Beschreibung |\n|---|---|---|\n| field | str | {en_desc} |\n",
        encoding="utf-8",
    )

    result = process_file(tr, en, tm, "docs.aspose.org", "de", write=True)

    assert result.tm_filled_cells == 1
    assert result.changed is True
    fixed_text = tr.read_text(encoding="utf-8")
    assert "Ruft den Namen des Feldes" in fixed_text


def test_process_file_no_tm_hit_routes_to_still_missing(tmp_path, monkeypatch):
    tm = _make_tm(tmp_path, monkeypatch)
    en_desc = "Gets or sets the value of another field entirely uncached"

    en = tmp_path / "en.md"
    en.write_text(
        f"---\ntitle: X\n---\n| Name | Type | Description |\n|---|---|---|\n| field | str | {en_desc} |\n",
        encoding="utf-8",
    )
    tr = tmp_path / "tr.md"
    original = f"---\ntitle: X\n---\n| Name | Typ | Beschreibung |\n|---|---|---|\n| field | str | {en_desc} |\n"
    tr.write_text(original, encoding="utf-8")

    result = process_file(tr, en, tm, "docs.aspose.org", "de", write=True)

    assert result.tm_filled_cells == 0
    assert result.still_missing_cells == 1
    assert result.changed is False
    assert tr.read_text(encoding="utf-8") == original  # untouched


def test_process_file_aligns_by_row_key_not_line_position(tmp_path, monkeypatch):
    # Regression guard for a real data-corruption incident mid-mission:
    # EN and TR prose *before* the table has a different line count
    # (routine -- translated text is rarely the same length), which shifted
    # every row's EN lookup by a per-file offset when alignment used raw
    # body line-index. In the real incident this caused a correct English
    # description to be overwritten with the literal table header word
    # "Description". Alignment must key on the row's first-cell identifier
    # (never translated), immune to any line-count difference.
    tm = _make_tm(tmp_path, monkeypatch)
    darken_desc = "Represents a blend mode that selects the darker of the fill and background colors"
    tm.store(site_id="reference.aspose.org", src_lang="en", tgt_lang="bg", text=darken_desc, translation="ПРАВИЛЕН ПРЕВОД")

    en = tmp_path / "en.md"
    en.write_text(
        "---\ntitle: X\n---\n"
        "One paragraph of English prose before the table.\n\n"
        "| Value | Description |\n|---|---|\n"
        f"| `Darken` | {darken_desc} |\n"
        "| `Lighten` |  |\n",
        encoding="utf-8",
    )
    tr = tmp_path / "tr.md"
    tr.write_text(
        "---\ntitle: X\n---\n"
        "Един параграф.\nВтори ред превод.\nТрети ред тук за да измести номерата на редовете спрямо английския.\n\n"
        "| Value | Description |\n|---|---|\n"
        f"| `Darken` | {darken_desc} |\n"
        "| `Lighten` |  |\n",
        encoding="utf-8",
    )

    result = process_file(tr, en, tm, "reference.aspose.org", "bg", write=True)

    fixed_text = tr.read_text(encoding="utf-8")
    assert "ПРАВИЛЕН ПРЕВОД" in fixed_text
    assert result.tm_filled_cells == 1
    # Critical: the header row's own cell ("Description") must never appear
    # as a filled-in value anywhere in the body.
    import re as _re

    data_rows = [ln for ln in fixed_text.splitlines() if ln.strip().startswith("|") and "Darken" not in ln and "Lighten" not in ln and "Value" not in ln]
    assert not any(_re.fullmatch(r"\|\s*Description\s*\|", ln.strip()) for ln in data_rows)


def test_process_file_treats_duplicate_en_key_as_ambiguous_not_a_guess(tmp_path, monkeypatch):
    # Regression guard: EN source can legitimately list the same identifier
    # twice in one table (confirmed real, e.g. reference.aspose.org/en/3d/
    # net/_index.md has two "Axis" rows). Silently keeping "whichever EN
    # row wins the dict" risks matching a TR row to its sibling's
    # description instead of its own. Must never fill in this case.
    tm = _make_tm(tmp_path, monkeypatch)
    desc_a = "First Axis description that is long enough to be flagged as English prose here"
    desc_b = "Second Axis description that is long enough to be flagged as English prose here"
    tm.store(site_id="reference.aspose.org", src_lang="en", tgt_lang="de", text=desc_a, translation="UEBERSETZUNG_A")
    tm.store(site_id="reference.aspose.org", src_lang="en", tgt_lang="de", text=desc_b, translation="UEBERSETZUNG_B")

    en = tmp_path / "en.md"
    en.write_text(
        "---\ntitle: X\n---\n| Name | Description |\n|---|---|\n"
        f"| `Axis` | {desc_a} |\n| `Axis` | {desc_b} |\n",
        encoding="utf-8",
    )
    tr = tmp_path / "tr.md"
    original = (
        "---\ntitle: X\n---\n| Name | Description |\n|---|---|\n"
        f"| `Axis` | {desc_a} |\n| `Axis` | {desc_b} |\n"
    )
    tr.write_text(original, encoding="utf-8")

    result = process_file(tr, en, tm, "reference.aspose.org", "de", write=True)

    assert result.tm_filled_cells == 0  # ambiguous key -- never guessed
    assert result.still_missing_cells == 2
    assert tr.read_text(encoding="utf-8") == original  # untouched


def test_find_table_rows_excludes_header_row(tmp_path, monkeypatch):
    from fill_table_cells_from_tm import find_table_rows

    body = "prose\n\n| Value | Description |\n|---|---|\n| `Darken` | text |\n"
    rows = find_table_rows(body)
    assert len(rows) == 1
    assert rows[0]["cells"][0] == "`Darken`"


def test_process_file_skips_short_cells_and_separator_rows(tmp_path, monkeypatch):
    tm = _make_tm(tmp_path, monkeypatch)
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: X\n---\n| Name | Type | Description |\n|---|---|---|\n| x | str | short |\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    original = "---\ntitle: X\n---\n| Name | Typ | Beschreibung |\n|---|---|---|\n| x | str | short |\n"
    tr.write_text(original, encoding="utf-8")

    result = process_file(tr, en, tm, "docs.aspose.org", "de", write=True)

    assert result.total_flagged_cells == 0  # "short" is under the 20-char threshold, not flagged at all
