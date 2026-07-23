"""HT-QUALITY-GATES-001 Phase 8 (F3): tests for unit_heal.py's gate-rerun
healing path (_heal_via_gate_rerun), which fixes root cause RC2 -- queue
entries whose issues are gate-registry-derived (e.g. "refusal_artifact_gate29")
were invisible to UnitQualityScorer's fixed 10-type vocabulary, so re-scoring
always found nothing and the file was silently marked "skipped_clean" even
when the gate issue was still genuinely present.
"""
from __future__ import annotations

from scripts.quality.unit_heal import _heal_via_gate_rerun, gate_id_from_issue_name


_EN_MD = """---
title: "Sample"
description: "Sample class"
---

Some prose about a sample class with enough words to be meaningful.
"""


def test_gate_id_from_issue_name_recognizes_gate_vocabulary():
    assert gate_id_from_issue_name("refusal_artifact_gate29") == 29
    assert gate_id_from_issue_name("placeholder_leak_gate30") == 30
    assert gate_id_from_issue_name("gate99_something_new") == 99


def test_gate_id_from_issue_name_rejects_unit_scorer_vocabulary():
    # These belong to UnitQualityScorer, not the gate registry -- must not
    # be misidentified as gate-derived.
    for name in (
        "mojibake_detector", "shortcode_leak_detector", "duplicate_run_detector",
        "language_purity_detector", "link_path_detector",
    ):
        assert gate_id_from_issue_name(name) is None


def test_heal_via_gate_rerun_fixes_auto_clean_issue(tmp_path):
    # Gate 12 (_gate_double_periods, auto_clean): a stray ".." in prose
    # (source has none) is mechanically fixable with no model call.
    tr_broken = """---
title: "Sample"
description: "Sample class"
---

Some prose about a sample class with enough words to be meaningful..
"""
    tr_file = tmp_path / "sample.md"
    tr_file.write_text(tr_broken, encoding="utf-8")

    stats = {}
    outcome = _heal_via_gate_rerun(
        en_content=_EN_MD,
        tr_content=tr_broken,
        tr_file=tr_file,
        locale="es",
        gate_issue_types={"gate12_double_periods"},
        dry_run=False,
        stats=stats,
    )

    assert outcome == "fixed"
    written = tr_file.read_text(encoding="utf-8")
    assert ".." not in written.split("---")[-1]
    assert stats.get("units_fixed", 0) == 1


def test_heal_via_gate_rerun_detects_stale_queue_entry_as_clean(tmp_path):
    # The queue said this file had an issue, but the current on-disk content
    # is already clean (fixed by something else since the sweep ran).
    tr_clean = """---
title: "Sample"
description: "Sample class"
---

Some prose about a sample class with enough words to be meaningful.
"""
    tr_file = tmp_path / "sample.md"
    tr_file.write_text(tr_clean, encoding="utf-8")

    stats = {}
    outcome = _heal_via_gate_rerun(
        en_content=_EN_MD,
        tr_content=tr_clean,
        tr_file=tr_file,
        locale="es",
        gate_issue_types={"gate12_double_periods"},
        dry_run=False,
        stats=stats,
    )

    assert outcome == "clean"
    assert stats.get("skipped_clean", 0) == 1
    # Must not have been rewritten.
    assert tr_file.read_text(encoding="utf-8") == tr_clean


def test_heal_via_gate_rerun_reports_needs_retranslation_for_non_autofixable_gate(tmp_path):
    # Gate 29 (_gate_refusal_artifact, block, no auto_clean): a real,
    # currently-present refusal leak this CPU-only healer cannot mechanically
    # fix -- must be reported as needing retranslation, NOT silently marked
    # clean (the exact bug root cause RC2 describes).
    tr_broken = """---
title: "Sample"
description: "Sample class"
---

Please provide the text you want translated.
"""
    tr_file = tmp_path / "sample.md"
    tr_file.write_text(tr_broken, encoding="utf-8")
    original = tr_file.read_text(encoding="utf-8")

    stats = {}
    outcome = _heal_via_gate_rerun(
        en_content=_EN_MD,
        tr_content=tr_broken,
        tr_file=tr_file,
        locale="es",
        gate_issue_types={"refusal_artifact_gate29"},
        dry_run=False,
        stats=stats,
    )

    assert outcome == "needs_retranslation"
    assert stats.get("gate_needs_retranslation", 0) == 1
    # Must not have been rewritten, and definitely not marked "fixed"/"clean".
    assert tr_file.read_text(encoding="utf-8") == original
    assert stats.get("units_fixed", 0) == 0
    assert stats.get("skipped_clean", 0) == 0


def test_heal_via_gate_rerun_detects_still_failing_warn_tier_gate(tmp_path):
    """Regression test for the CRITICAL bug found by this session's
    independent verification pass: _heal_via_gate_rerun originally called
    evaluate(), whose internal dispatcher (_run_content_gates) runs every
    "warn"-action gate against a DISPOSABLE, discarded WriteGateResult (by
    design, for the production write path -- a bug in a brand-new gate
    must never start blocking real writes). Checking evaluate()'s returned
    result.passed therefore ALWAYS read True for a warn-tier gate
    regardless of whether it still failed -- silently reproducing root
    cause RC2 through a different mechanism, for every gate this session
    added (37-43, all warn-tier) plus the pre-existing warn gates 31-35.

    Directly reproduced pre-fix: this exact fixture (a real, currently-
    present Gate 37 TM-collision) returned outcome="clean" and left the
    broken file marked done. Post-fix (using run_all_content_gates(),
    which returns a REAL per-gate result never discarded regardless of
    action tier), it must correctly report needs_retranslation.
    """
    en_collision = (
        "---\ntitle: FooClass\ndescription: \"`FooClass` enum with 3 values\"\n---\n"
        "Body text about the FooClass enum.\n"
    )
    tr_collision = (
        "---\ntitle: FooClass\ndescription: \"`BarClass` enum with 3 values\"\n---\n"
        "Texto sobre la enumeracion.\n"
    )
    tr_file = tmp_path / "FooClass.md"
    tr_file.write_text(tr_collision, encoding="utf-8")
    original = tr_file.read_text(encoding="utf-8")

    stats = {}
    outcome = _heal_via_gate_rerun(
        en_content=en_collision,
        tr_content=tr_collision,
        tr_file=tr_file,
        locale="es",
        gate_issue_types={"gate37_tm_collision"},
        dry_run=False,
        stats=stats,
    )

    assert outcome == "needs_retranslation", (
        "A still-failing warn-tier gate (37) must be reported as needing "
        "retranslation, not silently marked clean -- this is the exact RC2 "
        "regression the independent verification pass found."
    )
    assert stats.get("gate_needs_retranslation", 0) == 1
    assert stats.get("skipped_clean", 0) == 0
    assert tr_file.read_text(encoding="utf-8") == original


def test_heal_via_gate_rerun_dry_run_does_not_write(tmp_path):
    tr_broken = """---
title: "Sample"
description: "Sample class"
---

Some prose about a sample class with enough words to be meaningful..
"""
    tr_file = tmp_path / "sample.md"
    tr_file.write_text(tr_broken, encoding="utf-8")
    original = tr_file.read_text(encoding="utf-8")

    stats = {}
    outcome = _heal_via_gate_rerun(
        en_content=_EN_MD,
        tr_content=tr_broken,
        tr_file=tr_file,
        locale="es",
        gate_issue_types={"gate12_double_periods"},
        dry_run=True,
        stats=stats,
    )

    assert outcome == "fixed"
    assert tr_file.read_text(encoding="utf-8") == original  # unchanged on disk
