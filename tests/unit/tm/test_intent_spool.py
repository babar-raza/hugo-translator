from pathlib import Path

from src.tm.intent_spool import TMIntentSpool, TMIntentWriter
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import TranslationEntry
from src.tm.translation_memory import TranslationMemory


def _payload(text="source"):
    return {
        "site_id": "docs.aspose.org",
        "src_lang": "en",
        "tgt_lang": "de",
        "text": text,
        "translation": "ziel",
    }


def test_intent_is_idempotent_and_written_once(tmp_path: Path):
    spool = TMIntentSpool(tmp_path / "intents.sqlite3")
    assert spool.enqueue(_payload()) == spool.enqueue(_payload())

    class L2:
        def __init__(self):
            self.calls = []

        def store(self, **kwargs):
            self.calls.append(kwargs)
            return True

    l2 = L2()
    result = TMIntentWriter(spool, l2).run_once(owner="writer")
    assert result["applied"] == 1
    assert result["APPLIED"] == 1
    assert len(l2.calls) == 1


def test_expired_claim_is_reclaimed_without_lost_intent(tmp_path: Path):
    spool = TMIntentSpool(tmp_path / "intents.sqlite3")
    spool.enqueue(_payload())
    first = spool.claim("crashed", lease_seconds=0.01)
    assert len(first) == 1
    import time

    time.sleep(0.02)
    second = spool.claim("recovery")
    assert [item["intent_id"] for item in second] == [item["intent_id"] for item in first]


def test_batch_store_routes_to_spool_without_reader_side_l2_or_l3_mutation(tmp_path: Path):
    class L2:
        def batch_store(self, entries):
            raise AssertionError("reader-side batch L2 mutation")

    class L3:
        def batch_add(self, entries):
            raise AssertionError("reader-side batch L3 mutation")

    spool = TMIntentSpool(tmp_path / "intents.sqlite3")
    tm = TranslationMemory(L1Cache(), L2(), L3(), intent_spool=spool)
    count = tm.batch_store([
        TranslationEntry("one", "eins", "docs.aspose.org", "en", "de"),
        TranslationEntry("two", "zwei", "docs.aspose.org", "en", "de"),
    ])
    assert count == 2
    assert spool.stats()["PENDING"] == 2
