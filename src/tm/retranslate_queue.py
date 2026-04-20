"""
Retranslate queue — tracks output files that need retranslation after quality failures.

Written by the engine when a file's overwrite is blocked and both the existing and
new translations are the wrong language (CASE 4). The next content worker run reads
this queue and force-includes the affected source files, bypassing the completion-aware
filter (Stage 2A) so TM improvements can reach files that are stuck with bad output.

Format: JSONL, one entry per line:
    {"output_path": "/abs/path/to/file.ar.md", "tgt_lang": "ar", "queued_at": "...", "retry_count": 1}

- All paths are stored as absolute resolved strings.
- Max retries: 3. After 3 failed retranslation attempts, the entry is dropped with a warning.
- Thread-safety: best-effort (appends are atomic on most OS/FS; rewrites use temp file).
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)

_QUEUE_FILE = Path("data/retranslate_queue.jsonl")
_QUARANTINE_FILE = Path("data/quarantine.jsonl")
_MAX_RETRIES = 3

# After this many MT failures, the entry is flagged for LLM escalation.
# Checked by load_queued_llm_paths() which the engine reads to decide whether
# to override the model to "professionalize_llm" for stuck files.
_LLM_ESCALATION_THRESHOLD = 2


def _queue_path() -> Path:
    return _QUEUE_FILE


def add_to_queue(output_path: Path, tgt_lang: str) -> None:
    """
    Add an output file to the retranslate queue.

    Called when CASE 4 fires: both the existing and the new translation are
    wrong-language, so overwrite is blocked and the file is permanently stuck.

    Args:
        output_path: Absolute path to the blocked output file.
        tgt_lang: Expected target language code.
    """
    try:
        queue_file = _queue_path()
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "output_path": str(output_path.resolve()),
            "tgt_lang": tgt_lang,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": 1,
        }
        with queue_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info(
            f"retranslate_queue: added {output_path.name} ({tgt_lang}) — "
            f"will bypass completion filter on next run"
        )
    except Exception as e:
        logger.warning(f"retranslate_queue: failed to add {output_path}: {e}")


def load_queued_paths() -> Set[str]:
    """
    Return the set of absolute output path strings that need retranslation.

    Entries with retry_count > MAX_RETRIES are excluded (permanently dropped).

    Returns:
        Set of absolute output file path strings in the queue.
    """
    queue_file = _queue_path()
    if not queue_file.exists():
        return set()
    queued: Set[str] = set()
    try:
        with queue_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("retry_count", 1) <= _MAX_RETRIES:
                        queued.add(entry["output_path"])
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception as e:
        logger.warning(f"retranslate_queue: failed to load queue: {e}")
    return queued


def load_queued_llm_paths() -> Set[str]:
    """
    Return the set of absolute output path strings that are eligible for LLM escalation.

    These are entries where retry_count >= _LLM_ESCALATION_THRESHOLD AND
    retry_count <= _MAX_RETRIES (not yet permanently dropped).

    The engine uses this set to override the model to "professionalize_llm" for files
    that M2M100 has consistently failed on. Engine-side wiring: check output_path against
    this set before calling _translate_to_language() and pass model_id_override if enabled.

    Returns:
        Set of absolute output file path strings ready for LLM escalation.
    """
    queue_file = _queue_path()
    if not queue_file.exists():
        return set()
    llm_paths: Set[str] = set()
    try:
        with queue_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    retry_count = entry.get("retry_count", 1)
                    if _LLM_ESCALATION_THRESHOLD <= retry_count <= _MAX_RETRIES:
                        llm_paths.add(entry["output_path"])
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception as e:
        logger.warning(f"retranslate_queue: failed to load LLM escalation paths: {e}")
    return llm_paths


def remove_from_queue(output_path: Path) -> None:
    """
    Remove a successfully written file from the queue.

    Called after the engine successfully writes a translation for a queued file.

    Args:
        output_path: Absolute path to the output file that was successfully written.
    """
    _rewrite_queue(remove_path=str(output_path.resolve()), increment_path=None)


def increment_retry(output_path: Path) -> None:
    """
    Increment the retry count for a queued file.

    If the retry count exceeds MAX_RETRIES, the entry is permanently dropped
    with a warning log. This prevents unbounded retranslation churn.

    Args:
        output_path: Absolute path to the output file.
    """
    _rewrite_queue(remove_path=None, increment_path=str(output_path.resolve()))


def _rewrite_queue(remove_path: str | None, increment_path: str | None) -> None:
    """Atomically rewrite the queue file with remove/increment applied."""
    queue_file = _queue_path()
    if not queue_file.exists():
        return
    try:
        lines = queue_file.read_text(encoding="utf-8").splitlines()
        kept = []
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                path = entry.get("output_path", "")
                if remove_path and path == remove_path:
                    continue  # drop entry (successfully retranslated)
                if increment_path and path == increment_path:
                    entry["retry_count"] = entry.get("retry_count", 1) + 1
                    if entry["retry_count"] > _MAX_RETRIES:
                        logger.warning(
                            f"retranslate_queue: max retries ({_MAX_RETRIES}) exceeded for "
                            f"{Path(path).name} — moving to quarantine"
                        )
                        _quarantine_entry(entry)
                        continue  # drop entry from active queue
                kept.append(json.dumps(entry))
            except (json.JSONDecodeError, KeyError):
                kept.append(line)  # preserve malformed lines

        # Atomic write via temp file
        dir_ = queue_file.parent
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=dir_, delete=False, suffix=".tmp"
        ) as tmp:
            tmp.write("\n".join(kept))
            if kept:
                tmp.write("\n")
            tmp_path = tmp.name
        os.replace(tmp_path, queue_file)
    except Exception as e:
        logger.warning(f"retranslate_queue: failed to rewrite queue: {e}")


def _quarantine_entry(entry: dict) -> None:
    """Append a permanently dropped entry to the quarantine log.

    The quarantine file is append-only and never cleaned by automation.
    Operators review it manually to identify files that consistently fail
    translation quality checks.

    Args:
        entry: The original retranslate queue entry dict.
    """
    try:
        quarantine_file = _QUARANTINE_FILE
        quarantine_file.parent.mkdir(parents=True, exist_ok=True)
        record = {
            **entry,
            "quarantined_at": datetime.now(timezone.utc).isoformat(),
            "reason": "max_retries_exceeded",
        }
        with quarantine_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        logger.warning(
            f"retranslate_queue: quarantined {Path(entry.get('output_path', '')).name} "
            f"— requires manual review (data/quarantine.jsonl)"
        )
    except Exception as e:
        logger.warning(f"retranslate_queue: failed to write quarantine entry: {e}")


def load_quarantined_paths() -> Set[str]:
    """Return the set of absolute output path strings in the quarantine log.

    Used for monitoring and reporting. The quarantine log is never cleaned
    automatically — operators must review and decide whether to manually
    re-queue or permanently exclude files.

    Returns:
        Set of absolute output file path strings that have been quarantined.
    """
    quarantine_file = _QUARANTINE_FILE
    if not quarantine_file.exists():
        return set()
    paths: Set[str] = set()
    try:
        with quarantine_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "output_path" in entry:
                        paths.add(entry["output_path"])
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception as e:
        logger.warning(f"retranslate_queue: failed to load quarantine: {e}")
    return paths
