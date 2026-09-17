"""Resumable, manifest-scoped zero-defect campaign execution."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from src.model_runtime.campaign_llm_policy import campaign_llm_scope
from src.tm.rejected_task_queue import RejectedTaskQueue
from src.tm.retry_records import RejectedTranslationTask
from src.utils.atomic_write import atomic_write
from src.utils.file_lock import FileLock, LockError
from src.workers.content_commit_title import content_commit_title
from src.workers.git_provenance import (
    GovernedProvenanceError,
    governed_subject_pattern,
    verify_governed_add,
)
from src.workers.heal_queue import active_hold, is_quarantined, is_source_path_quarantined

from .campaign_manifest import (
    CampaignManifest,
    CampaignManifestError,
    git_dirty_paths,
    legacy_integer_gate_receipt_fingerprint,
    receipt_fingerprint,
    sha256_file,
)

logger = logging.getLogger(__name__)


def _force_serialize_all_backends() -> bool:
    """Read the TC-APT-046 rollback switch.

    ``translation_engine.concurrency.force_serialize_all_backends`` defaults to
    ``True``: until a real canary at ``max_parallel_jobs > 1`` has proven otherwise,
    the campaign path behaves exactly as it did before TC-APT-044. Flipping the key
    to ``false`` needs no code change. A missing/unreadable config must not silently
    unserialize the run, so every failure resolves to ``True``.
    """
    try:
        from src.utils.config_loader import get_global_config

        config = get_global_config() or {}
    except Exception:  # pragma: no cover - config load is exercised elsewhere
        return True
    concurrency = (config.get("translation_engine") or {}).get("concurrency") or {}
    return bool(concurrency.get("force_serialize_all_backends", True))


class CampaignLedger:
    """Thread-safe metadata-only acceptance and rejection ledger."""

    def __init__(self, root: Path, campaign_id: str) -> None:
        self.root = root / campaign_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.receipts_path = self.root / "acceptance_receipts.jsonl"
        self.failures_path = self.root / "failure_metadata.jsonl"
        self.summary_path = self.root / "summary.json"
        self._process_lock_path = self.root / "ledger-process.lock"
        self._lock = threading.RLock()
        self._receipt_index = self.receipts()

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        # Stream line-by-line rather than path.read_text().splitlines(): that
        # held the whole file plus its split lines in memory at once, and
        # heal_queue.jsonl (10k+ lines and growing) triggered a real
        # MemoryError under 4-worker concurrent load (2026-09-17 full-portfolio
        # sweep, PID contention over shared system RAM alongside per-worker
        # model buffers).
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def receipts(self) -> dict[str, dict[str, Any]]:
        return {row["output_path"]: row for row in self._read_jsonl(self.receipts_path)}

    def append_receipt(self, receipt: dict[str, Any]) -> None:
        if "content" in receipt or "translated_content" in receipt:
            raise ValueError("campaign receipts must never contain candidate text")
        row = {
            **receipt,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }
        row["receipt_sha256"] = receipt_fingerprint(row)
        output = str(row.get("output_path") or "")
        if not output:
            raise ValueError("campaign receipt requires output_path")
        with self._lock, FileLock(self._process_lock_path, timeout=30):
            # Refresh under the inter-process lock: every shard worker has an
            # independent in-memory ledger index.
            self._receipt_index = self.receipts()
            previous = self._receipt_index.get(output)
            if previous is not None:
                comparable_previous = {
                    key: value
                    for key, value in previous.items()
                    if key not in {"accepted_at", "receipt_sha256"}
                }
                comparable_row = {
                    key: value
                    for key, value in row.items()
                    if key not in {"accepted_at", "receipt_sha256"}
                }
                if comparable_previous != comparable_row:
                    raise ValueError(f"conflicting acceptance receipt: {output}")
                return
            self._append_unlocked(self.receipts_path, row)
            self._receipt_index[output] = row

    def append_failure(
        self,
        *,
        source_path: str,
        output_path: str,
        target_lang: str,
        error: str,
        attempt: int = 0,
        job_id: str | None = None,
        gate: str = "pipeline",
        source_sha256: str | None = None,
        candidate_sha256: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self._append(
            self.failures_path,
            {
                "source_path": source_path,
                "output_path": output_path,
                "target_lang": target_lang,
                "job_id": job_id or f"{source_path}::{target_lang}::{output_path}",
                "gate": gate,
                "reason": error[:1000],
                "attempt": attempt,
                "source_sha256": source_sha256,
                "candidate_sha256": candidate_sha256,
                "model_id": model_id,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def latest_failure(self, *, output_path: str, target_lang: str) -> dict[str, Any] | None:
        """Return the latest metadata-only failure for a resumable job."""
        failures = self.recent_failures(
            output_path=output_path,
            target_lang=target_lang,
            limit=1,
        )
        return failures[-1] if failures else None

    def recent_failures(
        self,
        *,
        output_path: str,
        target_lang: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return recent metadata-only failures for cumulative retry guidance."""
        if limit < 1:
            raise ValueError("failure history limit must be positive")
        if not self.failures_path.is_file():
            return []
        matches: list[dict[str, Any]] = []
        with self.failures_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("output_path") == output_path and row.get("target_lang") == target_lang:
                    matches.append(row)
                    if len(matches) > limit:
                        matches.pop(0)
        return matches

    def replace_receipts(self, receipts: list[dict[str, Any]]) -> None:
        """Atomically replace metadata-only receipts after verified migration."""
        if any("content" in row or "translated_content" in row for row in receipts):
            raise ValueError("campaign receipts must never contain candidate text")
        encoded = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in receipts
        )
        with self._lock, FileLock(self._process_lock_path, timeout=30):
            atomic_write(
                path=self.receipts_path,
                content=encoded,
                encoding="utf-8",
                fsync=True,
                create_parents=True,
            )
            self._receipt_index = {str(row["output_path"]): row for row in receipts}

    def _append(self, path: Path, row: dict[str, Any]) -> None:
        with self._lock, FileLock(self._process_lock_path, timeout=30):
            self._append_unlocked(path, row)

    @staticmethod
    def _append_unlocked(path: Path, row: dict[str, Any]) -> None:
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

    def write_summary(self, payload: dict[str, Any]) -> None:
        # TC-PORT-LLM-009: summary.json is a reporting/progress artifact --
        # reconcile_receipted_commits.py and _validated_resume_receipts both
        # read acceptance_receipts.jsonl/commit_batches.jsonl directly and
        # never this file, so losing one write is recoverable (the next
        # write_summary call, or the next run, produces a fresh one).
        # Confirmed live under a real 4-worker soak: with 4 concurrent child
        # processes all finishing near the same moment, this call (including
        # the mid-run progress checkpoints, not just the final one) can hit
        # the same lock contention _append_heal_ticket already guards
        # against, and previously crashed the whole worker process over a
        # non-critical reporting write.
        try:
            with self._lock, FileLock(self._process_lock_path, timeout=30):
                atomic_write(
                    path=self.summary_path,
                    content=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                    fsync=True,
                    create_parents=True,
                )
        except LockError as exc:
            logger.error(
                "summary.json write timed out under lock contention (this "
                "write dropped, not fatal -- the next write_summary call or "
                "run produces a fresh one): %s",
                exc,
            )

    def model_outcomes(self) -> dict[str, dict[str, int]]:
        """Return candidate-free, current-campaign model dispositions."""
        outcomes: dict[str, dict[str, int]] = {}

        def bucket(model_id: str) -> dict[str, int]:
            return outcomes.setdefault(
                model_id or "unknown",
                {"accepted": 0, "rejected": 0, "provider_error": 0, "queued": 0},
            )

        for receipt in self.receipts().values():
            bucket(str(receipt.get("model_fingerprint") or "unknown"))["accepted"] += 1
        for failure in self._read_jsonl(self.failures_path):
            model = bucket(str(failure.get("model_id") or "unknown"))
            if str(failure.get("gate")) == "campaign_job_exception":
                model["provider_error"] += 1
            else:
                model["rejected"] += 1
        retry_outcomes = self.retry_queue_outcomes()
        # A deferred campaign writes a human-facing heal ticket *and* its
        # canonical SQLite retry task.  Once the latter exists it is the
        # lifecycle authority; counting both would leave an ACCEPTED retry
        # falsely reported as still queued.
        if not retry_outcomes:
            for ticket in self._read_jsonl(self.root.parent / "heal_queue.jsonl"):
                if ticket.get("campaign_id") != self.root.name:
                    continue
                bucket(str(ticket.get("processing_model") or "unknown"))["queued"] += 1
        for outcome in retry_outcomes:
            counts = bucket(str(outcome["model_target"]))
            if outcome["state"] == "ACCEPTED":
                counts["accepted"] += 1
            elif outcome["state"] in {"QUEUED", "CLAIMED"}:
                counts["queued"] += 1
            elif outcome["state"] == "DEAD_LETTER":
                counts["rejected"] += 1
        return dict(sorted(outcomes.items()))

    def retry_queue_outcomes(self) -> list[dict[str, Any]]:
        """Read deferred retry dispositions for this campaign, if its queue exists."""
        path = self.root.parent / "rejected_tasks.sqlite3"
        if not path.is_file():
            return []
        return RejectedTaskQueue(path).campaign_outcomes(self.root.name)

    def attempt_model_outcomes(self) -> dict[str, dict[str, dict[str, int]]]:
        """Return active-campaign, candidate-free outcomes by model and attempt.

        Failure metadata is append-only: a duplicate-retry suppression can add a
        second row for the same invocation.  Count each ``job_id``/attempt/model
        tuple once so summary counters describe provider/model attempts rather
        than ledger writes.  Older receipts without the additive attempt fields
        remain readable under ``unknown``.
        """
        outcomes: dict[str, dict[str, dict[str, int]]] = {}

        def bucket(model_id: str, attempt: int | str) -> dict[str, int]:
            return outcomes.setdefault(model_id or "unknown", {}).setdefault(
                str(attempt),
                {"attempted": 0, "accepted": 0, "rejected": 0, "provider_error": 0},
            )

        seen: set[tuple[str, str, str]] = set()
        for failure in self._read_jsonl(self.failures_path):
            model_id = str(failure.get("model_id") or "unknown")
            attempt = str(failure.get("attempt") if failure.get("attempt") is not None else "unknown")
            key = (str(failure.get("job_id") or failure.get("output_path") or "unknown"), attempt, model_id)
            if key in seen:
                continue
            seen.add(key)
            counts = bucket(model_id, attempt)
            counts["attempted"] += 1
            if str(failure.get("gate")) == "campaign_job_exception":
                counts["provider_error"] += 1
            else:
                counts["rejected"] += 1

        for receipt in self.receipts().values():
            model_id = str(
                receipt.get("attempt_model_id") or receipt.get("model_fingerprint") or "unknown"
            )
            attempt = str(receipt.get("campaign_attempt") if receipt.get("campaign_attempt") is not None else "unknown")
            key = (str(receipt.get("output_path") or "unknown"), attempt, model_id)
            counts = bucket(model_id, attempt)
            # A receipt may follow failure metadata for the same invocation
            # only in malformed legacy artifacts.  Do not inflate attempts.
            if key not in seen:
                seen.add(key)
                counts["attempted"] += 1
            counts["accepted"] += 1

        return {
            model_id: {attempt: dict(counts) for attempt, counts in sorted(by_attempt.items())}
            for model_id, by_attempt in sorted(outcomes.items())
        }

    def zero_acceptance_recommendations(
        self,
        *,
        warning_after_attempts: int,
        stop_recommendation_after_attempts: int,
    ) -> dict[str, Any]:
        """Return advisory systemic-failure recommendations; never stop a run."""
        if warning_after_attempts < 1 or stop_recommendation_after_attempts < warning_after_attempts:
            raise ValueError("zero-acceptance thresholds must be positive and ordered")
        recommendations: list[dict[str, Any]] = []
        for model_id, by_attempt in self.attempt_model_outcomes().items():
            attempted = sum(counts["attempted"] for counts in by_attempt.values())
            accepted = sum(counts["accepted"] for counts in by_attempt.values())
            if attempted < warning_after_attempts or accepted:
                continue
            recommendations.append(
                {
                    "model_id": model_id,
                    "attempted": attempted,
                    "accepted": accepted,
                    "recommendation": (
                        "recommend_pause_and_investigate"
                        if attempted >= stop_recommendation_after_attempts
                        else "warn_and_continue"
                    ),
                }
            )
        return {
            "warning_after_attempts": warning_after_attempts,
            "stop_recommendation_after_attempts": stop_recommendation_after_attempts,
            "recommendations": recommendations,
        }

    def llm_call_outcomes(self) -> dict[str, dict[str, int]]:
        """Summarize policy-accounted LLM calls without candidate payloads."""
        outcomes: dict[str, dict[str, int]] = {}
        for event in self._read_jsonl(self.root / "llm_calls.jsonl"):
            category = str(event.get("category") or "unknown")
            outcome = str(event.get("outcome") or "unknown")
            outcomes.setdefault(category, {})[outcome] = (
                outcomes.setdefault(category, {}).get(outcome, 0) + 1
            )
        return {
            category: dict(sorted(counts.items()))
            for category, counts in sorted(outcomes.items())
        }

    def acceleration_metrics(self) -> dict[str, int]:
        """Aggregate receipt-bound fast-path facts without reading candidate text."""
        fields = (
            "i18n_hits", "tm_hits", "l1_hits", "l2_hits", "semantic_tm_hits",
            "professionalize_calls", "ast_batches", "individual_fallback_batches",
            "validation_retries",
        )
        totals = {field: 0 for field in fields}
        for receipt in self.receipts().values():
            metrics = receipt.get("translation_stats") or {}
            for field in fields:
                try:
                    totals[field] += int(metrics.get(field, 0) or 0)
                except (TypeError, ValueError):
                    # A malformed historical receipt must remain visible but
                    # cannot make status reporting fail during recovery.
                    continue
        return totals


