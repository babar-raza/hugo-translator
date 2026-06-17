"""Unit tests for scripts/ops/sprint_loop_controller.py.

Tests state machine transitions, summary classification, directive
emission, and negative controls (fail-closed behavior).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Import the controller module
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import scripts.ops.sprint_loop_controller as controller_module
from scripts.ops.sprint_loop_controller import (
    InvalidTransitionError,
    classify_summary,
    decide_next_stage,
    emit_directive,
    load_loop_state,
    parse_stage1_output,
    parse_stage2_output,
    parse_stage3_output,
    run_cycle,
    save_loop_state,
    transition,
    validate_no_invalid_final_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    """Create a temporary run directory."""
    d = tmp_path / "test-run"
    d.mkdir()
    return d


def _write_stage3_summary(run_dir: Path, **overrides) -> None:
    """Write a stage3 final-sprint-summary.yaml with given fields."""
    stage_dir = run_dir / "stage3-execution"
    stage_dir.mkdir(parents=True, exist_ok=True)
    defaults = {
        "verdict": "EXECUTION_COMPLETE_VERIFIED",
        "summary_type": "STRUCTURED",
        "all_green": "true",
        "accepted_count": "3",
        "rerouted_count": "0",
        "blocked_count": "0",
        "evidence_bundle_path": "/tmp/evidence",
        "open_issues": "",
    }
    defaults.update(overrides)
    lines = [f"{k}: {v}" for k, v in defaults.items()]
    (stage_dir / "final-sprint-summary.yaml").write_text("\n".join(lines), encoding="utf-8")


def _write_stage3_scores(run_dir: Path, evaluations: list) -> None:
    """Write quality-scores.json."""
    stage_dir = run_dir / "stage3-execution"
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "quality-scores.json").write_text(
        json.dumps({"evaluations": evaluations, "reroute_log": []}),
        encoding="utf-8",
    )


def _write_stage1_issues(run_dir: Path, issues: list) -> None:
    """Write stage1-audit/issues.json."""
    stage_dir = run_dir / "stage1-audit"
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "issues.json").write_text(
        json.dumps(
            {
                "issues": issues,
                "claim_classifications": [],
                "evidence_quality_verdict": "STRONG",
                "next_stage_recommendation": {"next_stage": "PROMPT_2", "reason": "test"},
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# State management tests
# ---------------------------------------------------------------------------


class TestStateManagement:
    def test_load_creates_idle_state(self, run_dir: Path) -> None:
        state = load_loop_state(run_dir)
        assert state["current_state"] == "IDLE"
        assert state["cycle_count"] == 0

    def test_save_and_reload(self, run_dir: Path) -> None:
        state = load_loop_state(run_dir)
        state["current_state"] = "STAGE1_PENDING"
        save_loop_state(state, run_dir)
        reloaded = load_loop_state(run_dir)
        assert reloaded["current_state"] == "STAGE1_PENDING"

    def test_transition_valid(self, run_dir: Path) -> None:
        state = load_loop_state(run_dir)
        transition(state, "STAGE1_PENDING", "test")
        assert state["current_state"] == "STAGE1_PENDING"
        assert len(state["transitions"]) == 1

    def test_transition_invalid_rejected(self, run_dir: Path) -> None:
        state = load_loop_state(run_dir)
        with pytest.raises(InvalidTransitionError):
            transition(state, "STAGE3_COMPLETE", "skip ahead")

    def test_transition_skip_verified_rejected(self, run_dir: Path) -> None:
        """NC-8: State transition that skips VERIFIED is rejected."""
        state = load_loop_state(run_dir)
        transition(state, "STAGE1_PENDING", "start")
        # Cannot jump from STAGE1_PENDING to STAGE3_COMPLETE
        with pytest.raises(InvalidTransitionError):
            transition(state, "STAGE3_COMPLETE", "skip")


# ---------------------------------------------------------------------------
# Summary classification tests
# ---------------------------------------------------------------------------


class TestSummaryClassification:
    def test_missing_summary(self) -> None:
        """NC-2: Missing summary -> MISSING."""
        assert classify_summary(None) == "MISSING"

    def test_missing_summary_type(self) -> None:
        assert classify_summary({"summary_type": "MISSING"}) == "MISSING"

    def test_prose_only(self) -> None:
        """NC-1: Prose-only summary -> PROSE_ONLY."""
        assert classify_summary({"summary_type": "PROSE_ONLY"}) == "PROSE_ONLY"

    def test_structured_all_green(self) -> None:
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "all_green": True,
            "evidence_bundle_path": "/tmp/evidence",
            "evaluations": [{"verdict": "ACCEPTED"}],
            "reroute_log": [],
            "open_issues": [],
            "accepted_count": 1,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "STRUCTURED_ALL_GREEN"

    def test_structured_not_green_with_rerouted(self) -> None:
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_REROUTED_REWORK_REQUIRED",
            "all_green": False,
            "evidence_bundle_path": "/tmp/evidence",
            "evaluations": [{"verdict": "REROUTED"}],
            "reroute_log": [],
            "accepted_count": 0,
            "rerouted_count": 1,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "STRUCTURED_NOT_GREEN"

    def test_contradictory_all_green_but_reroute_log(self) -> None:
        """NC-3/NC-7: All-green claim but reroute log non-empty -> CONTRADICTORY."""
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "all_green": True,
            "evidence_bundle_path": "/tmp/evidence",
            "evaluations": [{"verdict": "ACCEPTED"}],
            "reroute_log": [{"taskcard_id": "TC-01", "reason": "test"}],
            "accepted_count": 1,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "CONTRADICTORY"

    def test_contradictory_all_green_but_open_issues(self) -> None:
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "all_green": True,
            "evidence_bundle_path": "/tmp/evidence",
            "evaluations": [{"verdict": "ACCEPTED"}],
            "reroute_log": [],
            "open_issues": ["L1-001"],
            "accepted_count": 1,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "CONTRADICTORY"

    def test_evidence_missing(self) -> None:
        """NC-5: Evidence bundle missing -> EVIDENCE_MISSING."""
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "evidence_bundle_path": None,
            "evaluations": [{"verdict": "ACCEPTED"}],
            "accepted_count": 1,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "EVIDENCE_MISSING"

    def test_scores_missing(self) -> None:
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "evidence_bundle_path": "/tmp/evidence",
            "evaluations": [],
            "accepted_count": 1,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "SCORES_MISSING"

    def test_blocked_external(self) -> None:
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "BLOCKED_EXTERNAL",
        }
        assert classify_summary(output) == "BLOCKED_EXTERNAL"

    def test_taskcards_incomplete(self) -> None:
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "evidence_bundle_path": "/tmp/evidence",
            "evaluations": [{"verdict": "ACCEPTED"}],
            "accepted_count": 0,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "TASKCARDS_INCOMPLETE"


# ---------------------------------------------------------------------------
# Decision logic tests
# ---------------------------------------------------------------------------


class TestDecisionLogic:
    def test_missing_routes_to_prompt1(self, run_dir: Path) -> None:
        """NC-2: Missing summary -> P1+P2+P3."""
        state = {
            "current_state": "STAGE3_COMPLETE",
            "transitions": [],
            "cycle_count": 0,
            "summary_classification": None,
            "next_directive": None,
        }
        directive = decide_next_stage(state, "MISSING", run_dir)
        assert directive["action"] == "RUN_PROMPT_1"

    def test_prose_only_routes_to_prompt2(self, run_dir: Path) -> None:
        """NC-1: Prose-only -> P2+P3."""
        state = {
            "current_state": "STAGE3_COMPLETE",
            "transitions": [],
            "cycle_count": 0,
            "summary_classification": None,
            "next_directive": None,
        }
        directive = decide_next_stage(state, "PROSE_ONLY", run_dir)
        assert directive["action"] == "RUN_PROMPT_2"

    def test_not_green_routes_to_prompt2(self, run_dir: Path) -> None:
        state = {
            "current_state": "STAGE3_COMPLETE",
            "transitions": [],
            "cycle_count": 0,
            "summary_classification": None,
            "next_directive": None,
        }
        directive = decide_next_stage(state, "STRUCTURED_NOT_GREEN", run_dir)
        assert directive["action"] == "RUN_PROMPT_2"

    def test_all_green_routes_to_adversarial(self, run_dir: Path) -> None:
        state = {
            "current_state": "STAGE3_COMPLETE",
            "transitions": [],
            "cycle_count": 0,
            "summary_classification": None,
            "next_directive": None,
        }
        directive = decide_next_stage(state, "STRUCTURED_ALL_GREEN", run_dir)
        assert directive["action"] == "RUN_ADVERSARIAL_REVIEW"
        assert state["current_state"] == "ADVERSARIAL_REVIEW"

    def test_blocked_external_terminates(self, run_dir: Path) -> None:
        state = {
            "current_state": "STAGE3_COMPLETE",
            "transitions": [],
            "cycle_count": 0,
            "summary_classification": None,
            "next_directive": None,
        }
        directive = decide_next_stage(state, "BLOCKED_EXTERNAL", run_dir)
        assert directive["action"] == "BLOCK"
        assert state["current_state"] == "TERMINATED"


# ---------------------------------------------------------------------------
# Invalid final state tests
# ---------------------------------------------------------------------------


class TestInvalidFinalStates:
    def test_next_prompt_needed_rejected(self) -> None:
        """NC-6: NEXT_PROMPT_NEEDED is never valid as final state."""
        state = {"current_state": "NEXT_PROMPT_NEEDED"}
        with pytest.raises(InvalidTransitionError, match="never valid"):
            validate_no_invalid_final_state(state)

    def test_prose_only_accepted_rejected(self) -> None:
        state = {"current_state": "PROSE_ONLY_ACCEPTED"}
        with pytest.raises(InvalidTransitionError):
            validate_no_invalid_final_state(state)

    def test_score_below_4_accepted_rejected(self) -> None:
        state = {"current_state": "SCORE_BELOW_4_ACCEPTED"}
        with pytest.raises(InvalidTransitionError):
            validate_no_invalid_final_state(state)

    def test_evidence_package_missing_accepted_rejected(self) -> None:
        state = {"current_state": "EVIDENCE_PACKAGE_MISSING_ACCEPTED"}
        with pytest.raises(InvalidTransitionError):
            validate_no_invalid_final_state(state)

    def test_valid_terminal_state_ok(self) -> None:
        state = {"current_state": "TERMINATED"}
        validate_no_invalid_final_state(state)  # Should not raise


# ---------------------------------------------------------------------------
# Stage output parsing tests
# ---------------------------------------------------------------------------


class TestStageOutputParsing:
    def test_parse_stage1_missing(self, run_dir: Path) -> None:
        assert parse_stage1_output(run_dir) is None

    def test_parse_stage1_present(self, run_dir: Path) -> None:
        _write_stage1_issues(
            run_dir,
            [
                {
                    "issue_id": "L1-001",
                    "issue_level": "L1_EXECUTION",
                    "title": "Test issue",
                    "description": "A test issue for schema validation",
                    "severity": "HIGH",
                    "blocker": True,
                }
            ],
        )
        result = parse_stage1_output(run_dir)
        assert result is not None
        assert len(result["issues"]) == 1

    def test_parse_stage3_missing(self, run_dir: Path) -> None:
        result = parse_stage3_output(run_dir)
        assert result is not None
        assert result["summary_type"] == "MISSING"

    def test_parse_stage3_structured(self, run_dir: Path) -> None:
        _write_stage3_summary(run_dir)
        _write_stage3_scores(run_dir, [{"taskcard_id": "TC-01", "verdict": "ACCEPTED"}])
        result = parse_stage3_output(run_dir)
        assert result is not None
        assert result["summary_type"] == "STRUCTURED"
        assert len(result["evaluations"]) == 1


# ---------------------------------------------------------------------------
# Directive emission tests
# ---------------------------------------------------------------------------


class TestDirectiveEmission:
    def test_emit_writes_file(self, run_dir: Path) -> None:
        state = {"next_directive": {"action": "RUN_PROMPT_1", "reason": "test"}}
        path = emit_directive(state, run_dir)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["action"] == "RUN_PROMPT_1"


# ---------------------------------------------------------------------------
# Full cycle tests
# ---------------------------------------------------------------------------


class TestFullCycle:
    def test_initial_cycle_starts_stage1(self, run_dir: Path) -> None:
        state = run_cycle(run_dir, dry_run=True)
        assert state["current_state"] == "STAGE1_PENDING"
        assert state["next_directive"]["action"] == "RUN_PROMPT_1"

    def test_advance_after_stage1(self, run_dir: Path) -> None:
        # Initialize
        run_cycle(run_dir)
        # Write stage1 output
        _write_stage1_issues(run_dir, [])
        # Advance
        state = run_cycle(run_dir, advance=True)
        assert state["current_state"] == "STAGE2_PENDING"

    def test_force_stage(self, run_dir: Path) -> None:
        state = run_cycle(run_dir, force_stage=1)
        assert state["current_state"] == "STAGE1_PENDING"


# ---------------------------------------------------------------------------
# TC-HARDEN-01: Schema validation tests
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """TC-HARDEN-01: parse_stage1_output and parse_stage3_output validate schemas."""

    def test_parse_stage1_rejects_nonconforming_output(self, run_dir: Path) -> None:
        """Stage 1 issues.json missing claim_classifications must return None."""
        stage_dir = run_dir / "stage1-audit"
        stage_dir.mkdir(parents=True, exist_ok=True)
        # Missing required 'claim_classifications' field
        (stage_dir / "issues.json").write_text(
            json.dumps(
                {
                    "issues": [],
                    "evidence_quality_verdict": "STRONG",
                    "next_stage_recommendation": {"next_stage": "PROMPT_2", "reason": "x"},
                    # claim_classifications intentionally omitted
                }
            ),
            encoding="utf-8",
        )
        result = parse_stage1_output(run_dir)
        assert result is None, (
            "parse_stage1_output must return None when issues.json violates the schema"
        )

    def test_parse_stage1_accepts_conforming_output(self, run_dir: Path) -> None:
        """Schema-valid issues.json must return the parsed dict."""
        _write_stage1_issues(run_dir, [])
        result = parse_stage1_output(run_dir)
        assert result is not None
        assert "issues" in result

    def test_parse_stage3_handles_nonconforming_scores_safely(self, run_dir: Path) -> None:
        """Stage 3 scores missing 'final_sprint_summary' must NOT crash (only warn)."""
        _write_stage3_summary(run_dir)
        stage_dir = run_dir / "stage3-execution"
        stage_dir.mkdir(parents=True, exist_ok=True)
        # Missing required 'final_sprint_summary' field
        (stage_dir / "quality-scores.json").write_text(
            json.dumps({"evaluations": [], "reroute_log": []}),
            encoding="utf-8",
        )
        # Should not raise — warning is logged, output is handled safely
        result = parse_stage3_output(run_dir)
        assert result is not None
        assert "evaluations" in result


# ---------------------------------------------------------------------------
# TC-HARDEN-02: YAML parser tests
# ---------------------------------------------------------------------------


class TestYAMLParser:
    """TC-HARDEN-02: parse_stage3_output uses yaml.safe_load for YAML files."""

    def test_parse_stage3_multiline_open_issues(self, run_dir: Path) -> None:
        """open_issues as a YAML list must parse as a Python list with 2 elements."""
        stage_dir = run_dir / "stage3-execution"
        stage_dir.mkdir(parents=True, exist_ok=True)
        yaml_content = (
            "verdict: EXECUTION_COMPLETE_VERIFIED\n"
            "summary_type: STRUCTURED\n"
            "all_green: true\n"
            "accepted_count: 1\n"
            "rerouted_count: 0\n"
            "blocked_count: 0\n"
            "evidence_bundle_path: /tmp/evidence\n"
            "open_issues:\n"
            "  - issue1\n"
            "  - issue2\n"
        )
        (stage_dir / "final-sprint-summary.yaml").write_text(yaml_content, encoding="utf-8")
        result = parse_stage3_output(run_dir)
        assert result is not None
        open_issues = result.get("open_issues", "NOT_PARSED")
        assert isinstance(open_issues, list), (
            f"open_issues must be a Python list, got {type(open_issues)}: {open_issues!r}"
        )
        assert len(open_issues) == 2

    def test_classify_summary_detects_contradiction_with_list_open_issues(
        self,
    ) -> None:
        """all_green=True with non-empty open_issues list must return CONTRADICTORY."""
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "all_green": True,  # Python bool (as yaml.safe_load returns)
            "evidence_bundle_path": "/tmp/evidence",
            "evaluations": [{"verdict": "ACCEPTED"}],
            "reroute_log": [],
            "open_issues": ["issue1", "issue2"],  # Python list, not empty string
            "accepted_count": 1,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "CONTRADICTORY"

    def test_classify_summary_bool_all_green_accepted(self) -> None:
        """Python bool True (from yaml.safe_load) must be handled as all_green=True."""
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "all_green": True,  # bool, not string
            "evidence_bundle_path": "/tmp/evidence",
            "evaluations": [{"verdict": "ACCEPTED"}],
            "reroute_log": [],
            "open_issues": [],
            "accepted_count": 1,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        assert classify_summary(output) == "STRUCTURED_ALL_GREEN"


# ---------------------------------------------------------------------------
# TC-HARDEN-03: Adversarial review gate tests
# ---------------------------------------------------------------------------


def _setup_adversarial_review_state(run_dir: Path) -> None:
    """Set loop state to ADVERSARIAL_REVIEW so run_cycle --advance enters that branch."""
    state = {
        "run_id": run_dir.name,
        "current_state": "ADVERSARIAL_REVIEW",
        "cycle_count": 1,
        "transitions": [
            {"from_state": "STAGE3_COMPLETE", "to_state": "ADVERSARIAL_REVIEW", "reason": "test"}
        ],
        "summary_classification": "STRUCTURED_ALL_GREEN",
        "next_directive": None,
    }
    save_loop_state(state, run_dir)


class TestAdversarialReviewGate:
    """TC-HARDEN-03: Adversarial review requires review-result.json with final_decision."""

    def test_adversarial_review_requires_review_result_json(self, run_dir: Path) -> None:
        """Directory only (no review-result.json) must NOT transition to TERMINATED."""
        _setup_adversarial_review_state(run_dir)
        ar_dir = run_dir / "adversarial-review"
        ar_dir.mkdir(parents=True, exist_ok=True)
        # No review-result.json — directory only
        state = run_cycle(run_dir, advance=True)
        assert state["current_state"] == "ADVERSARIAL_REVIEW", (
            "Directory existence alone must not advance state to TERMINATED"
        )

    def test_adversarial_review_accepts_on_accepted_decision(self, run_dir: Path) -> None:
        """review-result.json with final_decision=ACCEPTED must transition to TERMINATED."""
        _setup_adversarial_review_state(run_dir)
        ar_dir = run_dir / "adversarial-review"
        ar_dir.mkdir(parents=True, exist_ok=True)
        (ar_dir / "review-result.json").write_text(
            json.dumps(
                {
                    "review_date": "2026-06-17",
                    "challenges": [],
                    "final_decision": "ACCEPTED",
                    "reason": "All issues addressed.",
                }
            ),
            encoding="utf-8",
        )
        state = run_cycle(run_dir, advance=True)
        assert state["current_state"] == "TERMINATED"
        assert state["next_directive"]["action"] == "ACCEPT"

    def test_adversarial_review_reroutes_on_rerouted_decision(self, run_dir: Path) -> None:
        """review-result.json with final_decision=REROUTED must transition to REWORK_PENDING."""
        _setup_adversarial_review_state(run_dir)
        ar_dir = run_dir / "adversarial-review"
        ar_dir.mkdir(parents=True, exist_ok=True)
        (ar_dir / "review-result.json").write_text(
            json.dumps(
                {
                    "review_date": "2026-06-17",
                    "challenges": ["Evidence gap found in TC-01"],
                    "final_decision": "REROUTED",
                    "reason": "Evidence gap requires rework.",
                }
            ),
            encoding="utf-8",
        )
        state = run_cycle(run_dir, advance=True)
        assert state["current_state"] == "REWORK_PENDING"
        assert state["next_directive"]["action"] == "RUN_PROMPT_2"

    def test_adversarial_review_rejects_schema_invalid_result(self, run_dir: Path) -> None:
        """review-result.json missing required 'reason' field must NOT advance state."""
        _setup_adversarial_review_state(run_dir)
        ar_dir = run_dir / "adversarial-review"
        ar_dir.mkdir(parents=True, exist_ok=True)
        # Missing 'reason' — violates adversarial-review-result.schema.json
        (ar_dir / "review-result.json").write_text(
            json.dumps(
                {
                    "review_date": "2026-06-17",
                    "challenges": [],
                    "final_decision": "ACCEPTED",
                    # 'reason' intentionally absent
                }
            ),
            encoding="utf-8",
        )
        state = run_cycle(run_dir, advance=True)
        assert state["current_state"] == "ADVERSARIAL_REVIEW", (
            "Schema-invalid review-result.json (missing 'reason') must not advance state to TERMINATED"
        )


# ---------------------------------------------------------------------------
# TC-HARDEN-05: NC-10 proof tests
# ---------------------------------------------------------------------------


class TestNC10EvidenceBundleEnforcement:
    """TC-HARDEN-05: null evidence_bundle_path must produce EVIDENCE_MISSING classification."""

    def test_nc10_evidence_bundle_path_null_rejected(self) -> None:
        """NC-10: null evidence_bundle_path must return EVIDENCE_MISSING."""
        output = {
            "summary_type": "STRUCTURED",
            "verdict": "EXECUTION_COMPLETE_VERIFIED",
            "all_green": True,
            "evidence_bundle_path": None,  # null — NC-10 trigger
            "evaluations": [{"verdict": "ACCEPTED"}],
            "reroute_log": [],
            "open_issues": [],
            "accepted_count": 1,
            "rerouted_count": 0,
            "blocked_count": 0,
        }
        result = classify_summary(output)
        assert result == "EVIDENCE_MISSING", (
            "classify_summary must return EVIDENCE_MISSING when evidence_bundle_path is None"
        )


# ---------------------------------------------------------------------------
# TC-PHASE3-01: Fallback path tests (YAML_AVAILABLE=False, JSONSCHEMA_AVAILABLE=False)
# ---------------------------------------------------------------------------


class TestFallbackPaths:
    """TC-PHASE3-01: Verify graceful degradation when pyyaml or jsonschema are absent."""

    def test_jsonschema_unavailable_parse_stage1_accepts_without_validation(
        self, run_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When JSONSCHEMA_AVAILABLE=False, schema-invalid stage1 output is returned (not None)."""
        # Write an issues.json that violates the schema (missing required fields).
        # With jsonschema available this would be rejected; without it should pass through.
        stage_dir = run_dir / "stage1-audit"
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "issues.json").write_text(
            json.dumps({"issues": [{"issue_id": "L1-001"}]}),  # missing claim_classifications etc.
            encoding="utf-8",
        )
        monkeypatch.setattr(controller_module, "JSONSCHEMA_AVAILABLE", False)
        result = parse_stage1_output(run_dir)
        assert result is not None, (
            "When JSONSCHEMA_AVAILABLE=False, parse_stage1_output must skip validation "
            "and return the data instead of None"
        )
        assert "issues" in result

    def test_yaml_unavailable_parse_stage3_uses_line_parser(
        self, run_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When YAML_AVAILABLE=False, parse_stage3_output falls back to line-by-line parser."""
        stage_dir = run_dir / "stage3-execution"
        stage_dir.mkdir(parents=True, exist_ok=True)
        # Write a flat YAML file parseable by the line-by-line fallback.
        (stage_dir / "final-sprint-summary.yaml").write_text(
            "verdict: EXECUTION_COMPLETE_VERIFIED\nsummary_type: STRUCTURED\nall_green: true\n"
            "accepted_count: 1\nrerouted_count: 0\nblocked_count: 0\n"
            "evidence_bundle_path: /tmp/evidence\nopen_issues: \n",
            encoding="utf-8",
        )
        # Write a minimal scores file to avoid scores-related branches.
        (stage_dir / "quality-scores.json").write_text(
            json.dumps(
                {
                    "evaluations": [{"taskcard_id": "TC-01", "verdict": "ACCEPTED"}],
                    "reroute_log": [],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(controller_module, "YAML_AVAILABLE", False)
        # Also disable jsonschema to avoid spurious schema warning on scores
        monkeypatch.setattr(controller_module, "JSONSCHEMA_AVAILABLE", False)
        result = parse_stage3_output(run_dir)
        assert result is not None
        assert result.get("summary_type") == "STRUCTURED", (
            "Fallback line-by-line parser must extract summary_type from flat YAML"
        )


# ---------------------------------------------------------------------------
# TC-PHASE3-02: parse_stage2_output unit tests
# ---------------------------------------------------------------------------


class TestParseStage2Output:
    """TC-PHASE3-02: Unit tests for parse_stage2_output (absent/present/multiline)."""

    def test_parse_stage2_absent_returns_none(self, run_dir: Path) -> None:
        """parse_stage2_output returns None when stage2-plan/ directory is absent."""
        result = parse_stage2_output(run_dir)
        assert result is None

    def test_parse_stage2_present_flat_verdict(self, run_dir: Path) -> None:
        """parse_stage2_output extracts plan_verdict and taskcards from valid stage2 output."""
        stage_dir = run_dir / "stage2-plan"
        stage_dir.mkdir(parents=True, exist_ok=True)
        # Write one JSONL taskcard line.
        (stage_dir / "taskcards.jsonl").write_text(
            json.dumps({"task_id": "TC-01", "title": "Fix gap"}) + "\n",
            encoding="utf-8",
        )
        # Write a flat YAML verdict file.
        (stage_dir / "ready-for-execution-verdict.yaml").write_text(
            "plan_verdict: PLAN_HARDENED\n",
            encoding="utf-8",
        )
        result = parse_stage2_output(run_dir)
        assert result is not None
        assert result["plan_verdict"] == "PLAN_HARDENED"
        assert isinstance(result["taskcards"], list)
        assert len(result["taskcards"]) == 1
        assert result["taskcards"][0]["task_id"] == "TC-01"

    def test_parse_stage2_multiline_verdict_yaml(self, run_dir: Path) -> None:
        """parse_stage2_output handles multi-line YAML in ready-for-execution-verdict.yaml."""
        stage_dir = run_dir / "stage2-plan"
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "taskcards.jsonl").write_text(
            json.dumps({"task_id": "TC-02", "title": "Multiline test"}) + "\n",
            encoding="utf-8",
        )
        # Multi-line YAML with a block scalar note field that would break a line parser.
        (stage_dir / "ready-for-execution-verdict.yaml").write_text(
            "plan_verdict: PLAN_HARDENED_WITH_CAVEATS\n"
            "notes: |\n"
            "  Line one of notes.\n"
            "  Line two of notes.\n",
            encoding="utf-8",
        )
        result = parse_stage2_output(run_dir)
        assert result is not None
        assert result["plan_verdict"] == "PLAN_HARDENED_WITH_CAVEATS", (
            "yaml.safe_load must correctly extract plan_verdict from multi-line YAML"
        )
