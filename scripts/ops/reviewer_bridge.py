"""TC-AGT-09: Reviewer App MCP Bridge.

Reads run-signal JSON files from ``data/signals/`` and bridges them to the
reviewer app (recruitize-ai-review-agent) via MCP JSON-RPC 2.0 protocol.

The reviewer app exposes tools via a streamable HTTP MCP endpoint:
  POST <MCP_URL>
  Authorization: Bearer <TOKEN>
  Content-Type: application/json

  {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
   "params": {"name": "review_agent.start_run", "arguments": {...}}}

The tool schema is ``{runId: string, directive: object}``.
The directive is open-ended; the bridge maps translation signal fields
into it so the reviewer app creates a run record for observability.

Usage:
    python scripts/ops/reviewer_bridge.py --once           # Process latest signal
    python scripts/ops/reviewer_bridge.py --all            # Process all unposted signals
    python scripts/ops/reviewer_bridge.py --dry-run        # Show what would be posted
    python scripts/ops/reviewer_bridge.py --signal <path>  # Post a specific signal file

Environment:
    REVIEWER_MCP_URL:   MCP endpoint URL (required for live mode)
    REVIEWER_MCP_TOKEN: Bearer token (required for live mode)

Dry-run mode is the default when env vars are not set.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SIGNALS_DIR = Path("data/signals")
_POSTED_MARKERS_DIR = Path("data/signals/.posted")
_PROTOCOL_VERSION = "2025-03-26"
_TOOL_NAME = "review_agent.start_run"


class ReviewerBridgeError(Exception):
    """Raised when a bridge operation fails."""


class MCPClient:
    """Minimal MCP JSON-RPC 2.0 client for the reviewer app."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: int = 30,
    ):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None
        self._rpc_id = 0
        self._initialized = False

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request to the MCP endpoint."""
        try:
            import requests
        except ImportError:
            raise ReviewerBridgeError("requests package not available")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }

        resp = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout)

        # Capture session ID from response
        if not self.session_id:
            self.session_id = resp.headers.get("mcp-session-id")

        if not resp.ok:
            raise ReviewerBridgeError(
                f"MCP {method} failed ({resp.status_code}): {resp.text[:500]}"
            )

        data = resp.json()
        if "error" in data and data["error"]:
            raise ReviewerBridgeError(f"MCP {method} error: {json.dumps(data['error'])}")
        return data.get("result", {})

    def initialize(self) -> None:
        """Initialize the MCP session."""
        if self._initialized:
            return
        self.rpc(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "clientInfo": {
                    "name": "hugo-translator-reviewer-bridge",
                    "version": "0.1.0",
                },
                "capabilities": {},
            },
        )
        self._initialized = True

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool."""
        self.initialize()
        return self.rpc("tools/call", {"name": name, "arguments": arguments})


def _map_signal_to_directive(signal: dict[str, Any]) -> dict[str, Any]:
    """Map a run signal to a reviewer app run directive."""
    files = signal.get("files", {})
    validators = signal.get("validators", {})
    llm_usage = signal.get("llm_usage", {})

    return {
        "run_id": signal.get("run_id", ""),
        "source": "hugo-translator",
        "mission": signal.get("mission", "Content Translation"),
        "site_id": signal.get("site_id", ""),
        "status": signal.get("status", "completed"),
        "timestamp": signal.get("timestamp", ""),
        "metrics": {
            "files_processed": files.get("processed", 0),
            "files_accepted": files.get("accepted", 0),
            "files_rejected": files.get("rejected", 0),
            "files_retried": files.get("retried", 0),
            "validators_run": validators.get("run", 0),
            "validators_passed": validators.get("passed", 0),
            "validators_failed": validators.get("failed", 0),
            "llm_calls": llm_usage.get("calls", 0),
            "llm_tokens": llm_usage.get("tokens", 0),
        },
        "verdict": signal.get("verdict", ""),
        "autonomy_score": signal.get("autonomy_score", 0.0),
        "blockers": signal.get("blockers", []),
        "evidence_path": signal.get("evidence_path", ""),
    }


def _is_posted(signal_path: Path) -> bool:
    """Check if a signal has already been posted."""
    marker = _POSTED_MARKERS_DIR / f"{signal_path.stem}.posted"
    return marker.exists()


