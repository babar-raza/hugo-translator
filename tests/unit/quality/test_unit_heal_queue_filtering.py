"""TC-HLN-006: unit_heal.py's queue entries must not be silently skipped
when --issue-types is used with the documented _detector vocabulary.

Root cause: process_queue() pre-filtered queue entries by comparing
entry["issues"][*]["type"] (merge_audit_queues.py's plain-string vocabulary,
e.g. "encoding_corruption") directly against --issue-types values (always
documented and used with UnitQualityScorer's _detector-suffixed vocabulary,
e.g. "mojibake_detector"). The two vocabularies never overlap, so this
pre-filter silently matched zero files whenever --issue-types was passed --
exactly the module's own documented usage example. The real, correct filter
(scorer.score() -> issue_type in issue_types) already existed downstream and
uses the right vocabulary; the broken pre-filter has been removed.
"""

from pathlib import Path

from scripts.quality.unit_heal import process_queue

_EN_MD = """---
title: "DiffUtils"
description: "DiffUtils class"
---

Some prose about diffing utilities.
"""

# Body paragraph contains a mojibake em-dash artifact ("â€"") that
# UnitQualityScorer's mojibake_detector matches on sight.
_TR_MD = """---
title: "DiffUtils"
description: "DiffUtils class"
---

Deyalar hakkında â€" bazı metin burada.
"""


def _write_pair(tmp_path: Path):
    en_path = tmp_path / "en.md"
    tr_path = tmp_path / "tr.md"
    en_path.write_text(_EN_MD, encoding="utf-8")
    tr_path.write_text(_TR_MD, encoding="utf-8")
    return en_path, tr_path


def _write_queue(tmp_path: Path, en_path: Path, tr_path: Path) -> Path:
    import json

    queue_path = tmp_path / "queue.jsonl"
    # Deliberately uses merge_audit_queues.py's plain-string vocabulary,
    # matching real data/audit/master_heal_queue.jsonl entries -- NOT the
    # _detector-suffixed vocabulary the CLI's --issue-types expects.
    entry = {
        "file_path": str(tr_path),
        "en_path": str(en_path),
        "locale": "tr",
        "site_id": "reference.aspose.org",
        "issues": [{"type": "encoding_corruption", "unit_indices": [], "priority": 1}],
        "max_priority": 1,
    }
    queue_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return queue_path


class TestQueueEntryIsNotSkippedByVocabularyMismatch:
    def test_documented_issue_types_usage_actually_processes_the_file(self, tmp_path):
        """The exact scenario from unit_heal.py's own module docstring:
        --issue-types mojibake_detector against a real master_heal_queue.jsonl-
        shaped entry. Before the fix, this always resulted in 0 processed
        files regardless of real content -- pure vocabulary mismatch."""
        en_path, tr_path = _write_pair(tmp_path)
        queue_path = _write_queue(tmp_path, en_path, tr_path)
        done_path = tmp_path / "done.jsonl"

        stats = process_queue(
            queue_path=queue_path,
            sites=["reference.aspose.org"],
            locales=None,
            issue_types=["mojibake_detector"],
            max_files=10,
            model_override=None,
            dry_run=True,
            done_path=done_path,
        )

        assert stats["processed"] == 1, (
            "File must be processed -- it was previously skipped at the "
            "queue-entry pre-filter due to comparing incompatible issue-type "
            "vocabularies (plain 'encoding_corruption' vs. filter value "
            "'mojibake_detector')."
        )
        assert stats["skipped_clean"] == 0

    def test_site_filter_still_works(self, tmp_path):
        """Site/locale filtering (same vocabulary on both sides) must still
        correctly exclude non-matching entries -- only the issue-type
        pre-filter was removed, not filtering in general."""
        en_path, tr_path = _write_pair(tmp_path)
        queue_path = _write_queue(tmp_path, en_path, tr_path)
        done_path = tmp_path / "done.jsonl"

        stats = process_queue(
            queue_path=queue_path,
            sites=["docs.aspose.org"],  # entry's site_id is reference.aspose.org
            locales=None,
            issue_types=None,
            max_files=10,
            model_override=None,
            dry_run=True,
            done_path=done_path,
        )

        assert stats["processed"] == 0

    def test_no_issue_types_filter_still_processes_everything(self, tmp_path):
        """Baseline: omitting --issue-types entirely (the other common usage)
        must continue to work exactly as before."""
        en_path, tr_path = _write_pair(tmp_path)
        queue_path = _write_queue(tmp_path, en_path, tr_path)
        done_path = tmp_path / "done.jsonl"

        stats = process_queue(
            queue_path=queue_path,
            sites=["reference.aspose.org"],
            locales=None,
            issue_types=None,
            max_files=10,
            model_override=None,
            dry_run=True,
            done_path=done_path,
        )

        assert stats["processed"] == 1
