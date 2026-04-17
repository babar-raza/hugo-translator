"""
Worker lifecycle telemetry helper.

Provides fire-and-forget telemetry for worker lifecycle events via the
local-telemetry HTTP API. All methods are non-fatal: exceptions are caught
and logged so telemetry never blocks the main workflow.

Usage:
    from src.observability.worker_telemetry import emit_worker_event, start_worker_run, complete_worker_run

    # Fire-and-forget completed event
    emit_worker_event(agent_name="content_worker", job_type="worker_preflight",
                      status="success", metrics={"gpu_ok": True})

    # Long-running run (POST then PATCH)
    eid = start_worker_run("content_worker", "worker_lifecycle")
    # ... do work ...
    complete_worker_run(eid, status="success", duration_ms=12000)
"""

import logging
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_TELEMETRY_API_URL: str | None = None


def _get_api_url() -> str:
    """Return cached telemetry API base URL."""
    global _TELEMETRY_API_URL
    if _TELEMETRY_API_URL is None:
        _TELEMETRY_API_URL = os.getenv("TELEMETRY_API_URL", "http://localhost:8765")
    return _TELEMETRY_API_URL


def _post_run(run_data: dict) -> str | None:
    """POST a run to the telemetry API. Returns event_id on success, None on failure."""
    try:
        import requests as _requests

        resp = _requests.post(
            f"{_get_api_url()}/api/v1/runs",
            json=run_data,
            timeout=5,
        )
        if resp.status_code == 201:
            logger.debug(f"Telemetry POST ok: {run_data['event_id']} ({run_data['job_type']})")
            return run_data["event_id"]
        else:
            logger.debug(f"Telemetry POST {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        logger.debug(f"Telemetry POST failed (non-fatal): {exc}")
    return None


def _patch_run(event_id: str, update: dict) -> bool:
    """PATCH an existing run. Returns True on success."""
    try:
        import requests as _requests

        resp = _requests.patch(
            f"{_get_api_url()}/api/v1/runs/{event_id}",
            json=update,
            timeout=5,
        )
        if resp.status_code == 200:
            logger.debug(f"Telemetry PATCH ok: {event_id}")
            return True
        else:
            logger.debug(f"Telemetry PATCH {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        logger.debug(f"Telemetry PATCH failed (non-fatal): {exc}")
    return False


def _build_base_run(
    agent_name: str,
    job_type: str,
    trigger_type: str = "scheduled",
) -> dict:
    """Build a base run dict with common fields."""
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    return {
        "event_id": event_id,
        "run_id": f"{now}-{agent_name}-{job_type}-{uuid.uuid4().hex[:8]}",
        "agent_name": agent_name,
        "job_type": job_type,
        "trigger_type": trigger_type,
        "start_time": now,
        "host": socket.gethostname(),
        "environment": os.getenv("HUGO_TRANSLATOR_ENV", "dev"),
    }


def emit_worker_event(
    agent_name: str,
    job_type: str,
    trigger_type: str = "scheduled",
    status: str = "success",
    metrics: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    error_summary: str | None = None,
    duration_ms: int = 0,
    items_discovered: int = 0,
    items_succeeded: int = 0,
    items_failed: int = 0,
) -> str | None:
    """
    Emit a completed worker lifecycle event (fire-and-forget).

    Creates a single POST with status already set (typically "success" or
    "failure"). Use this for discrete events like preflight results, site
    discovery, GPU checks, etc.

    Returns:
        event_id on success, None on failure.
    """
    run_data = _build_base_run(agent_name, job_type, trigger_type)
    now = run_data["start_time"]
    run_data.update({
        "status": status,
        "end_time": now,
        "duration_ms": duration_ms,
        "items_discovered": items_discovered,
        "items_succeeded": items_succeeded,
        "items_failed": items_failed,
    })
    if metrics:
        run_data["metrics_json"] = metrics
    if context:
        run_data["context_json"] = context
    if error_summary:
        run_data["error_summary"] = error_summary
    return _post_run(run_data)


def start_worker_run(
    agent_name: str,
    job_type: str,
    trigger_type: str = "scheduled",
    context: dict[str, Any] | None = None,
) -> str | None:
    """
    Start a long-running worker telemetry run.

    POSTs a run with status="running". Returns event_id so the caller
    can later PATCH it via complete_worker_run().

    Returns:
        event_id on success, None on failure.
    """
    run_data = _build_base_run(agent_name, job_type, trigger_type)
    run_data["status"] = "running"
    if context:
        run_data["context_json"] = context
    return _post_run(run_data)


def complete_worker_run(
    event_id: str,
    status: str = "success",
    duration_ms: int = 0,
    metrics: dict[str, Any] | None = None,
    error_summary: str | None = None,
    output_summary: str | None = None,
    items_succeeded: int = 0,
    items_failed: int = 0,
) -> bool:
    """
    Complete (PATCH) a previously started worker run.

    Updates the run with final status, duration, metrics, and error info.

    Returns:
        True on success, False on failure.
    """
    now = datetime.now(timezone.utc).isoformat()
    update: dict[str, Any] = {
        "status": status,
        "end_time": now,
        "duration_ms": duration_ms,
    }
    if metrics:
        update["metrics_json"] = metrics
    if error_summary:
        update["error_summary"] = error_summary
    if output_summary:
        update["output_summary"] = output_summary
    if items_succeeded:
        update["items_succeeded"] = items_succeeded
    if items_failed:
        update["items_failed"] = items_failed
    return _patch_run(event_id, update)
