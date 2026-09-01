"""
TC-P7-12 acceptance: unit tests for scripts/quality/verify_fix.py against
known-good (fix holds) and known-bad (fix didn't actually take) synthetic
fixtures, per taskcard.
"""
from __future__ import annotations

import sys
from pathlib import Path

_QUALITY_DIR = Path(__file__).resolve().parents[3] / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

from verify_fix import (  # noqa: E402
    blast_radius_diff,
    check_link_targets_resolve,
    detector_still_fires,
)

EN_FM = "---\ntitle: Installation\n---\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_title_mismatch_known_good_fix_holds(tmp_path):
    site_root = tmp_path / "docs.aspose.org"
    en_path = _write(
        site_root / "en" / "cells" / "java" / "_index.md",
        "---\ntitle: Cells\n---\nbody\n",
    )
    tr_path = _write(
        site_root / "de" / "cells" / "java" / "_index.md",
        "---\ntitle: Cells\n---\nkoerper\n",
    )
    fires, _ = detector_still_fires(
        "title_mismatch", en_path.read_text(encoding="utf-8"), tr_path.read_text(encoding="utf-8"),
        tr_path, en_path, "de", "docs.aspose.org",
    )
    assert fires is False


def test_title_mismatch_known_bad_still_fires(tmp_path):
    site_root = tmp_path / "docs.aspose.org"
    en_path = _write(
        site_root / "en" / "cells" / "java" / "_index.md",
        "---\ntitle: Cells\n---\nbody\n",
    )
    tr_path = _write(
        site_root / "de" / "cells" / "java" / "_index.md",
        "---\ntitle: Zellen\n---\nkoerper\n",
    )
    fires, detail = detector_still_fires(
        "title_mismatch", en_path.read_text(encoding="utf-8"), tr_path.read_text(encoding="utf-8"),
        tr_path, en_path, "de", "docs.aspose.org",
    )
    assert fires is True
    assert "Zellen" in detail


