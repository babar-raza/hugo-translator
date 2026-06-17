"""TC-AGT-11: Run-history-backed model selection.

Selects the best translation model for a (site, language) pair based on
historical run quality data. Falls back to the configured default model
when insufficient history is available.

Data sources:
- continuation_state.json runs_history (acceptance rates per run)
- validation_metrics.jsonl (per-file validation outcomes)

Selection logic:
1. Collect historical outcomes for the (site, lang) pair
2. Compute acceptance rate per model used
3. Rank models by acceptance rate
4. Return the top-ranked model, or default if insufficient data

Config section in global.yaml:
    model_selector:
      enabled: false
      min_history_runs: 5
      default_model: m2m100
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VALIDATION_METRICS_FILE = Path("data/logs/validation_metrics.jsonl")


@dataclass
class ModelScore:
    """Tracks quality metrics for a model on a specific (site, lang) pair."""

    model_id: str
    total_files: int = 0
    accepted_files: int = 0
    rejected_files: int = 0
    retried_files: int = 0

    @property
    def acceptance_rate(self) -> float:
        if self.total_files == 0:
            return 0.0
        return self.accepted_files / self.total_files


@dataclass
class ModelRecommendation:
    """Result of model selection."""

    recommended_model: str
    reason: str
    confidence: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    fallback_used: bool = False


def _extract_site_from_path(file_path: str) -> str:
    """Extract site_id from a validation metrics file path.

    Paths follow the pattern: .../content/{domain}/{product}/en/...
    e.g. "D:\\...\\docs.aspose.net\\words\\en\\..." → "docs.aspose.net.words"
    """
    parts = Path(file_path).parts
    # Find "en" (source language dir) and walk back to get domain.product
    for i, part in enumerate(parts):
        if part == "en" and i >= 2:
            domain = parts[i - 2]  # e.g. "docs.aspose.net"
            product = parts[i - 1]  # e.g. "words"
            return f"{domain}.{product}"
    return ""


def _load_validation_metrics(
    site_id: str,
    target_lang: str,
    *,
    metrics_file: Path | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Load validation metrics entries for a (site, lang) pair.

    The real JSONL schema (from decision_engine.py) uses ``lang`` (not
    ``target_lang``) and has no ``site_id`` field — the site is inferred
    from the ``file`` path.  For backward compatibility with synthetic test
    data that may use ``site_id``/``target_lang``, both field names are
    accepted.
    """
    path = metrics_file or _VALIDATION_METRICS_FILE
    if not path.exists():
        return []
    entries = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                # Accept both real schema (lang, file) and synthetic (target_lang, site_id)
                entry_lang = entry.get("lang") or entry.get("target_lang", "")
                entry_site = entry.get("site_id") or _extract_site_from_path(entry.get("file", ""))
                if entry_site == site_id and entry_lang == target_lang:
                    entries.append(entry)
                    if len(entries) >= limit:
                        break
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.warning("model_selector: failed to load metrics: %s", e)
    return entries


def _load_run_history(
    site_id: str,
    target_lang: str,
    *,
    continuation_state_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Load run history entries for a (site, lang) pair from continuation state."""
    from src.workers.continuation_state import get_run_history

    history = get_run_history(limit=50, state_file=continuation_state_file)
    matching = []
    for run in history:
        if run.get("site_id") == site_id:
            if target_lang in run.get("langs", []):
                matching.append(run)
    return matching


def compute_model_scores(
    metrics: list[dict[str, Any]],
    *,
    default_model: str = "unknown",
) -> dict[str, ModelScore]:
    """Compute per-model quality scores from validation metrics.

    Handles both real JSONL (``decision`` as int 0/1/2 per
    ``ValidationDecision`` enum, no ``model_id``) and synthetic test data
    (``decision`` as string "ACCEPT"/"REJECT"/"RETRY", ``model_id`` present).
    """
    scores: dict[str, ModelScore] = {}
    for entry in metrics:
        model = entry.get("model_id") or default_model
        if model not in scores:
            scores[model] = ModelScore(model_id=model)
        score = scores[model]
        score.total_files += 1
        decision = entry.get("decision", "")
        if decision in (0, "ACCEPT"):
            score.accepted_files += 1
        elif decision in (2, "REJECT"):
            score.rejected_files += 1
        elif decision in (1, "RETRY"):
            score.retried_files += 1
    return scores


def select_model(
    site_id: str,
    target_lang: str,
    *,
    config: dict[str, Any] | None = None,
    metrics_file: Path | None = None,
    continuation_state_file: Path | None = None,
) -> ModelRecommendation:
    """Select the best model for a (site, lang) pair.

    Args:
        site_id: Translation site identifier.
        target_lang: Target language code.
        config: Model selector config from global.yaml.
        metrics_file: Path to validation_metrics.jsonl.
        continuation_state_file: Path to continuation_state.json.

    Returns:
        ModelRecommendation with the selected model and reasoning.
    """
    cfg = config or {}
    enabled = cfg.get("enabled", False)
    min_runs = cfg.get("min_history_runs", 5)
    default_model = cfg.get("default_model", "m2m100")

    if not enabled:
        return ModelRecommendation(
            recommended_model=default_model,
            reason="Model selector disabled — using default",
            fallback_used=True,
        )

    # Load validation metrics
    metrics = _load_validation_metrics(site_id, target_lang, metrics_file=metrics_file)

    if len(metrics) < min_runs:
        return ModelRecommendation(
            recommended_model=default_model,
            reason=f"Insufficient history ({len(metrics)} < {min_runs}) — using default",
            fallback_used=True,
        )

    # Compute scores per model
    scores = compute_model_scores(metrics, default_model=default_model)

    if not scores:
        return ModelRecommendation(
            recommended_model=default_model,
            reason="No model scores computed — using default",
            fallback_used=True,
        )

    # Rank by acceptance rate (descending), break ties by total_files (more data = more confidence)
    ranked = sorted(
        scores.values(),
        key=lambda s: (s.acceptance_rate, s.total_files),
        reverse=True,
    )

    best = ranked[0]
    candidates = [
        {
            "model_id": s.model_id,
            "acceptance_rate": round(s.acceptance_rate, 4),
            "total_files": s.total_files,
            "accepted": s.accepted_files,
            "rejected": s.rejected_files,
        }
        for s in ranked
    ]

    confidence = min(1.0, best.total_files / (min_runs * 2))

    recommendation = ModelRecommendation(
        recommended_model=best.model_id,
        reason=f"Best acceptance rate: {best.acceptance_rate:.2%} ({best.accepted_files}/{best.total_files})",
        confidence=confidence,
        candidates=candidates,
        fallback_used=False,
    )

    logger.info(
        "model_selector: site=%s lang=%s → %s (rate=%.2f%%, confidence=%.2f)",
        site_id,
        target_lang,
        best.model_id,
        best.acceptance_rate * 100,
        confidence,
    )
    return recommendation
