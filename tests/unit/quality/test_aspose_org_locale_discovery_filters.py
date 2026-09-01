"""
Directory-discovery-bypass regression coverage for the Aspose.org 26-locale
contract (scenario 6 in the locale-restriction task: an unsupported
destination directory must not create translation/maintenance work).

Before this change, heal_english_headings.py, surgical_retranslate.py,
delete_for_retranslate.py, and backfill_frontmatter_ids.py all discovered
locales via a raw `site_root.iterdir()` scan whenever `--locales` was
omitted, completely ignoring the site's active target_langs. These tests
build a fixture content tree containing a retired-locale directory (`bg/`,
the same negative-control locale used across the locale-policy suite) plus
an approved one (`de/`) and assert `bg` is never touched by auto-discovery,
and that delete_for_retranslate.py refuses to delete `bg/` content even
when explicitly requested.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.quality import backfill_frontmatter_ids, delete_for_retranslate, surgical_retranslate
from scripts.quality.heal_english_headings import run_scan
from src.utils.config_loader import ConfigService
from src.utils.locale_policy import LocalePolicyViolation, validate_requested_locales

RETIRED_LOCALE = "bg"
APPROVED_LOCALE = "de"
SITE_ID = "docs.aspose.org"


def _make_site_tree(tmp_path: Path) -> Path:
    content_root = tmp_path / "content"
    site_root = content_root / SITE_ID
    for locale, body in (
        ("en", "Hello world, this is the source page."),
        (APPROVED_LOCALE, "Hallo Welt, das ist die Zielseite."),
        (RETIRED_LOCALE, "Здравей свят, това е целевата страница."),
    ):
        locale_dir = site_root / locale
        locale_dir.mkdir(parents=True)
        (locale_dir / "index.md").write_text(
            f"---\ntitle: Test\n---\n{body}\n", encoding="utf-8"
        )
    return content_root


def test_delete_for_retranslate_auto_discovery_excludes_retired_locale(tmp_path, capsys):
    content_root = _make_site_tree(tmp_path)
    delete_for_retranslate.run(
        content_root=content_root,
        sites=[SITE_ID],
        only_locales=None,
        apply=False,
        only_issues=None,
        max_files=None,
        verbose=False,
    )
    out = capsys.readouterr().out
    assert f"{APPROVED_LOCALE}:" in out
    assert f"{RETIRED_LOCALE}:" not in out


def test_delete_for_retranslate_never_deletes_retired_locale_even_auto_discovered(tmp_path):
    content_root = _make_site_tree(tmp_path)
    bg_file = content_root / SITE_ID / RETIRED_LOCALE / "index.md"
    assert bg_file.exists()

    delete_for_retranslate.run(
        content_root=content_root,
        sites=[SITE_ID],
        only_locales=None,
        apply=True,  # --apply, but bg/ was excluded from auto-discovery
        only_issues=None,
        max_files=None,
        verbose=False,
    )
    assert bg_file.exists(), "retired-locale file must never be deleted by auto-discovery"


def test_delete_for_retranslate_rejects_explicit_retired_locale_request():
    # main()-level guard: an explicit --locales bg must be refused outright,
    # not silently filtered to zero work. docs.aspose.org has
    # strict_locale_allowlist: true, so this must raise.
    site_profile = ConfigService("config").get_site_profile(SITE_ID)
    with pytest.raises(LocalePolicyViolation):
        validate_requested_locales(site_profile, [RETIRED_LOCALE])


def test_surgical_retranslate_auto_discovery_excludes_retired_locale(tmp_path, capsys):
    content_root = _make_site_tree(tmp_path)
    surgical_retranslate.run(
        content_root=content_root,
        only_locales=None,
        apply=False,
        only_issues=None,
        max_files=None,
        verbose=False,
        sites=[SITE_ID],
    )
    out = capsys.readouterr().out
    assert f"{APPROVED_LOCALE}:" in out
    assert f"{RETIRED_LOCALE}:" not in out


def test_backfill_frontmatter_ids_auto_discovery_excludes_retired_locale(tmp_path, capsys):
    content_root = _make_site_tree(tmp_path)
    backfill_frontmatter_ids.run(
        content_root=content_root,
        site=SITE_ID,
        only_locales=None,
        apply=False,
        verbose=False,
    )
    out = capsys.readouterr().out
    assert f"Locales: ['{APPROVED_LOCALE}']" in out
    assert RETIRED_LOCALE not in out


def test_heal_english_headings_scan_auto_discovery_excludes_retired_locale(tmp_path, capsys):
    content_root = _make_site_tree(tmp_path)

    import scripts.quality.heal_english_headings as heh

    original_resolve = heh._resolve_content_root
    heh._resolve_content_root = lambda: content_root
    try:
        run_scan(sites=[SITE_ID], locales=[], categories=set(), max_files=0)
    finally:
        heh._resolve_content_root = original_resolve

    out = capsys.readouterr().out
    assert f"{APPROVED_LOCALE:4s}:" in out
    assert f"{RETIRED_LOCALE:4s}:" not in out
