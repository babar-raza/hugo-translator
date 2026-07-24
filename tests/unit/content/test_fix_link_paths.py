"""TC-P7-05 acceptance: unit tests for scripts/content/fix_link_paths.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_CONTENT_DIR = Path(__file__).resolve().parents[3] / "scripts" / "content"
if str(_SCRIPTS_CONTENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_CONTENT_DIR))

from fix_link_paths import fix_file, reverse_collapsed_dots  # noqa: E402


def test_reverse_collapsed_dots_single_segment():
    assert reverse_collapsed_dots("./developer-guide/") == "../developer-guide/"


def test_reverse_collapsed_dots_double_segment():
    assert reverse_collapsed_dots("././developer-guide/") == "../../developer-guide/"


def test_reverse_collapsed_dots_leaves_bare_relative_unchanged():
    assert reverse_collapsed_dots("installation/") == "installation/"


def test_fix_file_exact_match_case(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: X\n---\n[Guide](../developer-guide/)\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: X\n---\n[Anleitung](./developer-guide/)\n", encoding="utf-8")

    outcome = fix_file(tr, en, write=True)

    assert outcome.changed is True
    assert outcome.fixed_links == [("./developer-guide/", "../developer-guide/")]
    fixed_text = tr.read_text(encoding="utf-8")
    assert "[Anleitung](../developer-guide/)" in fixed_text


def test_fix_file_non_exact_match_routes_to_backlog_not_forced(tmp_path):
    # Stale-content case (root cause 2): the "corrected" reverse-transform
    # doesn't match anything in EN -- must NOT force a guess.
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: X\n---\n[Scene](/3d/java/scene/)\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: X\n---\n[Transform](/3d/java/transform/)\n", encoding="utf-8")

    outcome = fix_file(tr, en, write=True)

    assert outcome.changed is False
    assert outcome.unresolved_links == ["/3d/java/transform/"]
    # File untouched
    assert tr.read_text(encoding="utf-8") == "---\ntitle: X\n---\n[Transform](/3d/java/transform/)\n"


def test_fix_file_only_replaces_the_specific_corrupted_target(tmp_path):
    # A second, already-correct "./"-style link in the same file (if such a
    # thing existed pre-corruption) must not be touched by the fix -- only
    # the link target(s) actually flagged as corrupted (present in TR, absent
    # from EN) get rewritten.
    en = tmp_path / "en.md"
    en.write_text(
        "---\ntitle: X\n---\n[Guide](../developer-guide/)\n[Other](./same-dir-page/)\n",
        encoding="utf-8",
    )
    tr = tmp_path / "tr.md"
    tr.write_text(
        "---\ntitle: X\n---\n[Anleitung](./developer-guide/)\n[Andere](./same-dir-page/)\n",
        encoding="utf-8",
    )

    outcome = fix_file(tr, en, write=True)

    assert outcome.changed is True
    fixed_text = tr.read_text(encoding="utf-8")
    assert "[Anleitung](../developer-guide/)" in fixed_text
    assert "[Andere](./same-dir-page/)" in fixed_text  # untouched: it was never corrupted (matches EN as-is)


def test_fix_file_is_idempotent(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: X\n---\n[Guide](../developer-guide/)\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: X\n---\n[Anleitung](./developer-guide/)\n", encoding="utf-8")

    outcome1 = fix_file(tr, en, write=True)
    assert outcome1.changed is True
    fixed = tr.read_text(encoding="utf-8")

    outcome2 = fix_file(tr, en, write=True)
    assert outcome2.changed is False
    assert tr.read_text(encoding="utf-8") == fixed


def test_fix_file_dry_run_does_not_write(tmp_path):
    en = tmp_path / "en.md"
    en.write_text("---\ntitle: X\n---\n[Guide](../developer-guide/)\n", encoding="utf-8")
    tr = tmp_path / "tr.md"
    original = "---\ntitle: X\n---\n[Anleitung](./developer-guide/)\n"
    tr.write_text(original, encoding="utf-8")

    outcome = fix_file(tr, en, write=False)

    assert outcome.changed is True
    assert tr.read_text(encoding="utf-8") == original
