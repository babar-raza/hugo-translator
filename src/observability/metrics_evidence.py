"""Evidence sidecar, posted markers, and JSONL ledger for Agent Metrics.

Evidence files are local-only and never posted to the Google Sheet.
They preserve the full context of each metrics posting attempt.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
_WRITE_TIMEOUT_S = 10  # OneDrive-safe timeout


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_write(path: Path, data: str) -> bool:
    """Write data to file with OneDrive-safe timeout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_write, path, data)
            future.result(timeout=_WRITE_TIMEOUT_S)
        return True
    except FutureTimeoutError:
        logger.warning("Write timed out (OneDrive?): %s", path)
        return False
    except Exception as e:
        logger.warning("Write failed: %s — %s", path, e)
        return False


def _do_write(path: Path, data: str) -> None:
    path.write_text(data, encoding="utf-8")


def compute_payload_hash(payload_dict: dict) -> str:
    """SHA-256 of the canonical JSON payload."""
    canonical = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvidenceWriter:
    """Manages evidence sidecars, posted markers, and JSONL ledger."""

    def __init__(self, evidence_dir: str = "data/metrics/agent_evidence",
                 ledger_file: str | None = None):
        self.evidence_dir = Path(evidence_dir)
        self.ledger_file = Path(ledger_file) if ledger_file else self.evidence_dir / "metrics_ledger.jsonl"
        self._lock = threading.Lock()

    # ── Posted markers ──────────────────────────────────────────────

    def _marker_path(self, segment_run_id: str) -> Path:
        return self.evidence_dir / "markers" / f"{segment_run_id}.posted"

    def is_already_posted(self, segment_run_id: str) -> bool:
        return self._marker_path(segment_run_id).exists()

    def write_posted_marker(self, segment_run_id: str) -> bool:
        return _safe_write(self._marker_path(segment_run_id), _now_iso())

    # ── Evidence sidecar ────────────────────────────────────────────

    def _sidecar_path(self, segment_run_id: str) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.evidence_dir / date_str / f"{segment_run_id}.json"

    def write_pre_post_sidecar(
        self,
        segment_run_id: str,
        ids: dict,
        execution_context: dict,
        scope: dict,
        llm_provider: dict,
        posted_payload: dict,
        call_accounting: dict,
        items_detail: dict,
        error_detail: str | dict | None = None,
        trigger_type: str = "scheduled",
        output_summary: str = "",
        dry_run: bool = True,
    ) -> Path | None:
        """Write sidecar with posting.status = 'posting_in_progress' BEFORE POST."""
        sidecar = {
            "schema_version": SCHEMA_VERSION,
            "ids": ids,
            "execution_context": execution_context,
            "scope": scope,
            "llm_provider": llm_provider,
            "posted_payload": posted_payload,
            "call_accounting": call_accounting,
            "items_detail": items_detail,
            "error_detail": error_detail,
            "trigger_type": trigger_type,
            "output_summary": output_summary,
            "posting": {
                "status": "dry_run" if dry_run else "posting_in_progress",
                "dry_run": dry_run,
                "posted_marker_path": str(self._marker_path(segment_run_id)),
                "payload_hash": compute_payload_hash(posted_payload),
                "response_code": None,
                "error": None,
            },
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        path = self._sidecar_path(segment_run_id)
        data = json.dumps(sidecar, indent=2, ensure_ascii=False)
        if _safe_write(path, data):
            return path
        return None

    def update_sidecar_post_result(
        self,
        segment_run_id: str,
        status: str,
        response_code: int | None = None,
        error: str | None = None,
    ) -> bool:
        """Update existing sidecar with post result."""
        path = self._sidecar_path(segment_run_id)
        if not path.exists():
            logger.warning("Sidecar not found for update: %s", path)
            return False
        try:
            sidecar = json.loads(path.read_text(encoding="utf-8"))
            sidecar["posting"]["status"] = status
            sidecar["posting"]["response_code"] = response_code
            sidecar["posting"]["error"] = error
            sidecar["updated_at"] = _now_iso()
            data = json.dumps(sidecar, indent=2, ensure_ascii=False)
            return _safe_write(path, data)
        except Exception as e:
            logger.warning("Failed to update sidecar: %s — %s", path, e)
            return False

    # ── JSONL ledger ────────────────────────────────────────────────

    def append_ledger(self, segment_run_id: str, event: str, detail: dict | None = None) -> bool:
        """Append a line to the JSONL ledger."""
        entry = {
            "timestamp": _now_iso(),
            "segment_run_id": segment_run_id,
            "event": event,
        }
        if detail:
            entry["detail"] = detail
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.ledger_file, "a", encoding="utf-8") as f:
                    f.write(line)
                return True
            except Exception as e:
                logger.warning("Ledger append failed: %s", e)
                return False

    # ── Convenience ─────────────────────────────────────────────────

    def full_post_lifecycle(
        self,
        segment_run_id: str,
        ids: dict,
        execution_context: dict,
        scope: dict,
        llm_provider: dict,
        posted_payload: dict,
        call_accounting: dict,
        items_detail: dict,
        error_detail: str | dict | None = None,
        trigger_type: str = "scheduled",
        output_summary: str = "",
        dry_run: bool = True,
    ) -> dict:
        """Return lifecycle dict for poster to use. Does NOT post."""
        # Check duplicate
        if self.is_already_posted(segment_run_id):
            self.append_ledger(segment_run_id, "skipped_duplicate")
            return {"action": "skipped_duplicate"}

        # Pre-post sidecar
        sidecar_path = self.write_pre_post_sidecar(
            segment_run_id=segment_run_id,
            ids=ids,
            execution_context=execution_context,
            scope=scope,
            llm_provider=llm_provider,
            posted_payload=posted_payload,
            call_accounting=call_accounting,
            items_detail=items_detail,
            error_detail=error_detail,
            trigger_type=trigger_type,
            output_summary=output_summary,
            dry_run=dry_run,
        )
        self.append_ledger(segment_run_id, "pre_post", {"sidecar_path": str(sidecar_path)})
        return {
            "action": "ready_to_post" if not dry_run else "dry_run",
            "sidecar_path": sidecar_path,
        }

    def record_post_success(self, segment_run_id: str, response_code: int) -> None:
        self.update_sidecar_post_result(segment_run_id, "posted", response_code=response_code)
        self.write_posted_marker(segment_run_id)
        self.append_ledger(segment_run_id, "post_confirmed", {"response_code": response_code})

    def record_post_failure(self, segment_run_id: str, error: str, response_code: int | None = None) -> None:
        self.update_sidecar_post_result(segment_run_id, "failed", response_code=response_code, error=error)
        self.append_ledger(segment_run_id, "post_failed", {"error": error, "response_code": response_code})
