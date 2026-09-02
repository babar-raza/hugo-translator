"""TC-APT-007: all 13 eligibility states + precedence edge cases (plan section 7.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.workers import eligibility as el

KNOWN = frozenset({"ar", "bg", "de", "en", "fr"})
PROFILE = frozenset({"ar", "de", "fr"})
SHA_A = "a" * 64
SHA_B = "b" * 64
FP1, FP2 = "1" * 64, "2" * 64
PP1, PP2 = "8" * 64, "9" * 64


def facts(**over) -> el.CellFacts:
    base = dict(
        target_lang="de",
        known_langs=KNOWN,
        profile_langs=PROFILE,
        site_id="docs.aspose.org",
        family="cells",
        current_source_sha256=SHA_A,
        current_profile_fp=FP1,
        current_protection_fp=PP1,
    )
    base.update(over)
    return el.CellFacts(**base)


@pytest.mark.parametrize(
    "over,state,reason",
    [
        ({"target_lang": "xx"}, "UNSUPPORTED_LANGUAGE", "lang_not_in_registry"),
        ({"target_lang": "bg"}, "EXCLUDED_BY_PROFILE", "locale_not_in_profile_allowlist"),
        ({"source_exists": False}, "SOURCE_INVALID", "source_missing"),
        ({"source_readable": False}, "SOURCE_INVALID", "source_unreadable"),
        ({"source_yaml_ok": False}, "SOURCE_INVALID", "frontmatter_yaml_invalid"),
        ({"source_nonempty": False}, "SOURCE_INVALID", "empty_after_frontmatter"),
        ({"assigned_model": "nllb_200_1.3b"}, "BLOCKED", "nllb_licensing_not_approved"),
        ({"on_hold": True}, "BLOCKED", "governance_hold"),
        (
            {
                "review_result": "REJECTED",
                "review_source_sha256": SHA_A,
                "review_profile_fp": FP1,
                "review_protection_fp": PP1,
            },
            "MANUAL_REVIEW_REJECTED",
            "claude_rejected_unchanged",
        ),
        (
            {"last_attempt_failed": True, "attempts": 5},
            "FAILED_PRIOR_VALIDATION",
            "max_attempts_exhausted",
        ),
        ({"target_exists": False}, "MISSING_TRANSLATION", "target_absent"),
        (
            {"target_exists": True, "provenance_kind": "UNKNOWN"},
            "UNKNOWN_PROVENANCE",
            "no_trustworthy_provenance",
        ),
        (
            {"target_exists": True, "provenance_kind": "GIT_COMMIT_BACKED"},
            "UNKNOWN_PROVENANCE",
            "no_trustworthy_provenance",
        ),
        (
            {
                "target_exists": True,
                "provenance_kind": "RECEIPT_BACKED",
                "provenance_source_sha256": SHA_B,
                "provenance_profile_fp": FP1,
                "provenance_protection_fp": PP1,
            },
            "SOURCE_CHANGED",
            "source_sha256_differs_from_provenance",
        ),
        (
            {
                "target_exists": True,
                "provenance_kind": "RECEIPT_BACKED",
                "provenance_source_sha256": SHA_A,
                "provenance_profile_fp": FP2,
                "provenance_protection_fp": PP1,
            },
            "PROFILE_CHANGED",
            "profile_fingerprint_differs",
        ),
        (
            {
                "target_exists": True,
                "provenance_kind": "RECEIPT_BACKED",
                "provenance_source_sha256": SHA_A,
                "provenance_profile_fp": FP1,
                "provenance_protection_fp": PP2,
            },
            "PROTECTION_RULE_CHANGED",
            "protection_fingerprint_differs",
        ),
        (
            {
                "target_exists": True,
                "provenance_kind": "RECEIPT_BACKED",
                "provenance_source_sha256": SHA_A,
                "provenance_profile_fp": FP1,
                "provenance_protection_fp": PP1,
                "tm_lineage_config_fp": "cfg-bad",
                "lineage_denylist": frozenset({"cfg-bad"}),
            },
            "MODEL_OR_PROMPT_INVALIDATED",
            "tm_lineage_denylisted",
        ),
        (
            {
                "target_exists": True,
                "provenance_kind": "AUDITED_BASELINE",
                "provenance_source_sha256": SHA_A,
                "provenance_profile_fp": FP1,
                "provenance_protection_fp": PP1,
            },
            "UP_TO_DATE",
            "provenance_current",
        ),
    ],
)
def test_each_state_is_reachable(over, state, reason):
    v = el.classify(facts(**over))
    assert (v.state, v.reason_code) == (state, reason)


def test_precedence_excluded_beats_source_invalid_and_blocked():
    v = el.classify(facts(target_lang="bg", source_exists=False, on_hold=True))
    assert v.state == "EXCLUDED_BY_PROFILE"


def test_precedence_blocked_outranks_review_and_validation_states():
    v = el.classify(
        facts(
            on_hold=True,
            review_result="REJECTED",
            review_source_sha256=SHA_A,
            review_profile_fp=FP1,
            review_protection_fp=PP1,
            target_exists=True,
        )
    )
    assert v.state == "BLOCKED"  # a licensing/hold block is never misread as a quality problem


def test_stale_rejection_falls_through_when_source_changed():
    v = el.classify(
        facts(
            review_result="REJECTED",
            review_source_sha256=SHA_B,  # reviewed an older source
            review_profile_fp=FP1,
            review_protection_fp=PP1,
            target_exists=True,
            provenance_kind="RECEIPT_BACKED",
            provenance_source_sha256=SHA_B,
        )
    )
    assert (
        v.state == "SOURCE_CHANGED"
    )  # rejection is stale -> fresh reappraisal, not MANUAL_REVIEW_REJECTED


def test_stale_rejection_falls_through_when_protection_rules_changed():
    v = el.classify(
        facts(
            review_result="REJECTED",
            review_source_sha256=SHA_A,
            review_profile_fp=FP1,
            review_protection_fp=PP2,
            target_exists=False,
        )
    )
    assert v.state == "MISSING_TRANSLATION"


def test_failed_prior_validation_only_while_nothing_changed():
    exhausted = facts(
        last_attempt_failed=True,
        attempts=5,
        review_source_sha256=SHA_B,
        review_profile_fp=FP1,
        review_protection_fp=PP1,
    )
    assert el.classify(exhausted).state == "MISSING_TRANSLATION"  # source moved on -> retry allowed
    still = facts(
        last_attempt_failed=True,
        attempts=5,
        review_source_sha256=SHA_A,
        review_profile_fp=FP1,
        review_protection_fp=PP1,
    )
    assert el.classify(still).state == "FAILED_PRIOR_VALIDATION"
    not_exhausted = facts(last_attempt_failed=True, attempts=2)
    assert el.classify(not_exhausted).state == "MISSING_TRANSLATION"


def test_nllb_block_lifts_only_with_explicit_approval():
    assert el.classify(facts(assigned_model="nllb_200_600m")).state == "BLOCKED"
    assert (
        el.classify(facts(assigned_model="nllb_200_600m", nllb_approved=True)).state
        == "MISSING_TRANSLATION"
    )
    assert el.classify(facts(assigned_model="m2m100_418m")).state == "MISSING_TRANSLATION"


def test_holds_and_denylist_loaders(tmp_path: Path):
    holds = tmp_path / "holds.yaml"
    holds.write_text(
        "holds:\n  - site_id: kb.aspose.org\n    reason: freeze\n  - site_id: docs.aspose.org\n    family: cells\n    reason: rework\n",
        encoding="utf-8",
    )
    h = el.load_holds(holds)
    assert el.is_on_hold(h, "kb.aspose.org", "anything") and el.is_on_hold(
        h, "docs.aspose.org", "cells"
    )
    assert not el.is_on_hold(h, "docs.aspose.org", "words")
    assert el.load_holds(tmp_path / "missing.yaml") == set()
    deny = tmp_path / "deny.json"
    deny.write_text(
        json.dumps(
            {
                "denylist": [
                    {"fingerprint": "cfg-x", "reason": "gate-12 regex"},
                    {"model_id": "nllb_200_1.3b"},
                    "raw-fp",
                ]
            }
        ),
        encoding="utf-8",
    )
    assert el.load_lineage_denylist(deny) == frozenset({"cfg-x", "nllb_200_1.3b", "raw-fp"})
    assert el.load_lineage_denylist(tmp_path / "none.json") == frozenset()


def test_source_validity_checks(tmp_path: Path):
    ok = tmp_path / "ok.md"
    ok.write_text("---\ntitle: t\n---\nbody\n", encoding="utf-8")
    assert el.source_validity(ok) == {
        "source_exists": True,
        "source_readable": True,
        "source_nonempty": True,
        "source_yaml_ok": True,
    }
    empty = tmp_path / "empty.md"
    empty.write_text("---\ntitle: t\n---\n   \n", encoding="utf-8")
    assert el.source_validity(empty)["source_nonempty"] is False
    bad = tmp_path / "bad.md"
    bad.write_text("---\ntitle: [unclosed\n---\nbody\n", encoding="utf-8")
    assert el.source_validity(bad)["source_yaml_ok"] is False
    assert el.source_validity(tmp_path / "nope.md")["source_exists"] is False


def test_reclassify_ledger_transitions_rows(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from src.workers.work_ledger import WorkLedger

    repo = tmp_path / "repo"
    src = repo / "content/docs.aspose.org/en/cells/net/a.md"
    src.parent.mkdir(parents=True)
    src.write_text("---\ntitle: t\n---\nbody\n", encoding="utf-8")
    import hashlib

    real_sha = hashlib.sha256(src.read_bytes()).hexdigest()
    ledger = WorkLedger(tmp_path / "ledger.sqlite3")
    base = dict(
        site_id="docs.aspose.org",
        family="cells",
        platform="net",
        source_path="content/docs.aspose.org/en/cells/net/a.md",
        source_sha256=SHA_B,  # stale hash recorded at backfill
        profile_fingerprint=FP2,
        protection_fingerprint=PP2,
    )
    ledger.upsert(
        {
            **base,
            "target_lang": "de",
            "expected_output_path": "x/de.md",
            "target_exists": False,
            "eligibility_state": "MISSING_TRANSLATION",
            "eligibility_reason_code": "target_absent",
        }
    )
    ledger.upsert(
        {
            **base,
            "target_lang": "bg",
            "expected_output_path": "x/bg.md",
            "target_exists": True,
            "target_sha256": SHA_A,
            "eligibility_state": "EXCLUDED_BY_PROFILE",
            "eligibility_reason_code": "locale_not_in_profile_allowlist",
        }
    )
    ledger.upsert(
        {
            **base,
            "target_lang": "fr",
            "expected_output_path": "x/fr.md",
            "target_exists": True,
            "target_sha256": SHA_A,
            "provenance_kind": "RECEIPT_BACKED",
            "provenance_source_sha256": SHA_B,
            "eligibility_state": "UP_TO_DATE",
            "eligibility_reason_code": "receipt_source_match",
        }
    )
    monkeypatch.setattr(
        "src.workers.fingerprints.site_fingerprints",
        lambda profile, repo: {"profile_fingerprint": FP1, "protection_fingerprint": PP1},
    )
    profile = SimpleNamespace(target_langs=["ar", "de", "fr"])
    summary = el.reclassify_ledger(
        ledger,
        content_repo=repo,
        profiles={"docs.aspose.org": profile},
        translator_repo=tmp_path,
        known_langs=KNOWN,
        nllb_approved=False,
        holds_path=tmp_path / "holds.yaml",
        denylist_path=tmp_path / "deny.json",
    )
    assert (
        summary["rows"] == 3 and summary["changed"] == 3
    )  # sha/fingerprints refreshed on every row
    assert (
        summary["transitions"]["UP_TO_DATE->SOURCE_CHANGED"] == 1
    )  # receipt was for the stale source
    rows = {r["target_lang"]: r for r in ledger.query(site_id="docs.aspose.org")}
    assert rows["fr"]["eligibility_state"] == "SOURCE_CHANGED"
    assert rows["de"]["source_sha256"] == real_sha and rows["de"]["profile_fingerprint"] == FP1
    assert rows["bg"]["eligibility_state"] == "EXCLUDED_BY_PROFILE"
    dry = el.reclassify_ledger(
        ledger,
        content_repo=repo,
        profiles={"docs.aspose.org": profile},
        translator_repo=tmp_path,
        known_langs=KNOWN,
        nllb_approved=False,
        holds_path=tmp_path / "holds.yaml",
        denylist_path=tmp_path / "deny.json",
        dry_run=True,
    )
    assert dry["changed"] == 0  # idempotent
    ledger.close()
