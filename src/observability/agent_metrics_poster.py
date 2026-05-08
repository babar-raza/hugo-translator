"""Agent Metrics API poster — HTTP POST with dry-run, secret handling, 302 support.

Amendment #2: Stage 8 test posting is SYNCHRONOUS to capture response code,
update evidence/ledger, and allow row verification. Production posting is
fire-and-forget.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

logger = logging.getLogger(__name__)

_PLACEHOLDER_TOKENS = {"YOUR_TOKEN_HERE", "changeme", "CHANGE_ME", "placeholder", "xxx"}
_MAX_TEST_ROWS_PER_SPRINT = 3
_test_rows_posted = 0
_test_rows_lock = threading.Lock()


def _get_secret(env_var_name: str) -> str | None:
    """Read secret from environment variable. Reject placeholders."""
    val = os.environ.get(env_var_name, "").strip()
    if not val:
        return None
    if val.lower() in {p.lower() for p in _PLACEHOLDER_TOKENS}:
        logger.warning("Rejected placeholder token in %s", env_var_name)
        return None
    return val


class AgentMetricsPoster:
    """Posts metrics payloads to the Agent Metrics API endpoint."""

    def __init__(
        self,
        endpoint_env: str = "AGENT_METRICS_ENDPOINT",
        token_env: str = "AGENT_METRICS_TOKEN",
        timeout_seconds: int = 15,
        dry_run: bool = True,
        fire_and_forget: bool = True,
    ):
        self.endpoint = _get_secret(endpoint_env)
        self.token = _get_secret(token_env)
        self.timeout_seconds = timeout_seconds
        self.dry_run = dry_run
        self.fire_and_forget = fire_and_forget
        self._enabled = True

        if not self.endpoint or not self.token:
            if not self.dry_run:
                logger.warning(
                    "Agent metrics posting disabled: missing %s or %s env var",
                    endpoint_env, token_env,
                )
            self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def post(self, payload_dict: dict, job_type: str = "") -> dict:
        """Post payload to API.

        Returns dict with keys: posted, dry_run, response_code, error.
        For test posts (job_type="test"), posting is always synchronous.
        """
        result = {"posted": False, "dry_run": self.dry_run, "response_code": None, "error": None}

        if self.dry_run:
            logger.info("DRY RUN: would post %d-key payload", len(payload_dict))
            logger.debug("DRY RUN payload: %s", json.dumps(payload_dict, indent=2))
            return result

        if not self._enabled:
            result["error"] = "posting disabled (missing secrets)"
            return result

        # Enforce test-row limit
        if job_type == "Test":
            with _test_rows_lock:
                global _test_rows_posted
                if _test_rows_posted >= _MAX_TEST_ROWS_PER_SPRINT:
                    result["error"] = f"test row limit reached ({_MAX_TEST_ROWS_PER_SPRINT})"
                    logger.warning("Test row limit reached, skipping POST")
                    return result

        # Test posts are always synchronous (Amendment #2)
        is_sync = job_type == "Test" or not self.fire_and_forget

        if is_sync:
            return self._do_post_sync(payload_dict, job_type)
        else:
            self._do_post_async(payload_dict, job_type)
            result["posted"] = True  # optimistic for fire-and-forget
            return result

    def _do_post_sync(self, payload_dict: dict, job_type: str) -> dict:
        """Synchronous POST — returns full result with response_code."""
        result = {"posted": False, "dry_run": False, "response_code": None, "error": None}
        try:
            import urllib.request
            import urllib.error

            # Token passed as query parameter (Google Apps Script convention)
            from urllib.parse import urlencode, urlparse, urlunparse, parse_qs
            parsed = urlparse(self.endpoint)
            qs = parse_qs(parsed.query)
            qs["token"] = [self.token]
            new_query = urlencode(qs, doseq=True)
            url = urlunparse(parsed._replace(query=new_query))

            data = json.dumps(payload_dict).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            response = urllib.request.urlopen(req, timeout=self.timeout_seconds)
            result["response_code"] = response.getcode()
            result["posted"] = True

            # Increment test row counter on success
            if job_type == "Test":
                with _test_rows_lock:
                    global _test_rows_posted
                    _test_rows_posted += 1

            logger.info("POST success: HTTP %d", result["response_code"])

        except urllib.error.HTTPError as e:
            result["response_code"] = e.code
            # Handle Google Apps Script 302 redirect — follow with GET to get JSON
            if e.code in (301, 302, 303, 307):
                redirect_url = e.headers.get("Location")
                result["posted"] = True
                if job_type == "Test":
                    with _test_rows_lock:
                        _test_rows_posted += 1
                logger.info("POST redirect (%d) — treated as success", e.code)
                # Follow redirect to capture confirmation JSON
                if redirect_url:
                    try:
                        confirm = urllib.request.urlopen(redirect_url, timeout=self.timeout_seconds)
                        confirm_body = confirm.read().decode("utf-8", errors="replace")
                        result["response_body"] = confirm_body
                        logger.info("Redirect response: %s", confirm_body[:200])
                    except Exception as re:
                        logger.debug("Redirect follow failed (non-fatal): %s", re)
            else:
                result["error"] = f"HTTP {e.code}: {e.reason}"
                logger.warning("POST failed: %s", result["error"])
        except Exception as e:
            result["error"] = str(e)
            logger.warning("POST failed: %s", result["error"])

        return result

    def _do_post_async(self, payload_dict: dict, job_type: str) -> None:
        """Fire-and-forget POST in background thread."""
        def _post():
            try:
                import urllib.request
                import urllib.error
                from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

                parsed = urlparse(self.endpoint)
                qs = parse_qs(parsed.query)
                qs["token"] = [self.token]
                new_query = urlencode(qs, doseq=True)
                url = urlunparse(parsed._replace(query=new_query))

                data = json.dumps(payload_dict).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=self.timeout_seconds)
                logger.info("Async POST success")
            except Exception as e:
                logger.warning("Async POST failed: %s", e)

        thread = threading.Thread(target=_post, daemon=True)
        thread.start()


def reset_test_row_counter() -> None:
    """Reset test row counter (for testing only)."""
    global _test_rows_posted
    with _test_rows_lock:
        _test_rows_posted = 0


def get_test_rows_posted() -> int:
    """Get current test row count."""
    return _test_rows_posted
