from pathlib import Path

from src.tm.intent_spool import TMIntentSpool, TMIntentWriter


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
