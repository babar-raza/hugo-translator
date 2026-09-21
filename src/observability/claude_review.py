"""Claude review protocol: supervisory verdict schema, queues, and the STOP trigger (TC-APT-012).

Mission ``aspose-org-full-portfolio-translation-20260901``, plan sections 9.1-9.3 and 10.

* :class:`ClaudeReviewResult` is the mission's supervisory artifact -- the ONLY verdict with
  authority to halt production (plan section 10).  It is modelled on ``FidelityVerdict``'s shape
  but deliberately does **not** copy its fail-open behaviour: a review that cannot be produced
  resolves to ``BLOCKED_EXTERNAL`` with a ``recommended_action``, never to a missing result a
  caller could mistake for "nothing to review" (plan 2.7 / 9.3).
* Two queues (plan 9.1): the **Block-Queue** (every failure whose gate is one of the 13
  unvalidated gates 31-35 / 37-44, or an ``llm_provider_failure``) is mandatory at batch size 1;
  the **Accepted-Sample-Queue** is stratified sampling of receipted output, forced to batch size
  1 for risk-flagged files (fallback-produced, retried, gate-36 warn, revalidated, hallucination-
  routed, drift-adjacent).
* Verdicts are appended to ``data/campaigns/<id>/claude_reviews.jsonl``; only a redacted pointer
  goes into the work ledger's ``claude_review_result`` field (the ledger stays content-free).
* :func:`stop_decision` implements plan section 10 step 1: a ``REJECT_SYSTEMIC`` /
  ``REJECT_ISOLATED`` verdict stops new work for the affected scope and names the blast-radius
  query the heal cycle must run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

#: The 13 write gates that ship as literal `warn` and have never had a false-positive check
#: (plan 2.3). Any failure on one of these is mandatory Block-Queue review at batch size 1.
UNVALIDATED_GATE_IDS: frozenset[int] = frozenset(
    {31, 32, 33, 34, 35, 37, 38, 39, 40, 41, 42, 43, 44}
)
LLM_PROVIDER_FAILURE = "llm_provider_failure"
#: Risk flags that force a sampled file to batch size 1 (plan 9.1).
RISK_FLAGS: tuple[str, ...] = (
    "fallback_produced",
    "retried",
    "gate36_warn",
    "revalidated_receipt",
    "hallucination_routed",
    "drift_adjacent",
)
Verdict = Literal["APPROVE", "REJECT_SYSTEMIC", "REJECT_ISOLATED", "BLOCKED_EXTERNAL"]
PIPELINE_STAGES: tuple[str, ...] = (
    "parse",
    "extract",
    "mask",
    "inference",
    "validate",
    "reconstruct",
    "write_gate",
    "tm",
)
#: Reused from src/observability/blocker_classifier.py's taxonomy (plan section 10 step 4).
BLOCKER_CATEGORIES: tuple[str, ...] = (
    "CONFIG_ERROR",
    "DATA_QUALITY",
    "MODEL_LIMITATION",
    "EXTERNAL_DEPENDENCY",
    "RESOURCE_EXHAUSTION",
    "UNKNOWN",
)


class ClaudeReviewIssue(BaseModel):
    category: str
    severity: Literal["info", "warning", "critical"]
    description: str
    gate_id_correlate: int | None = None
    unit_fingerprint: str | None = None  # truncated sha256, never raw text


class ClaudeReviewResult(BaseModel):
    review_id: str
    campaign_id: str
    batch_id: str
    source_path: str
    output_path: str
    target_lang: str
    source_sha256: str
    output_sha256: str
    reviewed_at: str
    reviewer_model: str = "claude-sonnet-5"
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    issues: list[ClaudeReviewIssue] = Field(default_factory=list)
    gate_hits_reviewed: list[int] = Field(default_factory=list)
    fidelity_verdict_ref: dict[str, Any] | None = None
    judge_claude_disagreement: bool = False
    systemic_scope: dict[str, Any] | None = None
    recommended_action: str = ""
    linked_regression_fixture: str | None = None

    @property
    def is_rejection(self) -> bool:
        return self.verdict in ("REJECT_SYSTEMIC", "REJECT_ISOLATED")

    def ledger_pointer(self) -> dict[str, Any]:
        """Redacted pointer for the work ledger (content-free by construction)."""
        return {
            "review_id": self.review_id,
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "reviewed_at": self.reviewed_at,
            "issue_count": len(self.issues),
        }


def new_review_id(output_path: str, target_lang: str) -> str:
    stem = Path(output_path).stem[:40].replace(" ", "-")
    return f"rev-{target_lang}-{stem}-{uuid.uuid4().hex[:8]}"


def blocked_external(
    *,
    campaign_id: str,
    batch_id: str,
    source_path: str,
    output_path: str,
    target_lang: str,
    source_sha256: str,
    output_sha256: str,
    reason: str,
    recommended_action: str,
    reviewer_model: str = "claude-sonnet-5",
) -> ClaudeReviewResult:
    """A review that could not be completed -- explicit, never a silent pass (plan 9.3)."""
    return ClaudeReviewResult(
        review_id=new_review_id(output_path, target_lang),
        campaign_id=campaign_id,
        batch_id=batch_id,
        source_path=source_path,
        output_path=output_path,
        target_lang=target_lang,
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        reviewer_model=reviewer_model,
        verdict="BLOCKED_EXTERNAL",
        confidence=0.0,
        issues=[
            ClaudeReviewIssue(
                category="review_unavailable", severity="critical", description=reason
            )
        ],
        recommended_action=recommended_action,
    )


# --------------------------------------------------------------------------- queues
def is_block_queue_failure(failure: dict[str, Any]) -> bool:
    """True for a failure that MUST be reviewed at batch size 1 (plan 9.1)."""
    gate = failure.get("gate")
    if isinstance(gate, str) and gate.strip() == LLM_PROVIDER_FAILURE:
        return True
    try:
        return int(gate) in UNVALIDATED_GATE_IDS
    except (TypeError, ValueError):
        return str(failure.get("reason", "")).strip() == LLM_PROVIDER_FAILURE


def build_block_queue(failures: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every unvalidated-gate / provider failure, deduplicated by (output, lang), batch size 1."""
    seen: set[tuple[str, str]] = set()
    queue: list[dict[str, Any]] = []
    for failure in failures:
        if not is_block_queue_failure(failure):
            continue
        key = (str(failure.get("output_path", "")), str(failure.get("target_lang", "")))
        if key in seen:
            continue
        seen.add(key)
        queue.append({**failure, "batch_size": 1, "queue": "block", "mandatory": True})
    return queue


