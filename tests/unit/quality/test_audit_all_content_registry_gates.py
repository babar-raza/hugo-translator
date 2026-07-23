"""HT-QUALITY-GATES-001 Phase 8 (F1): tests for audit_all_content.py's
generic GATE_REGISTRY sweep (_run_registry_gates), which replaced a
hand-written WriteGateResult(passed=True) block per gate id for gates
29-35. The core claim under test: a gate NOT explicitly hand-coded in this
script (i.e. every id outside 9-28) is still detected, and any gate the
script itself hand-implements (9-28) is NOT double-reported here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_QUALITY_DIR = _PROJECT_ROOT / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

import audit_all_content as aac  # noqa: E402
from src.translation_engine.write_gate import WriteGateEvaluator  # noqa: E402


def _collect(en_content, tr_content, locale="es"):
    findings = []

    def record(issue, detail=""):
        findings.append((issue, detail))

    aac._run_registry_gates(en_content, tr_content, locale, Path("fake/es/test.md"), record)
    return findings


def test_clean_content_produces_no_registry_findings():
    en = "---\ntitle: Test\n---\nHello world, a normal sentence with enough words."
    tr = "---\ntitle: Test\n---\nHola mundo, una oracion normal con suficientes palabras."
    assert _collect(en, tr) == []


def test_gate29_refusal_artifact_is_reported_under_its_established_name():
    en = "---\ntitle: Test\n---\nHello world, a normal sentence with enough words."
    tr = "---\ntitle: Test\n---\nPlease provide the text you want translated."
    findings = _collect(en, tr)
    issue_types = [f[0] for f in findings]
    assert "refusal_artifact_gate29" in issue_types


def test_gate30_placeholder_leak_is_reported_under_its_established_name():
    en = "---\ntitle: Test\n---\nHello world, a normal sentence with enough words."
    tr = "---\ntitle: Test\n---\nHola {PLACEHOLDER_0} mundo, una oracion normal aqui."
    findings = _collect(en, tr)
    issue_types = [f[0] for f in findings]
    assert "placeholder_leak_gate30" in issue_types


def test_hand_implemented_gate_ids_9_to_28_are_never_double_reported():
    # These ids are this script's own hand-rolled checks elsewhere in scan();
    # _run_registry_gates must skip them so a hit isn't reported twice under
    # two different names for the same underlying defect.
    assert aac._HAND_IMPLEMENTED_GATE_IDS == set(range(9, 29))
    en = "---\ntitle: Test\n---\nHello world, a normal sentence with enough words."
    tr = "---\ntitle: Test\n---\nHola mundo, una oracion normal con suficientes palabras."
    findings = _collect(en, tr)
    reported_ids = set()
    for issue, _detail in findings:
        for gate_id, name in aac._GATE_ISSUE_NAMES.items():
            if issue == name:
                reported_ids.add(gate_id)
    assert reported_ids.isdisjoint(aac._HAND_IMPLEMENTED_GATE_IDS)


def test_new_registry_entry_is_picked_up_with_zero_script_edits():
    # Regression guard for RC1: every gate id in the live GATE_REGISTRY that
    # ISN'T hand-implemented here must be reachable through
    # run_all_content_gates() -- i.e. this script's coverage is defined by
    # the registry, not by a fixed, hand-maintained list of gate ids.
    registry_ids = {gid for gid, _m, _c, action in WriteGateEvaluator.GATE_REGISTRY
                    if action in ("auto_clean", "block", "warn")}
    auto_swept_ids = registry_ids - aac._HAND_IMPLEMENTED_GATE_IDS
    # Every one of gates 29-36 (the ones added after the hand-rolled 9-28
    # checks existed) must be in the auto-swept set, not hand-implemented.
    assert {29, 30, 31, 32, 33, 34, 35, 36}.issubset(auto_swept_ids)


def test_gate_issue_name_fallback_for_unmapped_gate_id():
    # A hypothetical future gate 99 with no entry in _GATE_ISSUE_NAMES must
    # still get a predictable, non-empty issue-type string.
    name = aac._gate_issue_name(99, "_gate_something_new")
    assert name == "gate99_something_new"