def _mark_posted(signal_path: Path) -> None:
    """Create a marker file for a successfully posted signal."""
    _POSTED_MARKERS_DIR.mkdir(parents=True, exist_ok=True)
    marker = _POSTED_MARKERS_DIR / f"{signal_path.stem}.posted"
    marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def load_signal(signal_path: Path) -> dict[str, Any]:
    """Load and validate a run signal file."""
    if not signal_path.exists():
        raise ReviewerBridgeError(f"Signal file not found: {signal_path}")
    try:
        data = json.loads(signal_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ReviewerBridgeError(f"Invalid JSON in signal file: {e}")

    # Minimal validation
    required = {"run_id", "status", "verdict"}
    missing = required - set(data.keys())
    if missing:
        raise ReviewerBridgeError(f"Signal missing required fields: {missing}")
    return data


def post_signal(
    signal: dict[str, Any],
    *,
    client: MCPClient | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Post a signal to the reviewer app.

    Returns a result dict with: posted, dry_run, directive, response.
    """
    directive = _map_signal_to_directive(signal)

    result: dict[str, Any] = {
        "posted": False,
        "dry_run": dry_run,
        "directive": directive,
        "response": None,
        "error": None,
    }

    if dry_run:
        logger.info(
            "[DRY-RUN] Would post signal %s to reviewer app",
            signal.get("run_id", "?"),
        )
        return result

    if client is None:
        result["error"] = "No MCP client configured"
        return result

    try:
        run_id = signal.get("run_id", "")
        response = client.call_tool(_TOOL_NAME, {"runId": run_id, "directive": directive})
        result["posted"] = True
        result["response"] = response
        logger.info(
            "Posted signal %s to reviewer app",
            run_id or "?",
        )
    except ReviewerBridgeError as e:
        result["error"] = str(e)
        logger.warning("Failed to post signal: %s", e)

    return result


def process_signals(
    *,
    signals_dir: Path | None = None,
    all_signals: bool = False,
    signal_path: Path | None = None,
    dry_run: bool = False,
    mcp_url: str | None = None,
    mcp_token: str | None = None,
) -> list[dict[str, Any]]:
    """Process run signals and post them to the reviewer app.

    Args:
        signals_dir: Directory containing signal files.
        all_signals: If True, process all unposted signals. Otherwise, latest only.
        signal_path: If provided, process only this specific signal file.
        dry_run: If True, don't actually post.
        mcp_url: MCP endpoint URL.
        mcp_token: MCP bearer token.

    Returns:
        List of result dicts (one per signal processed).
    """
    sdir = signals_dir or _SIGNALS_DIR
    results: list[dict[str, Any]] = []

    # Determine effective dry_run
    url = mcp_url or os.environ.get("REVIEWER_MCP_URL", "")
    token = mcp_token or os.environ.get("REVIEWER_MCP_TOKEN", "")
    if not url or not token:
        if not dry_run:
            logger.info("REVIEWER_MCP_URL or REVIEWER_MCP_TOKEN not set — falling back to dry-run")
        dry_run = True

    client = None
    if not dry_run and url and token:
        client = MCPClient(url, token)

    # Collect signal files to process
    if signal_path:
        signal_files = [signal_path]
    else:
        if not sdir.exists():
            logger.info("No signals directory found: %s", sdir)
            return results
        signal_files = sorted(sdir.glob("run-signal-*.json"))
        if not all_signals:
            signal_files = signal_files[-1:] if signal_files else []

    for sf in signal_files:
        if not signal_path and _is_posted(sf):
            logger.debug("Signal already posted: %s", sf.name)
            continue

        try:
            signal = load_signal(sf)
            result = post_signal(signal, client=client, dry_run=dry_run)
            result["signal_file"] = str(sf)
            results.append(result)

            if result["posted"]:
                _mark_posted(sf)
        except ReviewerBridgeError as e:
            results.append(
                {
                    "signal_file": str(sf),
                    "posted": False,
                    "error": str(e),
                }
            )

    return results


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Hugo Translator → Reviewer App MCP Bridge")
    parser.add_argument("--once", action="store_true", help="Process latest signal only")
    parser.add_argument(
        "--all", action="store_true", dest="all_signals", help="Process all unposted signals"
    )
    parser.add_argument("--signal", type=Path, help="Process a specific signal file")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually post")
    parser.add_argument(
        "--signals-dir", type=Path, default=None, help="Signals directory (default: data/signals/)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    results = process_signals(
        signals_dir=args.signals_dir,
        all_signals=args.all_signals,
        signal_path=args.signal,
        dry_run=args.dry_run,
    )

    posted = sum(1 for r in results if r.get("posted"))
    errors = sum(1 for r in results if r.get("error"))
    dry_runs = sum(1 for r in results if r.get("dry_run"))

    print(f"\nProcessed: {len(results)} signal(s)")
    print(f"  Posted:   {posted}")
    print(f"  Dry-run:  {dry_runs}")
    print(f"  Errors:   {errors}")

    if errors:
        for r in results:
            if r.get("error"):
                print(f"  ERROR: {r['signal_file']}: {r['error']}")

    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
