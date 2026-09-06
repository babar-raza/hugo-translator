"""TC-APT-039: production-review qualification ledger.

Acceptance (plan §11): "a review reject on an m2m100 cell is automatically
retried on the LLM (and vice versa) before quarantine; the routing table and
per-cell ledger are populated from live verdicts; a test proves the auto-flip."
"""

import json
import os
import time

import pytest

from src.workers.qualification_ledger import (
    AUTO_FLIP_THRESHOLD,
    AUTO_FLIP_WINDOW,
    STRATIFIED_SAMPLING_THRESHOLD,
    _lock_path,
    consecutive_clean_count,
    cross_model_retry_target,
    models_tried,
    qualifies_for_stratified_sampling,
    record_verdict,
    rolling_reject_rate,
    should_auto_flip_primary,
)

SITE = "blog.aspose.org"
PATH = "content/blog.aspose.org/words/net/words-document-net/index.md"
LANG = "fa"
CLASS = "unclassified"


def _record(tmp_path, model, verdict, source_path=PATH, target_lang=LANG):
    return record_verdict(
        site_id=SITE,
        source_path=source_path,
        target_lang=target_lang,
        content_class=CLASS,
        model=model,
        verdict=verdict,
        ledger_path=tmp_path / "cells.jsonl",
    )


class TestRecordVerdict:
    def test_rejects_an_invalid_verdict(self, tmp_path):
        with pytest.raises(ValueError):
            _record(tmp_path, "m2m100_418m", "MAYBE")

    def test_never_stores_candidate_text_fields(self, tmp_path):
        row = _record(tmp_path, "m2m100_418m", "REJECT")
        assert "translated_text" not in row
        assert "candidate" not in row
        assert set(row.keys()) == {
            "site_id",
            "source_path",
            "target_lang",
            "content_class",
            "model",
            "verdict",
            "rubric_rules",
            "heal_retrigger",
            "recorded_at",
        }


