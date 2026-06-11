"""Tests for TM improvement candidate prioritization (TC-AGENT-04)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tm.improvement_queue import (
    ImprovementCandidate,
    ImprovementQueue,
    compute_uncertainty,
)


def _make_candidate(
    retry_count: int = 0,
    quality_score: float = 0.5,
    error_count: int = 0,
    text: str = "hello",
) -> ImprovementCandidate:
    return ImprovementCandidate(
        site_id="test.site",
        src_lang="en",
        tgt_lang="de",
        text=text,
        translation="hallo",
        metadata={
            "retry_count": retry_count,
            "quality_score": quality_score,
            "error_count": error_count,
        },
    )


class TestComputeUncertainty:
    def test_uncertainty_computation_known_values(self) -> None:
        # retry=2*0.4 + (1-0.5)*0.3 + 1*0.3 = 0.8+0.15+0.3 = 1.25 -> clamped to 1.0
        c = _make_candidate(retry_count=2, quality_score=0.5, error_count=1)
        assert compute_uncertainty(c) == 1.0

    def test_high_retry_gets_higher_priority(self) -> None:
        low = _make_candidate(retry_count=0, quality_score=0.8, error_count=0)
        high = _make_candidate(retry_count=2, quality_score=0.3, error_count=1)
        assert compute_uncertainty(high) > compute_uncertainty(low)

    def test_missing_metadata_safe_default(self) -> None:
        c = ImprovementCandidate(
            site_id="test",
            src_lang="en",
            tgt_lang="de",
            text="hello",
            translation="hallo",
            metadata=None,
        )
        score = compute_uncertainty(c)
        # retry=0*0.4 + (1-0.5)*0.3 + 0*0.3 = 0.15
        assert abs(score - 0.15) < 0.001

    def test_empty_metadata_safe_default(self) -> None:
        c = ImprovementCandidate(
            site_id="test",
            src_lang="en",
            tgt_lang="de",
            text="hello",
            translation="hallo",
            metadata={},
        )
        score = compute_uncertainty(c)
        assert abs(score - 0.15) < 0.001

    def test_uncertainty_clamped_0_1(self) -> None:
        # Extreme high values
        c = _make_candidate(retry_count=10, quality_score=0.0, error_count=5)
        assert compute_uncertainty(c) == 1.0

        # All zeros
        c2 = _make_candidate(retry_count=0, quality_score=1.0, error_count=0)
        assert compute_uncertainty(c2) == 0.0

    def test_zero_uncertainty_for_perfect_candidate(self) -> None:
        c = _make_candidate(retry_count=0, quality_score=1.0, error_count=0)
        assert compute_uncertainty(c) == 0.0


class TestPopCandidatesByPriority:
    def test_priority_pop_returns_highest_first(self, tmp_path: Path) -> None:
        queue = ImprovementQueue(tmp_path)

        # Add candidates with varying uncertainty
        queue.append_candidate(
            site_id="s",
            src_lang="en",
            tgt_lang="de",
            text="low",
            translation="t",
            metadata={"retry_count": 0, "quality_score": 0.9, "error_count": 0},
        )
        queue.append_candidate(
            site_id="s",
            src_lang="en",
            tgt_lang="de",
            text="high",
            translation="t",
            metadata={"retry_count": 2, "quality_score": 0.3, "error_count": 1},
        )
        queue.append_candidate(
            site_id="s",
            src_lang="en",
            tgt_lang="de",
            text="mid",
            translation="t",
            metadata={"retry_count": 1, "quality_score": 0.5, "error_count": 0},
        )

        popped = queue.pop_candidates_by_priority(limit=3)
        assert len(popped) == 3
        # Highest uncertainty should be first
        scores = [compute_uncertainty(c) for c in popped]
        assert scores == sorted(scores, reverse=True)

    def test_priority_pop_respects_limit(self, tmp_path: Path) -> None:
        queue = ImprovementQueue(tmp_path)
        for i in range(5):
            queue.append_candidate(
                site_id="s",
                src_lang="en",
                tgt_lang="de",
                text=f"text_{i}",
                translation="t",
                metadata={"retry_count": i},
            )

        popped = queue.pop_candidates_by_priority(limit=2)
        assert len(popped) == 2
        # Remaining should still be in queue
        assert queue.count() == 3

    def test_fifo_pop_unchanged(self, tmp_path: Path) -> None:
        """Verify pop_candidates() still returns FIFO order (backward compat)."""
        queue = ImprovementQueue(tmp_path)
        texts = ["first", "second", "third"]
        for t in texts:
            queue.append_candidate(
                site_id="s",
                src_lang="en",
                tgt_lang="de",
                text=t,
                translation="t",
            )

        popped = queue.pop_candidates(limit=3)
        assert [c.text for c in popped] == texts

    def test_empty_queue_returns_empty(self, tmp_path: Path) -> None:
        queue = ImprovementQueue(tmp_path)
        assert queue.pop_candidates_by_priority(limit=10) == []
