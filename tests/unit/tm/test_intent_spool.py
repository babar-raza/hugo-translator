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


def test_reconcile_requeues_expired_claim_without_touching_applied_intent(tmp_path: Path):
    spool = TMIntentSpool(tmp_path / "intents.sqlite3")
    first, second = spool.enqueue(_payload("one")), spool.enqueue(_payload("two"))
    claimed = spool.claim("crashed", limit=2, lease_seconds=1)
    spool.complete(next(item["intent_id"] for item in claimed if item["intent_id"] == first), "crashed")
    assert spool.requeue_expired_claims(now=10**11) == 1
    assert spool.stats() == {"PENDING": 1, "CLAIMED": 0, "APPLIED": 1}
    assert second in [item["intent_id"] for item in spool.claim("recovery")]


def test_reconcile_l3_repairs_applied_intent_missing_from_l3_without_duplicating_present_one(
    tmp_path: Path,
):
    """A writer crash between spool.complete() and the batch's trailing
    save_index() leaves the spool believing an L3 write landed when it never
    reached disk. reconcile_l3() must restore exactly the missing entry and
    leave an already-present one untouched (no duplicate vector)."""

    class L2:
        def store(self, **kwargs):
            return True

    class FakeL3:
        def __init__(self, known):
            self.known = set(known)
            self.add_calls: list[str] = []
            self.saved = False

        def update_entry(self, entry_id, new_translation, new_metadata=None):
            return entry_id in self.known

        def add_entry(self, entry_id, **kwargs):
            self.add_calls.append(entry_id)
            self.known.add(entry_id)

        def save_index(self):
            self.saved = True

    spool = TMIntentSpool(tmp_path / "intents.sqlite3")
    missing_id = spool.enqueue(_payload("missing"))
    present_id = spool.enqueue(_payload("present"))
    for intent in spool.claim("crashed", limit=2):
        spool.complete(intent["intent_id"], "crashed")
    assert spool.stats() == {"PENDING": 0, "CLAIMED": 0, "APPLIED": 2}

    present_entry_id = TMIntentWriter._l3_entry_id(_payload("present"))
    missing_entry_id = TMIntentWriter._l3_entry_id(_payload("missing"))
    l3 = FakeL3(known={present_entry_id})
    writer = TMIntentWriter(spool, L2(), l3)

    result = writer.reconcile_l3()
    assert result == {"checked": 2, "repaired": 1}
    assert l3.add_calls == [missing_entry_id]
    assert l3.saved is True

    # Re-running is a safe no-op: nothing left missing, nothing re-added.
    l3.saved = False
    assert writer.reconcile_l3() == {"checked": 2, "repaired": 0}
    assert l3.add_calls == [missing_entry_id]
    assert l3.saved is False
    assert spool.stats() == {"PENDING": 0, "CLAIMED": 0, "APPLIED": 2}  # both remain APPLIED


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
