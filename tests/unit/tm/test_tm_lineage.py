"""TC-APT-008: first-class TM lineage, by_config_fingerprint index (O(matches)), read-time denylist."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.tm import lineage as ln
from src.tm.l2_persistent import L2PersistentTM, TranslationEntry
from scripts.tm.backfill_tm_lineage_index import backfill


@pytest.fixture()
def denylist_path(tmp_path: Path, monkeypatch):
    path = tmp_path / "invalidated_lineage.json"
    monkeypatch.setenv("HT_TM_LINEAGE_DENYLIST", str(path))
    ln._default = None
    yield path
    ln._default = None


@pytest.fixture()
def tm(tmp_path: Path, denylist_path, monkeypatch):
    store = L2PersistentTM(db_path=tmp_path / "l2_lmdb", max_size_mb=16)
    monkeypatch.setattr(store, "_validate_translation_language", lambda *_a, **_k: True)
    yield store
    store.close()


def test_lineage_of_prefers_first_class_then_metadata():
    e = TranslationEntry(
        "s",
        "t",
        "site",
        "en",
        "de",
        metadata={"config_fingerprint": "fp-meta", "model": "m2m100_418m"},
    )
    assert (e.config_fingerprint, e.model_id) == (
        "fp-meta",
        "m2m100_418m",
    )  # backfilled in __post_init__
    e2 = TranslationEntry(
        "s",
        "t",
        "site",
        "en",
        "de",
        config_fingerprint="fp-first",
        metadata={"config_fingerprint": "fp-meta"},
    )
    assert ln.lineage_of(e2) == ("fp-first", None)
    assert ln.lineage_of({"model_id": "professionalize_llm"}) == (None, "professionalize_llm")
    assert ln.lineage_of({}) == (None, None)


def test_from_dict_ignores_unknown_keys_and_legacy_entries_load():
    legacy = {
        "source_text": "s",
        "translation": "t",
        "site_id": "x",
        "src_lang": "en",
        "tgt_lang": "de",
        "future_key": 1,
    }
    e = TranslationEntry.from_dict(legacy)
    assert e.config_fingerprint is None and e.model_id is None and e.field_name == ""


def test_store_indexes_lineage_and_lookup_is_by_fingerprint(tm):
    for i in range(30):
        tm.store(
            "site",
            "en",
            "de",
            f"text {i}",
            f"Text {i}",
            metadata={"config_fingerprint": "fp-A" if i % 3 else "fp-B", "model": "m2m100_418m"},
        )
    tm.store("site", "en", "de", "no lineage", "Keine", metadata={})
    assert tm.count_by_config_fingerprint("fp-A") == 20
    assert tm.count_by_config_fingerprint("fp-B") == 10
    assert tm.count_by_config_fingerprint("fp-none") == 0
    got = list(tm.iter_by_config_fingerprint("fp-B"))
    assert len(got) == 10 and all(
        e.config_fingerprint == "fp-B" and e.model_id == "m2m100_418m" for e in got
    )
    stats = tm.lineage_index_stats()
    assert stats == {"indexed_keys": 30, "distinct_fingerprints": 2}


def test_denylist_suppresses_lookup_at_read_time_and_is_reversible(tm, denylist_path):
    tm.store(
        "site",
        "en",
        "de",
        "hello",
        "hallo",
        metadata={"config_fingerprint": "fp-bad", "model": "m2m100_418m"},
    )
    tm.store("site", "en", "de", "world", "welt", metadata={"config_fingerprint": "fp-good"})
    assert tm.exact_lookup("site", "en", "de", "hello").translation == "hallo"
    dl = ln.default_denylist()
    dl.add(
        fingerprint="fp-bad",
        reason="gate-12 double-dot regex lineage (G-04)",
        taskcard="TC-APT-009",
    )
    assert tm.exact_lookup("site", "en", "de", "hello") is None  # denied, not deleted
    assert tm.denied_lookups == 1
    assert tm.exact_lookup("site", "en", "de", "world").translation == "welt"
    # the bytes are still there (reversible): clearing the file restores the entry
    denylist_path.write_text(json.dumps({"denylist": []}), encoding="utf-8")
    assert tm.exact_lookup("site", "en", "de", "hello").translation == "hallo"


def test_denylist_by_model_id_and_unreadable_file_keeps_last_view(tmp_path):
    path = tmp_path / "deny.json"
    dl = ln.LineageDenylist(path)
    assert dl.is_denied("fp", "nllb_200_1.3b") is False
    dl.add(model_id="nllb_200_1.3b", reason="permanent non-use (TC-APT-005)")
    assert dl.is_denied(None, "nllb_200_1.3b") is True and dl.is_denied("fp", None) is False
    path.write_text("{corrupt", encoding="utf-8")
    assert dl.is_denied(None, "nllb_200_1.3b") is True  # last good view retained
    with pytest.raises(ValueError):
        dl.add(reason="nothing to deny")


def test_filter_denied_for_l3_matches(denylist_path):
    dl = ln.default_denylist()
    dl.add(fingerprint="fp-x", reason="test")
    matches = [
        SimpleNamespace(metadata={"config_fingerprint": "fp-x"}),
        SimpleNamespace(metadata={"config_fingerprint": "fp-y"}),
        SimpleNamespace(metadata={}),
    ]
    kept, dropped = ln.filter_denied(matches)
    assert dropped == 1 and [m.metadata.get("config_fingerprint") for m in kept] == ["fp-y", None]


def test_backfill_promotes_metadata_lineage_and_indexes(tm):
    # write legacy-shaped entries directly (no first-class fields, no index) like the 940K store
    from src.tm.normalization import make_tm_key

    legacy = []
    for i in range(12):
        meta = (
            {"config_fingerprint": "fp-old", "campaign_id": "c1"}
            if i % 2 == 0
            else ({"model": "m2m100_418m"} if i % 3 == 0 else {})
        )
        raw = {
            "source_text": f"s{i}",
            "translation": f"t{i}",
            "site_id": "site",
            "src_lang": "en",
            "tgt_lang": "fr",
            "context": None,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "metadata": meta,
            "field_name": "",
        }
        legacy.append(
            (
                make_tm_key("site", "en", "fr", f"s{i}").encode("utf-8"),
                json.dumps(raw).encode("utf-8"),
            )
        )
    with tm._lock:
        with tm.env.begin(write=True) as txn:
            for k, v in legacy:
                txn.put(k, v)
    assert tm.lineage_index_stats()["indexed_keys"] == 0
    dry = backfill(tm, dry_run=True)
    assert (
        dry["counts"]["entries"] == 12 and dry["counts"]["to_rewrite"] == 6 + 2
    )  # fp-old x6 + model-only (i=3,9)
    assert dry["counts"]["lineage_unknown"] == 4 and tm.lineage_index_stats()["indexed_keys"] == 0
    live = backfill(tm, dry_run=False)
    assert live["counts"]["to_rewrite"] == 8
    assert tm.count_by_config_fingerprint("fp-old") == 6
    again = backfill(tm, dry_run=False)
    assert (
        again["counts"]["already_first_class"] == 8 and again["counts"].get("to_rewrite", 0) == 0
    )  # idempotent
    e = tm.exact_lookup("site", "en", "fr", "s0")
    assert (
        e.config_fingerprint == "fp-old" and e.metadata["config_fingerprint"] == "fp-old"
    )  # dual-written
