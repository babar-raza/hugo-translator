"""Source-based, claim-safe Professionalize retry consumer.

This worker never receives rejected candidate bytes.  It reads the immutable
source file, delegates generation to the configured provider abstraction, then
requires complete-document validation before atomically publishing output and
appending a TM intent.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from src.tm.intent_spool import TMIntentSpool
from src.tm.rejected_task_queue import RejectedTaskQueue
from src.tm.retry_records import RejectedTranslationTask


class DocumentProvider(Protocol):
    def generate(self, system_prompt: str, user_text: str) -> tuple[str, int, int]: ...


Validator = Callable[[str, str, RejectedTranslationTask], dict[str, Any] | None]


def write_retry_heartbeat(path: Path, *, status: str, queue: RejectedTaskQueue) -> None:
    """Write payload-free health state without loading a provider or model."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"timestamp": datetime.now(timezone.utc).isoformat(), "status": status, **queue.health()},
            sort_keys=True,
        ),
        encoding="utf-8",
    )


class ProfessionalizeRetryWorker:
    """Consumes retry tasks without CUDA; one task is claimed by one worker."""

    def __init__(self, *, queue: RejectedTaskQueue, intent_spool: TMIntentSpool,
                 provider: DocumentProvider, repository_root: Path,
                 validate_document: Validator, live_mode: bool = False) -> None:
        self.queue = queue
        self.intent_spool = intent_spool
        self.provider = provider
        self.repository_root = Path(repository_root).resolve()
        self.validate_document = validate_document
        self.live_mode = live_mode

    def run_once(self, *, owner: str | None = None, limit: int = 1, lease_seconds: float = 300) -> dict[str, int]:
        owner = owner or f"professionalize-retry-{uuid.uuid4()}"
        counts = {"accepted": 0, "retried": 0, "dead_lettered": 0}
        for task_id, task, attempt in self.queue.claim(owner, limit=limit, lease_seconds=lease_seconds):
            disposition = self._process(task_id, task, attempt, owner)
            counts[disposition] += 1
        return {**counts, **self.queue.stats()}

    def _path(self, value: str) -> Path:
        path = (self.repository_root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        if path != self.repository_root and self.repository_root not in path.parents:
            raise ValueError("path escapes repository root")
        return path

    def _process(self, task_id: str, task: RejectedTranslationTask, attempt: int, owner: str) -> str:
        try:
            source_path, output_path = self._path(task.source_path), self._path(task.output_path)
            # Hash immutable on-disk bytes before decoding.  Text-mode newline
            # normalization on Windows would otherwise turn a valid CRLF source
            # into a false SOURCE_DRIFT rejection.
            source_bytes = source_path.read_bytes()
            if hashlib.sha256(source_bytes).hexdigest() != task.source_sha256:
                self.queue.dead_letter(task_id, owner, "SOURCE_DRIFT")
                return "dead_lettered"
            source = source_bytes.decode("utf-8")
            if not self.live_mode:
                self.queue.retry(task_id, owner, "LIVE_MODE_DISABLED")
                return "retried"
            candidate, input_tokens, output_tokens = self.provider.generate(
                "Translate the complete Hugo document. Preserve structure, front matter, links, and code.", source
            )
            campaign_receipt = self.validate_document(source, candidate, task)
            receipt = {"receipt_id": uuid.uuid4().hex, "task_id": task_id,
                       "source_sha256": task.source_sha256,
                       "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
                       "model_target": task.model_target,
                       "input_tokens": input_tokens, "output_tokens": output_tokens}
            if campaign_receipt is not None:
                # AcceptedTranslation.receipt() is metadata-only. Keep it
                # nested so the queue's own durable receipt remains backward
                # compatible while campaign consumers can attest all 44 gates.
                receipt["campaign_receipt"] = campaign_receipt
            # Publish only after complete-document validation, then make its
            # receipt durable before appending an eventual-consistency TM intent.
            self._atomic_write(output_path, candidate)
            self.queue.accepted(task_id, owner, receipt)
            intent_id = self.intent_spool.enqueue({
                "site_id": task.site_id, "src_lang": "en", "tgt_lang": task.target_lang,
                "text": source, "translation": candidate,
                "metadata": {"campaign_id": task.campaign_id, "retry_task_id": task_id,
                             "model_target": task.model_target},
            })
            self.queue.attach_intent(task_id, intent_id)
            return "accepted"
        except Exception as exc:
            if attempt >= task.retry_budget:
                self.queue.dead_letter(task_id, owner, type(exc).__name__)
                return "dead_lettered"
            self.queue.retry(task_id, owner, type(exc).__name__)
            return "retried"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            file.write(content)
            temporary = Path(file.name)
        os.replace(temporary, path)


class _SlotGuardedProvider:
    """Adapts an LLMModelBackend to the DocumentProvider protocol.

    Mirrors src/translation_engine/correction.py's attempt_correction(), the
    only other place that calls a backend's raw ``_provider.generate()``
    directly: that call bypasses LLMModelBackend.translate()/translate_batch(),
    so it must acquire the cross-process slot itself (TC-APT-094) or it
    evades the fleet-wide cap on in-flight professionalize_llm calls.
    """

    def __init__(self, backend) -> None:
        self._backend = backend

    def generate(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        if self._backend._provider is None:
            raise RuntimeError("professionalize_llm provider not initialized")
        with self._backend._llm_slot():
            return self._backend._provider.generate(system_prompt, user_text)


def build_professionalize_provider(model_id: str = "professionalize_llm") -> DocumentProvider:
    """Construct the real, slot-guarded Professionalize provider.

    Safe to call even outside live_mode: constructing a provider costs an API
    client handle, not a translation -- ProfessionalizeRetryWorker never
    calls .generate() unless live_mode=True.
    """
    from src.model_runtime.llm_backend import LLMModelBackend
    from src.model_runtime.registry import ModelRegistry

    model_info = ModelRegistry().get_model(model_id)
    backend = LLMModelBackend(model_info, device="api")
    backend.load()
    return _SlotGuardedProvider(backend)


def build_default_validator() -> Validator:
    """A whole-document validate_document callback over ValidationSuite's
    default battery (placeholders, structure, links, completeness, language
    consistency, shortcodes, metadata contamination, repetition).

    This is deliberately narrower than campaign_runner's full zero-defect
    gate battery: FrontmatterProtectionValidator, TerminologyPreservationValidator
    and FilePlacementValidator all require site-profile-specific constructor
    arguments this consumer does not have (it processes tasks from the queue,
    not manifest-scoped campaign jobs). Raises ValueError on any validator
    failure; ProfessionalizeRetryWorker's caller retries or dead-letters.
    """
    from src.translation_engine.validation.base import ValidationSeverity
    from src.translation_engine.validation.validation_suite import ValidationSuite

    suite = ValidationSuite()

    def validate_document(source: str, candidate: str, task: RejectedTranslationTask) -> None:
        result = suite.validate_aggregated(
            source, candidate, {"target_lang": task.target_lang, "site_id": task.site_id}
        )
        # This consumer publishes a whole-document LLM candidate with none of
        # the segment-pipeline's other protections behind it, for a cell that
        # already failed once -- a WARNING-level structural drift (a dropped
        # heading or link) is exactly the class of defect worth blocking here,
        # so the bar is has_errors() OR has_warnings(), not just success
        # (ValidationResult.success only reflects ERROR-severity issues).
        if result.has_errors() or result.has_warnings():
            issues = "; ".join(
                str(issue) for issue in result.issues if issue.severity != ValidationSeverity.INFO
            )[:500]
            raise ValueError(f"validate_document: {issues or 'validation failed'}")

    return validate_document


def build_campaign_zero_defect_validator(engine, repository_root: Path) -> Validator:
    """Adapt TranslationEngine's immutable all-44-gate acceptance boundary.

    The caller supplies a campaign-configured engine, avoiding a second model
    loader in this API-only worker.  It returns the signed, candidate-free
    campaign receipt required for a retry to be treated as campaign acceptance.
    """
    root = Path(repository_root).resolve()

    def validate_document(source: str, candidate: str, task: RejectedTranslationTask) -> dict[str, Any]:
        source_path = (root / task.source_path).resolve()
        output_path = (root / task.output_path).resolve()
        if root not in source_path.parents or root not in output_path.parents:
            raise ValueError("campaign validation path escapes repository root")
        accepted = engine.accept_candidate_bytes(
            source_bytes=source.encode("utf-8"),
            candidate_bytes=candidate.encode("utf-8"),
            source_path=source_path,
            output_path=output_path,
            target_lang=task.target_lang,
            site_id=task.site_id,
            model_fingerprint=task.model_target,
        )
        receipt = accepted.receipt()
        if receipt.get("campaign_id") != task.campaign_id:
            raise ValueError("campaign acceptance receipt has the wrong campaign_id")
        return receipt

    return validate_document


def build_campaign_validator_from_manifest(
    *, campaign_manifest: Path, config_root: Path, repository_root: Path
) -> Validator:
    """Create the campaign-configured all-gate validator without translating.

    Reuses the autonomous worker setup solely to construct the established
    config/TM/model-loader/validation graph.  It uses CPU because this retry
    consumer must never compete with the CUDA M2M primary worker.
    """
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
        AutonomousWorkerConfig,
    )

    worker = AutonomousContentTranslationWorker(
        AutonomousWorkerConfig(
            config_root=str(config_root),
            mode="oneshot",
            device="cpu",
            campaign_manifest=str(campaign_manifest),
            validation_policy="zero-defect",
        )
    )
    worker.setup()
    if worker.campaign is None or Path(worker.campaign.content_repo).resolve() != Path(repository_root).resolve():
        raise ValueError("campaign manifest content repository does not match --repository-root")
    return build_campaign_zero_defect_validator(worker.translation_engine, repository_root)


def load_retry_worker_config(config_root: Path) -> dict[str, Any]:
    """Load and validate the retry-worker's additive global configuration."""
    import yaml

    defaults: dict[str, Any] = {
        "enabled": False,
        "live_mode": False,
        "queue_path": "data/campaigns/rejected_tasks.sqlite3",
        "intent_spool_path": "data/tm/intent_spool.sqlite3",
        "model_id": "professionalize_llm",
        "concurrency": 1,
        "lease_seconds": 300.0,
        "limit": 1,
        "heartbeat_path": "data/logs/professionalize_retry_worker.heartbeat",
    }
    path = Path(config_root) / "global.yaml"
    if not path.exists():
        raise ValueError(f"retry worker config missing: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    configured = loaded.get("professionalize_retry", {})
    if not isinstance(configured, dict):
        raise ValueError("professionalize_retry must be a mapping")
    result = {**defaults, **configured}
    if not isinstance(result["model_id"], str) or not result["model_id"].strip():
        raise ValueError("professionalize_retry.model_id must be a non-empty string")
    if int(result["concurrency"]) != 1:
        raise ValueError("professionalize_retry.concurrency must be 1; claims provide scale-out")
    if int(result["limit"]) < 1 or float(result["lease_seconds"]) <= 0:
        raise ValueError("professionalize_retry limit and lease_seconds must be positive")
    return result


def parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(
        description="Drain RejectedTaskQueue through the Professionalize retry consumer."
    )
    parser.add_argument(
        "--repository-root",
        required=True,
        help="Content repository root that RejectedTranslationTask paths are relative to.",
    )
    parser.add_argument("--config-root", default="config")
    parser.add_argument(
        "--campaign-manifest",
        default=None,
        help="Required with --live; supplies the zero-defect validation and receipt context.",
    )
    parser.add_argument("--queue-path", default=None)
    parser.add_argument("--intent-spool-path", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--lease-seconds", type=float, default=None)
    parser.add_argument("--owner", default=None)
    parser.add_argument("--heartbeat-path", default=None)
    parser.add_argument(
        "--action",
        choices=("run", "stats", "enqueue", "dead-letter", "reconcile"),
        default="run",
        help="run claims bounded retry work; stats inspects safely; enqueue validates one canonical task.",
    )
    parser.add_argument(
        "--task-json",
        default=None,
        help="Path to exactly one canonical RejectedTranslationTask JSON object; required for --action enqueue.",
    )
    parser.add_argument("--task-id", default=None, help="Canonical task ID for --action dead-letter.")
    parser.add_argument("--reason", default=None, help="Bounded operator reason for --action dead-letter.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually call professionalize_llm and publish output. Without this "
        "flag every claimed task is retried without any provider call or write "
        "(safe to run repeatedly to inspect queue depth).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import json

    args = parse_args(argv)
    config = load_retry_worker_config(Path(args.config_root))
    live_mode = bool(args.live or config["live_mode"])
    queue = RejectedTaskQueue(Path(args.queue_path or config["queue_path"]))
    heartbeat_path = Path(args.heartbeat_path or config["heartbeat_path"])
    if args.action == "stats":
        write_retry_heartbeat(heartbeat_path, status="stats", queue=queue)
        print(json.dumps(queue.health(), sort_keys=True))
        return 0
    if args.action == "enqueue":
        if not args.task_json:
            raise ValueError("--task-json is required for --action enqueue")
        raw_task = json.loads(Path(args.task_json).read_text(encoding="utf-8"))
        if not isinstance(raw_task, dict):
            raise ValueError("--task-json must contain one JSON object")
        task = RejectedTranslationTask.from_mapping(raw_task)
        if task.state != "QUEUED":
            raise ValueError("only QUEUED tasks may be enqueued")
        print(json.dumps({"task_id": queue.enqueue(task)}, sort_keys=True))
        return 0
    if args.action == "dead-letter":
        if not args.task_id or not args.reason:
            raise ValueError("--task-id and --reason are required for --action dead-letter")
        queue.operator_dead_letter(args.task_id, args.reason)
        print(json.dumps({"state": "DEAD_LETTER", "task_id": args.task_id}, sort_keys=True))
        return 0
    if args.action == "reconcile":
        intent_spool = TMIntentSpool(Path(args.intent_spool_path or config["intent_spool_path"]))
        print(json.dumps({
            "retry_claims_requeued": queue.requeue_expired_claims(),
            "tm_intent_claims_requeued": intent_spool.requeue_expired_claims(),
        }, sort_keys=True))
        write_retry_heartbeat(heartbeat_path, status="reconciled", queue=queue)
        return 0
    intent_spool = TMIntentSpool(Path(args.intent_spool_path or config["intent_spool_path"]))
    if live_mode and not args.campaign_manifest:
        raise ValueError("--live requires --campaign-manifest for zero-defect campaign validation")
    provider = build_professionalize_provider(config["model_id"]) if live_mode else _InertProvider()
    validator = (
        build_campaign_validator_from_manifest(
            campaign_manifest=Path(args.campaign_manifest),
            config_root=Path(args.config_root),
            repository_root=Path(args.repository_root),
        )
        if live_mode
        else build_default_validator()
    )
    worker = ProfessionalizeRetryWorker(
        queue=queue,
        intent_spool=intent_spool,
        provider=provider,
        repository_root=Path(args.repository_root),
        validate_document=validator,
        live_mode=live_mode,
    )
    result = worker.run_once(
        owner=args.owner,
        limit=args.limit or int(config["limit"]),
        lease_seconds=args.lease_seconds or float(config["lease_seconds"]),
    )
    write_retry_heartbeat(heartbeat_path, status="completed", queue=queue)
    print(json.dumps(result, sort_keys=True))
    return 0


class _InertProvider:
    """Never called: live_mode=False makes ProfessionalizeRetryWorker retry
    every claimed task before reaching any provider call. Exists only so
    main() need not special-case constructing a provider in dry-run mode.
    """

    def generate(self, system_prompt: str, user_text: str) -> tuple[str, int, int]:
        raise AssertionError("_InertProvider must never be called (live_mode=False)")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
