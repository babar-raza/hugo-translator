"""Source-based, claim-safe Professionalize retry consumer.

This worker never receives rejected candidate bytes.  It reads the immutable
source file, delegates generation to the configured provider abstraction, then
requires complete-document validation before atomically publishing output and
appending a TM intent.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Protocol

from src.tm.intent_spool import TMIntentSpool
from src.tm.rejected_task_queue import RejectedTaskQueue
from src.tm.retry_records import RejectedTranslationTask


class DocumentProvider(Protocol):
    def generate(self, system_prompt: str, user_text: str) -> tuple[str, int, int]: ...


Validator = Callable[[str, str, RejectedTranslationTask], None]


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
            source = source_path.read_text(encoding="utf-8")
            if hashlib.sha256(source.encode("utf-8")).hexdigest() != task.source_sha256:
                self.queue.dead_letter(task_id, owner, "SOURCE_DRIFT")
                return "dead_lettered"
            if not self.live_mode:
                self.queue.retry(task_id, owner, "LIVE_MODE_DISABLED")
                return "retried"
            candidate, input_tokens, output_tokens = self.provider.generate(
                "Translate the complete Hugo document. Preserve structure, front matter, links, and code.", source
            )
            self.validate_document(source, candidate, task)
            receipt = {"receipt_id": uuid.uuid4().hex, "task_id": task_id,
                       "source_sha256": task.source_sha256,
                       "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
                       "model_target": task.model_target,
                       "input_tokens": input_tokens, "output_tokens": output_tokens}
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