def test_double_period_known_good_fix_holds():
    en_text = "---\ntitle: X\n---\nno periods here\n"
    tr_text = "---\ntitle: X\n---\nEine Zeile ohne Doppelpunkt. Ende.\n"
    fires, _ = detector_still_fires("double_period", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is False


def test_double_period_known_bad_still_fires():
    en_text = "---\ntitle: X\n---\nno periods here\n"
    tr_text = "---\ntitle: X\n---\nEine Zeile mit Fehler.. Ende.\n"
    fires, detail = detector_still_fires("double_period", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is True
    assert detail == ".."


def test_double_period_ignores_code_fences():
    en_text = "---\ntitle: X\n---\nno periods here\n"
    tr_text = "---\ntitle: X\n---\n```python\nx = a..b\n```\nEnde.\n"
    fires, _ = detector_still_fires("double_period", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is False


def test_link_path_corrupted_known_good_fix_holds():
    en_text = "---\ntitle: X\n---\n[Guide](../developer-guide/)\n"
    tr_text = "---\ntitle: X\n---\n[Anleitung](../developer-guide/)\n"
    fires, _ = detector_still_fires(
        "link_path_corrupted", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org"
    )
    assert fires is False


def test_link_path_corrupted_known_bad_still_fires():
    en_text = "---\ntitle: X\n---\n[Guide](../developer-guide/)\n"
    tr_text = "---\ntitle: X\n---\n[Anleitung](./developer-guide/)\n"
    fires, detail = detector_still_fires(
        "link_path_corrupted", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org"
    )
    assert fires is True
    assert "./developer-guide/" in detail


def test_link_targets_resolve_known_good(tmp_path):
    site_root = tmp_path / "docs.aspose.org"
    _write(site_root / "de" / "cells" / "developer-guide" / "_index.md", "content\n")
    tr_path = _write(
        site_root / "de" / "cells" / "getting-started" / "_index.md",
        "---\ntitle: X\n---\n[Guide](../developer-guide/)\n",
    )
    ok, unresolved = check_link_targets_resolve(tr_path.read_text(encoding="utf-8"), tr_path, "docs.aspose.org")
    assert ok is True
    assert unresolved == []


def test_link_targets_resolve_accounts_for_hugo_leaf_page_url_segment(tmp_path):
    # Regression guard for the real bug found mid-mission: a non-_index.md
    # leaf page (e.g. installation.md) renders to a Hugo URL with an EXTRA
    # implied path segment beyond its filesystem directory (foo.md ->
    # ".../foo/"), so "../../developer-guide/" from
    # "3d/java/getting-started/installation.md" correctly resolves to
    # "3d/java/developer-guide/" (up past both getting-started/ AND the
    # implied installation/ segment) -- resolving against the filesystem
    # parent alone (one "../" short) incorrectly flags this as broken.
    site_root = tmp_path / "docs.aspose.org"
    _write(site_root / "de" / "3d" / "java" / "developer-guide" / "_index.md", "content\n")
    tr_path = _write(
        site_root / "de" / "3d" / "java" / "getting-started" / "installation.md",
        "---\ntitle: X\n---\n[Guide](../../developer-guide/)\n",
    )
    ok, unresolved = check_link_targets_resolve(tr_path.read_text(encoding="utf-8"), tr_path, "docs.aspose.org")
    assert ok is True
    assert unresolved == []


def test_link_targets_resolve_index_md_still_uses_filesystem_directory_directly(tmp_path):
    # _index.md's page URL IS its filesystem directory (no extra segment) --
    # confirms the fix didn't break the already-passing _index.md case.
    site_root = tmp_path / "docs.aspose.org"
    _write(site_root / "de" / "cells" / "developer-guide" / "_index.md", "content\n")
    tr_path = _write(
        site_root / "de" / "cells" / "getting-started" / "_index.md",
        "---\ntitle: X\n---\n[Guide](../developer-guide/)\n",
    )
    ok, unresolved = check_link_targets_resolve(tr_path.read_text(encoding="utf-8"), tr_path, "docs.aspose.org")
    assert ok is True
    assert unresolved == []


def test_link_targets_resolve_known_bad_dangling_target(tmp_path):
    site_root = tmp_path / "docs.aspose.org"
    tr_path = _write(
        site_root / "de" / "cells" / "getting-started" / "_index.md",
        "---\ntitle: X\n---\n[Guide](../nonexistent-page/)\n",
    )
    ok, unresolved = check_link_targets_resolve(tr_path.read_text(encoding="utf-8"), tr_path, "docs.aspose.org")
    assert ok is False
    assert "../nonexistent-page/" in unresolved


def test_code_fence_dropped_known_good_fix_holds():
    en_text = "---\ntitle: X\n---\n" + "\n".join(f"```\ncode{i}\n```" for i in range(3))
    tr_text = en_text  # fences preserved
    fires, _ = detector_still_fires(
        "code_fence_dropped", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org"
    )
    assert fires is False


def test_code_fence_dropped_known_bad_still_fires():
    en_text = "---\ntitle: X\n---\n" + "\n".join(f"```\ncode{i}\n```" for i in range(3))
    tr_text = "---\ntitle: X\n---\nno fences at all here\n"
    fires, _ = detector_still_fires(
        "code_fence_dropped", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org"
    )
    assert fires is True


def test_empty_body_known_good_fix_holds():
    en_text = "---\ntitle: X\n---\n" + ("This is a real body with real content. " * 5)
    tr_text = "---\ntitle: X\n---\n" + ("Dies ist ein echter Textkoerper. " * 5)
    fires, _ = detector_still_fires("empty_body", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is False


def test_empty_body_known_bad_still_fires():
    en_text = "---\ntitle: X\n---\n" + ("This is a real body with real content. " * 5)
    tr_text = "---\ntitle: X\n---\n\n"
    fires, _ = detector_still_fires("empty_body", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is True


def test_shortcode_leak_known_good_fix_holds():
    en_text = "---\ntitle: X\n---\nno shortcodes\n"
    tr_text = "---\ntitle: X\n---\nkeine shortcodes\n"
    fires, _ = detector_still_fires("shortcode_leak", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is False


def test_shortcode_leak_known_bad_still_fires():
    en_text = "---\ntitle: X\n---\nno shortcodes\n"
    tr_text = "---\ntitle: X\n---\n**{{< sections cols=\"4\" >}}**: leaked\n"
    fires, _ = detector_still_fires("shortcode_leak", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is True


def test_blast_radius_diff_small_change_passes():
    before = "line1\nline2\nline3\nline4\nline5\n"
    after = "line1\nline2 FIXED\nline3\nline4\nline5\n"
    ok, _ = blast_radius_diff(before, after)
    assert ok is True


def test_newline_explosion_known_good_fix_holds():
    en_text = "\n".join(f"line{i}" for i in range(20))
    tr_text = "\n".join(f"Zeile{i}" for i in range(22))
    fires, _ = detector_still_fires("newline_explosion", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is False


def test_newline_explosion_known_bad_still_fires():
    en_text = "\n".join(f"line{i}" for i in range(20))
    tr_text = "\n".join(f"Zeile{i}" for i in range(60))
    fires, detail = detector_still_fires("newline_explosion", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org")
    assert fires is True
    assert "EN=" in detail


def test_table_desc_not_translated_known_good_fix_holds():
    # Non-Latin script (ja) so the translated description can never falsely
    # pattern-match as English prose, unlike Latin-alphabet languages sharing
    # short lowercase words (de "und"/"den" etc.) with the EN_WORD_LINE regex.
    en_text = "---\ntitle: X\n---\n| Name | Type | Description |\n|---|---|---|\n"
    tr_lines = ["---", "title: X", "---", "| 名前 | 型 | 説明 |", "|---|---|---|"]
    for i in range(4):
        tr_lines.append(f"| フィールド{i} | str | フィールド{i}の値を取得または設定する長い説明文です |")
    tr_text = "\n".join(tr_lines)
    fires, _ = detector_still_fires(
        "table_desc_not_translated", en_text, tr_text, Path("x.md"), Path("en.md"), "ja", "docs.aspose.org"
    )
    assert fires is False


def test_table_desc_not_translated_known_bad_still_fires():
    en_text = "---\ntitle: X\n---\n| Name | Type | Description |\n|---|---|---|\n"
    tr_lines = ["---", "title: X", "---", "| Name | Typ | Beschreibung |", "|---|---|---|"]
    for i in range(4):
        tr_lines.append(f"| field{i} | str | Gets or sets the value of field number {i} in this record |")
    tr_text = "\n".join(tr_lines)
    fires, detail = detector_still_fires(
        "table_desc_not_translated", en_text, tr_text, Path("x.md"), Path("en.md"), "de", "docs.aspose.org"
    )
    assert fires is True
    assert "desc cells English" in detail


def test_verify_fix_ignores_preexisting_completeness_issue_unrelated_to_fix(tmp_path):
    # Regression guard: a file can carry a pre-existing, out-of-scope defect
    # (e.g. a dropped trailing link -- Gate 34/35 territory, not this
    # mission's) that exists identically in both before and after text. That
    # must not block an otherwise-correct double_period fix.
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "quality"))
    from verify_fix import verify_fix

    en = _write(
        tmp_path / "en.md",
        "---\ntitle: X\n---\nSome long enough source paragraph with real content here for ratio checks.\n"
        "See also [Enterprise API](https://kb.aspose.com/3d/java/).\n",
    )
    # Both before and after are missing the trailing link -- pre-existing,
    # not introduced by this fix. Only the double-period is different.
    before = "---\ntitle: X\n---\nSome long enough translated paragraph with real content here.. for ratio checks.\n"
    after = "---\ntitle: X\n---\nSome long enough translated paragraph with real content here. for ratio checks.\n"
    tr_path = tmp_path / "tr.md"
    tr_path.write_text(after, encoding="utf-8")

    result = verify_fix("double_period", tr_path, en, before, after, "de", "docs.aspose.org")

    assert result.completeness_issues == []
    assert result.passed is True


def test_blast_radius_diff_wholesale_rewrite_fails():
    before = "\n".join(f"line{i}" for i in range(20))
    after = "\n".join(f"totally different {i}" for i in range(20))
    ok, detail = blast_radius_diff(before, after)
    assert ok is False
    assert "%" in detail
