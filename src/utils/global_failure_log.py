"""
Global failure log for all translation paths.

Appends to data/failures/global_failures.jsonl (process-safe via file locking on Windows).
All translation paths (unified_translate, autonomous_worker, governed_retranslate,
inprocess_worker) should call log_failure() on file-level failures.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_LOG_PATH = Path("data/failures/global_failures.jsonl")
_log_path: Path | None = None


def _get_log_path() -> Path:
    """Resolve and cache the log file path."""
    global _log_path
    if _log_path is not None:
        return _log_path

    # Try project root from common markers
    for marker in ("config/global.yaml", "src/translation_engine"):
        candidate = Path.cwd()
        while candidate != candidate.parent:
            if (candidate / marker).exists():
                _log_path = candidate / _DEFAULT_LOG_PATH
                _log_path.parent.mkdir(parents=True, exist_ok=True)
                return _log_path
            candidate = candidate.parent

    # Fallback: relative to CWD
    _log_path = Path.cwd() / _DEFAULT_LOG_PATH
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    return _log_path


def _append_locked(path: Path, line: str) -> None:
    """Append a line to file with cross-process locking (Windows msvcrt / Unix fcntl)."""
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    try:
        if sys.platform == "win32":
            import msvcrt
            # Retry lock acquisition briefly
            for _ in range(50):
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.02)
            else:
                # Give up on locking, write anyway (better than losing the record)
                pass
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)

        os.write(fd, (line + "\n").encode("utf-8"))
        os.fsync(fd)

        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def log_failure(
    site_id: str,
    locale: str,
    rel_path: str,
    source: str,
    error_type: str,
    error_category: str = "",
    error_msg: str = "",
    model_id: str = "",
    attempt: int = 1,
) -> None:
    """Append a failure record to global_failures.jsonl (process-safe)."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "site_id": site_id,
        "locale": locale,
        "rel_path": str(rel_path).replace("\\", "/"),
        "source": source,
        "error_type": error_type,
        "error_category": error_category,
        "error_msg": str(error_msg)[:500],
        "model_id": model_id,
        "attempt": attempt,
        "resolved": False,
    }
    line = json.dumps(record, ensure_ascii=False)
    try:
        _append_locked(_get_log_path(), line)
    except Exception as e:
        logger.warning(f"Failed to write to global failure log: {e}")


def load_unresolved(
    site_filter: str | None = None,
    locale_filter: str | None = None,
) -> list[dict]:
    """Load unresolved failure records, optionally filtered."""
    path = _get_log_path()
    if not path.exists():
        return []

    results = []
    seen = {}  # (site_id, locale, rel_path) -> last record

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("resolved"):
                # Mark key as resolved
                key = (rec["site_id"], rec["locale"], rec["rel_path"])
                seen.pop(key, None)
                continue
            if site_filter and rec.get("site_id") != site_filter:
                continue
            if locale_filter and rec.get("locale") != locale_filter:
                continue
            key = (rec["site_id"], rec["locale"], rec["rel_path"])
            seen[key] = rec

    return list(seen.values())


def mark_resolved(site_id: str, locale: str, rel_path: str) -> None:
    """Append a resolved marker for the given file."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "site_id": site_id,
        "locale": locale,
        "rel_path": str(rel_path).replace("\\", "/"),
        "source": "resolution",
        "error_type": "resolved",
        "resolved": True,
    }
    line = json.dumps(record, ensure_ascii=False)
    try:
        _append_locked(_get_log_path(), line)
    except Exception as e:
        logger.warning(f"Failed to write resolution to global failure log: {e}")


def merge_legacy_failures(
    legacy_files: list[Path] | None = None,
    source_label: str = "legacy_import",
) -> int:
    """One-time: merge legacy JSONL failure files into global format. Returns count merged."""
    if legacy_files is None:
        root = _get_log_path().parent.parent.parent  # up from data/failures/
        legacy_files = list((root / ".local").glob("unified_failed*.jsonl"))
        quarantine = root / "data" / "quarantine.jsonl"
        if quarantine.exists():
            legacy_files.append(quarantine)

    count = 0
    for fpath in legacy_files:
        if not fpath.exists():
            continue
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                log_failure(
                    site_id=rec.get("site_id", "unknown"),
                    locale=rec.get("locale", rec.get("tgt_lang", "")),
                    rel_path=rec.get("rel_path", rec.get("output_path", "")),
                    source=source_label,
                    error_type=rec.get("error_type", "unknown"),
                    error_category=rec.get("error_category", rec.get("reason", "")),
                    error_msg=rec.get("error_msg", ""),
                    model_id=rec.get("model_id", ""),
                    attempt=rec.get("attempt", rec.get("retry_count", 1)),
                )
                count += 1

    return count
