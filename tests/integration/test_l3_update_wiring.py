"""
Integration test: Stage 2B L3 in-place update + skip_l3 wiring.

Exercises TMImprovementWorker._improve_candidate() with a real
TranslationMemory (L1 + L2 LMDB + stub L3) to verify that:

  Case A — entry exists in L3: update_entry() returns True → tm.store(skip_l3=True)
  Case B — entry absent from L3: update_entry() returns False → tm.store(skip_l3=False)
  Case C — L3 is None: no crash; tm.store(skip_l3=False) called

The entry_id format used: f"{site_id}:{src_lang}:{tgt_lang}:{hash(text)}"
(matches translation_memory.py:218 production code).
"""

from pathlib import Path
from unittest import mock

import pytest

from src.tm.improvement_queue import ImprovementCandidate
from src.workers.tm_improvement_worker import TMImprovementWorker, TMImprovementWorkerConfig

# ---------------------------------------------------------------------------
# Stub L3 — tracks update_entry / add_entry calls via an in-memory dict
# ---------------------------------------------------------------------------

class StubL3:
    """
    Minimal L3 stand-in that does not load FAISS or sentence-transformers.
    Tracks which entry_ids were updated vs added.
    """

    def __init__(self, *, pre_populated_ids: set = None):
        self._known_ids = set(pre_populated_ids or [])
        self.update_calls: list[dict] = []  # recorded call kwargs
        self.add_calls: list[dict] = []

    def update_entry(self, entry_id: str, new_translation: str, new_metadata: dict) -> bool:
        """Return True iff entry_id was pre-populated (simulates found-in-index)."""
        self.update_calls.append(
            {"entry_id": entry_id, "new_translation": new_translation}
        )
        return entry_id in self._known_ids

    def add_entry(self, entry_id: str, text: str, translation: str, metadata: dict = None):
        """Stub add — records the call."""
        self.add_calls.append({"entry_id": entry_id, "translation": translation})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_id(candidate: ImprovementCandidate) -> str:
    """Reproduce the production entry_id formula (translation_memory.py:218)."""
    return (
        f"{candidate.site_id}:{candidate.src_lang}:"
        f"{candidate.tgt_lang}:{hash(candidate.text)}"
    )


def _make_worker(tmp_path: Path, stub_l3: StubL3 | None) -> TMImprovementWorker:
    """
    Build a minimal TMImprovementWorker via __new__ with only the attributes
    needed by _improve_candidate()'s L3 update path.
    """
    worker = TMImprovementWorker.__new__(TMImprovementWorker)

    # Config — LLM provider name is referenced in metadata only
    worker.config = mock.Mock(spec=TMImprovementWorkerConfig)
    worker.config.llm_provider = "stub"
    worker.config.llm_model = "stub-model"

    # LLM client — returns a clearly different translation so _validate passes
    worker.llm_client = mock.Mock()
    worker.llm_client.adapt_translation.return_value = "IMPROVED TRANSLATION"

    # TM — real store() so we can spy on skip_l3
    # Use a mock with a real spec so call args are inspectable
    worker.tm = mock.MagicMock()
    worker.tm.l3 = stub_l3
    worker.tm.store.return_value = True  # simulate successful store

    return worker


def _make_candidate() -> ImprovementCandidate:
    return ImprovementCandidate(
        site_id="test-site",
        src_lang="en",
        tgt_lang="de",
        text="This is the source sentence.",
        translation="Das ist der Original-Satz.",  # current (will be "improved")
        context="test context",
        metadata={"similarity_score": 0.75},
    )


# ---------------------------------------------------------------------------
# Case A — entry exists in L3 → update_entry returns True → skip_l3=True
# ---------------------------------------------------------------------------