class CampaignRunner:
    """Execute only jobs enumerated by a pinned CampaignManifest."""

    # TC-APT-046: retry budget handed to the dedicated, out-of-process
    # Professionalize retry consumer for a deferred campaign's terminal
    # heal ticket (src/workers/professionalize_retry_worker.py).
    _DEFERRED_RETRY_BUDGET = 2

    _LOCALE_NAMES = {
        "ar": "Arabic",
        "cs": "Czech",
        "de": "German",
        "el": "Greek",
        "es": "Spanish",
        "fa": "Persian",
        "fr": "French",
        "he": "Hebrew",
        "hi": "Hindi",
        "hu": "Hungarian",
        "id": "Indonesian",
        "it": "Italian",
        "ja": "Japanese",
        "ko": "Korean",
        "nl": "Dutch",
        "pl": "Polish",
        "pt": "Portuguese",
        "ro": "Romanian",
        "ru": "Russian",
        "sv": "Swedish",
        "th": "Thai",
        "tr": "Turkish",
        "uk": "Ukrainian",
        "vi": "Vietnamese",
        "zh": "Chinese",
    }
    _LOCALE_SCRIPT_HINTS = {
        "ar": "Arabic script",
        "el": "Greek script",
        "fa": "Persian script",
        "he": "Hebrew script",
        "hi": "Devanagari script",
        "ja": "Japanese script",
        "ko": "Hangul",
        "ru": "Cyrillic script",
        "th": "Thai script",
        "uk": "Cyrillic script",
        "zh": "Chinese Han characters",
    }
    _PRODUCT_LINK_LABEL_TRANSLATIONS = {
        "ar": "Aspose.Words لـ .NET",
        "cs": "Aspose.Words pro .NET",
        "de": "Aspose.Words für .NET",
        "el": "Aspose.Words για .NET",
        "es": "Aspose.Words para .NET",
        "fa": "Aspose.Words برای .NET",
        "fr": "Aspose.Words pour .NET",
        "he": "Aspose.Words עבור .NET",
        "hi": ".NET के लिए Aspose.Words",
        "hu": "Aspose.Words .NET-hez",
        "id": "Aspose.Words untuk .NET",
        "it": "Aspose.Words per .NET",
        "ja": ".NET 向け Aspose.Words",
        "ko": ".NET용 Aspose.Words",
        "nl": "Aspose.Words voor .NET",
        "pl": "Aspose.Words dla .NET",
        "pt": "Aspose.Words para .NET",
        "ro": "Aspose.Words pentru .NET",
        "ru": "Aspose.Words для .NET",
        "sv": "Aspose.Words för .NET",
        "th": "Aspose.Words สำหรับ .NET",
        "tr": ".NET için Aspose.Words",
        "uk": "Aspose.Words для .NET",
        "vi": "Aspose.Words dành cho .NET",
        "zh": "Aspose.Words（适用于 .NET）",
    }
    _GITHUB_REPOSITORY_LABEL_TRANSLATIONS = {
        "ar": "مستودع GitHub",
        "cs": "Repozitář GitHub",
        "de": "GitHub-Repository",
        "el": "Αποθετήριο GitHub",
        "es": "Repositorio de GitHub",
        "fa": "مخزن GitHub",
        "fr": "Dépôt GitHub",
        "he": "מאגר GitHub",
        "hi": "GitHub रिपॉज़िटरी",
        "hu": "GitHub-adattár",
        "id": "Repositori GitHub",
        "it": "Repository su GitHub",
        "ja": "GitHub リポジトリ",
        "ko": "GitHub 저장소",
        "nl": "GitHub-opslagplaats",
        "pl": "Repozytorium GitHub",
        "pt": "Repositório do GitHub",
        "ro": "Depozit GitHub",
        "ru": "Репозиторий GitHub",
        "sv": "GitHub-arkiv",
        "th": "ที่เก็บ GitHub",
        "tr": "GitHub deposu",
        "uk": "Репозиторій GitHub",
        "vi": "Kho lưu trữ GitHub",
        "zh": "GitHub 代码仓库",
    }
    _LOCALE_RETRY_HINTS = {
        "cs": (
            "If the source title is 'Spreadsheet Management in Rust with "
            "Aspose.Cells FOSS', translate that title exactly as "
            "'Řízení tabulek v jazyce Rust s Aspose.Cells FOSS'. This wording "
            "is idiomatic Czech and supplies an unambiguous Czech language "
            "signal; do not use a Czech/Slovak-neutral paraphrase."
        ),
        "de": (
            "If the source seoTitle is 'Aspose.Words FOSS for .NET — "
            "Open-Source Word Document Library', translate that seoTitle "
            "exactly as 'Aspose.Words FOSS für .NET — eine quelloffene "
            "Bibliothek für Word-Dokumente'. This wording is idiomatic German "
            "and supplies unambiguous German language signals."
        ),
        "es": (
            "If the source title is 'Introducing Aspose.Words FOSS for .NET', "
            "translate that title exactly as 'Lanzamiento de Aspose.Words FOSS "
            "para .NET'. This wording is idiomatic Spanish and supplies an "
            "unambiguous Spanish language signal while preserving the product "
            "and platform tokens."
        ),
        "nl": (
            "For a short Dutch technical title, translate the source phrase "
            "'Deep Dive' idiomatically as 'Een grondige analyse van'. "
            "Do not use an English or Afrikaans-like literal calque."
        ),
        "ro": (
            "If the source seoTitle is 'Aspose.HTML FOSS for Python — CSSOM, "
            "Cascade, and Computed Styles', translate that seoTitle exactly as "
            "'Aspose.HTML FOSS pentru Python — CSSOM, cascada și stilurile "
            "calculate'. This wording is idiomatic Romanian and supplies "
            "unambiguous Romanian language signals while preserving the "
            "product and API tokens."
        ),
    }

    def __init__(
        self,
        *,
        manifest: CampaignManifest,
        translation_engine,
        translator_repo: Path,
        ledger_root: Path = Path("data/campaigns"),
    ) -> None:
        self.manifest = manifest
        self.engine = translation_engine
        self.translator_repo = translator_repo.resolve()
        self.content_repo = Path(manifest.content_repo).resolve()
        self.ledger = CampaignLedger(ledger_root, manifest.campaign_id)
        # The engine owns one model instance.  Candidate jobs have distinct
        # source/output paths, while these two maps provide only narrowly
        # scoped retry routing for the currently running job.
        self._engine_campaign_state_lock = threading.RLock()
        # TC-APT-044: the former engine-wide _model_execution_lock (which
        # serialized EVERY translate_file call, GPU or API alike, and silently
        # defeated LLM concurrency) is deleted. GPU generation is now
        # serialized where the hazard actually lives: each
        # HuggingFaceBackend/CTranslate2Backend instance carries its own
        # _generation_lock, which also covers a circuit-breaker reroute to the
        # m2m100 fallback (the returned instance is locked no matter how it
        # was resolved). The shared-parser hazard the old lock also papered
        # over was fixed at the source by TC-APT-043.
        #
        # TC-APT-046 step 1: an instant, code-free rollback to that old,
        # fully-serialized behaviour, for the case where a canary at
        # max_parallel_jobs > 1 shows something the regression tests do not.
        # Scoped to the campaign path only -- the deleted lock never covered
        # the CLI's parallel-language executor, so re-serializing that here
        # would be a new restriction rather than a rollback. Inert while
        # max_parallel_jobs is 1 (only one job is ever in flight), which is why
        # it can default to the safe value without costing throughput today.
        self._force_serialize_lock = threading.RLock()
        self._force_serialize = _force_serialize_all_backends()
        # A deferred escalation campaign must never make an incidental in-run
        # Professionalize request from lower-level repair helpers.  Those
        # cells fail closed and become queue tickets for the dedicated retry
        # consumer instead.
        if hasattr(self.engine, "campaign_context"):
            self.engine.campaign_context["defer_llm_fallbacks"] = (
                self.manifest.retry_policy.get("llm_escalation_mode") == "deferred"
                or bool(self.manifest.retry_policy.get("professionalize_only", False))
            )

    def _llm_event(self, event):
        self.ledger._append(self.ledger.root / "llm_calls.jsonl", event)

    def _startup_checkpoint(self, phase: str) -> None:
        """Emit opt-in, candidate-free startup progress for bounded recovery probes."""
        if os.environ.get("CAMPAIGN_STARTUP_DIAGNOSTICS") == "1":
            print(f"[{self.manifest.campaign_id}] runner {phase}", flush=True)

    # TC-APT-046: a deferred campaign's terminal heal ticket is also the
    # dedicated retry consumer's only feed. Built lazily so campaigns that
    # never open one (the immediate-mode majority) never create the file.
    @property
    def _rejected_task_queue(self) -> RejectedTaskQueue:
        queue = getattr(self, "_rejected_task_queue_instance", None)
        if queue is None:
            queue = RejectedTaskQueue(self.ledger.root.parent / "rejected_tasks.sqlite3")
            self._rejected_task_queue_instance = queue
        return queue

    def _enqueue_rejected_retry(
        self,
        *,
        source: Any,
        locale: str,
        expected_output: str,
        gate: str,
        failure: dict[str, Any] | None,
    ) -> None:
        candidate_sha256 = str(failure.get("candidate_sha256") or "") if failure else ""
        task = RejectedTranslationTask.from_mapping(
            {
                "campaign_id": self.manifest.campaign_id,
                "site_id": getattr(source, "site_id", ""),
                "source_path": source.source_path,
                "output_path": expected_output,
                "source_sha256": source.source_sha256,
                "target_lang": locale,
                "failure_category": f"auto:{gate}",
                "failure_fingerprint": candidate_sha256 or f"auto:{gate}",
                "retry_budget": self._DEFERRED_RETRY_BUDGET,
                "model_target": str(self.manifest.retry_policy.get("llm_model") or "professionalize_llm"),
            }
        )
        self._rejected_task_queue.enqueue(task)

    @contextmanager
    def _rollback_serialization(self):
        """Serialize engine calls when the TC-APT-046 rollback switch is on."""
        if not self._force_serialize:
            yield
            return
        with self._force_serialize_lock:
            yield

    def _validated_resume_receipts(self) -> dict[str, dict[str, Any]]:
        receipts = self.ledger.receipts()
        valid: dict[str, dict[str, Any]] = {}
        receipt_migrations: dict[str, dict[str, Any]] = {}
        expected_outputs = {
            output: (source, locale)
            for source in self.manifest.sources
            for locale, output in source.outputs.items()
        }
        for output, receipt in receipts.items():
            if output not in expected_outputs:
                raise CampaignManifestError(f"receipt outside campaign scope: {output}")
            source, locale = expected_outputs[output]
            claimed_fingerprint = receipt.get("receipt_sha256")
            unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            if not claimed_fingerprint or receipt_fingerprint(unsigned) != claimed_fingerprint:
                if (
                    claimed_fingerprint
                    and legacy_integer_gate_receipt_fingerprint(unsigned) == claimed_fingerprint
                ):
                    migrated = dict(unsigned)
                    migrated["receipt_sha256"] = receipt_fingerprint(unsigned)
                    receipt_migrations[output] = migrated
                else:
                    raise CampaignManifestError(
                        f"acceptance receipt fingerprint mismatch: {output}"
                    )
            expected_context = {
                "campaign_id": self.manifest.campaign_id,
                "source_path": source.source_path,
                "output_path": output,
                "source_sha256": source.source_sha256,
                "target_lang": locale,
                "validation_policy": "zero-defect",
                "config_fingerprint": self.manifest.config_fingerprint,
            }
            for field_name, expected_value in expected_context.items():
                current_receipt = receipt_migrations.get(output, receipt)
                if current_receipt.get(field_name) != expected_value:
                    if field_name == "config_fingerprint":
                        # A manifest fingerprint may legitimately advance while
                        # hardening the canary.  Never waive the mismatch: rerun
                        # all final write gates over the already accepted bytes,
                        # require an unchanged fixed point, then atomically
                        # replace receipt metadata with the new fingerprint.
                        migrated = self._revalidate_accepted_receipt(
                            current_receipt,
                            source=source,
                            locale=locale,
                            output_path=output,
                        )
                        receipt_migrations[output] = migrated
                        continue
                    source_path = self.content_repo / source.source_path
                    legacy_normalized_source_sha = hashlib.sha256(
                        source_path.read_text(encoding="utf-8").encode("utf-8")
                    ).hexdigest()
                    if (
                        field_name == "source_sha256"
                        and current_receipt.get(field_name) == legacy_normalized_source_sha
                    ):
                        migrated = {
                            key: value
                            for key, value in current_receipt.items()
                            if key != "receipt_sha256"
                        }
                        migrated[field_name] = expected_value
                        migrated["receipt_sha256"] = receipt_fingerprint(migrated)
                        receipt_migrations[output] = migrated
                        continue
                    raise CampaignManifestError(f"receipt {field_name} mismatch for {output}")
            output_path = self.content_repo / output
            if not output_path.is_file():
                raise CampaignManifestError(f"receipt output missing: {output}")
            if sha256_file(output_path) != receipt.get("output_sha256"):
                raise CampaignManifestError(f"receipt/output hash mismatch: {output}")
            gates = receipt.get("gate_results") or {}
            max_gate_id = max((int(gate_id) for gate_id in gates), default=0)
            expected_gate_ids = {str(index) for index in range(1, max_gate_id + 1)}
            invalid_gates = [
                gate_id
                for gate_id, item in gates.items()
                if not isinstance(item, dict)
                or not item.get("passed", False)
                or str(item.get("action", "")).lower()
                in {
                    "warn",
                    "warning",
                    "skip",
                    "skipped",
                    "unavailable",
                    "exception",
                }
                or item.get("error") is not None
            ]
            if max_gate_id < 44 or set(gates) != expected_gate_ids or invalid_gates:
                raise CampaignManifestError(f"receipt is not all-pass: {output}")
            valid[output] = receipt_migrations.get(output, receipt)
        if receipt_migrations:
            self.ledger.replace_receipts(
                [receipt_migrations.get(output, receipt) for output, receipt in receipts.items()]
            )
        return valid

    def _revalidate_accepted_receipt(
        self,
        receipt: dict[str, Any],
        *,
        source: Any,
        locale: str,
        output_path: str,
    ) -> dict[str, Any]:
        """Reissue metadata only after a byte-identical final-gate rerun.

        This is the only receipt migration allowed for an evolving canary.
        It never invokes translation, never writes the content file, and fails
        if any gate changes or auto-cleaning would alter the accepted bytes.
        """
        source_path = self.content_repo / source.source_path
        target_path = self.content_repo / output_path
        if not source_path.is_file() or not target_path.is_file():
            raise CampaignManifestError(f"receipt revalidation input missing: {output_path}")
        if sha256_file(source_path) != source.source_sha256:
            raise CampaignManifestError(f"receipt revalidation source drift: {output_path}")
        if sha256_file(target_path) != receipt.get("output_sha256"):
            raise CampaignManifestError(f"receipt revalidation output drift: {output_path}")
        try:
            source_content = source_path.read_text(encoding="utf-8")
            accepted_content = target_path.read_text(encoding="utf-8")
            source_doc = self.engine.parser.parse_string(source_content)
            source_doc.source_path = source_path
        except (OSError, UnicodeError, ValueError) as exc:
            raise CampaignManifestError(
                f"receipt revalidation parse failure: {type(exc).__name__}"
            ) from exc
        profile = self.engine.config.get_site_profile(source.site_id)
        calculated = self.engine._get_output_path(source_path, locale, profile)
        if calculated.resolve() != target_path.resolve():
            raise CampaignManifestError(f"receipt revalidation routing mismatch: {output_path}")
        # Gate 36's external LLM score is deliberately stochastic.  Its final
        # PASS was already captured in the immutable receipt when these exact
        # source/output hashes were accepted.  Replaying it can produce a
        # contradictory score for unchanged bytes and does not verify anything
        # new.  Re-run every deterministic gate and replay only that immutable
        # accepted Gate 36 result; candidate acceptance itself still always
        # invokes the independent judge.
        accepted_gate36 = (receipt.get("gate_results") or {}).get("36")
        if not isinstance(accepted_gate36, dict) or not accepted_gate36.get("passed"):
            raise CampaignManifestError(f"receipt missing accepted fidelity pass: {output_path}")
        evaluator = self.engine._write_gate
        original_fidelity_gate = evaluator._gate_fidelity_judge

        def _replay_accepted_fidelity(*args: Any, **kwargs: Any) -> str:
            translated = args[1] if len(args) > 1 else str(kwargs.get("translated_content", ""))
            return translated

        evaluator._gate_fidelity_judge = _replay_accepted_fidelity
        try:
            gate_result = evaluator.evaluate_zero_defect(
                translated_content=accepted_content,
                source_content=source_content,
                target_lang=locale,
                output_path=target_path,
                source_doc=source_doc,
                # This is a read-only verification of the same expected output,
                # not an overwrite authorization.
                force_overwrite=True,
                site_profile=profile,
            )
        finally:
            evaluator._gate_fidelity_judge = original_fidelity_gate
        final_content = gate_result.cleaned_content
        if not gate_result.passed or final_content != accepted_content:
            raise CampaignManifestError(f"receipt revalidation gates failed: {output_path}")
        gate_results = {
            1: {"passed": True, "action": "verification", "error": None},
            **gate_result.gate_results,
        }
        gate_results[36] = accepted_gate36
        max_gate_id = max((int(gate_id) for gate_id in gate_results), default=0)
        expected_gate_ids = set(range(1, max_gate_id + 1))
        invalid = [
            gate_id
            for gate_id, item in gate_results.items()
            if not isinstance(item, dict)
            or not item.get("passed", False)
            or str(item.get("action", "")).lower()
            in {"warn", "warning", "skip", "skipped", "unavailable", "exception"}
            or item.get("error") is not None
        ]
        if max_gate_id < 44 or set(gate_results) != expected_gate_ids or invalid:
            raise CampaignManifestError(f"receipt revalidation not all-pass: {output_path}")
        migrated = {
            key: value
            for key, value in receipt.items()
            if key not in {"receipt_sha256", "accepted_at"}
        }
        migrated["config_fingerprint"] = self.manifest.config_fingerprint
        migrated["gate_results"] = {str(key): value for key, value in gate_results.items()}
        # Preserve the original acceptance time: only provenance metadata is
        # refreshed, content bytes and their original acceptance remain intact.
        migrated["accepted_at"] = receipt.get("accepted_at")
        migrated["receipt_sha256"] = receipt_fingerprint(migrated)
        return migrated

    def _append_campaign_receipt(self, receipt: dict[str, Any]) -> None:
        normalized = dict(receipt)
        for field_name in ("source_path", "output_path"):
            absolute = Path(normalized[field_name]).resolve()
            try:
                normalized[field_name] = absolute.relative_to(self.content_repo).as_posix()
            except ValueError as exc:
                raise CampaignManifestError(
                    f"receipt {field_name} is outside content repo: {absolute}"
                ) from exc
        # TC-APT-031: record the bytes this accepted output superseded (auditable, revertable).
        replacing = getattr(self.engine, "campaign_context", {}).get("replace_existing") or {}
        superseded = replacing.get(normalized["output_path"])
        if superseded:
            normalized["superseded_sha256"] = superseded
        # The engine owns receipt creation and deliberately has no campaign
        # attempt arguments.  The runner keeps this output-addressed mapping
        # under its state lock so concurrent jobs cannot attribute a receipt to
        # another job.  The fields are additive and legacy receipt readers
        # continue to work when they are absent.
        metadata = (
            getattr(self.engine, "campaign_context", {})
            .get("attempt_metadata_by_output", {})
            .get(str(Path(receipt["output_path"]).resolve()))
        )
        if metadata:
            normalized.update(metadata)
        self.ledger.append_receipt(normalized)

    def _quality_stop_recommendations(self) -> dict[str, Any]:
        """Read fail-safe advisory thresholds once for campaign summary evidence."""
        try:
            from src.utils.config_loader import get_global_config

            raw = get_global_config().get("campaign_quality", {}) or {}
            warning_after = int(raw.get("zero_acceptance_warning_after_attempts", 1))
            stop_after = int(raw.get("zero_acceptance_stop_recommendation_after_attempts", 3))
            hardware = get_global_config().get("hardware", {}) or {}
            vram_budget = hardware.get("max_gpu_memory_percent")
            result = self.ledger.zero_acceptance_recommendations(
                warning_after_attempts=warning_after,
                stop_recommendation_after_attempts=stop_after,
            )
            result["vram_budget_percent"] = vram_budget
            return result
        except (TypeError, ValueError):
            # A malformed operator threshold must not silently terminate a
            # campaign. Surface it as evidence and continue its unrelated work.
            return {"configuration_error": "invalid campaign_quality zero-acceptance thresholds"}

    def _summary_evidence(self) -> dict[str, Any]:
        """Shared, payload-free evidence for run and verify-only summaries."""
        return {
            "model_outcomes": self.ledger.model_outcomes(),
            "retry_queue_outcomes": self.ledger.retry_queue_outcomes(),
            "attempt_model_outcomes": self.ledger.attempt_model_outcomes(),
            "quality_stop_recommendations": self._quality_stop_recommendations(),
            "llm_call_outcomes": self.ledger.llm_call_outcomes(),
            "acceleration_metrics": self.ledger.acceleration_metrics(),
        }

    def _unreplaced_declaration(self, source: Any, locale: str, relative: str) -> bool:
        """TC-APT-031: True when ``relative`` is a declared replacement whose current bytes
        still equal ``expected_sha256`` -- i.e. the pre-existing original, not yet replaced.
        Such a file is governed provenance for recovery purposes and must never be deleted."""
        spec = source.replacement_for(locale) if hasattr(source, "replacement_for") else None
        if not spec:
            return False
        path = self.content_repo / relative
        return path.is_file() and sha256_file(path) == spec.get("expected_sha256")

    def _receipt_recovery_candidates(
        self,
    ) -> list[tuple[Any, str, str, str]]:
        """Return manifest outputs backed by immutable governed add commits.

        Each candidate must be the sole path added by its latest path commit,
        that commit must be after the pinned content baseline and reachable
        from the current branch, and the current bytes must equal the commit
        blob.  This deliberately excludes arbitrary pre-existing files.

        TC-APT-003: the five forensic rules live in ``src/workers/git_provenance``
        so the provenance backfill and this recovery path share ONE definition of
        governed commit provenance (diagnostics unchanged).
        """
        candidates: list[tuple[Any, str, str, str]] = []
        for source in self.manifest.sources:
            for locale, relative in source.outputs.items():
                output_path = self.content_repo / relative
                if not output_path.exists():
                    continue
                if not output_path.is_file():
                    raise CampaignManifestError(
                        f"receipt recovery output is not a file: {relative}"
                    )
                if self._unreplaced_declaration(source, locale, relative):
                    # TC-APT-031: a declared, not-yet-replaced original is governed by its
                    # manifest declaration, not by a shard commit -- not a recovery candidate.
                    continue
                pattern = governed_subject_pattern(
                    wave=source.wave,
                    site_id=source.site_id,
                    family=source.family,
                    platform=source.platform,
                    locale=locale,
                )
                try:
                    governed = verify_governed_add(
                        self.content_repo,
                        relative,
                        subject_pattern=pattern,
                        baseline_sha=self.manifest.content_repo_sha,
                        current_sha256=sha256_file(output_path),
                    )
                except GovernedProvenanceError as exc:
                    raise CampaignManifestError(str(exc)) from exc
                candidates.append((source, locale, relative, governed.commit_sha))
        return sorted(candidates, key=lambda item: item[2])

    def recover_committed_receipts(self) -> dict[str, Any]:
        """Recover lost receipts by revalidating governed committed bytes.

        This is not an acceptance shortcut: all candidate bytes are kept in
        memory and independently rerun through validation, verification,
        fidelity, all 44 gates, and placement.  Each all-pass metadata-only
        receipt is fsynced independently so an outage or later bad candidate
        cannot erase completed revalidation work; a resumed recovery validates
        existing receipt hashes before skipping them.
        """
        with FileLock(self.ledger.root / "campaign.lock", timeout=0):
            candidates = self._receipt_recovery_candidates()
            if not candidates:
                raise CampaignManifestError("receipt recovery found no governed committed outputs")
            existing_expected = {
                output
                for source in self.manifest.sources
                for locale, output in source.outputs.items()
                if (self.content_repo / output).exists()
                and not self._unreplaced_declaration(source, locale, output)
            }
            recovered_outputs = {item[2] for item in candidates}
            if recovered_outputs != existing_expected:
                raise CampaignManifestError(
                    "receipt recovery provenance does not cover every existing output"
                )
            existing_receipts = self._validated_resume_receipts()
            unexpected_receipts = set(existing_receipts) - recovered_outputs
            if unexpected_receipts:
                raise CampaignManifestError(
                    "receipt recovery ledger contains outputs without current "
                    "governed commit provenance"
                )

            self.manifest.verify_environment(
                translator_repo=self.translator_repo,
                require_clean=True,
                allow_existing_accepted=recovered_outputs,
            )
            self.engine.campaign_context.update(
                {
                    "campaign_id": self.manifest.campaign_id,
                    "config_fingerprint": self.manifest.config_fingerprint,
                }
            )

            for source, locale, relative, commit_sha in candidates:
                if relative in existing_receipts:
                    continue
                source_path = self.content_repo / source.source_path
                output_path = self.content_repo / relative
                try:
                    accepted = self.engine.accept_candidate_bytes(
                        source_bytes=source_path.read_bytes(),
                        candidate_bytes=output_path.read_bytes(),
                        source_path=source_path,
                        output_path=output_path,
                        target_lang=locale,
                        site_id=source.site_id,
                    )
                except Exception as exc:
                    raise CampaignManifestError(
                        f"receipt recovery validation failed for {relative}: {exc}"
                    ) from exc
                receipt = accepted.receipt()
                normalized = dict(receipt)
                for field_name in ("source_path", "output_path"):
                    normalized[field_name] = (
                        Path(normalized[field_name])
                        .resolve()
                        .relative_to(self.content_repo)
                        .as_posix()
                    )
                expected_context = {
                    "campaign_id": self.manifest.campaign_id,
                    "source_path": source.source_path,
                    "output_path": relative,
                    "source_sha256": source.source_sha256,
                    "target_lang": locale,
                    "validation_policy": "zero-defect",
                    "config_fingerprint": self.manifest.config_fingerprint,
                }
                if any(
                    normalized.get(field) != expected
                    for field, expected in expected_context.items()
                ):
                    raise CampaignManifestError(f"revalidated receipt context mismatch: {relative}")
                normalized["receipt_recovery"] = {
                    "mode": "all-gates-byte-revalidation-v1",
                    "commit_sha": commit_sha,
                }
                self.ledger.append_receipt(normalized)
                existing_receipts[relative] = self.ledger.receipts()[relative]

            verified = self._validated_resume_receipts()
            if set(verified) != recovered_outputs:
                raise CampaignManifestError("recovered receipt reconciliation failed")
            summary = {
                **self.manifest.to_summary(),
                "status": "RECEIPTS_RECOVERED",
                "accepted": len(verified),
                "remaining": self.manifest.expected_output_count - len(verified),
            }
            self.ledger.write_summary(summary)
            return summary

    # GC-01: git's own ref update uses a compare-and-swap lock, so a race
    # between two sessions committing to the same shared checkout at the
    # same instant fails loudly and safely (no corruption) with a message
    # matching one of these patterns -- confirmed live this session
    # ("fatal: cannot lock ref 'HEAD': is at X but expected Y"). This is a
    # transient, always-safely-retryable condition, unlike a genuine hook
    # rejection or merge conflict, which must still fail immediately.
    _GIT_REF_LOCK_RETRY_PATTERNS = ("cannot lock ref", "unable to lock")
    _GIT_REF_LOCK_MAX_ATTEMPTS = 3
    _GIT_REF_LOCK_RETRY_DELAY_S = 1.5

    def _git_commit_with_ref_lock_retry(self, message: list[str]) -> None:
        """Run `git commit` with a bounded retry for ref-lock contention only.

        Every other failure (hook rejection, nothing to commit, merge
        conflict, ...) propagates immediately on the first attempt -- this
        never masks a real failure, it only absorbs the specific, git-native,
        always-safe-to-retry race two concurrent sessions committing to the
        same shared checkout can hit.
        """
        last_exc: subprocess.CalledProcessError | None = None
        for attempt in range(1, self._GIT_REF_LOCK_MAX_ATTEMPTS + 1):
            try:
                subprocess.run(
                    ["git", "commit", "-m", *message],
                    cwd=self.content_repo,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").lower()
                is_ref_lock = any(pattern in stderr for pattern in self._GIT_REF_LOCK_RETRY_PATTERNS)
                if not is_ref_lock or attempt == self._GIT_REF_LOCK_MAX_ATTEMPTS:
                    if exc.stderr:
                        logger.error("git commit failed: %s", exc.stderr.strip())
                    raise
                logger.warning(
                    "git commit hit ref-lock contention (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    self._GIT_REF_LOCK_MAX_ATTEMPTS,
                    self._GIT_REF_LOCK_RETRY_DELAY_S,
                    exc.stderr.strip() if exc.stderr else exc,
                )
                last_exc = exc
                time.sleep(self._GIT_REF_LOCK_RETRY_DELAY_S)
        if last_exc:  # pragma: no cover - unreachable, loop always returns or raises
            raise last_exc

    def _commit_verified_outputs(self, shard_id: str) -> str | None:
        """Commit only checksum-verified, receipted campaign outputs."""
        branch = self.manifest.commit_policy.get("branch")
        if not branch:
            return None
        if self.manifest.commit_policy.get("push", False):
            raise CampaignManifestError("campaign policy prohibits autonomous push")

        current_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if current_branch != branch:
            raise CampaignManifestError(
                f"content branch {current_branch!r} != campaign branch {branch!r}"
            )

        receipts = self.ledger.receipts()
        dirty = {Path(item).as_posix() for item in git_dirty_paths(self.content_repo)}
        allowed = set(receipts)
        unexpected = sorted(dirty - allowed)
        if unexpected:
            raise CampaignManifestError(
                f"dirty path outside accepted receipt scope: {unexpected[:10]}"
            )
        commit_paths = sorted(dirty & allowed)
        if not commit_paths:
            return None
        try:
            title = content_commit_title(commit_paths, f"zero-defect shard {shard_id}")
        except ValueError as exc:
            raise CampaignManifestError(str(exc)) from exc
        for relative in commit_paths:
            receipt = receipts[relative]
            output = self.content_repo / relative
            if not output.is_file() or sha256_file(output) != receipt.get("output_sha256"):
                raise CampaignManifestError(
                    f"refusing commit for checksum-invalid output: {relative}"
                )

        subprocess.run(
            ["git", "add", "--", *commit_paths],
            cwd=self.content_repo,
            check=True,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if {Path(item).as_posix() for item in staged} != set(commit_paths):
            raise CampaignManifestError("staged diff differs from accepted output set")
        run_id = self._create_governed_skill_run(shard_id, len(commit_paths))
        message = [title]
        if run_id:
            message.extend(
                [
                    "-m",
                    (
                        f"Accepted outputs: {len(commit_paths)}; every file has an "
                        "all-44-gates zero-defect receipt."
                    ),
                    "-m",
                    "Skills invoked: [S-HT-02]",
                    "-m",
                    "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>",
                ]
            )
        try:
            self._git_commit_with_ref_lock_retry(message)
        except Exception:
            self._finalize_governed_skill_run(run_id, "failure")
            raise
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._finalize_governed_skill_run(run_id, "success", commit_sha)
        return commit_sha

    def _governance_command(self) -> list[str] | None:
        script = (
            self.content_repo / "scripts" / "pipeline" / "commands" / "ops" / "skill_run_manager.py"
        )
        if not script.is_file():
            return None
        candidates = [
            self.content_repo / ".venv" / "Scripts" / "python.exe",
            self.content_repo / ".venv" / "bin" / "python",
        ]
        python = next((path for path in candidates if path.is_file()), None)
        return [str(python or Path(sys.executable)), str(script)]

    def _create_governed_skill_run(self, shard_id: str, output_count: int) -> str | None:
        command = self._governance_command()
        if command is None:
            return None
        created = subprocess.run(
            [
                *command,
                "create",
                "--skills",
                "S-HT-02",
                "--plan",
                f"{self.manifest.campaign_id}:{shard_id}",
                "--run-type",
                "targeted",
            ],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        match = re.search(r"Created skill run record:\s*(\S+)", created.stdout)
        if not match:
            raise CampaignManifestError("governance tool did not return a skill run ID")
        run_id = match.group(1)
        subprocess.run(
            [
                *command,
                "record-step",
                "--run-id",
                run_id,
                "--skill",
                "S-HT-02",
                "--type",
                "full",
                "--steps",
                "managed-campaign",
                "--note",
                (f"Zero-defect campaign shard {shard_id}; {output_count} receipted outputs"),
            ],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return run_id

    def _finalize_governed_skill_run(
        self,
        run_id: str | None,
        outcome: str,
        commit_sha: str | None = None,
    ) -> None:
        command = self._governance_command()
        if not run_id or command is None:
            return
        args = [
            *command,
            "finalize",
            "--run-id",
            run_id,
            "--outcome",
            outcome,
        ]
        if commit_sha:
            args.extend(["--commit-sha", commit_sha])
        subprocess.run(
            args,
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _failure_metadata(result: Any) -> tuple[str, str]:
        """Return rejection metadata without persisting candidate-derived text."""
        error_count = len(getattr(result, "errors", None) or [])
        retry_count = int(getattr(result, "retry_attempts", 0) or 0)
        validation_result = getattr(result, "validation_result", None)
        # VA-01 (TC-APT-105 audit): `validators` names the validator(s) that
        # actually caused the reject decision -- ERROR severity only, since
        # the decision engine's own Rule 1/2/5 REJECT paths are ERROR-driven
        # (a WARNING-only validator can extend a retry loop or factor into
        # Rule 5's arbitration, but never causes a reject on its own).
        # Previously any validator reporting an issue at ANY severity showed
        # up here -- including one that only ever warned -- misattributing
        # causation, and this value also seeds a heal ticket's
        # root_cause_class (self._append_heal_ticket), so the inflated set
        # could quarantine on the wrong signal. warning_only_validators is
        # kept separately for observability, not causation.
        _issue_validator_severities: dict[str, set[str]] = {}
        for issue in getattr(validation_result, "issues", []) or []:
            severity = str(
                getattr(getattr(issue, "severity", None), "value", getattr(issue, "severity", ""))
            )
            if severity not in {"error", "warning"}:
                continue
            # TC-PORT-LLM-011: src/translation_engine/models.py::ValidationIssue
            # (used by segment_translator.py's own TranslationRetryableError
            # raises, e.g. ASTTranslation/BatchLanguagePurity) has a `rule`
            # field, not `validator` -- src/translation_engine/validation/
            # base.py::ValidationIssue (used by the real per-cell validators)
            # has `validator`, not `rule`. Falling back silently collapsed
            # every issue of the first kind to "unknown", so a genuine,
            # reproducible defect (e.g. empty translations for a blockquote
            # text-run unit) fingerprinted identically to a truly unclassified
            # failure -- indistinguishable in heal_queue.jsonl and unable to
            # benefit from RECURRENCE ESCALATION grouping by root cause.
            _issue_name = str(
                getattr(issue, "validator", None) or getattr(issue, "rule", None) or "unknown"
            )
            _issue_validator_severities.setdefault(_issue_name, set()).add(severity)
        validators = sorted(
            name for name, severities in _issue_validator_severities.items() if "error" in severities
        )
        warning_only_validators = sorted(
            name
            for name, severities in _issue_validator_severities.items()
            if severities == {"warning"}
        )
        verification_result = getattr(result, "verification_result", None)
        verification_checks = sorted(
            {
                re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    str(getattr(issue, "check_name", "unknown")),
                )
                or "unknown"
                for issue in getattr(verification_result, "issues", []) or []
                if str(getattr(issue, "severity", "")) in {"error", "warning"}
            }
        )
        raw_error = str(getattr(result, "error", "") or "")
        safe_codes = sorted(
            set(
                re.findall(
                    r"\b(?:GATE\d+|TC-[A-Z0-9-]+|" r"[A-Za-z][A-Za-z0-9_]*(?:Validator|Check))\b",
                    raw_error,
                )
            )
        )
        failed_gate_ids = sorted(
            int(gate_id)
            for gate_id, gate_result in (
                getattr(result, "rejection_gate_results", None) or {}
            ).items()
            if not bool(gate_result.get("passed", False))
        )
        safe_codes = sorted({*safe_codes, *(f"GATE{gate_id}" for gate_id in failed_gate_ids)})
        diagnostic_code = str(getattr(result, "rejection_diagnostic_code", "") or "")
        if diagnostic_code:
            safe_codes = sorted({*safe_codes, diagnostic_code})
        exception_classes = sorted(
            set(
                re.findall(
                    r"\b([A-Za-z][A-Za-z0-9_]*(?:Error|Exception|Incomplete)):",
                    raw_error,
                )
            )
        )
        score_match = re.search(r"\bscore=(\d+(?:\.\d+)?)\b", raw_error)
        verdict_match = re.search(r"\b(fail|warn|pass)\b", raw_error, re.IGNORECASE)
        unit_fingerprints = re.search(
            r"\bunit_fingerprints=([a-z0-9_:,-]+)\b",
            raw_error,
            re.IGNORECASE,
        )
        issue_fingerprints: list[str] = []
        for issue in getattr(validation_result, "issues", []) or []:
            severity = str(
                getattr(
                    getattr(issue, "severity", None),
                    "value",
                    getattr(issue, "severity", ""),
                )
            )
            if severity not in {"error", "warning"}:
                continue
            validator = (
                re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    # See the matching comment above: this issue may carry
                    # `rule` (models.ValidationIssue) instead of `validator`
                    # (validation/base.py::ValidationIssue).
                    str(
                        getattr(issue, "validator", None)
                        or getattr(issue, "rule", None)
                        or "unknown"
                    ),
                )
                or "unknown"
            )
            details = getattr(issue, "details", None) or {}
            if "ngram" in details:
                issue_kind = "ngram"
            elif "frequency" in details and "word" in details:
                issue_kind = "word_frequency"
            elif "sentence" in details:
                issue_kind = "sentence_duplication"
            elif "heading" in details:
                issue_kind = "heading_repetition"
            elif validator == "FrontmatterLanguageCheck":
                issue_kind = "frontmatter_language"
            elif validator == "SemanticSimilarityValidator":
                issue_kind = "semantic_similarity"
            elif validator == "ASTTranslation":
                issue_kind = "empty_translation_unit"
            elif validator == "BatchLanguagePurity":
                issue_kind = "batch_language_purity"
            else:
                issue_kind = "generic"
            location_hash = hashlib.sha256(
                str(getattr(issue, "location", "")).encode("utf-8")
            ).hexdigest()[:16]
            numeric_parts: list[str] = []
            for key in (
                "count",
                "threshold",
                "source_ngram_ceiling",
                "frequency",
                "source_word_freq_ceiling",
                "confidence",
                "letter_count",
                "latin_letter_ratio",
                "target_script_ratio",
                # StructureValidator's own numbers. Without these its failures
                # fingerprinted as "generic:...:numeric=none", so a cell that
                # exhausted five attempts told us nothing about WHAT mismatched --
                # observed on words-document-net's de cell, where the validator had
                # recorded the counts all along and the fingerprint discarded them.
                # Appended rather than merged into a general sweep so every
                # pre-existing fingerprint stays byte-identical.
                "source_count",
                "translation_count",
                "source_level",
                "translation_level",
                "src_len",
                "tgt_len",
                # SemanticSimilarityValidator's measured score (TC-PORT-LLM-011).
                # "threshold" was already here, but the one number that actually
                # tells a genuine semantic-drift reject apart from a false one --
                # the measured similarity itself -- was silently dropped, so
                # every such reject fingerprinted as "generic:...:numeric=none"
                # even when the validator had computed a real score.
                "similarity",
            ):
                value = details.get(key)
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                rendered = f"{value:.6g}" if isinstance(value, float) else str(value)
                numeric_parts.append(f"{key}={rendered}")
            categorical_parts: list[str] = []
            field = str(details.get("field", ""))
            if field in {"title", "description", "seoTitle", "summary"}:
                categorical_parts.append(f"field={field}")
            for key in ("detected_lang", "expected_lang"):
                value = str(details.get(key, "")).lower()
                if re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2})?", value):
                    categorical_parts.append(f"{key}={value}")
            # Structural tag names are schema, not candidate text, so they are safe to
            # record and they say which element mismatched. Pattern-constrained so a
            # detail value can never smuggle prose into the ledger.
            for key in ("src_tag", "tgt_tag"):
                value = str(details.get(key, "")).lower()
                if re.fullmatch(r"[a-z][a-z0-9]{0,9}", value):
                    categorical_parts.append(f"{key}={value}")
            # A validator that failed to run at all (e.g. SemanticSimilarityValidator
            # with no sentence encoder available) records details={"exception_type":
            # type(exc).__name__} instead of a numeric score. Class names are schema,
            # not candidate text, so safe to record; mirrors _SAFE_DETAIL_KEYS in
            # file_pipeline.py::_quarantine_diagnostic_candidate (ce7bcb69).
            exception_type_value = str(details.get("exception_type", ""))
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,60}", exception_type_value):
                categorical_parts.append(f"exception_type={exception_type_value}")
            payload_value = None
            for key in ("ngram", "word", "sentence", "heading"):
                value = details.get(key)
                if isinstance(value, str) and value:
                    payload_value = value
                    break
            payload_hash = (
                hashlib.sha256(payload_value.encode("utf-8")).hexdigest()[:16]
                if payload_value is not None
                else "none"
            )
            issue_fingerprints.append(
                ":".join(
                    [
                        validator,
                        severity,
                        issue_kind,
                        location_hash,
                        f"payload_sha256={payload_hash}",
                        *categorical_parts,
                        *(numeric_parts or ["numeric=none"]),
                    ]
                )
            )
        verification_fingerprints: list[str] = []
        for issue in getattr(verification_result, "issues", []) or []:
            severity = str(getattr(issue, "severity", ""))
            if severity not in {"error", "warning"}:
                continue
            check_name = (
                re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    str(getattr(issue, "check_name", "unknown")),
                )
                or "unknown"
            )
            location_hash = hashlib.sha256(
                str(getattr(issue, "location", "")).encode("utf-8")
            ).hexdigest()[:16]
            location = str(getattr(issue, "location", ""))
            field_match = re.fullmatch(
                r"frontmatter\.(title|description|seoTitle|summary)", location
            )
            metadata = getattr(issue, "metadata", None) or {}
            numeric_parts: list[str] = []
            for key, value in sorted(metadata.items()):
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                safe_key = re.sub(r"[^A-Za-z0-9_-]", "", str(key)) or "metric"
                rendered = f"{value:.6g}" if isinstance(value, float) else str(value)
                numeric_parts.append(f"{safe_key}={rendered}")
            verification_fingerprints.append(
                ":".join(
                    [
                        check_name,
                        severity,
                        location_hash,
                        *([f"field={field_match.group(1)}"] if field_match else []),
                        *(numeric_parts or ["numeric=none"]),
                    ]
                )
            )
        # VA-01 closed over-attribution (a warning-only validator must not be
        # named as the cause).  This closes the under-attribution half: under
        # `validation_policy: zero-defect` the decision engine's Rule 5 runs with
        # accept_after_max_retries=False and REJECTs a candidate whose only
        # remaining issues are WARNING severity, so `validators` is legitimately
        # empty and the gate fell through to the literal "pipeline" -- the heal
        # ticket then named nothing (`auto:pipeline`) even though
        # warning_only_validators recorded exactly what blocked the cell.  The
        # `warning:` prefix keeps the two kinds of attribution distinguishable at
        # a glance and in every root_cause_class that derives from this value.
        gate = (
            validators[0]
            if validators
            else (
                f"verification:{verification_checks[0]}"
                if verification_checks
                else (
                    safe_codes[0]
                    if safe_codes
                    else (
                        f"warning:{warning_only_validators[0]}"
                        if warning_only_validators
                        else "pipeline"
                    )
                )
            )
        )
        validator_text = ",".join(validators) if validators else "unknown"
        warning_only_validator_text = (
            ",".join(warning_only_validators) if warning_only_validators else "none"
        )
        reason = (
            f"translation_rejected; error_count={error_count}; "
            f"internal_retries={retry_count}; validators={validator_text}; "
            f"warning_only_validators={warning_only_validator_text}; "
            f"codes={','.join(safe_codes) if safe_codes else 'unknown'}; "
            f"exceptions="
            f"{','.join(exception_classes) if exception_classes else 'unknown'}; "
            f"verdict={verdict_match.group(1).lower() if verdict_match else 'unknown'}; "
            f"score={score_match.group(1) if score_match else 'unknown'}; "
            f"unit_fingerprints="
            f"{unit_fingerprints.group(1) if unit_fingerprints else 'none'}; "
            f"issue_fingerprints="
            f"{','.join(sorted(issue_fingerprints)) if issue_fingerprints else 'none'}; "
            f"verification_checks="
            f"{','.join(verification_checks) if verification_checks else 'none'}; "
            f"verification_fingerprints="
            f"{','.join(sorted(verification_fingerprints)) if verification_fingerprints else 'none'}; "
            f"error_sha256={hashlib.sha256(raw_error.encode('utf-8')).hexdigest()}"
        )
        return gate, reason

    @staticmethod
    def _frontmatter_source_guidance(
        source_path: Path | None, fields: list[str], target_lang: str
    ) -> str:
        """Build source-derived, candidate-free lexical retry boundaries."""
        if source_path is None or not source_path.is_file():
            return ""
        try:
            text = source_path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                return ""
            end = text.find("---", 3)
            if end < 0:
                return ""
            frontmatter = yaml.safe_load(text[3:end]) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            return ""
        selected = fields or ["title", "description", "seoTitle", "summary"]
        source_text = " ".join(str(frontmatter.get(field) or "") for field in selected)
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.+#-]*", source_text)
        if not tokens:
            return ""
        known_protected = {
            "FOSS",
            "Rust",
            "Python",
            "Java",
            "Microsoft",
            "Office",
        }
        protected: list[str] = []
        ordinary: list[str] = []
        stopwords = {
            "a",
            "an",
            "and",
            "all",
            "for",
            "in",
            "of",
            "the",
            "to",
            "with",
            "without",
        }

        def _is_identifier(token: str) -> bool:
            return (
                "." in token
                or token.isupper()
                or bool(re.search(r"[a-z][A-Z]", token))
                or token in known_protected
            )

        connectors: list[str] = []
        for idx, token in enumerate(tokens):
            is_identifier = _is_identifier(token)
            target = protected if is_identifier else ordinary
            if token not in target:
                target.append(token)
            # TC-APT-108: a stopword sandwiched between two preserved tokens
            # (e.g. "FOSS for Python") is exactly the shape the model was
            # observed leaving untranslated -- it reads as part of a fixed
            # product-name idiom. Naming it explicitly, instead of only
            # covering it under the generic "translate every other token"
            # instruction, is the channel the retry loop actually responds to.
            if (
                not is_identifier
                and token.casefold() in stopwords
                and idx > 0
                and _is_identifier(tokens[idx - 1])
                and idx + 1 < len(tokens)
                and _is_identifier(tokens[idx + 1])
                and token not in connectors
            ):
                connectors.append(token)
        substantive = [
            token for token in ordinary if token.casefold() not in stopwords and len(token) >= 4
        ][:40]
        field_text = ", ".join(selected)
        protected_text = ", ".join(protected) if protected else "none"
        substantive_text = ", ".join(substantive) if substantive else "all ordinary words"
        locale_label = CampaignRunner._target_locale_label(target_lang)
        guidance = (
            f"For source field(s) {field_text}, preserve exactly only these source tokens: "
            f"{protected_text}. Translate every other English source token into {locale_label}, "
            f"including these ordinary technical terms: {substantive_text}."
        )
        if connectors:
            connector_text = ", ".join(f'"{token}"' for token in connectors)
            guidance += (
                f" These preserved tokens are not a single fixed phrase: connector words between "
                f"them, such as {connector_text}, are ordinary language and must still be "
                f"translated into {locale_label}, not left in English."
            )
        return guidance

    @classmethod
    def _target_locale_label(cls, target_lang: str) -> str:
        """Return an explicit, governed language/script label for model feedback."""
        locale = target_lang.lower().split("-")[0]
        name = cls._LOCALE_NAMES.get(locale, target_lang)
        script = cls._LOCALE_SCRIPT_HINTS.get(locale)
        return f"{name} ({target_lang})" + (
            f", using {script} for all ordinary prose" if script else ""
        )

    @staticmethod
    def _sas_link_source_guidance(
        source_path: Path | None, raw_error: str, target_lang: str
    ) -> str:
        """Resolve hashed same-as-source link units to source-only lexical guidance."""
        if source_path is None or not source_path.is_file():
            return ""
        fingerprint_match = re.search(r"\bunit_fingerprints=([a-z0-9_:,-]+)\b", raw_error)
        if not fingerprint_match:
            return ""
        requested = {
            (digest, int(length))
            for digest, length in re.findall(
                r"(?:^|,)link_text:([a-f0-9]{16}):(\d+)",
                fingerprint_match.group(1),
            )
        }
        if not requested:
            return ""
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

        labels = re.findall(r"\[([^\]\r\n]+)\]\([^)]+\)", source_text)
        matched = [
            label
            for label in labels
            if (
                hashlib.sha256(label.encode("utf-8")).hexdigest()[:16],
                len(label),
            )
            in requested
        ]
        if not matched:
            return ""

        known_protected = {
            "FOSS",
            "Rust",
            "Python",
            "Java",
            "Microsoft",
            "Office",
        }
        protected: list[str] = []
        ordinary: list[str] = []
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+#-]*", " ".join(matched)):
            is_identifier = (
                "." in token
                or token.isupper()
                or bool(re.search(r"[a-z][A-Z]", token))
                or token in known_protected
            )
            target = protected if is_identifier else ordinary
            if token not in target:
                target.append(token)
        if not ordinary:
            return ""
        locale_label = CampaignRunner._target_locale_label(target_lang)
        guidance = (
            "For the affected source link label(s), preserve exactly only these "
            f"identifier/product tokens: {', '.join(protected) if protected else 'none'}. "
            f"Translate all ordinary label words into {locale_label}, including: "
            f"{', '.join(ordinary)}. Do not preserve the complete English label as a title."
        )
        if "Aspose.Words for .NET" in matched:
            locale = target_lang.lower().split("-")[0]
            exact = CampaignRunner._PRODUCT_LINK_LABEL_TRANSLATIONS.get(locale)
            if exact:
                guidance += (
                    " For the exact source label 'Aspose.Words for .NET', use "
                    f"the governed target label exactly as '{exact}'."
                )
        if "GitHub Repository" in matched:
            locale = target_lang.lower().split("-")[0]
            exact = CampaignRunner._GITHUB_REPOSITORY_LABEL_TRANSLATIONS.get(locale)
            if exact:
                guidance += (
                    " For the exact source label 'GitHub Repository', use "
                    f"the governed target label exactly as '{exact}'."
                )
        return guidance

    @staticmethod
    def _sas_text_source_guidance(
        source_path: Path | None, raw_error: str, target_lang: str
    ) -> str:
        """Rehydrate hashed AST text units into candidate-free retry guidance.

        Failure metadata deliberately retains only source-unit fingerprints.  A
        resumed campaign can safely resolve those fingerprints against the
        still-pinned English source and give the next model attempt precise
        source-only instructions without persisting rejected candidate text.
        """
        if source_path is None or not source_path.is_file():
            return ""
        fingerprint_match = re.search(r"\bunit_fingerprints=([a-z0-9_:,-]+)\b", raw_error)
        if not fingerprint_match:
            return ""
        requested = {
            (kind, digest, int(length))
            for kind, digest, length in re.findall(
                r"(?:^|,)(text):([a-f0-9]{16}):(\d+)",
                fingerprint_match.group(1),
            )
        }
        if not requested:
            return ""

        try:
            from src.translation_engine.extractor import TextUnitExtractor
            from src.translation_engine.parser import HugoParser
            from src.utils.config_loader import ConfigService

            parts = list(source_path.parts)
            content_index = next(
                index for index, part in enumerate(parts) if part.casefold() == "content"
            )
            site_id = parts[content_index + 1]
            profile = ConfigService(Path("config")).get_site_profile(site_id)
            terminology_file = Path("config/terminology/aspose_terms.txt")
            document = HugoParser().parse_file(source_path)
            extractor = TextUnitExtractor(
                segmentation_strategy=profile.body.ast_segmentation_strategy,
                terminology_file=terminology_file if terminology_file.is_file() else None,
                preserve_patterns=profile.body.preserve_patterns,
                site_profile=profile,
                target_lang=target_lang,
            )
            plan = extractor.extract_from_ast(document.ast, frontmatter=document.frontmatter)
        except (OSError, UnicodeError, ValueError, StopIteration, IndexError):
            return ""
        except Exception:
            # Retry guidance is supplemental.  The candidate must still fail
            # closed if source rehydration is unavailable for any reason.
            return ""

        matched: list[str] = []
        for unit in plan.units:
            source_text = str(getattr(unit, "source_text", "") or "")
            kind = str(
                getattr(
                    getattr(unit, "kind", ""),
                    "value",
                    getattr(unit, "kind", ""),
                )
            )
            fingerprint = (
                kind,
                hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:16],
                len(source_text),
            )
            if fingerprint in requested and source_text not in matched:
                matched.append(source_text)
        if not matched:
            return ""

        locale_label = CampaignRunner._target_locale_label(target_lang)
        numbered = " ".join(
            f"[{index}] {source_text}" for index, source_text in enumerate(matched, start=1)
        )
        return (
            "The affected exact English source units are listed below. Translate every "
            f"ordinary word in each complete unit into {locale_label}; preserve "
            "{PLACEHOLDER_n} tokens, product/API identifiers, code, versions, and file "
            f"formats exactly. Return no unit unchanged. Source units: {numbered}"
        )

    @staticmethod
    def _retry_feedback(
        result: Any,
        target_lang: str,
        prior_feedback: str | None = None,
        *,
        source_path: Path | None = None,
    ) -> str:
        """Build candidate-free instructions for the next governed attempt."""
        validation_result = getattr(result, "validation_result", None)
        issues = getattr(validation_result, "issues", []) or []
        validators = {str(getattr(issue, "validator", "")) for issue in issues}
        instructions: list[str] = []
        locale_label = CampaignRunner._target_locale_label(target_lang)
        locale_retry_hint = CampaignRunner._LOCALE_RETRY_HINTS.get(
            target_lang.lower().split("-")[0]
        )
        if "TerminologyPreservationValidator" in validators:
            # TC-APT-069: the frontmatter retry sends the UNMASKED original to the
            # model, so placeholder protection cannot preserve a governed term
            # there -- which is why seoTitle translated it in every locale
            # measured. The retry path does carry retry_feedback through to the
            # backend, so an explicit instruction is the channel that works where
            # masking cannot. Term names come from config/terminology.yaml, never
            # from a candidate, so this stays candidate-free.
            governed_terms = sorted(
                {
                    str((getattr(issue, "details", None) or {}).get("term", ""))
                    for issue in issues
                    if str(getattr(issue, "validator", "")) == "TerminologyPreservationValidator"
                    and (getattr(issue, "details", None) or {}).get("term")
                }
            )
            preamble = (
                "Reproduce these governed terms exactly as they appear in the source, "
                "character for character, without translating or transliterating them"
            )
            if governed_terms:
                term_text = ", ".join(f'"{term}"' for term in governed_terms)
                instructions.append(
                    f"{preamble}: {term_text}. "
                    "They are protected portfolio terminology and must stay in the source language "
                    "even when the surrounding sentence is fully translated. Translate everything "
                    "around them normally."
                )
            else:
                # Resume path: persisted failure metadata records the validator but
                # NOT the term, because string detail values are deliberately kept
                # out of fingerprints. A generic instruction is still actionable and
                # is better than losing the guidance entirely on restart.
                instructions.append(
                    "Reproduce every governed portfolio term exactly as it appears in the source, "
                    "character for character, without translating or transliterating it. Governed "
                    "terms are protected terminology and must stay in the source language even when "
                    "the surrounding sentence is fully translated. Translate everything around them "
                    "normally."
                )
        if "FrontmatterLanguageCheck" in validators:
            fields = sorted(
                {
                    str((getattr(issue, "details", None) or {}).get("field", ""))
                    for issue in issues
                    if str(getattr(issue, "validator", "")) == "FrontmatterLanguageCheck"
                    and str((getattr(issue, "details", None) or {}).get("field", ""))
                    in {"title", "description", "seoTitle", "summary"}
                }
            )
            field_text = ", ".join(fields) if fields else "unspecified"
            instructions.append(
                "Translate every translatable frontmatter field (title, description, "
                f"seoTitle, summary) fully into target locale {locale_label}; "
                f"the fields detected as failing were: {field_text}. "
                "preserve only product names, API identifiers, code, and file formats. "
                "Do not leave English prose."
            )
            if target_lang == "ar":
                instructions.append(
                    f"For each failing field ({field_text}), write ordinary prose in Arabic "
                    "script; Latin text is permitted only for protected product names, API "
                    "identifiers, code, and file formats."
                )
            source_guidance = CampaignRunner._frontmatter_source_guidance(
                source_path, fields, target_lang
            )
            if source_guidance:
                instructions.append(source_guidance)
            if locale_retry_hint:
                instructions.append(locale_retry_hint)
        if "RepetitionDetectorValidator" in validators:
            instructions.append(
                "Avoid adding repeated phrases or duplicate sentences beyond the source structure."
            )
        raw_error = str(getattr(result, "error", "") or "")
        if "GATE5" in raw_error:
            # Gate 5 is the file-level language-purity backstop. Its metadata
            # intentionally contains no candidate prose, so retry feedback
            # must be source/structure based: URLs and identifiers stay
            # verbatim, while labels and ordinary prose must be regenerated.
            instructions.append(
                "Perform a final language-purity pass over every ordinary-prose segment, "
                "especially Markdown link labels and headings. Preserve URLs, product names, "
                "API identifiers, code, versions, and placeholders exactly, but translate every "
                f"ordinary label/prose word into {locale_label}; do not leave or generate English "
                "link-label prose."
            )
        if "GATE36" in raw_error:
            instructions.append(
                "Preserve every source claim and section with no omission, reversal, or invented fact."
            )
        if "Gate 21 inline code translated" in raw_error:
            # Found live 2026-09-17 investigating a self-healing retry gap: this
            # exact defect (`Page.Annotations()` translated into the target
            # language) reproduced identically across two different locales
            # (ro, fa) with zero corrective guidance between attempts -- GATE5/
            # GATE36/TC-SAS-01 already get a targeted retry instruction, GATE21
            # never did, so every retry was a blind repeat of the same mistake.
            gate21_match = re.search(
                r"Gate 21 inline code translated: `(.*?)` → `(.*?)`", raw_error
            )
            if gate21_match:
                original_span = gate21_match.group(1)
                instructions.append(
                    "Reproduce this inline code span exactly as it appears in the source, "
                    f"character for character, without translating any part of it: `{original_span}`. "
                    "It is a code or API reference (a method call, class member, or identifier) "
                    "and must never be translated or transliterated, even partially."
                )
            else:
                instructions.append(
                    "Reproduce every inline code span (text inside backticks) exactly as it "
                    "appears in the source, character for character. Inline code is never "
                    "translated, even partially."
                )
        if "TC-SAS-01" in raw_error:
            instructions.append(
                "Translate every translatable source unit; identical output is allowed only for "
                "product names, API identifiers, and reviewed locale cognates."
            )
            source_guidance = CampaignRunner._sas_link_source_guidance(
                source_path, raw_error, target_lang
            )
            if source_guidance:
                instructions.append(source_guidance)
            text_source_guidance = CampaignRunner._sas_text_source_guidance(
                source_path, raw_error, target_lang
            )
            if text_source_guidance:
                instructions.append(text_source_guidance)
            if locale_retry_hint:
                instructions.append(locale_retry_hint)
        verification_result = getattr(result, "verification_result", None)

        def _verification_severity(issue: Any) -> str:
            severity = getattr(issue, "severity", "")
            return str(getattr(severity, "value", severity)).lower()

        failed_checks = sorted(
            {
                str(getattr(issue, "check_name", "unknown"))
                for issue in getattr(verification_result, "issues", []) or []
                if _verification_severity(issue) in {"error", "warning"}
            }
        )
        if failed_checks:
            instructions.append(
                "Correct every post-translation verification issue from these checks: "
                f"{', '.join(failed_checks)}. Preserve source meaning and structure, "
                f"and render all ordinary prose in target locale {locale_label}."
            )
            verification_fields = sorted(
                {
                    match.group(1)
                    for issue in getattr(verification_result, "issues", []) or []
                    if str(getattr(issue, "check_name", "")) == "language_detection"
                    and (
                        match := re.fullmatch(
                            r"frontmatter\.(title|description|seoTitle|summary)",
                            str(getattr(issue, "location", "")),
                        )
                    )
                }
            )
            if verification_fields:
                instructions.append(
                    "Translate every ordinary-language word in the affected "
                    f"frontmatter field(s) {', '.join(verification_fields)} into "
                    f"target locale {locale_label}."
                )
                source_guidance = CampaignRunner._frontmatter_source_guidance(
                    source_path, verification_fields, target_lang
                )
                if source_guidance:
                    instructions.append(source_guidance)
            if locale_retry_hint and "language_detection" in failed_checks:
                instructions.append(locale_retry_hint)
        if not instructions and not prior_feedback:
            instructions.append(
                f"Regenerate the complete translation in target locale {locale_label} and correct "
                "all prior validation failures without changing structure, code, links, or shortcodes."
            )
        additions = " ".join(instructions)
        if not prior_feedback:
            return additions
        if not additions or additions in prior_feedback:
            return prior_feedback
        return f"{prior_feedback} {additions}"

    @classmethod
    def _retry_feedback_from_failure(
        cls,
        failure: dict[str, Any] | None,
        target_lang: str,
        *,
        source_path: Path | None = None,
        prior_feedback: str | None = None,
    ) -> str | None:
        """Rehydrate safe retry guidance from metadata when resuming."""
        if not failure:
            return None
        reason = str(failure.get("reason") or "")
        gate = str(failure.get("gate") or "")
        validators: list[str] = []
        if gate == "FrontmatterLanguageCheck" or "FrontmatterLanguageCheck" in reason:
            validators.append("FrontmatterLanguageCheck")
        if "RepetitionDetectorValidator" in reason:
            validators.append("RepetitionDetectorValidator")
        if "TerminologyPreservationValidator" in reason:
            validators.append("TerminologyPreservationValidator")
        fields = re.findall(r"\bfield=(title|description|seoTitle|summary)\b", reason)
        issues = [
            SimpleNamespace(
                validator=validator,
                details={"field": fields[0]} if fields else {},
            )
            for validator in validators
        ]
        verification_checks_match = re.search(r"\bverification_checks=([A-Za-z0-9_,-]+)\b", reason)
        verification_issues = [
            SimpleNamespace(
                check_name=check,
                severity="warning",
                location=(
                    f"frontmatter.{fields[0]}"
                    if check == "language_detection" and fields
                    else next(
                        (
                            f"frontmatter.{field}"
                            for field in ("title", "description", "seoTitle", "summary")
                            if re.search(
                                rf"{re.escape(check)}:(?:error|warning):"
                                rf"{hashlib.sha256(f'frontmatter.{field}'.encode()).hexdigest()[:16]}",
                                reason,
                            )
                        ),
                        "",
                    )
                ),
                metadata={},
            )
            for check in (
                verification_checks_match.group(1).split(",")
                if verification_checks_match and verification_checks_match.group(1) != "none"
                else []
            )
        ]
        return cls._retry_feedback(
            SimpleNamespace(
                validation_result=SimpleNamespace(issues=issues),
                verification_result=SimpleNamespace(issues=verification_issues),
                error=reason,
            ),
            target_lang,
            prior_feedback,
            source_path=source_path,
        )

    @classmethod
    def _retry_feedback_from_failures(
        cls,
        failures: list[dict[str, Any]],
        target_lang: str,
        *,
        source_path: Path | None = None,
    ) -> str | None:
        """Fold distinct recent failure metadata into one safe instruction."""
        feedback: str | None = None
        for failure in failures:
            feedback = cls._retry_feedback_from_failure(
                failure,
                target_lang,
                source_path=source_path,
                prior_feedback=feedback,
            )
        return feedback

    def verify(
        self,
        *,
        resume: bool = False,
        shard_ids: frozenset[str] | None = None,
        require_clean: bool = True,
    ) -> dict[str, Any]:
        receipts = self._validated_resume_receipts() if resume else {}
        scope_sources: set[str] | None = None
        scope_outputs: set[str] | None = None
        if shard_ids:
            max_outputs = int(self.manifest.commit_policy.get("max_outputs_per_commit", 250))
            available = {
                str(shard["shard_id"]): shard
                for shard in self.manifest.shards(
                    resume_receipts=set(receipts),
                    max_outputs=max_outputs,
                )
            }
            unknown = sorted(shard_ids - set(available))
            if unknown:
                raise CampaignManifestError(
                    f"campaign shard is unknown or already complete: {unknown}"
                )
            selected = (available[shard_id] for shard_id in shard_ids)
            jobs = [job for shard in selected for job in shard["jobs"]]
            scope_sources = {source.source_path for source, _locale, _output in jobs}
            scope_outputs = {output for _source, _locale, output in jobs}
        self.manifest.verify_environment(
            translator_repo=self.translator_repo,
            require_clean=require_clean,
            allow_existing_accepted=set(receipts),
            scope_sources=scope_sources,
            scope_outputs=scope_outputs,
            allow_campaign_tm_drift=resume,
        )
        return {
            **self.manifest.to_summary(),
            "accepted": len(receipts),
            "remaining": self.manifest.expected_output_count - len(receipts),
        }

    def run(
        self,
        *,
        resume: bool = False,
        verify_only: bool = False,
        shard_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Run all campaign jobs or one explicitly pinned shard set.

        Shard workers may run in separate processes because their outputs are
        disjoint and the ledger is inter-process locked.  The default still
        holds a campaign-wide exclusion lock for compatibility and safety.
        """
        normalized = frozenset(shard_ids or ())
        lock_name = "campaign.lock"
        if normalized:
            lock_name = (
                "shard-"
                + hashlib.sha256("\n".join(sorted(normalized)).encode("utf-8")).hexdigest()[:16]
                + ".lock"
            )
        self._startup_checkpoint("lock_wait")
        with FileLock(self.ledger.root / lock_name, timeout=0):
            self._startup_checkpoint("lock_acquired")
            return self._run_locked(
                resume=resume,
                verify_only=verify_only,
                shard_ids=normalized or None,
            )

    def _primary_backend_is_deterministic(self, model_id: str) -> bool:
        """Whether ``model_id`` is a fully deterministic (non-LLM) backend.

        Every MT backend in config/model_registry.yaml (m2m100, nllb, opus,
        marian, small100 -- anything routed to HuggingFaceBackend or
        CTranslate2Backend) runs with do_sample=False and a fixed num_beams
        (src/model_runtime/loader.py) and never receives retry-feedback text
        (src/translation_engine/segment_translator.py only attaches it for
        ``isinstance(mt_model, LLMModelBackend)``).  So once such a backend
        rejects attempt 1, attempts 2 and 3 are guaranteed to reproduce
        byte-identical output -- there is no code path that could make them
        differ, and spending them is pure waste.

        This reads the same registry `backend` field ``_llm_identity_gate``
        already reads rather than instantiating a backend or hardcoding a
        model-id allowlist: ``ModelLoader._create_backend``
        (src/model_runtime/loader.py) routes backend in ("llm", "local_llm")
        to LLMModelBackend and everything else to a deterministic backend, so
        that field is the actual source of truth for the isinstance split.
        A model_id the registry can't resolve (e.g. a lightweight engine
        double in tests, or a future manifest field this campaign runner
        doesn't otherwise validate) is "unknown" -- preserve today's full
        3-attempt behaviour rather than guess.
        """
        try:
            registry = self.engine.model_loader.registry
            info = registry.get_model(model_id)
        except Exception:
            return False
        return getattr(info, "backend", None) not in ("llm", "local_llm")

    def _run_campaign_job(
        self,
        *,
        shard: dict[str, Any],
        source,
        locale: str,
        expected_output: str,
    ) -> tuple[bool, str]:
        """Run one immutable candidate job and return (accepted, output).

        This method is deliberately independent of shard accounting so a
        bounded executor can overlap parsing, validation and remote fidelity
        calls.  It never returns candidate text; failures are persisted only
        through the metadata-only ledger.
        """
        source_path = self.content_repo / source.source_path
        profile = self.engine.config.get_site_profile(source.site_id)
        calculated = self.engine._get_output_path(source_path, locale, profile)
        expected = self.content_repo / expected_output
        if calculated.resolve() != expected.resolve():
            raise CampaignManifestError(
                f"output routing mismatch: calculated={calculated}, expected={expected}"
            )
        resolved_output = str(expected.resolve())

        # QU-03: an active advisory hold is a deliberate operator "stop
        # touching this file" signal, distinct from and taking precedence
        # over any automated quarantine dimension below -- checked first,
        # regardless of prior failure history, so an unseen locale on a held
        # file is skipped too, not silently attempted.
        heal_queue_path = self.ledger.root.parent / "heal_queue.jsonl"
        hold = active_hold(source.source_path, heal_queue_path=heal_queue_path)
        if hold is not None:
            self._append_advisory_hold_skip(
                shard=shard, source=source, locale=locale, hold=hold
            )
            return False, resolved_output

        # QU-02: a (source_path, root_cause_class) pair whose OPEN heal tickets
        # span >=PER_FILE_QUARANTINE_THRESHOLD distinct locales is a systemic,
        # file-level defect -- skip it even for a locale that has never been
        # attempted, unlike the per-locale dimension below (the live case:
        # quickstart.md kept accumulating fresh single-locale LinkValidator
        # tickets across 7+ locales, never tripping the per-locale threshold).
        recovery_qualification = bool(
            getattr(self.engine, "campaign_context", {}).get("recovery_qualification", False)
        )
        file_quarantined, _file_root_cause = is_source_path_quarantined(
            source.source_path, heal_queue_path=heal_queue_path
        )
        if file_quarantined and not recovery_qualification:
            self._append_heal_ticket(
                shard=shard, source=source, locale=locale, expected_output=expected_output
            )
            return False, resolved_output

        # TC-APT-038: a (target_lang, root_cause_class) pair with >=3 OPEN heal
        # tickets anywhere in the portfolio is quarantined -- skip spending
        # fresh retry attempts on this job (no manifest/retry_policy needed)
        # and go straight to a (refreshed) ticket instead. Only applies to a
        # job with prior failure history on THIS exact cell: an unseen
        # candidate always gets its first attempt (plan §3 item 4 -- never
        # quarantine an unseen candidate).
        prior_failure = self.ledger.latest_failure(output_path=expected_output, target_lang=locale)
        if prior_failure is not None and not recovery_qualification:
            prior_root_cause = f"auto:{prior_failure.get('gate')}"
            if is_quarantined(
                locale,
                prior_root_cause,
                heal_queue_path=heal_queue_path,
            ):
                self._append_heal_ticket(
                    shard=shard, source=source, locale=locale, expected_output=expected_output
                )
                return False, resolved_output

        primary_attempts = int(self.manifest.retry_policy["primary_attempts"])
        llm_attempts = int(self.manifest.retry_policy["llm_escalation_attempts"])
        primary_model = str(self.manifest.retry_policy["primary_model"])
        llm_model = str(self.manifest.retry_policy["llm_model"])
        receipt = None
        result = None
        # TC-APT-031: governed replace-existing. An undeclared existing target is still a hard
        # stop (verify_environment). A declared one may be overwritten only while its current
        # bytes still hash to the declared expected_sha256 (no concurrent edit underneath).
        declared = source.replacement_for(locale) if hasattr(source, "replacement_for") else None
        original_sha = str(declared["expected_sha256"]) if declared else None
        if declared:
            if not expected.is_file():
                raise CampaignManifestError(
                    f"declared replacement target is missing: {expected_output}"
                )
            if sha256_file(expected) != original_sha:
                raise CampaignManifestError(
                    f"declared replacement pre-hash drift (concurrent change?): {expected_output}"
                )
        with self._engine_campaign_state_lock:
            if declared:
                self.engine.campaign_context.setdefault("replace_existing", {})[expected_output] = (
                    original_sha
                )
            llm_paths = getattr(self.engine, "_rtq_llm_output_paths", None)
            if llm_paths is None:
                llm_paths = set()
                self.engine._rtq_llm_output_paths = llm_paths
            feedback_by_output = getattr(self.engine, "_campaign_retry_feedback_by_output", None)
            if feedback_by_output is None:
                feedback_by_output = {}
                self.engine._campaign_retry_feedback_by_output = feedback_by_output
            attempt_metadata_by_output = self.engine.campaign_context.setdefault(
                "attempt_metadata_by_output", {}
            )

        # The primary invocation owns initial output plus its two guided
        # retries.  LLM escalation has exactly two one-attempt invocations.
        #
        # A fully deterministic primary backend (do_sample=False, fixed
        # num_beams, no retry-feedback channel -- see
        # _primary_backend_is_deterministic) reproduces byte-identical output
        # on every attempt, so its 2 guided retries are guaranteed no-ops:
        # collapse the primary retry budget to 0 (exactly 1 real invocation)
        # and fail fast to LLM escalation instead of burning 2 wasted GPU
        # generation cycles per cell. The manifest's declared primary_attempts
        # (and therefore the LLM phases' attempt numbering, which still
        # starts at primary_attempts + 1 for audit-trail continuity) is
        # unchanged -- only the wasted runtime re-invocations are skipped. An
        # LLM primary backend keeps today's exact 3-attempt behaviour.
        primary_retry_budget = primary_attempts - 1
        if self._primary_backend_is_deterministic(primary_model):
            primary_retry_budget = 0
        phases = [
            (False, primary_retry_budget, primary_attempts),
            *[(True, 0, primary_attempts + index) for index in range(1, llm_attempts + 1)],
        ]
        next_feedback = self._retry_feedback_from_failures(
            self.ledger.recent_failures(
                output_path=expected_output,
                target_lang=locale,
            ),
            locale,
            source_path=source_path,
        )
        seen_failure_fingerprints = {
            (str(row.get("candidate_sha256")), str(row.get("gate")))
            for row in self.ledger.recent_failures(
                output_path=expected_output,
                target_lang=locale,
            )
            if row.get("candidate_sha256")
        }
        try:
            for use_llm, retry_budget, attempt_number in phases:
                # A manifest model pin takes precedence over the adaptive
                # selector. TC-APT-045: the pin travels as a call-scoped
                # translate_file(model_id=...) argument instead of the former
                # engine.model_id_override attribute mutation, which raced
                # concurrent jobs sharing this engine instance.
                phase_model_id = llm_model if use_llm else primary_model
                with self._engine_campaign_state_lock:
                    if use_llm:
                        llm_paths.add(resolved_output)
                    if next_feedback:
                        feedback_by_output[resolved_output] = next_feedback
                    attempt_metadata_by_output[resolved_output] = {
                        "campaign_attempt": attempt_number,
                        "attempt_model_id": phase_model_id,
                    }
                translate_kwargs = {
                    "target_langs": [locale],
                    "validate": True,
                    # TC-APT-031/TC-APT-013: for a declared replace_existing cell, force=True
                    # too, not just force_overwrite. engine.translate_file()'s own
                    # _should_skip_translation runs BEFORE force_overwrite is ever consulted --
                    # it skips retranslation outright whenever the target already exists, is
                    # non-empty, and (mtime OR content-hash, whichever check fires) looks
                    # "already up to date" relative to the source -- exactly the state a
                    # replace_existing target is in by definition (unchanged source, existing
                    # target). Confirmed directly: a real replace_existing run silently no-opped
                    # (TranslationStats new=0, tm_hits=0, ~0.02s) with force=False despite a
                    # correct force_overwrite=True declaration; force=True on the same call
                    # produced a genuine translation. Leaving force=False for undeclared
                    # (MISSING_TRANSLATION) cells is unchanged and correct -- there is no
                    # existing target to skip past there. Portfolio-relevant: every declared
                    # replace_existing cell (112,584 in TC-APT-031's remit) was at risk of this
                    # same silent no-op depending on filesystem mtime ordering, which this fixes.
                    "force": bool(declared),
                    # TC-APT-031: overwrite ONLY the declared, pre-hash-verified target.
                    "force_overwrite": bool(declared),
                    "trigger_type": "campaign",
                    "retry_budget_override": retry_budget,
                    "model_id": phase_model_id,
                }
                policy_mode = (
                    "deferred"
                    if self.manifest.retry_policy.get("llm_escalation_mode") == "deferred"
                    else "immediate"
                )
                with (
                    self._rollback_serialization(),
                    campaign_llm_scope(
                        policy_mode,
                        "retry" if use_llm else "primary",
                        self._llm_event,
                        professionalize_only=bool(
                            self.manifest.retry_policy.get("professionalize_only", False)
                        ),
                        campaign_id=self.manifest.campaign_id,
                        source_path=source.source_path,
                        output_path=expected_output,
                        target_lang=locale,
                        attempt=attempt_number,
                    ),
                ):
                    result = self.engine.translate_file(
                        source.site_id, source_path, **translate_kwargs
                    )
                receipt = result.acceptance_receipts.get(locale)
                if receipt is None:
                    receipt = self.ledger.receipts().get(expected_output)
                if receipt is not None and expected.is_file():
                    break
                if expected.exists():
                    if declared and sha256_file(expected) == original_sha:
                        # The untouched original survived a rejected attempt: keep it.
                        pass
                    else:
                        expected.unlink(missing_ok=True)
                        raise CampaignManifestError(
                            f"rejected attempt produced an unreceipted output: {expected_output}"
                        )
                failure_gate, failure_reason = self._failure_metadata(result)
                candidate_sha256 = (getattr(result, "candidate_sha256", {}) or {}).get(locale)
                failure_fingerprint = (str(candidate_sha256), failure_gate)
                # A retry must be source-based and materially different when
                # it is meant to repair a prior failure.  The first repeated
                # paid candidate is recorded for audit, then further paid
                # retries are suppressed; the normal terminal heal ticket
                # path below retains the cell for a later consumer.
                duplicate_paid_candidate = (
                    use_llm
                    and candidate_sha256
                    and failure_fingerprint in seen_failure_fingerprints
                )
                next_feedback = self._retry_feedback(
                    result,
                    locale,
                    next_feedback,
                    source_path=source_path,
                )
                self.ledger.append_failure(
                    source_path=source.source_path,
                    output_path=expected_output,
                    target_lang=locale,
                    error=failure_reason,
                    attempt=attempt_number,
                    job_id=(f"{shard['shard_id']}::{source.source_path}::{locale}"),
                    source_sha256=source.source_sha256,
                    candidate_sha256=candidate_sha256,
                    model_id=phase_model_id,
                    gate=failure_gate,
                )
                seen_failure_fingerprints.add(failure_fingerprint)
                if duplicate_paid_candidate:
                    self.ledger.append_failure(
                        source_path=source.source_path,
                        output_path=expected_output,
                        target_lang=locale,
                        error="duplicate_candidate_failure_fingerprint",
                        attempt=attempt_number,
                        job_id=(f"{shard['shard_id']}::{source.source_path}::{locale}"),
                        source_sha256=source.source_sha256,
                        candidate_sha256=candidate_sha256,
                        model_id=phase_model_id,
                        gate="duplicate_retry_suppressed",
                    )
                    break
        except Exception as exc:
            # An engine crash must not leave an unreceipted bytes-on-disk
            # candidate behind.  Expected output is manifest-scoped.
            if (
                expected.exists()
                and receipt is None
                and not (declared and sha256_file(expected) == original_sha)
            ):
                expected.unlink(missing_ok=True)
            if isinstance(exc, CampaignManifestError):
                raise
            self.ledger.append_failure(
                source_path=source.source_path,
                output_path=expected_output,
                target_lang=locale,
                error=f"campaign_job_exception={type(exc).__name__}",
                attempt=0,
                job_id=(f"{shard['shard_id']}::{source.source_path}::{locale}"),
                source_sha256=source.source_sha256,
                model_id=(llm_model if "llm_model" in locals() else None),
                gate="campaign_job_exception",
            )
            return False, expected_output
        finally:
            with self._engine_campaign_state_lock:
                llm_paths.discard(resolved_output)
                feedback_by_output.pop(resolved_output, None)
                attempt_metadata_by_output.pop(resolved_output, None)
                if declared:
                    (self.engine.campaign_context.get("replace_existing") or {}).pop(
                        expected_output, None
                    )

        if receipt is None or not expected.is_file():
            return False, expected_output
        if Path(receipt["output_path"]).resolve() != expected.resolve():
            expected.unlink(missing_ok=True)
            raise CampaignManifestError(f"accepted receipt path mismatch for {expected_output}")
        return True, expected_output

    def _llm_identity_gate(self) -> dict[str, Any] | None:
        """TC-APT-021: run the model-identity canary for the manifest's LLM if the cadence elapsed.

        DRIFT records a review item and quarantines the model (force-opens its breaker) so
        ``ModelLoader`` reroutes to the automatic fallback and the campaign continues (plan
        section 21). UNAVAILABLE is recorded in the drift log, never treated as a pass.
        Returns the check as a dict for the run summary, or None when not applicable.
        """
        if self.manifest.retry_policy.get("llm_escalation_mode") == "deferred":
            # The identity canary is itself a provider request.  A deferred
            # campaign promises to enqueue Professionalize work rather than
            # perform any in-run provider call, so record this explicitly
            # instead of making an unaccounted exception to that policy.
            return {
                "status": "SKIPPED",
                "reason": "llm_escalation_mode=deferred",
                "cadence": "deferred",
            }
        try:
            te_cfg = self.engine.config.get_config().get("translation_engine", {}) or {}
        except Exception:
            te_cfg = {}
        cfg = te_cfg.get("llm_identity_check") or {}
        if not cfg.get("enabled", True):
            return None
        llm_model = str(self.manifest.retry_policy.get("llm_model") or "")
        if not llm_model:
            return None
        try:
            registry = self.engine.model_loader.registry
            info = registry.get_model(llm_model)
        except (
            Exception
        ) as exc:  # engine double without a registry (tests) -- not a provider failure
            logger.info("identity gate skipped: no model registry available (%s)", exc)
            return None
        if getattr(info, "backend", None) != "llm":
            return None
        from src.model_runtime import model_identity
        from src.model_runtime.contracts import LLMProviderConfig
        from src.model_runtime.llm_providers import create_provider

        interval = float(cfg.get("interval_hours", 6))
        identity_dir = Path(
            getattr(self.engine, "campaign_identity_dir", None)
            or cfg.get("identity_dir", "data/runtime/llm_identity")
        )
        if not model_identity.should_check(
            llm_model, interval_hours=interval, identity_dir=identity_dir
        ):
            last = model_identity.last_check(llm_model, identity_dir=identity_dir)
            return {**(last or {}), "cadence": "not_due"}
        provider = create_provider(LLMProviderConfig.from_model_info(info))
        check = model_identity.check_identity(
            provider,
            llm_model,
            identity_dir=identity_dir,
            quarantine_on_drift=bool(cfg.get("quarantine_on_drift", True)),
            quarantine_seconds=float(cfg.get("quarantine_seconds", 6 * 3600)),
        )
        level = logger.warning if check.status != "MATCH" else logger.info
        level(
            "model identity check for %s: %s (%s)%s",
            llm_model,
            check.status,
            check.detail,
            " -- QUARANTINED, work reroutes to the fallback" if check.quarantined else "",
        )
        return {**check.__dict__, "cadence": "checked"}

    def _run_locked(
        self,
        *,
        resume: bool = False,
        verify_only: bool = False,
        shard_ids: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        diagnostic_no_write = getattr(self.engine, "diagnostic_no_write", False) is True
        self._startup_checkpoint("verify_begin")
        summary = self.verify(
            resume=resume,
            shard_ids=shard_ids,
            # Diagnostic mode cannot write content, receipts, TM, or commits;
            # unrelated shared-worktree dirt is therefore not relevant to its
            # read-only candidate classification.
            require_clean=not diagnostic_no_write,
        )
        self._startup_checkpoint("verify_complete")
        if verify_only:
            self.ledger.write_summary({**summary, **self._summary_evidence(), "status": "VERIFIED"})
            return summary

        # TC-APT-021: model-identity canary before new LLM work (cadence-gated).
        identity_policy_mode = (
            "deferred"
            if self.manifest.retry_policy.get("llm_escalation_mode") == "deferred"
            else "immediate"
        )
        self._startup_checkpoint("identity_begin")
        with campaign_llm_scope(
            identity_policy_mode,
            "identity",
            self._llm_event,
            professionalize_only=bool(
                self.manifest.retry_policy.get("professionalize_only", False)
            ),
            campaign_id=self.manifest.campaign_id,
        ):
            self._llm_identity_check = self._llm_identity_gate()
        self._startup_checkpoint("identity_complete")

        self._startup_checkpoint("receipts_begin")
        receipts = self._validated_resume_receipts() if resume else {}
        self._startup_checkpoint("receipts_complete")
        self.engine.campaign_context.update(
            {
                "campaign_id": self.manifest.campaign_id,
                "config_fingerprint": self.manifest.config_fingerprint,
                "receipt_sink": self._append_campaign_receipt,
            }
        )

        accepted = len(receipts)
        failed = 0
        max_outputs = int(self.manifest.commit_policy.get("max_outputs_per_commit", 250))
        max_parallel_jobs = int(self.manifest.execution_policy.get("max_parallel_jobs", 1))
        self._startup_checkpoint("shards_begin")
        all_shards = list(
            self.manifest.shards(
                resume_receipts=set(receipts),
                max_outputs=max_outputs,
            )
        )
        self._startup_checkpoint(f"shards_complete count={len(all_shards)}")
        available_shards = {str(shard["shard_id"]) for shard in all_shards}
        if shard_ids and not shard_ids.issubset(available_shards):
            unknown = sorted(shard_ids - available_shards)
            raise CampaignManifestError(f"campaign shard is unknown or already complete: {unknown}")
        # TC-APT-041 (plan G-29/§0.2): a shard with some failed jobs still commits its
        # passing ones and the run still attempts every remaining shard -- a failing
        # cell no longer costs its siblings (same shard) or other pages (other shards)
        # their progress. Safe because _commit_verified_outputs only ever stages
        # checksum-receipted paths (a failed job has no receipt, so it can never be
        # swept into a commit); failed_shard_ids is surfaced in the final summary so
        # failures stay visible instead of silently disappearing.
        failed_shard_ids: list[str] = []
        for shard in all_shards:
            if shard_ids and shard["shard_id"] not in shard_ids:
                continue
            shard_accepted = 0
            shard_failed = 0
            self._startup_checkpoint(
                f"dispatch_begin shard={shard['shard_id']} jobs={len(shard['jobs'])}"
            )
            with ThreadPoolExecutor(
                max_workers=min(max_parallel_jobs, len(shard["jobs"]))
            ) as executor:
                future_to_job = {
                    executor.submit(
                        self._run_campaign_job,
                        shard=shard,
                        source=source,
                        locale=locale,
                        expected_output=expected_output,
                    ): (source, locale, expected_output)
                    for source, locale, expected_output in shard["jobs"]
                }
                for future in as_completed(future_to_job):
                    job_accepted, _output = future.result()
                    if job_accepted:
                        accepted += 1
                        shard_accepted += 1
                    else:
                        failed += 1
                        shard_failed += 1
                        source, locale, expected_output = future_to_job[future]
                        self._append_heal_ticket(
                            shard=shard,
                            source=source,
                            locale=locale,
                            expected_output=expected_output,
                        )
            self.ledger.write_summary(
                {
                    **self.manifest.to_summary(),
                    "status": "SHARD_COMPLETE" if shard_failed == 0 else "SHARD_PARTIAL",
                    "shard_id": shard["shard_id"],
                    "shard_accepted": shard_accepted,
                    "shard_failed": shard_failed,
                    "accepted": accepted,
                    "failed": failed,
                    "model_outcomes": self.ledger.model_outcomes(),
                    "attempt_model_outcomes": self.ledger.attempt_model_outcomes(),
                    "quality_stop_recommendations": self._quality_stop_recommendations(),
                    "llm_call_outcomes": self.ledger.llm_call_outcomes(),
                    "acceleration_metrics": self.ledger.acceleration_metrics(),
                }
            )
            if shard_failed:
                failed_shard_ids.append(str(shard["shard_id"]))
            commit_sha = None
            if self.manifest.commit_policy.get("enabled", True):
                commit_sha = self._commit_verified_outputs(shard["shard_id"])
            if commit_sha:
                self.ledger.write_summary(
                    {
                        **self.manifest.to_summary(),
                        "status": "SHARD_COMMITTED",
                        "shard_id": shard["shard_id"],
                        "commit_sha": commit_sha,
                        "accepted": accepted,
                        "failed": failed,
                        "model_outcomes": self.ledger.model_outcomes(),
                        "attempt_model_outcomes": self.ledger.attempt_model_outcomes(),
                        "quality_stop_recommendations": self._quality_stop_recommendations(),
                        "llm_call_outcomes": self.ledger.llm_call_outcomes(),
                        "acceleration_metrics": self.ledger.acceleration_metrics(),
                    }
                )

        partial = bool(shard_ids)
        final = {
            **self.manifest.to_summary(),
            "accepted": accepted,
            "failed": failed,
            "failed_shard_ids": failed_shard_ids,
            "remaining": self.manifest.expected_output_count - accepted,
            "model_outcomes": self.ledger.model_outcomes(),
            "attempt_model_outcomes": self.ledger.attempt_model_outcomes(),
            "quality_stop_recommendations": self._quality_stop_recommendations(),
            "llm_call_outcomes": self.ledger.llm_call_outcomes(),
            "acceleration_metrics": self.ledger.acceleration_metrics(),
            "status": (
                "SHARD_SET_COMPLETE"
                if partial and failed == 0
                else (
                    "COMPLETE"
                    if accepted == self.manifest.expected_output_count and failed == 0
                    else "PARTIAL_WITH_TICKETS"
                )
            ),
        }
        self.ledger.write_summary(final)
        if final["status"] not in {"COMPLETE", "SHARD_SET_COMPLETE"}:
            # TC-APT-041 (plan §11): shards that failed already committed their
            # receipted outputs above -- an ordinary per-file review rejection
            # is expected Track-A traffic (it has a heal ticket now), not an
            # infrastructure failure, so it must never propagate as an
            # unhandled exception. execution_policy.on_job_failure="raise" is
            # kept for a caller that deliberately wants strict all-or-nothing
            # behavior (e.g. a targeted regression re-run proving a fix).
            on_job_failure = str(self.manifest.execution_policy.get("on_job_failure", "continue"))
            if on_job_failure == "raise":
                err = CampaignManifestError(
                    f"campaign incomplete: accepted={accepted}, failed={failed}, "
                    f"remaining={final['remaining']}, failed_shard_ids={failed_shard_ids}"
                )
                err.summary = final
                raise err
        return final

    def _append_heal_ticket(
        self,
        *,
        shard: dict[str, Any],
        source: Any,
        locale: str,
        expected_output: str,
    ) -> None:
        """TC-APT-041/038: record a content-free heal ticket for a job that
        exhausted every retry, so a per-file rejection is never silently lost
        once the run stops raising for it."""
        failure = self.ledger.latest_failure(output_path=expected_output, target_lang=locale)
        gate = str(failure.get("gate")) if failure else "unclassified"
        note = str(failure.get("reason", ""))[:1000] if failure else ""
        ticket = {
            "ticket_id": (
                f"auto-{self.manifest.campaign_id}-{shard['shard_id']}-"
                f"{Path(source.source_path).stem}"
            ),
            "site_id": shard.get("site_id", getattr(source, "site_id", "")),
            "source_path": source.source_path,
            "target_lang": locale,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "root_cause_class": f"auto:{gate}",
            "evidence_path": f"data/campaigns/{self.manifest.campaign_id}/failure_metadata.jsonl",
            "status": (
                "QUEUED"
                if self.manifest.retry_policy.get("llm_escalation_mode") == "deferred"
                else "OPEN"
            ),
            "processing_model": (
                self.manifest.retry_policy.get("llm_model")
                if self.manifest.retry_policy.get("llm_escalation_mode") == "deferred"
                else None
            ),
            "tier": "unclassified",
            "note": note,
        }
        heal_queue_path = self.ledger.root.parent / "heal_queue.jsonl"
        # TC-PORT-LLM-009: a heal ticket is best-effort observability, not a
        # correctness-critical write -- confirmed live under a real 4-worker
        # soak: enough jobs hit the QU-02/QU-38 quarantine-refresh branches in
        # the same burst (heavily-contaminated candidate pool) that one
        # thread's FileLock(ledger-process.lock, timeout=30) exceeded 30s,
        # raised LockError, and (uncaught) crashed the ENTIRE worker process
        # via the ThreadPoolExecutor future -- losing every other job still
        # in flight on the other 3 threads, not just this one ticket write.
        # Losing one ticket write is recoverable (the next attempt on this
        # cell regenerates it); losing a whole worker's in-flight batch is
        # not. Log loudly, never let this crash the process.
        try:
            self.ledger._append(heal_queue_path, ticket)
        except LockError as exc:
            logger.error(
                "Heal ticket write timed out under lock contention (ticket %s dropped, "
                "not fatal): %s",
                ticket["ticket_id"],
                exc,
            )
        if ticket["status"] == "QUEUED":
            self._enqueue_rejected_retry(
                source=source,
                locale=locale,
                expected_output=expected_output,
                gate=gate,
                failure=failure,
            )

    def _append_advisory_hold_skip(
        self,
        *,
        shard: dict[str, Any],
        source: Any,
        locale: str,
        hold: dict[str, Any],
    ) -> None:
        """QU-03: record that a job was skipped because of an active advisory
        hold, distinct from a heal ticket -- a hold is an operator decision,
        not a validator finding, and must never count toward either
        quarantine dimension in heal_queue.py. Written to its own file so
        campaign output clearly distinguishes a held job from a
        genuinely-attempted-and-failed one."""
        record = {
            "campaign_id": self.manifest.campaign_id,
            "shard_id": shard.get("shard_id"),
            "site_id": shard.get("site_id", getattr(source, "site_id", "")),
            "source_path": source.source_path,
            "target_lang": locale,
            "outcome": "held_by_advisory",
            "hold_reason": hold.get("reason"),
            "hold_expiry": hold.get("expiry"),
            "hold_created_at": hold.get("created_at"),
            "skipped_at": datetime.now(timezone.utc).isoformat(),
        }
        # TC-PORT-LLM-009: same reasoning as _append_heal_ticket -- best-effort
        # observability, must never crash the worker over lock contention.
        try:
            self.ledger._append(self.ledger.root / "advisory_holds_skipped.jsonl", record)
        except LockError as exc:
            logger.error(
                "Advisory-hold-skip record write timed out under lock contention "
                "(source=%s locale=%s dropped, not fatal): %s",
                source.source_path,
                locale,
                exc,
            )
