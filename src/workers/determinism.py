"""Rerun-determinism contract and measurement (TC-APT-023, plan section 5.1 root cause 5).

Nothing in this codebase stated what a rerun of the same job is *supposed* to produce.  This
module writes that contract down and measures it, because a consistency regression cannot be
detected against a standard that was never defined.

**Contract.**  Given an unchanged source, an unchanged ``profile_fingerprint``, an unchanged
``protection_fingerprint`` and a verified-unchanged model identity (TC-APT-021), two independent
runs of the same job must produce output that is either

  * ``BYTE_IDENTICAL``, or
  * ``SEMANTICALLY_EQUIVALENT``: all 44 write gates pass on both runs **and** a token-level
    near-duplicate check clears the similarity threshold, or
  * ``DIVERGENT`` -- a contract violation to investigate.

Both rates are *measured and recorded as ongoing metrics*, never assumed to be 100%: a hosted
LLM at ``temperature: 0`` is documented to retain some provider-side nondeterminism, which this
system cannot remove and does not pretend to (plan 5.1 item 6).

``similarity_threshold`` is a **proposal** (0.95) to be calibrated against Gate-3/4 data.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any

DEFAULT_SIMILARITY_THRESHOLD = 0.95  # PROPOSAL, calibrate at Gate 3/4
DEFAULT_BASELINE_PATH = Path("data/quality/rerun_determinism_baseline.json")
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class Outcome(str, Enum):
    BYTE_IDENTICAL = "BYTE_IDENTICAL"
    SEMANTICALLY_EQUIVALENT = "SEMANTICALLY_EQUIVALENT"
    DIVERGENT = "DIVERGENT"


@dataclass
class PairResult:
    key: str
    outcome: Outcome
    similarity: float
    gates_passed_both: bool
    first_sha256: str
    second_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "outcome": self.outcome.value,
            "similarity": round(self.similarity, 4),
            "gates_passed_both": self.gates_passed_both,
            "first_sha256": self.first_sha256,
            "second_sha256": self.second_sha256,
        }


@dataclass
class DeterminismReport:
    fingerprints: dict[str, str]
    similarity_threshold: float
    pairs: list[PairResult] = field(default_factory=list)
    measured_at: str = ""

    @property
    def byte_identical_rate(self) -> float:
        return self._rate(Outcome.BYTE_IDENTICAL)

    @property
    def semantic_equivalence_rate(self) -> float:
        """Byte-identical OR semantically equivalent -- i.e. the contract-satisfying share."""
        if not self.pairs:
            return 0.0
        ok = sum(1 for p in self.pairs if p.outcome is not Outcome.DIVERGENT)
        return ok / len(self.pairs)

    @property
    def divergent_rate(self) -> float:
        return self._rate(Outcome.DIVERGENT)

    def _rate(self, outcome: Outcome) -> float:
        if not self.pairs:
            return 0.0
        return sum(1 for p in self.pairs if p.outcome is outcome) / len(self.pairs)

    def as_dict(self) -> dict[str, Any]:
        sims = [p.similarity for p in self.pairs]
        return {
            "taskcard": "TC-APT-023",
            "measured_at": self.measured_at or datetime.now(timezone.utc).isoformat(),
            "fingerprints": self.fingerprints,
            "similarity_threshold": self.similarity_threshold,
            "pairs": len(self.pairs),
            "byte_identical_rate": round(self.byte_identical_rate, 4),
            "semantic_equivalence_rate": round(self.semantic_equivalence_rate, 4),
            "divergent_rate": round(self.divergent_rate, 4),
            "similarity_median": round(statistics.median(sims), 4) if sims else None,
            "similarity_min": round(min(sims), 4) if sims else None,
            "divergent": [p.as_dict() for p in self.pairs if p.outcome is Outcome.DIVERGENT][:20],
            "results": [p.as_dict() for p in self.pairs],
        }


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def token_similarity(first: str, second: str) -> float:
    """Token-level near-duplicate ratio (1.0 = identical token sequences)."""
    a, b = _TOKEN_RE.findall(first), _TOKEN_RE.findall(second)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def classify_pair(
    key: str,
    first: str,
    second: str,
    *,
    gates_passed_both: bool = True,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> PairResult:
    """Apply the contract to one (run 1, run 2) output pair."""
    if first == second:
        return PairResult(
            key, Outcome.BYTE_IDENTICAL, 1.0, gates_passed_both, sha256(first), sha256(second)
        )
    similarity = token_similarity(first, second)
    equivalent = gates_passed_both and similarity >= similarity_threshold
    return PairResult(
        key,
        Outcome.SEMANTICALLY_EQUIVALENT if equivalent else Outcome.DIVERGENT,
        similarity,
        gates_passed_both,
        sha256(first),
        sha256(second),
    )


def measure(
    pairs: Iterable[tuple[str, str, str]],
    *,
    fingerprints: dict[str, str],
    gate_results: dict[str, bool] | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> DeterminismReport:
    """``pairs`` = (key, run1_output, run2_output); ``gate_results`` = key -> gates passed on both."""
    gate_results = gate_results or {}
    report = DeterminismReport(
        fingerprints=dict(fingerprints),
        similarity_threshold=similarity_threshold,
        measured_at=datetime.now(timezone.utc).isoformat(),
    )
    for key, first, second in pairs:
        report.pairs.append(
            classify_pair(
                key,
                first,
                second,
                gates_passed_both=gate_results.get(key, True),
                similarity_threshold=similarity_threshold,
            )
        )
    return report


def fingerprints_unchanged(
    baseline: dict[str, str], current: dict[str, str]
) -> tuple[bool, list[str]]:
    """The contract's precondition: it only binds while every fingerprint is unchanged."""
    changed = [k for k, v in baseline.items() if current.get(k) != v]
    return (not changed), changed