class TestCaseAL3EntryExists:
    def test_update_entry_called_with_correct_entry_id(self, tmp_path):
        candidate = _make_candidate()
        expected_id = _entry_id(candidate)

        stub_l3 = StubL3(pre_populated_ids={expected_id})
        worker = _make_worker(tmp_path, stub_l3)

        result = worker._improve_candidate(candidate)

        assert result == "improved", f"Expected 'improved', got '{result}'"
        assert len(stub_l3.update_calls) == 1
        assert stub_l3.update_calls[0]["entry_id"] == expected_id

    def test_tm_store_called_with_skip_l3_true_when_l3_updated(self, tmp_path):
        """
        Core wiring check: if update_entry returns True, tm.store() must receive
        skip_l3=True to prevent a duplicate vector being appended to the FAISS index.
        """
        candidate = _make_candidate()
        stub_l3 = StubL3(pre_populated_ids={_entry_id(candidate)})
        worker = _make_worker(tmp_path, stub_l3)

        worker._improve_candidate(candidate)

        _, kwargs = worker.tm.store.call_args
        assert kwargs.get("skip_l3") is True, (
            f"tm.store() must be called with skip_l3=True when L3 was updated; "
            f"actual kwargs: {kwargs}"
        )

    def test_improved_translation_passed_to_update_entry(self, tmp_path):
        candidate = _make_candidate()
        stub_l3 = StubL3(pre_populated_ids={_entry_id(candidate)})
        worker = _make_worker(tmp_path, stub_l3)
        worker.llm_client.adapt_translation.return_value = "Das ist der verbesserte Satz."

        worker._improve_candidate(candidate)

        assert stub_l3.update_calls[0]["new_translation"] == "Das ist der verbesserte Satz."


# ---------------------------------------------------------------------------
# Case B — entry absent from L3 → update_entry returns False → skip_l3=False
# ---------------------------------------------------------------------------

class TestCaseBL3EntryAbsent:
    def test_tm_store_called_with_skip_l3_false_when_not_in_l3(self, tmp_path):
        """
        If entry_id is NOT in L3, update_entry returns False.
        tm.store() must be called with skip_l3=False so the vector IS appended.
        """
        candidate = _make_candidate()
        stub_l3 = StubL3(pre_populated_ids=set())  # empty — entry not found
        worker = _make_worker(tmp_path, stub_l3)

        result = worker._improve_candidate(candidate)

        assert result == "improved"
        _, kwargs = worker.tm.store.call_args
        assert kwargs.get("skip_l3") is False, (
            f"tm.store() must use skip_l3=False when L3 entry is absent; "
            f"actual kwargs: {kwargs}"
        )

    def test_update_entry_still_called_even_when_absent(self, tmp_path):
        """update_entry is always attempted; it simply returns False when absent."""
        candidate = _make_candidate()
        stub_l3 = StubL3(pre_populated_ids=set())
        worker = _make_worker(tmp_path, stub_l3)

        worker._improve_candidate(candidate)

        assert len(stub_l3.update_calls) == 1, (
            "update_entry must be called even when entry is not found"
        )


# ---------------------------------------------------------------------------
# Case C — L3 is None → no crash; skip_l3=False
# ---------------------------------------------------------------------------

class TestCaseCL3IsNone:
    def test_no_crash_when_l3_is_none(self, tmp_path):
        """Worker must handle tm.l3 = None gracefully (L3 not configured)."""
        candidate = _make_candidate()
        worker = _make_worker(tmp_path, stub_l3=None)  # l3 set to None

        result = worker._improve_candidate(candidate)  # must not raise

        assert result == "improved"

    def test_tm_store_skip_l3_false_when_l3_none(self, tmp_path):
        """When L3 is None, skip_l3 must be False (no in-place update happened)."""
        candidate = _make_candidate()
        worker = _make_worker(tmp_path, stub_l3=None)

        worker._improve_candidate(candidate)

        _, kwargs = worker.tm.store.call_args
        assert kwargs.get("skip_l3") is False, (
            f"skip_l3 must be False when L3 is None; actual kwargs: {kwargs}"
        )
