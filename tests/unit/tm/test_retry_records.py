import pytest

from src.tm.retry_records import RejectedTranslationTask, TMWriteIntentRecord, adapt_legacy_record


def _task():
    return {
        "campaign_id": "c",
        "site_id": "docs.aspose.org",
        "source_path": "content/en/a.md",
        "output_path": "content/de/a.md",
        "source_sha256": "a" * 64,
        "target_lang": "de",
        "failure_category": "TC-SAS-01",
        "failure_fingerprint": "text:abc",
        "retry_budget": 2,
        "model_target": "professionalize_llm",
        "future_field": "kept",
    }


def test_task_is_strict_and_preserves_additive_fields():
    task = RejectedTranslationTask.from_mapping(_task())
    assert task.extensions == {"future_field": "kept"}
    with pytest.raises(ValueError, match="source_sha256"):
        RejectedTranslationTask.from_mapping({**_task(), "source_sha256": "wrong"})


def test_intent_identity_is_deterministic():
    first = TMWriteIntentRecord.from_mapping(
        {"site_id": "s", "src_lang": "en", "tgt_lang": "de", "text": "a", "translation": "b"}
    )
    assert (
        first.intent_id()
        == TMWriteIntentRecord.from_mapping(
            {"site_id": "s", "src_lang": "en", "tgt_lang": "de", "text": "a", "translation": "b"}
        ).intent_id()
    )


@pytest.mark.parametrize("kind", ["heal", "retranslate", "improvement"])
def test_legacy_rows_are_preserved_when_identity_is_incomplete(kind):
    result = adapt_legacy_record(kind, {"output_path": "x.md", "tgt_lang": "de", "unknown": 7})
    assert result["disposition"] == "UNRESOLVED_LEGACY"
    assert result["raw"]["unknown"] == 7
