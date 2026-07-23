"""HT-QUALITY-GATES-001 Phase 8: regression gate preventing RC1/RC2 from
silently recurring for gate #44 onward.

RC1 was: a new GATE_REGISTRY entry was live in production/healing but
invisible to the offline audit sweep unless someone remembered a second,
hand-written edit in audit_all_content.py. RC2 was: the healer's queue-entry
vocabulary and its actual repair logic (UnitQualityScorer) were two
independently-drifted vocabularies, so a gate-derived finding could reach
the queue and still never be acted on.

These tests assert the STRUCTURAL invariants that make both roots causes
impossible to reintroduce silently:
  1. Every content-tier registry gate not hand-implemented in
     audit_all_content.py is reachable via run_all_content_gates() --
     i.e. the sweep's coverage is DEFINED BY the registry, not by a
     separately-maintained list.
  2. Every registry gate id's canonical issue name round-trips through
     gate_id_from_issue_name() -- i.e. the healer's gate-rerun routing
     (Phase 8 F3) will recognize ANY gate's finding, present or future,
     without needing its own per-gate allowlist.

If a future gate breaks either invariant, these tests fail at add-time,
not months later when a Phase-N reconnaissance rediscovers the same "no
detector" pattern for a category that was actually detected but never
reached remediation.
"""
from __future__ import annotations

import sys
from pathlib import Path

from src.translation_engine.write_gate import (
    WriteGateEvaluator,
    gate_id_from_issue_name,
    gate_issue_name,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_QUALITY_DIR = _PROJECT_ROOT / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _content_tier_gate_ids() -> set[int]:
    return {
        gid for gid, _method, _cat, action in WriteGateEvaluator.GATE_REGISTRY
        if action in ("auto_clean", "block", "warn")
    }


class TestSweepAutoPropagation:
    """RC1 invariant: audit_all_content.py's coverage is defined by the
    registry, not a hand-maintained list that can silently fall out of
    sync with it."""

    def test_every_non_hand_implemented_content_gate_is_swept(self):
        import audit_all_content as aac

        registry_ids = _content_tier_gate_ids()
        auto_swept_ids = registry_ids - aac._HAND_IMPLEMENTED_GATE_IDS

        # Real content that shouldn't trigger anything -- just proves every
        # id in auto_swept_ids actually appears in run_all_content_gates()'s
        # output keys (i.e. is reachable), regardless of pass/fail.
        en = "---\ntitle: Test\n---\nA normal English paragraph with enough words to be meaningful.\n"
        tr = "---\ntitle: Test\n---\nUn parrafo normal en espanol con suficientes palabras.\n"
        gate_results, _final_content = aac._GATE_EVALUATOR.run_all_content_gates(en, tr, "es", Path("fake/es/test.md"))

        missing = auto_swept_ids - set(gate_results.keys())
        assert not missing, (
            f"Gate id(s) {missing} are content-tier registry entries not hand-"
            f"implemented in audit_all_content.py, but run_all_content_gates() "
            f"didn't return a result for them -- the sweep would silently miss "
            f"this gate's findings (RC1 regression)."
        )

    def test_hand_implemented_ids_are_still_a_subset_of_9_to_28(self):
        """Documents the current boundary explicitly -- if this ever needs
        to change (e.g. gate 9-28 concepts get consolidated into the
        registry-driven path), it should be a deliberate edit, not a
        silent drift."""
        import audit_all_content as aac

        assert aac._HAND_IMPLEMENTED_GATE_IDS == set(range(9, 29))


class TestHealerGateRoutingRoundTrip:
    """RC2 invariant: the healer's gate-derived-issue detection
    (gate_id_from_issue_name) must recognize EVERY registry gate's
    canonical name, not just the ones it happened to be tested against."""

    def test_every_content_gate_issue_name_round_trips(self):
        method_by_id = {
            gid: method for gid, method, _cat, _action in WriteGateEvaluator.GATE_REGISTRY
        }
        for gate_id in _content_tier_gate_ids():
            name = gate_issue_name(gate_id, method_by_id[gate_id])
            recovered = gate_id_from_issue_name(name)
            assert recovered == gate_id, (
                f"Gate {gate_id}'s issue name {name!r} does not round-trip back "
                f"to its own id (got {recovered}) -- unit_heal.py's gate-rerun "
                f"path (Phase 8 F3) would fail to recognize this gate's queue "
                f"entries as gate-derived, silently falling through to "
                f"UnitQualityScorer's mismatched vocabulary (RC2 regression)."
            )

    def test_unit_scorer_vocabulary_never_collides_with_gate_names(self):
        """The two vocabularies (gate-derived vs. UnitQualityScorer-derived)
        must stay disjoint, or unit_heal.py's routing in process_queue()
        would misclassify an issue type."""
        unit_scorer_vocab = {
            "mojibake_detector", "shortcode_leak_detector", "inline_code_integrity_detector",
            "empty_unit_detector", "hallucination_length_detector", "short_api_desc_detector",
            "language_purity_detector", "duplicate_run_detector", "link_path_detector",
            "newline_ratio_detector",
        }
        for name in unit_scorer_vocab:
            assert gate_id_from_issue_name(name) is None, (
                f"UnitQualityScorer vocabulary entry {name!r} was misidentified "
                f"as gate-derived -- this would route it to the gate-rerun path "
                f"instead of UnitQualityScorer, which owns it."
            )