class TestCrossModelRetry:
    def test_untried_other_model_is_offered_as_the_retry_target(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        record_verdict(
            site_id=SITE, source_path=PATH, target_lang=LANG, content_class=CLASS,
            model="m2m100_418m", verdict="REJECT", ledger_path=ledger,
        )
        target = cross_model_retry_target(
            SITE, PATH, LANG, rejected_model="m2m100_418m",
            other_model="professionalize_llm", ledger_path=ledger,
        )
        assert target == "professionalize_llm"

    def test_both_models_tried_means_quarantine_not_a_third_retry(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        record_verdict(
            site_id=SITE, source_path=PATH, target_lang=LANG, content_class=CLASS,
            model="m2m100_418m", verdict="REJECT", ledger_path=ledger,
        )
        record_verdict(
            site_id=SITE, source_path=PATH, target_lang=LANG, content_class=CLASS,
            model="professionalize_llm", verdict="REJECT", ledger_path=ledger,
        )
        target = cross_model_retry_target(
            SITE, PATH, LANG, rejected_model="professionalize_llm",
            other_model="m2m100_418m", ledger_path=ledger,
        )
        assert target is None

    def test_an_unseen_cell_has_no_models_tried(self, tmp_path):
        assert models_tried(SITE, PATH, LANG, ledger_path=tmp_path / "cells.jsonl") == set()

    def test_a_different_source_path_does_not_count_as_tried(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        record_verdict(
            site_id=SITE, source_path="content/blog.aspose.org/other/index.md",
            target_lang=LANG, content_class=CLASS, model="m2m100_418m",
            verdict="REJECT", ledger_path=ledger,
        )
        target = cross_model_retry_target(
            SITE, PATH, LANG, rejected_model="m2m100_418m",
            other_model="professionalize_llm", ledger_path=ledger,
        )
        assert target == "professionalize_llm"


class TestAutoFlip:
    def test_does_not_flip_before_a_full_window_of_verdicts(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        for _ in range(AUTO_FLIP_WINDOW - 1):
            record_verdict(
                site_id=SITE, source_path=PATH, target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict="REJECT", ledger_path=ledger,
            )
        assert not should_auto_flip_primary(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger)

    def test_flips_once_the_window_exceeds_threshold_reject_rate(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        # 5 REJECT out of 20 = exactly 25% > 20% threshold.
        for i in range(AUTO_FLIP_WINDOW):
            verdict = "REJECT" if i < 5 else "APPROVE"
            record_verdict(
                site_id=SITE, source_path=f"page{i}.md", target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict=verdict, ledger_path=ledger,
            )
        assert rolling_reject_rate(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger) == 0.25
        assert should_auto_flip_primary(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger)

    def test_does_not_flip_at_exactly_the_threshold(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        # 4 REJECT out of 20 = exactly 20%, the plan says "exceeds 20%", not >=.
        for i in range(AUTO_FLIP_WINDOW):
            verdict = "REJECT" if i < 4 else "APPROVE"
            record_verdict(
                site_id=SITE, source_path=f"page{i}.md", target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict=verdict, ledger_path=ledger,
            )
        assert not should_auto_flip_primary(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger)

    def test_only_the_most_recent_window_counts(self, tmp_path):
        """An old bad patch must not haunt the cell forever once enough clean cells follow."""
        ledger = tmp_path / "cells.jsonl"
        for i in range(10):
            record_verdict(
                site_id=SITE, source_path=f"old{i}.md", target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict="REJECT", ledger_path=ledger,
            )
        for i in range(AUTO_FLIP_WINDOW):
            record_verdict(
                site_id=SITE, source_path=f"new{i}.md", target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict="APPROVE", ledger_path=ledger,
            )
        assert rolling_reject_rate(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger) == 0.0
        assert not should_auto_flip_primary(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger)

    def test_no_recorded_verdicts_returns_none_not_a_crash(self, tmp_path):
        assert rolling_reject_rate(SITE, LANG, CLASS, "m2m100_418m", ledger_path=tmp_path / "cells.jsonl") is None

    def test_a_different_model_on_the_same_cell_has_an_independent_rate(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        for i in range(AUTO_FLIP_WINDOW):
            record_verdict(
                site_id=SITE, source_path=f"p{i}.md", target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict="REJECT", ledger_path=ledger,
            )
        assert rolling_reject_rate(SITE, LANG, CLASS, "professionalize_llm", ledger_path=ledger) is None


class TestStratifiedSamplingPromotion:
    def test_not_qualified_below_threshold(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        for i in range(STRATIFIED_SAMPLING_THRESHOLD - 1):
            record_verdict(
                site_id=SITE, source_path=f"p{i}.md", target_lang=LANG, content_class=CLASS,
                model="professionalize_llm", verdict="APPROVE", ledger_path=ledger,
            )
        assert consecutive_clean_count(SITE, LANG, CLASS, "professionalize_llm", ledger_path=ledger) == (
            STRATIFIED_SAMPLING_THRESHOLD - 1
        )
        assert not qualifies_for_stratified_sampling(
            SITE, LANG, CLASS, "professionalize_llm", ledger_path=ledger
        )

    def test_qualifies_at_threshold_consecutive_clean_cells(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        for i in range(STRATIFIED_SAMPLING_THRESHOLD):
            record_verdict(
                site_id=SITE, source_path=f"p{i}.md", target_lang=LANG, content_class=CLASS,
                model="professionalize_llm", verdict="APPROVE", ledger_path=ledger,
            )
        assert qualifies_for_stratified_sampling(
            SITE, LANG, CLASS, "professionalize_llm", ledger_path=ledger
        )

    def test_a_single_defect_reverts_the_streak_to_zero(self, tmp_path):
        """project/loop-prompt.md §4.2: 'instant 100% reversion on any defect'."""
        ledger = tmp_path / "cells.jsonl"
        for i in range(STRATIFIED_SAMPLING_THRESHOLD):
            record_verdict(
                site_id=SITE, source_path=f"p{i}.md", target_lang=LANG, content_class=CLASS,
                model="professionalize_llm", verdict="APPROVE", ledger_path=ledger,
            )
        record_verdict(
            site_id=SITE, source_path="pX.md", target_lang=LANG, content_class=CLASS,
            model="professionalize_llm", verdict="REJECT", ledger_path=ledger,
        )
        assert consecutive_clean_count(SITE, LANG, CLASS, "professionalize_llm", ledger_path=ledger) == 0
        assert not qualifies_for_stratified_sampling(
            SITE, LANG, CLASS, "professionalize_llm", ledger_path=ledger
        )

    def test_a_different_content_class_is_tracked_independently(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        for i in range(STRATIFIED_SAMPLING_THRESHOLD):
            record_verdict(
                site_id=SITE, source_path=f"p{i}.md", target_lang=LANG, content_class="blog_post",
                model="professionalize_llm", verdict="APPROVE", ledger_path=ledger,
            )
        assert qualifies_for_stratified_sampling(
            SITE, LANG, "blog_post", "professionalize_llm", ledger_path=ledger
        )
        assert not qualifies_for_stratified_sampling(
            SITE, LANG, "docs_page", "professionalize_llm", ledger_path=ledger
        )


class TestHealRetriggerExcludedFromLadderMath:
    """TC-APT-092: a heal-queue retrigger measures "did the targeted fix
    work," not ordinary cohort throughput -- mixing the two would let a
    burst of heal retries manufacture a false PROVEN streak or sink a
    cohort's rate on cells that were never part of its normal flow."""

    def test_heal_retrigger_reject_does_not_count_toward_reject_rate(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        for i in range(AUTO_FLIP_WINDOW):
            record_verdict(
                site_id=SITE, source_path=f"p{i}.md", target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict="APPROVE", ledger_path=ledger,
            )
        # A flood of heal-retrigger REJECTs must not tip the rate over threshold.
        for i in range(10):
            record_verdict(
                site_id=SITE, source_path=f"heal{i}.md", target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict="REJECT", heal_retrigger=True, ledger_path=ledger,
            )
        assert rolling_reject_rate(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger) == 0.0
        assert not should_auto_flip_primary(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger)

    def test_heal_retrigger_approve_does_not_inflate_consecutive_clean_count(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        record_verdict(
            site_id=SITE, source_path="p0.md", target_lang=LANG, content_class=CLASS,
            model="m2m100_418m", verdict="REJECT", ledger_path=ledger,
        )
        for i in range(STRATIFIED_SAMPLING_THRESHOLD):
            record_verdict(
                site_id=SITE, source_path=f"heal{i}.md", target_lang=LANG, content_class=CLASS,
                model="m2m100_418m", verdict="APPROVE", heal_retrigger=True, ledger_path=ledger,
            )
        assert consecutive_clean_count(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger) == 0
        assert not qualifies_for_stratified_sampling(
            SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger
        )


class TestIndexCache:
    """TC-APT-092: cells.jsonl is re-read on every query in the naive
    implementation -- quadratic after backfill. The cache must stay correct
    (never serve stale data) while avoiding a full reparse when nothing
    changed."""

    def test_a_query_after_an_external_append_sees_the_new_row(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        record_verdict(
            site_id=SITE, source_path=PATH, target_lang=LANG, content_class=CLASS,
            model="m2m100_418m", verdict="APPROVE", ledger_path=ledger,
        )
        assert consecutive_clean_count(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger) == 1

        # Simulate a DIFFERENT process appending directly (bypassing this
        # process's record_verdict, so its own cache-invalidation-on-write
        # cannot be what makes this pass).
        row = {
            "site_id": SITE, "source_path": PATH, "target_lang": LANG,
            "content_class": CLASS, "model": "m2m100_418m", "verdict": "APPROVE",
            "rubric_rules": [], "heal_retrigger": False, "recorded_at": "2026-01-01T00:00:00+00:00",
        }
        # Ensure a distinct mtime on filesystems with coarse timestamp resolution.
        time.sleep(0.01)
        with ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        os.utime(ledger, None)

        assert consecutive_clean_count(SITE, LANG, CLASS, "m2m100_418m", ledger_path=ledger) == 2

    def test_lock_file_uses_the_established_sibling_suffix_convention(self, tmp_path):
        ledger = tmp_path / "cells.jsonl"
        assert _lock_path(ledger) == tmp_path / "cells.jsonl.lock"
