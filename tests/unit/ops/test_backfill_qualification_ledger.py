"""TC-APT-092: backfill_qualification_ledger.py must exclude gate-only
failures, correctly pair review-reject tickets against the specific
acceptance attempt they followed (not just "any" acceptance of that cell),
and tag heal-campaign-derived rows so cohort ladder math can exclude them.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ops.backfill_qualification_ledger import build_verdict_rows, classify_content

SOURCE = "content/blog.aspose.org/words/net/words-document-net/index.md"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _acceptance(source_path, target_lang, accepted_at, model="professionalize_llm"):
    return {
        "source_path": source_path,
        "target_lang": target_lang,
        "accepted_at": accepted_at,
        "model_fingerprint": model,
        "site_id": "blog.aspose.org",
    }


def _review_reject_ticket(source_path, target_lang, opened_at, note="human-rubric REJECT; rule RB-004"):
    return {
        "tier": "review_reject",
        "source_path": source_path,
        "target_lang": target_lang,
        "opened_at": opened_at,
        "note": note,
    }


class TestGateFailuresNeverEnterTheLedger:
    def test_failure_metadata_is_never_read_at_all(self, tmp_path):
        """The backfill only globs acceptance_receipts.jsonl -- a
        failure_metadata.jsonl full of gate names sitting right next to it
        must have zero effect on the result."""
        campaigns = tmp_path / "campaigns"
        _write_jsonl(
            campaigns / "gate5-x" / "acceptance_receipts.jsonl",
            [_acceptance(SOURCE, "de", "2026-09-01T00:00:00+00:00")],
        )
        _write_jsonl(
            campaigns / "gate5-x" / "failure_metadata.jsonl",
            [{"source_path": SOURCE, "target_lang": "de", "gate": "TC-SAS-01", "failed_at": "2026-09-01T00:00:01+00:00"}],
        )
        heal_queue = tmp_path / "heal_queue.jsonl"
        heal_queue.write_text("", encoding="utf-8")

        rows = build_verdict_rows(campaigns, heal_queue)
        assert len(rows) == 1
        assert rows[0]["verdict"] == "APPROVE"

    def test_auto_prefixed_heal_tickets_do_not_flip_the_verdict(self, tmp_path):
        """An auto:* heal_queue ticket (confirmed 2026-09-06: always a raw
        gate/validator name copied from failure_metadata.jsonl, never a
        review verdict) must not be treated as a review-reject."""
        campaigns = tmp_path / "campaigns"
        _write_jsonl(
            campaigns / "gate5-x" / "acceptance_receipts.jsonl",
            [_acceptance(SOURCE, "de", "2026-09-01T00:00:00+00:00")],
        )
        heal_queue = tmp_path / "heal_queue.jsonl"
        _write_jsonl(
            heal_queue,
            [
                {
                    "tier": None,
                    "root_cause_class": "auto:LanguageConsistencyValidator",
                    "source_path": SOURCE,
                    "target_lang": "de",
                    "opened_at": "2026-09-01T00:00:05+00:00",
                }
            ],
        )
        rows = build_verdict_rows(campaigns, heal_queue)
        assert rows[0]["verdict"] == "APPROVE"


class TestReviewRejectPairing:
    def test_a_review_reject_flips_the_matching_acceptance_to_reject(self, tmp_path):
        campaigns = tmp_path / "campaigns"
        _write_jsonl(
            campaigns / "gate5-x" / "acceptance_receipts.jsonl",
            [_acceptance(SOURCE, "ar", "2026-09-05T14:00:00+00:00")],
        )
        heal_queue = tmp_path / "heal_queue.jsonl"
        _write_jsonl(
            heal_queue,
            [_review_reject_ticket(SOURCE, "ar", "2026-09-05T14:09:54+00:00")],
        )
        rows = build_verdict_rows(campaigns, heal_queue)
        assert len(rows) == 1
        assert rows[0]["verdict"] == "REJECT"
        assert rows[0]["rubric_rules"] == ("RB-004",)

    def test_multiple_retry_cycles_pair_in_chronological_order_not_any_match(self, tmp_path):
        """words-document-net/fa was rejected, retried, accepted, rejected
        again in real data. The FIRST acceptance must pair with the FIRST
        reject only -- a later successful retry must not be silently
        swallowed by an earlier reject, and vice versa."""
        campaigns = tmp_path / "campaigns"
        _write_jsonl(
            campaigns / "gate5-a" / "acceptance_receipts.jsonl",
            [_acceptance(SOURCE, "fa", "2026-09-05T10:00:00+00:00")],
        )
        _write_jsonl(
            campaigns / "gate5-b" / "acceptance_receipts.jsonl",
            [_acceptance(SOURCE, "fa", "2026-09-05T18:00:00+00:00")],
        )
        heal_queue = tmp_path / "heal_queue.jsonl"
        _write_jsonl(
            heal_queue,
            [_review_reject_ticket(SOURCE, "fa", "2026-09-05T14:09:54+00:00")],
        )
        rows = build_verdict_rows(campaigns, heal_queue)
        rows.sort(key=lambda r: r["recorded_at"])
        assert len(rows) == 2
        assert rows[0]["verdict"] == "REJECT"  # the 10:00 attempt, rejected at 14:09
        assert rows[1]["verdict"] == "APPROVE"  # the 18:00 retry, never rejected

    def test_a_ticket_opened_before_any_acceptance_is_not_paired_backwards(self, tmp_path):
        campaigns = tmp_path / "campaigns"
        _write_jsonl(
            campaigns / "gate5-x" / "acceptance_receipts.jsonl",
            [_acceptance(SOURCE, "de", "2026-09-05T18:00:00+00:00")],
        )
        heal_queue = tmp_path / "heal_queue.jsonl"
        _write_jsonl(
            heal_queue,
            [_review_reject_ticket(SOURCE, "de", "2026-09-05T10:00:00+00:00")],
        )
        rows = build_verdict_rows(campaigns, heal_queue)
        assert rows[0]["verdict"] == "APPROVE"

    def test_different_cells_never_cross_pair(self, tmp_path):
        campaigns = tmp_path / "campaigns"
        other_source = "content/blog.aspose.org/cells/go/introducing-cells-foss-go/index.md"
        _write_jsonl(
            campaigns / "gate5-x" / "acceptance_receipts.jsonl",
            [
                _acceptance(SOURCE, "de", "2026-09-05T10:00:00+00:00"),
                _acceptance(other_source, "de", "2026-09-05T10:00:00+00:00"),
            ],
        )
        heal_queue = tmp_path / "heal_queue.jsonl"
        _write_jsonl(
            heal_queue,
            [_review_reject_ticket(SOURCE, "de", "2026-09-05T11:00:00+00:00")],
        )
        rows = build_verdict_rows(campaigns, heal_queue)
        by_path = {r["source_path"]: r["verdict"] for r in rows}
        assert by_path[SOURCE] == "REJECT"
        assert by_path[other_source] == "APPROVE"


class TestHealRetriggerTagging:
    def test_a_heal_prefixed_campaign_dir_is_tagged_as_a_retrigger(self, tmp_path):
        campaigns = tmp_path / "campaigns"
        _write_jsonl(
            campaigns / "heal-cells-go-w2" / "acceptance_receipts.jsonl",
            [_acceptance(SOURCE, "de", "2026-09-05T10:00:00+00:00")],
        )
        heal_queue = tmp_path / "heal_queue.jsonl"
        heal_queue.write_text("", encoding="utf-8")
        rows = build_verdict_rows(campaigns, heal_queue)
        assert rows[0]["heal_retrigger"] is True

    def test_an_ordinary_gate5_campaign_dir_is_not_a_retrigger(self, tmp_path):
        campaigns = tmp_path / "campaigns"
        _write_jsonl(
            campaigns / "gate5-cells-go" / "acceptance_receipts.jsonl",
            [_acceptance(SOURCE, "de", "2026-09-05T10:00:00+00:00")],
        )
        heal_queue = tmp_path / "heal_queue.jsonl"
        heal_queue.write_text("", encoding="utf-8")
        rows = build_verdict_rows(campaigns, heal_queue)
        assert rows[0]["heal_retrigger"] is False


class TestContentClassification:
    def test_reference_site_is_the_templated_api_class(self):
        assert (
            classify_content("content/reference.aspose.org/cells/net/class.html.md", "reference.aspose.org")
            == "reference_api_page"
        )

    def test_ordinary_blog_leaf_page_is_content_page(self):
        assert classify_content(SOURCE, "blog.aspose.org") == "content_page"