def compare_with_baseline(
    report: DeterminismReport,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    *,
    tolerance: float = 0.05,
) -> dict[str, Any]:
    """Gate-9 drift check: has determinism degraded since the Gate-3 baseline?

    Reports drift only when the fingerprints are unchanged -- a changed profile/protection/model
    fingerprint legitimately changes output, so it is a re-baseline event, not a regression.
    """
    if not baseline_path.is_file():
        return {"baseline": None, "drift": None, "note": "no baseline recorded yet"}
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    unchanged, changed = fingerprints_unchanged(
        baseline.get("fingerprints", {}), report.fingerprints
    )
    delta = report.semantic_equivalence_rate - float(baseline.get("semantic_equivalence_rate", 0.0))
    return {
        "baseline_measured_at": baseline.get("measured_at"),
        "baseline_semantic_equivalence_rate": baseline.get("semantic_equivalence_rate"),
        "current_semantic_equivalence_rate": round(report.semantic_equivalence_rate, 4),
        "delta": round(delta, 4),
        "fingerprints_unchanged": unchanged,
        "changed_fingerprints": changed,
        "drift": bool(unchanged and delta < -tolerance),
        "note": "a changed fingerprint is a re-baseline event, not a determinism regression"
        if not unchanged
        else "",
    }


def write_baseline(report: DeterminismReport, path: Path = DEFAULT_BASELINE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    return path


def translate_twice(
    backend: Any, texts: Sequence[str], src_lang: str, tgt_lang: str
) -> list[tuple[str, str, str]]:
    """Run the same batch through the same backend twice; returns (key, first, second) triples."""
    first, _, _ = backend.translate_with_token_counts(list(texts), src_lang, tgt_lang)
    second, _, _ = backend.translate_with_token_counts(list(texts), src_lang, tgt_lang)
    return [(f"{tgt_lang}:{i}", a, b) for i, (a, b) in enumerate(zip(first, second))]
