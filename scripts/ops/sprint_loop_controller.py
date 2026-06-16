"""Post-Sprint Autonomy Loop Controller.

Parses stage outputs (audit, plan-hardening, execution), classifies
summaries, and determines the next stage automatically. The user no
longer needs to manually choose which prompt to run.

Usage:
    python scripts/ops/sprint_loop_controller.py --run-dir <path> --dry-run
    python scripts/ops/sprint_loop_controller.py --run-dir <path> --advance
    python scripts/ops/sprint_loop_controller.py --run-dir <path> --force-stage 1

State is persisted in <run-dir>/loop-state.json.
Decisions are logged in <run-dir>/loop-events.jsonl.
The next action is written to <run-dir>/next-directive.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema  # type: ignore[import-untyped]

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False

try:
    import yaml  # type: ignore[import-untyped]

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, dict] = {}


def _repo_root() -> Path:
    """Return repository root (2 levels up from scripts/ops/)."""
    return Path(__file__).resolve().parent.parent.parent


def _load_schema(schema_path: Path) -> dict | None:
    """Load and cache a JSON schema from the given path."""
    key = str(schema_path)
    if key in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[key]
    if not schema_path.exists():
        logger.warning("Schema file not found: %s", schema_path)
        return None
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    _SCHEMA_CACHE[key] = schema
    return schema


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATES = [
    "IDLE",
    "STAGE1_PENDING",
    "STAGE1_COMPLETE",
    "STAGE2_PENDING",
    "STAGE2_COMPLETE",
    "STAGE3_PENDING",
    "STAGE3_COMPLETE",
    "REWORK_PENDING",
    "ADVERSARIAL_REVIEW",
    "TERMINATED",
]

VALID_TRANSITIONS: dict[str, list[str]] = {
    "IDLE": ["STAGE1_PENDING"],
    "STAGE1_PENDING": ["STAGE1_COMPLETE"],
    "STAGE1_COMPLETE": ["STAGE2_PENDING"],
    "STAGE2_PENDING": ["STAGE2_COMPLETE"],
    "STAGE2_COMPLETE": ["STAGE3_PENDING"],
    "STAGE3_PENDING": ["STAGE3_COMPLETE"],
    "STAGE3_COMPLETE": ["REWORK_PENDING", "ADVERSARIAL_REVIEW", "TERMINATED"],
    "REWORK_PENDING": ["STAGE1_PENDING", "STAGE2_PENDING", "STAGE3_PENDING"],
    "ADVERSARIAL_REVIEW": ["TERMINATED", "REWORK_PENDING"],
}

SUMMARY_CLASSIFICATIONS = [
    "STRUCTURED_ALL_GREEN",
    "STRUCTURED_NOT_GREEN",
    "PROSE_ONLY",
    "MISSING",
    "CONTRADICTORY",
    "EVIDENCE_MISSING",
    "SCORES_MISSING",
    "TASKCARDS_INCOMPLETE",
    "BLOCKED_EXTERNAL",
]

INVALID_FINAL_STATES = [
    "NEXT_PROMPT_NEEDED",
    "HUMAN_REVIEW_NEEDED_BEFORE_AGENT_REVIEW",
    "PROSE_ONLY_ACCEPTED",
    "SUMMARY_MISSING_ACCEPTED",
    "SCORE_BELOW_4_ACCEPTED",
    "EVIDENCE_PACKAGE_MISSING_ACCEPTED",
    "PLAN_UPDATED_NOT_EXECUTED",
    "EXECUTED_NOT_EVALUATED",
    "PROMPT_ASSETS_DISCONNECTED",
    "TASKCARDS_MISSING_ACCEPTED",
]

PROMPT_PATHS = {
    1: "docs/governance/prompts/prompt1-post-sprint-audit.md",
    2: "docs/governance/prompts/prompt2-plan-hardening.md",
    3: "docs/governance/prompts/prompt3-controlled-execution.md",
}

STAGE_DIRS = {
    1: "stage1-audit",
    2: "stage2-plan",
    3: "stage3-execution",
}


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_loop_state(run_dir: Path) -> dict[str, Any]:
    """Load or create loop state from run_dir/loop-state.json."""
    state_file = run_dir / "loop-state.json"
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {
        "run_id": run_dir.name,
        "current_state": "IDLE",
        "cycle_count": 0,
        "transitions": [],
        "summary_classification": None,
        "next_directive": None,
    }


def save_loop_state(state: dict[str, Any], run_dir: Path) -> Path:
    """Atomically write loop state."""
    state_file = run_dir / "loop-state.json"
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(state_file)
    return state_file


def append_event(event: dict[str, Any], run_dir: Path) -> None:
    """Append a decision event to the JSONL log."""
    event["timestamp"] = _now_iso()
    log_file = run_dir / "loop-events.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


# ---------------------------------------------------------------------------
# Transition logic
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""


def transition(state: dict[str, Any], to_state: str, reason: str) -> None:
    """Perform a state transition with validation."""
    from_state = state["current_state"]
    allowed = VALID_TRANSITIONS.get(from_state, [])
    if to_state not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from {from_state} to {to_state}. Allowed: {allowed}"
        )
    state["transitions"].append(
        {
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
            "timestamp": _now_iso(),
        }
    )
    state["current_state"] = to_state


def validate_no_invalid_final_state(state: dict[str, Any]) -> None:
    """Reject if current_state would be an invalid final state."""
    current = state["current_state"]
    if current in INVALID_FINAL_STATES:
        raise InvalidTransitionError(
            f"State '{current}' is never valid as a final state. "
            f"The controller must choose a concrete next stage."
        )


# ---------------------------------------------------------------------------
# Stage output parsing
# ---------------------------------------------------------------------------


def parse_stage1_output(run_dir: Path) -> dict[str, Any] | None:
    """Parse Stage 1 audit output.

    Validates issues.json against stage1-issue-model.schema.json when jsonschema
    is available.  Returns None if the file is absent or schema-invalid.
    """
    stage_dir = run_dir / STAGE_DIRS[1]
    issues_file = stage_dir / "issues.json"
    if not issues_file.exists():
        return None
    data = json.loads(issues_file.read_text(encoding="utf-8"))
    if JSONSCHEMA_AVAILABLE:
        schema_path = _repo_root() / "schemas" / "stage1-issue-model.schema.json"
        stage1_schema = _load_schema(schema_path)
        if stage1_schema is not None:
            try:
                jsonschema.validate(data, stage1_schema)
            except jsonschema.ValidationError as exc:
                logger.warning("Stage 1 issues.json failed schema validation: %s", exc.message)
                return None
    return data


def parse_stage2_output(run_dir: Path) -> dict[str, Any] | None:
    """Parse Stage 2 plan output using yaml.safe_load for the verdict file."""
    stage_dir = run_dir / STAGE_DIRS[2]
    verdict_file = stage_dir / "ready-for-execution-verdict.yaml"
    taskcards_file = stage_dir / "taskcards.jsonl"
    if not taskcards_file.exists():
        return None
    taskcards = []
    for line in taskcards_file.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            taskcards.append(json.loads(line))
    result: dict[str, Any] = {"taskcards": taskcards}
    if verdict_file.exists():
        if YAML_AVAILABLE:
            try:
                verdict_data = yaml.safe_load(verdict_file.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                logger.warning("Failed to parse ready-for-execution-verdict.yaml: %s", exc)
                verdict_data = {}
            if isinstance(verdict_data, dict):
                plan_verdict = verdict_data.get("plan_verdict", "")
                if plan_verdict:
                    result["plan_verdict"] = str(plan_verdict)
        else:
            # Fallback: single-line key: value extraction
            for vline in verdict_file.read_text(encoding="utf-8").splitlines():
                if vline.startswith("plan_verdict:"):
                    result["plan_verdict"] = vline.split(":", 1)[1].strip().strip('"')
    return result


def parse_stage3_output(run_dir: Path) -> dict[str, Any] | None:
    """Parse Stage 3 execution output.

    Uses yaml.safe_load for the summary file (supports multi-line values and
    YAML lists).  Validates quality-scores.json against the stage3 schema when
    jsonschema is available.
    """
    stage_dir = run_dir / STAGE_DIRS[3]
    summary_file = stage_dir / "final-sprint-summary.yaml"
    scores_file = stage_dir / "quality-scores.json"

    if not summary_file.exists():
        return {"summary_type": "MISSING"}

    # Parse summary with yaml.safe_load when available
    if YAML_AVAILABLE:
        try:
            summary = yaml.safe_load(summary_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse final-sprint-summary.yaml: %s", exc)
            summary = {}
        if not isinstance(summary, dict):
            summary = {}
    else:
        # Fallback: single-line key: value extraction (does not support YAML lists)
        summary = {}
        for line in summary_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, _, val = line.partition(":")
                summary[key.strip()] = val.strip().strip('"')

    # Check for structured vs prose
    if "verdict" not in summary or "summary_type" not in summary:
        summary["summary_type"] = "PROSE_ONLY"

    # Load and validate scores if available
    if scores_file.exists():
        scores_data = json.loads(scores_file.read_text(encoding="utf-8"))
        if JSONSCHEMA_AVAILABLE:
            schema_path = _repo_root() / "schemas" / "stage3-quality-score.schema.json"
            stage3_schema = _load_schema(schema_path)
            if stage3_schema is not None:
                try:
                    jsonschema.validate(scores_data, stage3_schema)
                except jsonschema.ValidationError as exc:
                    logger.warning(
                        "Stage 3 quality-scores.json failed schema validation: %s",
                        exc.message,
                    )
        summary["evaluations"] = scores_data.get("evaluations", [])
        summary["reroute_log"] = scores_data.get("reroute_log", [])
    else:
        summary["evaluations"] = []

    return summary


def parse_stage_output(stage: int, run_dir: Path) -> dict[str, Any] | None:
    """Parse output for a given stage number."""
    parsers = {1: parse_stage1_output, 2: parse_stage2_output, 3: parse_stage3_output}
    parser = parsers.get(stage)
    if not parser:
        return None
    return parser(run_dir)


# ---------------------------------------------------------------------------
# Summary classification
# ---------------------------------------------------------------------------


def classify_summary(stage3_output: dict[str, Any] | None) -> str:
    """Classify Stage 3 output into a summary classification."""
    if stage3_output is None:
        return "MISSING"

    summary_type = stage3_output.get("summary_type", "MISSING")

    if summary_type == "MISSING":
        return "MISSING"

    if summary_type == "PROSE_ONLY":
        return "PROSE_ONLY"

    # Check for blocked external
    verdict = stage3_output.get("verdict", "")
    if verdict == "BLOCKED_EXTERNAL":
        return "BLOCKED_EXTERNAL"

    # Check for evidence
    evidence_path = stage3_output.get("evidence_bundle_path")
    if evidence_path is None or evidence_path == "null":
        return "EVIDENCE_MISSING"

    # Check for scores
    evaluations = stage3_output.get("evaluations", [])
    if not evaluations:
        return "SCORES_MISSING"

    # Check for incomplete taskcards
    accepted_count = int(stage3_output.get("accepted_count", 0))
    rerouted_count = int(stage3_output.get("rerouted_count", 0))
    blocked_count = int(stage3_output.get("blocked_count", 0))
    total = accepted_count + rerouted_count + blocked_count
    if total == 0:
        return "TASKCARDS_INCOMPLETE"

    # Check for contradictions (handle both str and bool from yaml.safe_load)
    all_green = stage3_output.get("all_green", False)
    if isinstance(all_green, str):
        all_green = all_green.lower() == "true"
    elif not isinstance(all_green, bool):
        all_green = bool(all_green)
    reroute_log = stage3_output.get("reroute_log", [])
    open_issues = stage3_output.get("open_issues", [])

    if all_green and (reroute_log or open_issues):
        return "CONTRADICTORY"

    # Check scores for failures
    for ev in evaluations:
        v = ev.get("verdict", "")
        if v == "REROUTED":
            return "STRUCTURED_NOT_GREEN"

    if all_green:
        return "STRUCTURED_ALL_GREEN"

    return "STRUCTURED_NOT_GREEN"


# ---------------------------------------------------------------------------
# Next-stage decision
# ---------------------------------------------------------------------------


def decide_next_stage(state: dict[str, Any], classification: str, run_dir: Path) -> dict[str, Any]:
    """Determine the next directive based on summary classification."""
    directive: dict[str, Any] = {"reason": ""}

    if classification == "MISSING":
        directive = {
            "action": "RUN_PROMPT_1",
            "prompt_asset_path": PROMPT_PATHS[1],
            "input_dir": str(run_dir),
            "output_dir": str(run_dir / STAGE_DIRS[1]),
            "open_issues": [],
            "reason": "No sprint summary found. Running full audit cycle.",
        }
        transition(state, _rework_to_stage("STAGE1_PENDING", state), "Summary missing")

    elif classification == "PROSE_ONLY":
        directive = {
            "action": "RUN_PROMPT_2",
            "prompt_asset_path": PROMPT_PATHS[2],
            "input_dir": str(run_dir / STAGE_DIRS[1]),
            "output_dir": str(run_dir / STAGE_DIRS[2]),
            "open_issues": [],
            "reason": "Prose-only summary. Running plan hardening then execution.",
        }
        transition(
            state,
            _rework_to_stage("STAGE2_PENDING", state),
            "Prose-only summary requires plan hardening",
        )

    elif classification == "STRUCTURED_NOT_GREEN":
        directive = {
            "action": "RUN_PROMPT_2",
            "prompt_asset_path": PROMPT_PATHS[2],
            "input_dir": str(run_dir / STAGE_DIRS[3]),
            "output_dir": str(run_dir / STAGE_DIRS[2]),
            "open_issues": _extract_open_issues(run_dir),
            "reason": "Structured summary with open issues. Feeding to plan hardening.",
        }
        transition(
            state,
            _rework_to_stage("STAGE2_PENDING", state),
            "Structured but not all green",
        )

    elif classification == "EVIDENCE_MISSING":
        directive = {
            "action": "RUN_EVIDENCE_REPAIR",
            "prompt_asset_path": PROMPT_PATHS[3],
            "input_dir": str(run_dir / STAGE_DIRS[3]),
            "output_dir": str(run_dir / STAGE_DIRS[3]),
            "open_issues": [],
            "reason": "Evidence bundle missing. Running evidence repair.",
        }
        transition(
            state,
            _rework_to_stage("STAGE3_PENDING", state),
            "Evidence bundle missing",
        )

    elif classification == "SCORES_MISSING":
        directive = {
            "action": "RUN_QUALITY_SCORING",
            "prompt_asset_path": PROMPT_PATHS[3],
            "input_dir": str(run_dir / STAGE_DIRS[3]),
            "output_dir": str(run_dir / STAGE_DIRS[3]),
            "open_issues": [],
            "reason": "Quality scores missing. Running scoring.",
        }
        transition(
            state,
            _rework_to_stage("STAGE3_PENDING", state),
            "Quality scores missing",
        )

    elif classification == "TASKCARDS_INCOMPLETE":
        directive = {
            "action": "RUN_PROMPT_2",
            "prompt_asset_path": PROMPT_PATHS[2],
            "input_dir": str(run_dir / STAGE_DIRS[3]),
            "output_dir": str(run_dir / STAGE_DIRS[2]),
            "open_issues": [],
            "reason": "Taskcards incomplete. Running plan hardening.",
        }
        transition(
            state,
            _rework_to_stage("STAGE2_PENDING", state),
            "Taskcards incomplete",
        )

    elif classification == "CONTRADICTORY":
        directive = {
            "action": "RUN_PROMPT_1",
            "prompt_asset_path": PROMPT_PATHS[1],
            "input_dir": str(run_dir),
            "output_dir": str(run_dir / STAGE_DIRS[1]),
            "open_issues": [],
            "reason": "Contradictory summary (all-green claim but reroute log non-empty). Re-auditing.",
        }
        transition(
            state,
            _rework_to_stage("STAGE1_PENDING", state),
            "Contradictory summary",
        )

    elif classification == "BLOCKED_EXTERNAL":
        directive = {
            "action": "BLOCK",
            "reason": "True external blocker verified. Packaging evidence and stopping.",
        }
        transition(state, "TERMINATED", "Blocked by external dependency")

    elif classification == "STRUCTURED_ALL_GREEN":
        directive = {
            "action": "RUN_ADVERSARIAL_REVIEW",
            "prompt_asset_path": PROMPT_PATHS[1],
            "input_dir": str(run_dir / STAGE_DIRS[3]),
            "output_dir": str(run_dir / "adversarial-review"),
            "open_issues": [],
            "reason": "All green. Running adversarial review before acceptance.",
        }
        transition(state, "ADVERSARIAL_REVIEW", "All green — adversarial review")

    state["summary_classification"] = classification
    state["next_directive"] = directive
    return directive


def _rework_to_stage(target: str, state: dict[str, Any]) -> str:
    """Navigate through REWORK_PENDING if needed to reach the target stage."""
    current = state["current_state"]
    # If we can go directly, do so
    allowed = VALID_TRANSITIONS.get(current, [])
    if target in allowed:
        return target
    # Go through REWORK_PENDING first
    if "REWORK_PENDING" in allowed:
        transition(state, "REWORK_PENDING", "Rework required")
        return target
    # If at STAGE3_COMPLETE, go to REWORK_PENDING then target
    if current == "STAGE3_COMPLETE":
        transition(state, "REWORK_PENDING", "Rework required")
        return target
    return target


def _extract_open_issues(run_dir: Path) -> list[str]:
    """Extract open issue IDs from Stage 3 self-review."""
    issues_file = run_dir / STAGE_DIRS[3] / "self-review-issues.json"
    if not issues_file.exists():
        return []
    try:
        data = json.loads(issues_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            issues = data.get("issues", [])
        elif isinstance(data, list):
            issues = data
        else:
            return []
        return [i.get("issue_id", "") for i in issues if i.get("blocker")]
    except (json.JSONDecodeError, KeyError):
        return []


# ---------------------------------------------------------------------------
# Directive emission
# ---------------------------------------------------------------------------


def emit_directive(state: dict[str, Any], run_dir: Path) -> Path:
    """Write next-directive.json to run directory."""
    directive = state.get("next_directive", {})
    directive_file = run_dir / "next-directive.json"
    tmp = directive_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(directive, indent=2), encoding="utf-8")
    tmp.replace(directive_file)
    return directive_file


# ---------------------------------------------------------------------------
# Main controller cycle
# ---------------------------------------------------------------------------


def run_cycle(
    run_dir: Path, *, advance: bool = False, dry_run: bool = False, force_stage: int | None = None
) -> dict[str, Any]:
    """Run one controller cycle."""
    run_dir.mkdir(parents=True, exist_ok=True)

    state = load_loop_state(run_dir)
    current = state["current_state"]

    append_event(
        {"event": "cycle_start", "state": current, "advance": advance, "dry_run": dry_run},
        run_dir,
    )

    if force_stage is not None:
        # Force a specific stage
        target = f"STAGE{force_stage}_PENDING"
        if current != "IDLE":
            if "REWORK_PENDING" in VALID_TRANSITIONS.get(current, []):
                transition(state, "REWORK_PENDING", f"Forced to stage {force_stage}")
            elif current == "REWORK_PENDING":
                pass  # Already in rework
        if current == "IDLE" and target == "STAGE1_PENDING":
            transition(state, target, f"Forced to stage {force_stage}")
        elif state["current_state"] == "REWORK_PENDING":
            transition(state, target, f"Forced to stage {force_stage}")

        directive = {
            "action": f"RUN_PROMPT_{force_stage}",
            "prompt_asset_path": PROMPT_PATHS.get(force_stage, ""),
            "input_dir": str(run_dir),
            "output_dir": str(run_dir / STAGE_DIRS.get(force_stage, f"stage{force_stage}")),
            "open_issues": [],
            "reason": f"Forced to stage {force_stage} by operator.",
        }
        state["next_directive"] = directive

    elif current == "IDLE":
        # Initial state — start with Stage 1
        transition(state, "STAGE1_PENDING", "Initial loop start")
        directive = {
            "action": "RUN_PROMPT_1",
            "prompt_asset_path": PROMPT_PATHS[1],
            "input_dir": str(run_dir),
            "output_dir": str(run_dir / STAGE_DIRS[1]),
            "open_issues": [],
            "reason": "Starting fresh loop with audit.",
        }
        state["next_directive"] = directive

    elif advance:
        # Determine which stage just completed
        if current == "STAGE1_PENDING":
            s1 = parse_stage1_output(run_dir)
            if s1 is None:
                logger.warning("Stage 1 output not found. Cannot advance.")
            else:
                transition(state, "STAGE1_COMPLETE", "Stage 1 output parsed")
                transition(state, "STAGE2_PENDING", "Advancing to plan hardening")
                state["next_directive"] = {
                    "action": "RUN_PROMPT_2",
                    "prompt_asset_path": PROMPT_PATHS[2],
                    "input_dir": str(run_dir / STAGE_DIRS[1]),
                    "output_dir": str(run_dir / STAGE_DIRS[2]),
                    "open_issues": [],
                    "reason": "Stage 1 complete. Advancing to plan hardening.",
                }

        elif current == "STAGE2_PENDING":
            s2 = parse_stage2_output(run_dir)
            if s2 is None:
                logger.warning("Stage 2 output not found. Cannot advance.")
            else:
                verdict = s2.get("plan_verdict", "")
                if "NOT_READY" in verdict:
                    logger.warning("Plan not ready: %s", verdict)
                else:
                    transition(state, "STAGE2_COMPLETE", "Stage 2 output parsed")
                    transition(state, "STAGE3_PENDING", "Advancing to execution")
                    state["next_directive"] = {
                        "action": "RUN_PROMPT_3",
                        "prompt_asset_path": PROMPT_PATHS[3],
                        "input_dir": str(run_dir / STAGE_DIRS[2]),
                        "output_dir": str(run_dir / STAGE_DIRS[3]),
                        "open_issues": [],
                        "reason": "Stage 2 complete. Advancing to controlled execution.",
                    }

        elif current == "STAGE3_PENDING":
            s3 = parse_stage3_output(run_dir)
            transition(state, "STAGE3_COMPLETE", "Stage 3 output parsed")
            classification = classify_summary(s3)
            decide_next_stage(state, classification, run_dir)
            if classification == "STRUCTURED_ALL_GREEN":
                state["cycle_count"] = state.get("cycle_count", 0) + 1

        elif current == "ADVERSARIAL_REVIEW":
            # After adversarial review, require review-result.json with final_decision.
            # Directory existence alone is insufficient — content must be parsed.
            ar_dir = run_dir / "adversarial-review"
            review_result_file = ar_dir / "review-result.json"
            if not review_result_file.exists():
                logger.warning(
                    "Adversarial review result not found or not parseable"
                    " — staying in ADVERSARIAL_REVIEW"
                )
            else:
                try:
                    review_result = json.loads(review_result_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Adversarial review result not parseable: %s"
                        " — staying in ADVERSARIAL_REVIEW",
                        exc,
                    )
                    review_result = None
                if review_result is not None:
                    final_decision = review_result.get("final_decision", "")
                    if final_decision == "ACCEPTED":
                        transition(state, "TERMINATED", "Adversarial review complete — accepted")
                        state["next_directive"] = {
                            "action": "ACCEPT",
                            "reason": "All green. Adversarial review passed. Loop complete.",
                        }
                    elif final_decision == "REROUTED":
                        reroute_reason = review_result.get(
                            "reason", "Adversarial review required rework"
                        )
                        logger.info("Adversarial review REROUTED: %s", reroute_reason)
                        transition(state, "REWORK_PENDING", "Adversarial review required rework")
                        state["next_directive"] = {
                            "action": "RUN_PROMPT_2",
                            "prompt_asset_path": PROMPT_PATHS[2],
                            "input_dir": str(run_dir / STAGE_DIRS[3]),
                            "output_dir": str(run_dir / STAGE_DIRS[2]),
                            "open_issues": review_result.get("challenges", []),
                            "reason": reroute_reason,
                        }
                    else:
                        logger.warning(
                            "Adversarial review result has unknown final_decision: %r"
                            " — staying in ADVERSARIAL_REVIEW",
                            final_decision,
                        )

    validate_no_invalid_final_state(state)

    append_event(
        {
            "event": "cycle_end",
            "state": state["current_state"],
            "classification": state.get("summary_classification"),
            "directive_action": (state.get("next_directive") or {}).get("action"),
        },
        run_dir,
    )

    if not dry_run:
        save_loop_state(state, run_dir)
        emit_directive(state, run_dir)

    return state


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post-Sprint Autonomy Loop Controller")
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Path to the sprint-loop run directory",
    )
    parser.add_argument(
        "--advance",
        action="store_true",
        help="Advance the loop after the current stage completes",
    )
    parser.add_argument(
        "--force-stage",
        type=int,
        choices=[1, 2, 3],
        help="Force the loop to a specific stage",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without persisting state",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        state = run_cycle(
            args.run_dir,
            advance=args.advance,
            dry_run=args.dry_run,
            force_stage=args.force_stage,
        )
    except InvalidTransitionError as exc:
        logger.error("Invalid transition: %s", exc)
        return 1

    directive = state.get("next_directive") or {}
    logger.info("State: %s", state["current_state"])
    logger.info("Classification: %s", state.get("summary_classification", "N/A"))
    logger.info("Next action: %s", directive.get("action", "N/A"))
    logger.info("Reason: %s", directive.get("reason", "N/A"))

    if args.dry_run:
        print(json.dumps(state, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
