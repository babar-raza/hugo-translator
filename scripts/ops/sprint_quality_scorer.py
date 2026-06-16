"""Sprint Quality Scorer.

Evaluates taskcard quality against the sprint quality rubric
(config/sprint_quality_rubric.yaml). Determines ACCEPTED, REROUTED,
or BLOCKED for each taskcard based on 15-dimension scoring.

Usage:
    python scripts/ops/sprint_quality_scorer.py --scores-file <path> [--dry-run]
    python scripts/ops/sprint_quality_scorer.py --scores-file <path> --rubric <path>

Reads quality-scores.json (or creates a template), evaluates against
the rubric, and writes verdict/reroute information back.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RUBRIC = Path("config/sprint_quality_rubric.yaml")

# All 15 dimensions in evaluation order
ALL_DIMENSIONS = [
    # Base (60%)
    "correctness",
    "completeness",
    "production_ready",
    "documentation",
    "testability",
    # Sprint (40%)
    "evidence_quality",
    "claim_verification",
    "root_cause_depth",
    "taskcard_precision",
    "dependency_mapping",
    "rollback_safety",
    "pilot_proof",
    "regression_check",
    "contract_compliance",
    "governance_adherence",
]

# Default weights (must sum to 1.0)
DEFAULT_WEIGHTS: dict[str, float] = {
    "correctness": 0.18,
    "completeness": 0.15,
    "production_ready": 0.15,
    "documentation": 0.06,
    "testability": 0.06,
    "evidence_quality": 0.04,
    "claim_verification": 0.04,
    "root_cause_depth": 0.04,
    "taskcard_precision": 0.04,
    "dependency_mapping": 0.04,
    "rollback_safety": 0.04,
    "pilot_proof": 0.04,
    "regression_check": 0.04,
    "contract_compliance": 0.04,
    "governance_adherence": 0.04,
}

CRITICAL_DIMENSIONS = {"correctness": 4.0, "completeness": 4.0}
OVERALL_MINIMUM = 4.0
DIMENSION_MINIMUM = 3.0


def load_rubric(rubric_path: Path) -> dict[str, float]:
    """Load weights from rubric YAML. Falls back to defaults."""
    if not rubric_path.exists():
        logger.warning("Rubric not found at %s, using defaults", rubric_path)
        return dict(DEFAULT_WEIGHTS)
    # Simple YAML parsing for weight values
    weights: dict[str, float] = {}
    try:
        text = rubric_path.read_text(encoding="utf-8")
        current_dim = None
        for line in text.splitlines():
            stripped = line.strip()
            # Detect dimension name (key with colon, indented under base/sprint)
            if stripped.endswith(":") and not stripped.startswith("#"):
                name = stripped[:-1].strip()
                if name in ALL_DIMENSIONS:
                    current_dim = name
            elif current_dim and stripped.startswith("weight:"):
                val = stripped.split(":", 1)[1].strip()
                # Strip inline comments (e.g., "0.18   # 0.30 * 0.60")
                if "#" in val:
                    val = val[: val.index("#")].strip()
                weights[current_dim] = float(val)
                current_dim = None
    except Exception as exc:
        logger.warning("Failed to parse rubric: %s. Using defaults.", exc)
        return dict(DEFAULT_WEIGHTS)

    # Fill any missing with defaults
    for dim in ALL_DIMENSIONS:
        if dim not in weights:
            weights[dim] = DEFAULT_WEIGHTS[dim]
    return weights


def compute_weighted_overall(scores: dict[str, float], weights: dict[str, float]) -> float:
    """Compute weighted overall score."""
    total = 0.0
    for dim in ALL_DIMENSIONS:
        score = scores.get(dim, 0.0)
        weight = weights.get(dim, 0.0)
        total += score * weight
    return round(total, 2)


def check_rework(scores: dict[str, float], weighted_overall: float) -> list[dict[str, Any]]:
    """Check which dimensions fail thresholds. Returns rework items."""
    rework_items: list[dict[str, Any]] = []

    # Check dimension minimums
    for dim in ALL_DIMENSIONS:
        score = scores.get(dim, 0.0)
        if score < DIMENSION_MINIMUM:
            rework_items.append(
                {
                    "dimension": dim,
                    "score": score,
                    "threshold": DIMENSION_MINIMUM,
                    "reason": f"{dim} scored {score}, below minimum {DIMENSION_MINIMUM}",
                }
            )

    # Check critical dimensions
    for dim, threshold in CRITICAL_DIMENSIONS.items():
        score = scores.get(dim, 0.0)
        if score < threshold and not any(r["dimension"] == dim for r in rework_items):
            rework_items.append(
                {
                    "dimension": dim,
                    "score": score,
                    "threshold": threshold,
                    "reason": f"Critical dimension {dim} scored {score}, below {threshold}",
                }
            )

    # Check overall
    if weighted_overall < OVERALL_MINIMUM:
        rework_items.append(
            {
                "dimension": "overall",
                "score": weighted_overall,
                "threshold": OVERALL_MINIMUM,
                "reason": f"Overall score {weighted_overall} below minimum {OVERALL_MINIMUM}",
            }
        )

    return rework_items


def evaluate_taskcard(
    taskcard_id: str,
    dimension_scores: dict[str, float],
    weights: dict[str, float],
) -> dict[str, Any]:
    """Evaluate a single taskcard and return its evaluation record."""
    weighted = compute_weighted_overall(dimension_scores, weights)
    rework = check_rework(dimension_scores, weighted)

    if rework:
        verdict = "REROUTED"
    else:
        verdict = "ACCEPTED"

    return {
        "taskcard_id": taskcard_id,
        "dimension_scores": dimension_scores,
        "weighted_overall": weighted,
        "verdict": verdict,
        "rework_items": rework,
        "reroute_count": 0,
    }


def evaluate_all(scores_data: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    """Evaluate all taskcards in a scores file."""
    evaluations = []
    reroute_log = []

    for ev in scores_data.get("evaluations", []):
        tc_id = ev.get("taskcard_id", "unknown")
        dim_scores = ev.get("dimension_scores", {})
        result = evaluate_taskcard(tc_id, dim_scores, weights)

        # Preserve reroute_count from input
        result["reroute_count"] = ev.get("reroute_count", 0)

        evaluations.append(result)

        if result["verdict"] == "REROUTED":
            reroute_log.append(
                {
                    "taskcard_id": tc_id,
                    "rerouted_at": "",
                    "reason": "; ".join(r["reason"] for r in result["rework_items"]),
                    "rework_owner": "agent",
                    "resolution": "REWORKED" if result["reroute_count"] > 0 else "REROUTED",
                }
            )

    # Build summary
    accepted = sum(1 for e in evaluations if e["verdict"] == "ACCEPTED")
    rerouted = sum(1 for e in evaluations if e["verdict"] == "REROUTED")
    all_green = rerouted == 0 and accepted > 0

    return {
        "run_id": scores_data.get("run_id", ""),
        "rubric_path": str(DEFAULT_RUBRIC),
        "evaluations": evaluations,
        "reroute_log": reroute_log,
        "final_sprint_summary": {
            "verdict": "EXECUTION_COMPLETE_VERIFIED"
            if all_green
            else "EXECUTION_REROUTED_REWORK_REQUIRED",
            "summary_type": "STRUCTURED",
            "all_green": all_green,
            "accepted_count": accepted,
            "rerouted_count": rerouted,
            "blocked_count": 0,
            "evidence_bundle_path": scores_data.get("evidence_bundle_path"),
            "open_issues": [],
        },
    }


def create_template(output_path: Path) -> None:
    """Create a template scores file for manual entry."""
    template = {
        "run_id": "template",
        "evaluations": [
            {
                "taskcard_id": "TC-EXAMPLE-01",
                "dimension_scores": dict.fromkeys(ALL_DIMENSIONS, 0),
                "weighted_overall": 0.0,
                "verdict": "",
                "rework_items": [],
                "reroute_count": 0,
            }
        ],
    }
    output_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
    logger.info("Template written to %s", output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sprint Quality Scorer")
    parser.add_argument(
        "--scores-file",
        type=Path,
        required=True,
        help="Path to quality-scores.json",
    )
    parser.add_argument(
        "--rubric",
        type=Path,
        default=DEFAULT_RUBRIC,
        help="Path to sprint quality rubric YAML",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without writing",
    )
    parser.add_argument(
        "--create-template",
        action="store_true",
        help="Create a template scores file",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.create_template:
        create_template(args.scores_file)
        return 0

    if not args.scores_file.exists():
        logger.error("Scores file not found: %s", args.scores_file)
        return 1

    weights = load_rubric(args.rubric)
    scores_data = json.loads(args.scores_file.read_text(encoding="utf-8"))
    result = evaluate_all(scores_data, weights)

    accepted = result["final_sprint_summary"]["accepted_count"]
    rerouted = result["final_sprint_summary"]["rerouted_count"]
    all_green = result["final_sprint_summary"]["all_green"]

    logger.info("Accepted: %d, Rerouted: %d, All green: %s", accepted, rerouted, all_green)

    if args.dry_run:
        print(json.dumps(result, indent=2))
    else:
        args.scores_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        logger.info("Results written to %s", args.scores_file)

    for entry in result.get("reroute_log", []):
        logger.warning("REROUTED: %s — %s", entry["taskcard_id"], entry["reason"])

    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