def risk_flags_of(receipt: dict[str, Any]) -> list[str]:
    """Risk flags a receipt carries (plan 9.1 forced-batch-size-1 conditions)."""
    flags: list[str] = []
    if receipt.get("provider_model") and receipt.get("provider_model") != receipt.get(
        "primary_model", receipt.get("provider_model")
    ):
        flags.append("fallback_produced")
    if receipt.get("rerouted") or receipt.get("fallback_used"):
        flags.append("fallback_produced")
    if int(receipt.get("attempt", 1) or 1) > 1 or receipt.get("retried"):
        flags.append("retried")
    gate36 = (receipt.get("gate_results") or {}).get("36") or (
        receipt.get("gate_results") or {}
    ).get(36)
    if isinstance(gate36, dict) and str(gate36.get("action", "")).lower() in ("warn", "warning"):
        flags.append("gate36_warn")
    if receipt.get("receipt_recovery") or receipt.get("revalidated"):
        flags.append("revalidated_receipt")
    if receipt.get("content_type_route") == "hallucination_prone" or receipt.get(
        "hallucination_routed"
    ):
        flags.append("hallucination_routed")
    if receipt.get("drift_adjacent"):
        flags.append("drift_adjacent")
    return sorted(set(flags))


def build_accepted_sample_queue(
    receipts: Sequence[dict[str, Any]],
    *,
    sample_size: int = 25,
    strata: Sequence[str] = ("site_id", "target_lang"),
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Stratified sample of receipted output; risk-flagged receipts are always included at size 1.

    Sampling is deterministic (sorted by receipt_sha256 within each stratum) so a review batch is
    reproducible from the ledger alone.
    """
    forced = [r for r in receipts if risk_flags_of(r)]
    remaining = [r for r in receipts if not risk_flags_of(r)]
    buckets: dict[tuple, list[dict[str, Any]]] = {}
    for receipt in remaining:
        key = tuple(str(receipt.get(field, "")) for field in strata)
        buckets.setdefault(key, []).append(receipt)
    for key in buckets:
        buckets[key].sort(key=lambda r: str(r.get("receipt_sha256", "")))
    sampled: list[dict[str, Any]] = []
    if buckets:
        index = 0
        keys = sorted(buckets)
        while len(sampled) < max(0, sample_size - len(forced)):
            progressed = False
            for key in keys:
                bucket = buckets[key]
                if index < len(bucket):
                    sampled.append(bucket[index])
                    progressed = True
                    if len(sampled) >= max(0, sample_size - len(forced)):
                        break
            if not progressed:
                break
            index += 1
    queue = [
        {
            **r,
            "queue": "accepted_sample",
            "batch_size": 1,
            "risk_flags": risk_flags_of(r),
            "mandatory": True,
        }
        for r in forced
    ]
    queue += [
        {
            **r,
            "queue": "accepted_sample",
            "batch_size": len(sampled),
            "risk_flags": [],
            "mandatory": False,
        }
        for r in sampled
    ]
    return queue


# --------------------------------------------------------------------------- persistence
def reviews_path(campaign_id: str, root: Path = Path("data/campaigns")) -> Path:
    return root / campaign_id / "claude_reviews.jsonl"


def append_review(result: ClaudeReviewResult, root: Path = Path("data/campaigns")) -> Path:
    path = reviews_path(result.campaign_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result.model_dump(), sort_keys=True) + "\n")
    return path


def load_reviews(campaign_id: str, root: Path = Path("data/campaigns")) -> list[ClaudeReviewResult]:
    path = reviews_path(campaign_id, root)
    if not path.is_file():
        return []
    out: list[ClaudeReviewResult] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(ClaudeReviewResult(**json.loads(line)))
    return out


# --------------------------------------------------------------------------- STOP trigger
def stop_decision(result: ClaudeReviewResult) -> dict[str, Any]:
    """Plan section 10 step 1: what a verdict stops, and the blast-radius query to run next.

    REJECT_SYSTEMIC stops every shard sharing the implicated pipeline stage (portfolio-wide);
    REJECT_ISOLATED stops only the affected cell's shard.  BLOCKED_EXTERNAL stops nothing but
    marks the row.  APPROVE stops nothing.
    """
    if not result.is_rejection:
        return {
            "stop": False,
            "scope": "none",
            "reason": result.verdict,
            "mark_rows": result.verdict == "BLOCKED_EXTERNAL",
        }
    scope_info = result.systemic_scope or {}
    systemic = result.verdict == "REJECT_SYSTEMIC"
    return {
        "stop": True,
        "scope": "portfolio" if systemic else "shard",
        "reason": result.verdict,
        "pipeline_stage": scope_info.get("pipeline_stage"),
        "blocker_category": scope_info.get("blocker_category"),
        "affected_gate_ids": sorted(
            scope_info.get("affected_gate_ids", []) or result.gate_hits_reviewed
        ),
        "blast_radius_query": scope_info.get("blast_radius_query")
        or (
            f"audit_all_content.py --sites {Path(result.output_path).parts[1] if len(Path(result.output_path).parts) > 1 else 'all'}"
            if systemic
            else f"output_path == {result.output_path!r}"
        ),
        "required_cycle": "plan section 10: persist -> earliest checkpoint -> two-dimension root cause -> regression fixture -> producer-side fix -> TM invalidation -> verify_fix -> sentinel sample -> resume",
        "mark_rows": True,
    }
