"""
Telemetry Database Cleanup Utility.

Cleans up stale "running" telemetry records from interrupted hugo-translator
sessions via the telemetry HTTP API. Should be called on application startup
to mark orphaned records.

Architecture:
    This module respects the single-writer pattern by using the telemetry API
    instead of directly accessing the database. All cleanup operations are
    performed via HTTP requests to maintain data integrity.

Usage:
    from observability.telemetry_cleanup import cleanup_stale_runs

    # At application startup, before any translation work
    cleanup_stale_runs(
        api_url="http://localhost:8765",
        max_age_hours=1
    )

Requirements:
    - Telemetry API must support GET /api/v1/runs and PATCH /api/v1/runs/{event_id}
    - If endpoints are not available, function degrades gracefully
"""

import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def cleanup_stale_runs(
    api_url: str = "http://localhost:8765",
    max_age_hours: int = 1,
    agent_name: str = "hugo-translator",
    dry_run: bool = False,
    timeout: int = 5,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Clean up stale "running" telemetry records via API.

    Marks old "running" records as "cancelled" if they're older than max_age_hours.
    This handles cases where hugo-translator was killed and couldn't update
    telemetry before shutdown.

    Args:
        api_url: Telemetry API base URL (e.g., "http://localhost:8765")
        max_age_hours: Mark records older than this as stale (default: 1 hour)
        agent_name: Agent name to filter (default: "hugo-translator")
        dry_run: If True, only report stale runs without updating
        timeout: Request timeout in seconds (default: 5)
        quiet: If True, suppress verbose logging (only errors and final summary)

    Returns:
        dict: Statistics about cleanup operation
            {
                "stale_runs_found": int,
                "updated": int,
                "errors": List[str],
                "api_available": bool
            }

    Example:
        >>> cleanup_stale_runs(max_age_hours=2)
        {'stale_runs_found': 3, 'updated': 3, 'errors': [], 'api_available': True}

    Notes:
        - Requires telemetry API v2.1+ with GET/PATCH endpoints
        - Gracefully handles API unavailability (returns empty stats)
        - Does NOT access database directly (respects single-writer pattern)
    """
    stats: Dict[str, Any] = {
        "stale_runs_found": 0,
        "updated": 0,
        "errors": [],
        "api_available": False,
    }

    try:
        # Calculate cutoff time
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cutoff_iso = cutoff.isoformat()

        if not quiet:
            logger.info(
                f"Telemetry cleanup check: max_age={max_age_hours}h, "
                f"agent={agent_name}, dry_run={dry_run}, api={api_url}"
            )

        # 1. Query for stale runs via GET /api/v1/runs
        try:
            response = requests.get(
                f"{api_url}/api/v1/runs",
                params={
                    "agent_name": agent_name,
                    "status": "running",
                    "created_before": cutoff_iso,
                },
                timeout=timeout,
            )

            if response.status_code == 404:
                logger.warning(
                    "Telemetry API cleanup endpoints not yet available "
                    "(GET /api/v1/runs returned 404). "
                    "Cleanup will be enabled when API is upgraded to v2.1+. "
                    "For now, stale runs will remain in database."
                )
                return stats

            if response.status_code == 405:
                logger.warning(
                    "Telemetry API cleanup endpoints not yet available "
                    "(GET /api/v1/runs returned 405 Method Not Allowed). "
                    "This likely means the telemetry API is not running or hasn't been upgraded to v2.1+. "
                    "Stale runs will remain in database until the API is available."
                )
                return stats

            response.raise_for_status()
            stale_runs = response.json()
            stats["api_available"] = True

        except requests.ConnectionError:
            logger.warning(
                f"Telemetry API not reachable at {api_url}. "
                "Skipping cleanup - stale runs will remain until next startup."
            )
            stats["errors"].append(f"API not reachable: {api_url}")
            return stats

        except requests.Timeout:
            logger.warning(
                f"Telemetry API timeout ({timeout}s) at {api_url}. "
                "Skipping cleanup."
            )
            stats["errors"].append(f"API timeout after {timeout}s")
            return stats

        except requests.RequestException as e:
            logger.error(f"Failed to query telemetry API: {e}")
            stats["errors"].append(f"API query failed: {e}")
            return stats

        # 2. Process stale runs
        if not isinstance(stale_runs, list):
            logger.error(
                f"Unexpected response from API: expected list, got {type(stale_runs)}"
            )
            stats["errors"].append("Invalid API response format")
            return stats

        stats["stale_runs_found"] = len(stale_runs)

        if not stale_runs:
            if not quiet:
                logger.info("No stale runs found")
            return stats

        if not quiet:
            logger.info(
                f"Found {len(stale_runs)} stale 'running' records "
                f"older than {max_age_hours}h"
            )

        # 3. Update each stale run via PATCH
        if not dry_run:
            now_iso = datetime.now(timezone.utc).isoformat()

            for run in stale_runs:
                event_id = run.get("event_id")
                run_id = run.get("run_id", "unknown")
                job_type = run.get("job_type", "unknown")
                created_at = run.get("created_at", "unknown")

                if not event_id:
                    logger.error(f"Stale run missing event_id: {run}")
                    stats["errors"].append(f"Missing event_id in run: {run_id}")
                    continue

                try:
                    patch_response = requests.patch(
                        f"{api_url}/api/v1/runs/{event_id}",
                        json={
                            "status": "cancelled",
                            "end_time": now_iso,
                            "error_summary": (
                                f"Stale run cleaned up on startup "
                                f"(created at {created_at})"
                            ),
                            "output_summary": "Process did not complete - cleanup on restart",
                        },
                        timeout=timeout,
                    )
                    patch_response.raise_for_status()
                    stats["updated"] += 1

                    if not quiet:
                        logger.info(
                            f"✓ Marked run {run_id} as cancelled (job: {job_type})"
                        )

                except requests.RequestException as e:
                    error_msg = f"Failed to update run {run_id}: {e}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)
                    continue

            if not quiet:
                logger.info(f"✓ Updated {stats['updated']} stale run(s)")

        else:
            if not quiet:
                logger.info(f"DRY RUN: Would update {len(stale_runs)} stale run(s)")

    except Exception as e:
        error_msg = f"Telemetry cleanup failed: {e}"
        logger.error(error_msg, exc_info=True)
        stats["errors"].append(error_msg)

    return stats
