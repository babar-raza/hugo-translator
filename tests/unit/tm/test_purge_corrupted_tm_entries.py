"""
TC-P7-13 acceptance: unit tests for scripts/tm/purge_corrupted_tm_entries.py.

Predicate tests use pure strings. The scan/delete tests open a raw LMDB env
directly (bypassing L2PersistentTM's canonical-path enforcement, which is
irrelevant to testing the cursor-scan-and-delete mechanics themselves) using
the same wire format L2PersistentTM writes (JSON-encoded TranslationEntry
dicts), so the test proves the actual read/write logic against the real
LMDB format, not a mock.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import lmdb

_SCRIPTS_TM_DIR = Path(__file__).resolve().parents[3] / "scripts" / "tm"
if str(_SCRIPTS_TM_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_TM_DIR))

from purge_corrupted_tm_entries import (  # noqa: E402
    build_predicate,
    collapsed_link_predicate,
    delete_l2_keys,
    double_period_predicate,
    scan_l2_for_purge,
)


def test_double_period_predicate_known_bad():
    assert double_period_predicate("Eine Zeile mit Fehler.. Ende.") is True


def test_double_period_predicate_known_good():
    assert double_period_predicate("Eine Zeile ohne Fehler. Ende.") is False


def test_double_period_predicate_ignores_code_fences():
    assert double_period_predicate("```python\nx = a..b\n```\nEnde.") is False


def test_collapsed_link_predicate_known_bad():
    assert collapsed_link_predicate("[Anleitung](./developer-guide/)") is True


def test_collapsed_link_predicate_known_good():
    assert collapsed_link_predicate("[Anleitung](../developer-guide/)") is False


def test_collapsed_link_predicate_ignores_bare_relative_link():
    # "installation/" (no dot prefix at all) is never touched by the
    # confirmed corruption pattern -- must not false-positive on it.
    assert collapsed_link_predicate("[Installation](installation/)") is False


def test_build_predicate_combines_checks():
    predicate = build_predicate({"double_period", "link_path_corrupted"})
    assert predicate("Fehler.. Ende.") is True
    assert predicate("[x](./y/)") is True
    assert predicate("alles gut. Ende.") is False


def _entry(site_id: str, tgt_lang: str, translation: str, field_name: str = "") -> dict:
    return {
        "source_text": "src",
        "translation": translation,
        "site_id": site_id,
        "src_lang": "en",
        "tgt_lang": tgt_lang,
        "context": None,
        "timestamp": None,
        "metadata": {},
        "field_name": field_name,
    }


def _make_test_env(tmp_path, entries: dict[str, dict]):
    db_path = tmp_path / "test_l2.lmdb"
    db_path.mkdir()
    env = lmdb.open(str(db_path), map_size=10 * 1024 * 1024, max_dbs=1)
    with env.begin(write=True) as txn:
        for key, entry in entries.items():
            txn.put(key.encode("utf-8"), json.dumps(entry).encode("utf-8"))
    return env


def test_scan_l2_for_purge_finds_only_matching_scoped_entries(tmp_path):
    entries = {
        "docs.aspose.org:en:de:hash1": _entry("docs.aspose.org", "de", "Fehler.. Ende."),
        "docs.aspose.org:en:de:hash2": _entry("docs.aspose.org", "de", "alles gut. Ende."),
        "docs.aspose.org:en:fr:hash3": _entry("docs.aspose.org", "fr", "Erreur.. Fin."),  # wrong tgt_lang, out of scope
        "kb.aspose.org:en:de:hash4": _entry("kb.aspose.org", "de", "Fehler.. Ende."),  # wrong site, out of scope
    }
    env = _make_test_env(tmp_path, entries)
    predicate = build_predicate({"double_period"})

    result = scan_l2_for_purge(env, "docs.aspose.org", "de", predicate)

    assert result.scanned == 2  # only docs.aspose.org:de entries counted
    assert len(result.matched_keys) == 1
    assert result.matched_keys[0] == b"docs.aspose.org:en:de:hash1"
    env.close()


def test_delete_l2_keys_removes_exact_matches_only(tmp_path):
    entries = {
        "docs.aspose.org:en:de:hash1": _entry("docs.aspose.org", "de", "Fehler.. Ende."),
        "docs.aspose.org:en:de:hash2": _entry("docs.aspose.org", "de", "alles gut. Ende."),
    }
    env = _make_test_env(tmp_path, entries)
    predicate = build_predicate({"double_period"})
    result = scan_l2_for_purge(env, "docs.aspose.org", "de", predicate)

    n_deleted = delete_l2_keys(env, result.matched_keys)

    assert n_deleted == 1
    with env.begin() as txn:
        assert txn.get(b"docs.aspose.org:en:de:hash1") is None
        assert txn.get(b"docs.aspose.org:en:de:hash2") is not None
    env.close()


def test_delete_l2_keys_handles_scoped_keys_delete_cannot_reach(tmp_path):
    # This is the actual gap TC-P7-13 exists to close: a scoped key
    # (site_id:field_name:src_lang:tgt_lang:hash) that L2PersistentTM's own
    # delete() can never recompute, since it only ever builds the unscoped
    # shape. The raw-cursor approach here deletes by exact key bytes, so it
    # reaches scoped entries delete() cannot.
    scoped_key = "docs.aspose.org:title:en:de:hash_scoped"
    entries = {scoped_key: _entry("docs.aspose.org", "de", "Titel.. Ende.", field_name="title")}
    env = _make_test_env(tmp_path, entries)
    predicate = build_predicate({"double_period"})
    result = scan_l2_for_purge(env, "docs.aspose.org", "de", predicate)

    assert result.matched_keys == [scoped_key.encode("utf-8")]
    n_deleted = delete_l2_keys(env, result.matched_keys)
    assert n_deleted == 1
    env.close()
