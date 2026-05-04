"""CI stdout heartbeat to prevent CI systems from killing long-running translation jobs.

Spawns a daemon thread that prints periodic heartbeat messages to stdout.
Only active when the CI environment variable is set (GitHub Actions, GitLab CI)
or when explicitly enabled via force=True.

Source: Pattern from GitLab project 368 (ai-powered-multilingual-translation).
"""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_heartbeat_started = False
_heartbeat_lock = threading.Lock()


def start_ci_heartbeat(interval: int = 60, force: bool = False) -> bool:
    """Start a daemon heartbeat thread for CI log visibility.

    Args:
        interval: Seconds between heartbeat messages (default 60).
        force: If True, start heartbeat even outside CI environments.

    Returns:
        True if heartbeat thread was started, False if skipped or already running.
    """
    global _heartbeat_started

    if not force and not os.getenv("CI"):
        return False

    with _heartbeat_lock:
        if _heartbeat_started:
            return False
        _heartbeat_started = True

    def _beat():
        while True:
            try:
                print("[heartbeat] translation in progress...", flush=True)
            except Exception:
                pass
            time.sleep(interval)

    t = threading.Thread(target=_beat, daemon=True, name="ci-heartbeat")
    t.start()
    logger.debug("CI heartbeat started (interval=%ds)", interval)
    return True
