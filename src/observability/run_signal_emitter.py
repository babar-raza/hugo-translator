"""TC-AGT-01: Run signal emitter for reviewer-facing output.

Emits a JSON signal file after each translation run, containing
structured metadata consumable by external review systems (e.g.,
the recruitize-ai-review-agent via MCP).

Signal files are append-only and written to data/signals/.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_SIGNALS_DIR = Path("data/signals")


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class RunVerdict(str, Enum):
    CLEAN_RUN = "CLEAN_RUN"
    DEGRADED_RUN = "DEGRADED_RUN"
    FAILED_RUN = "FAILED_RUN"
    BLOCKED = "BLOCKED"


class ProductionSafety(str, Enum):
    SAFE = "SAFE"
    DEGRADED = "DEGRADED"
    UNSAFE = "UNSAFE"


class FileStats(BaseModel):
    processed: int = 0
    accepted: int = 0
    rejected: int = 0
    retried: int = 0


class ValidatorStats(BaseModel):
    run: int = 0
    passed: int = 0
    failed: int = 0


class LLMUsage(BaseModel):
    calls: int = 0
    tokens: int = 0
    model: str = ""
    dry_run: bool = True


class Blocker(BaseModel):
    id: str
    type: str
    description: str


class RunSignal(BaseModel):
    """Structured signal emitted after each translation run."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mission: str = "Content Translation"
    site_id: str = ""
    status: RunStatus = RunStatus.COMPLETED
    taskcard_ids: list[str] = Field(default_factory=list)
    lane_status: dict[str, str] = Field(default_factory=dict)
    files: FileStats = Field(default_factory=FileStats)
    validators: ValidatorStats = Field(default_factory=ValidatorStats)
    llm_usage: LLMUsage = Field(default_factory=LLMUsage)
    evidence_path: str = ""
    autonomy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    blockers: list[Blocker] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    verdict: RunVerdict = RunVerdict.CLEAN_RUN
    production_safety: ProductionSafety = ProductionSafety.SAFE
    next_action: str = ""
    run_summary: str = ""


def compute_verdict(files: FileStats) -> RunVerdict:
    """Compute run verdict from file statistics."""
    if files.processed == 0:
        return RunVerdict.BLOCKED
    if files.rejected > 0 and files.accepted == 0:
        return RunVerdict.FAILED_RUN
    if files.rejected > 0 or files.retried > 0:
        return RunVerdict.DEGRADED_RUN
    return RunVerdict.CLEAN_RUN


def compute_autonomy_score(
    manual_interventions: int = 0,
    total_decisions: int = 1,
) -> float:
    """Compute autonomy score (0-1) based on manual intervention ratio."""
    if total_decisions <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (manual_interventions / total_decisions)))


def emit_run_signal(
    signal: RunSignal,
    signals_dir: Path | None = None,
) -> Path:
    """Write a run signal to a JSON file.

    Args:
        signal: Validated RunSignal model.
        signals_dir: Directory for signal files (default: data/signals/).

    Returns:
        Path to the written signal file.
    """
    out_dir = signals_dir or _SIGNALS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"run-signal-{signal.run_id}.json"
    out_path = out_dir / filename

    data = signal.model_dump(mode="json")
    out_path.write_text(
        json.dumps(data, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Run signal emitted: %s", out_path)
    return out_path


def build_signal_from_run_stats(
    site_id: str,
    stats: dict[str, Any],
    llm_calls: int = 0,
    llm_tokens: int = 0,
    llm_model: str = "",
    llm_dry_run: bool = True,
    evidence_path: str = "",
    taskcard_ids: list[str] | None = None,
) -> RunSignal:
    """Build a RunSignal from translation run statistics.

    Args:
        site_id: Site identifier (e.g., "docs.aspose.net.words").
        stats: Translation run statistics dict (from engine/worker).
        llm_calls: Number of LLM API calls made.
        llm_tokens: Total tokens used in LLM calls.
        llm_model: LLM model ID used.
        llm_dry_run: Whether LLM was in dry-run mode.
        evidence_path: Path to evidence directory.
        taskcard_ids: Active taskcard IDs.

    Returns:
        Populated RunSignal ready for emission.
    """
    files = FileStats(
        processed=stats.get("files_processed", 0),
        accepted=stats.get("files_accepted", stats.get("translated", 0)),
        rejected=stats.get("files_rejected", stats.get("rejected", 0)),
        retried=stats.get("files_retried", stats.get("retried", 0)),
    )

    validators = ValidatorStats(
        run=stats.get("validators_run", 0),
        passed=stats.get("validators_passed", 0),
        failed=stats.get("validators_failed", 0),
    )

    verdict = compute_verdict(files)

    status = RunStatus.COMPLETED
    if verdict == RunVerdict.FAILED_RUN:
        status = RunStatus.FAILED
    elif verdict == RunVerdict.BLOCKED:
        status = RunStatus.ABORTED

    return RunSignal(
        site_id=site_id,
        status=status,
        files=files,
        validators=validators,
        llm_usage=LLMUsage(
            calls=llm_calls,
            tokens=llm_tokens,
            model=llm_model,
            dry_run=llm_dry_run,
        ),
        evidence_path=evidence_path,
        taskcard_ids=taskcard_ids or [],
        verdict=verdict,
        autonomy_score=compute_autonomy_score(),
    )
