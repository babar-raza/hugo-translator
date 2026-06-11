"""Run outcome recording for cross-run learning and regression detection.

Follows BenchmarkDatabase pattern: WAL mode, threading.Lock(), check_same_thread=False,
WAL checkpoint on close. All writes are single INSERT (no multi-statement transactions).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RunOutcome:
    run_id: str
    site_id: str
    target_lang: str
    timestamp: str
    files_attempted: int
    files_accepted: int
    files_rejected: int
    files_skipped: int
    retry_count: int
    acceptance_rate: float
    dominant_failure_type: str | None
    elapsed_seconds: float


@dataclass
class RegressionAlert:
    current_rate: float
    moving_avg: float
    delta: float
    site_id: str
    target_lang: str


class RunHistoryTracker:
    """SQLite-backed run outcome tracker.

    Follows BenchmarkDatabase pattern exactly:
    - WAL mode for concurrent reads
    - threading.Lock() wrapping all DB operations
    - check_same_thread=False
    - WAL checkpoint on close
    - :memory: support for tests
    """

    def __init__(self, db_path: str | Path = "data/metrics/run_history.db") -> None:
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._memory_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._memory_conn = self._create_connection()
        self._init_db()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _get_connection(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        return self._create_connection()

    def _close_connection(self, conn: sqlite3.Connection) -> None:
        if conn is not self._memory_conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS run_outcomes (
                        run_id TEXT PRIMARY KEY,
                        site_id TEXT NOT NULL,
                        target_lang TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        files_attempted INTEGER NOT NULL,
                        files_accepted INTEGER NOT NULL,
                        files_rejected INTEGER NOT NULL,
                        files_skipped INTEGER NOT NULL,
                        retry_count INTEGER NOT NULL,
                        acceptance_rate REAL NOT NULL,
                        dominant_failure_type TEXT,
                        elapsed_seconds REAL NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_run_outcomes_site_lang
                    ON run_outcomes (site_id, target_lang, timestamp)
                """)
                conn.commit()
            finally:
                self._close_connection(conn)

    def record_outcome(self, outcome: RunOutcome) -> None:
        """Record a single run outcome. Single INSERT, no multi-statement txn."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO run_outcomes
                    (run_id, site_id, target_lang, timestamp, files_attempted,
                     files_accepted, files_rejected, files_skipped, retry_count,
                     acceptance_rate, dominant_failure_type, elapsed_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        outcome.run_id,
                        outcome.site_id,
                        outcome.target_lang,
                        outcome.timestamp,
                        outcome.files_attempted,
                        outcome.files_accepted,
                        outcome.files_rejected,
                        outcome.files_skipped,
                        outcome.retry_count,
                        outcome.acceptance_rate,
                        outcome.dominant_failure_type,
                        outcome.elapsed_seconds,
                    ),
                )
                conn.commit()
            finally:
                self._close_connection(conn)

    def get_recent_outcomes(
        self, site_id: str, target_lang: str, limit: int = 20
    ) -> list[RunOutcome]:
        """Get recent run outcomes for a site/lang pair."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """SELECT * FROM run_outcomes
                    WHERE site_id = ? AND target_lang = ?
                    ORDER BY timestamp DESC LIMIT ?""",
                    (site_id, target_lang, limit),
                ).fetchall()
                return [
                    RunOutcome(
                        run_id=r["run_id"],
                        site_id=r["site_id"],
                        target_lang=r["target_lang"],
                        timestamp=r["timestamp"],
                        files_attempted=r["files_attempted"],
                        files_accepted=r["files_accepted"],
                        files_rejected=r["files_rejected"],
                        files_skipped=r["files_skipped"],
                        retry_count=r["retry_count"],
                        acceptance_rate=r["acceptance_rate"],
                        dominant_failure_type=r["dominant_failure_type"],
                        elapsed_seconds=r["elapsed_seconds"],
                    )
                    for r in rows
                ]
            finally:
                self._close_connection(conn)

    def get_acceptance_rate_trend(
        self, site_id: str, target_lang: str, window: int = 5
    ) -> float | None:
        """Get moving average of acceptance rate over last N runs."""
        outcomes = self.get_recent_outcomes(site_id, target_lang, limit=window)
        if not outcomes:
            return None
        return sum(o.acceptance_rate for o in outcomes) / len(outcomes)

    def detect_regression(
        self, site_id: str, target_lang: str, threshold: float = 0.15
    ) -> RegressionAlert | None:
        """Detect if current acceptance rate has dropped significantly.

        Compares the most recent run against the moving average of the previous
        runs. Returns an alert if the delta exceeds threshold.
        """
        outcomes = self.get_recent_outcomes(site_id, target_lang, limit=6)
        if len(outcomes) < 2:
            return None

        current = outcomes[0]
        previous = outcomes[1:]
        if not previous:
            return None

        moving_avg = sum(o.acceptance_rate for o in previous) / len(previous)
        delta = moving_avg - current.acceptance_rate

        if delta >= threshold:
            return RegressionAlert(
                current_rate=current.acceptance_rate,
                moving_avg=moving_avg,
                delta=delta,
                site_id=site_id,
                target_lang=target_lang,
            )
        return None

    def close(self) -> None:
        """Close all connections and checkpoint WAL."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
        elif self.db_path != ":memory:":
            conn = self._create_connection()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
