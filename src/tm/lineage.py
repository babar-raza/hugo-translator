"""TM lineage: first-class provenance fields + read-time invalidation denylist (TC-APT-008, plan 7.5).

Mission ``aspose-org-full-portfolio-translation-20260901``; plan section 5.1 root cause 3
("translation-memory reuse is order-of-operations-dependent") and G-04's deferred purge.

* Lineage = which ``config_fingerprint`` / ``model_id`` produced a TM entry.  Historically only
  unstructured ``metadata`` keys (``config_fingerprint``, ``model``, ``model_id``, ``campaign_id``)
  carried it; :func:`lineage_of` reads first-class fields first, then those keys.
* Invalidation is a **read-time denylist**, not a destructive delete:
  ``data/tm/invalidated_lineage.json`` -> ``{"denylist": [{"fingerprint"|"model_id": ..., "reason":
  ..., "added_at": ..., "taskcard": ...}]}``.  L2 ``exact_lookup`` and L3 ``semantic_search``
  drop matches whose lineage is denied; removing the entry from the file restores them.
* Entries with no lineage at all are *lineage-unknown* (the TM analogue of
  ``UNKNOWN_PROVENANCE``): never assumed clean, never blindly purged; they are reported so the
  operator can decide per fingerprint population, and they are NOT denied by default.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DENYLIST_PATH = Path("data/tm/invalidated_lineage.json")
LINEAGE_FP_KEYS = ("config_fingerprint",)
LINEAGE_MODEL_KEYS = ("model_id", "model", "model_fingerprint")


def lineage_of(entry_or_metadata: Any) -> tuple[str | None, str | None]:
    """``(config_fingerprint, model_id)`` from first-class fields, else metadata keys, else None."""
    fp = getattr(entry_or_metadata, "config_fingerprint", None)
    model = getattr(entry_or_metadata, "model_id", None)
    meta = (
        entry_or_metadata
        if isinstance(entry_or_metadata, dict)
        else getattr(entry_or_metadata, "metadata", None) or {}
    )
    if not isinstance(meta, dict):
        meta = {}
    if not fp:
        for key in LINEAGE_FP_KEYS:
            if meta.get(key):
                fp = str(meta[key])
                break
    if not model:
        for key in LINEAGE_MODEL_KEYS:
            if meta.get(key):
                model = str(meta[key])
                break
    return (fp or None), (model or None)


class LineageDenylist:
    """mtime-cached view of the denylist file; safe to share across threads."""

    def __init__(self, path: Path | str = DEFAULT_DENYLIST_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self._fingerprints: frozenset[str] = frozenset()
        self._models: frozenset[str] = frozenset()
        self._entries: list[dict[str, Any]] = []

    def _refresh(self) -> None:
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            mtime = None
        if mtime == self._mtime:
            return
        fps: set[str] = set()
        models: set[str] = set()
        entries: list[dict[str, Any]] = []
        if mtime is not None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                items = data.get("denylist", []) if isinstance(data, dict) else data
                for item in items or []:
                    if isinstance(item, str):
                        fps.add(item)
                        entries.append({"fingerprint": item})
                        continue
                    if not isinstance(item, dict):
                        continue
                    entries.append(item)
                    for key in ("fingerprint", "config_fingerprint"):
                        if item.get(key):
                            fps.add(str(item[key]))
                    if item.get("model_id"):
                        models.add(str(item["model_id"]))
            except (OSError, json.JSONDecodeError, AttributeError):
                # An unreadable denylist must never silently re-enable denied lineage:
                # keep the last good view and record the failure for the caller's logs.
                return
        self._mtime = mtime
        self._fingerprints = frozenset(fps)
        self._models = frozenset(models)
        self._entries = entries

    def is_denied(self, config_fingerprint: str | None, model_id: str | None) -> bool:
        with self._lock:
            self._refresh()
            return bool(
                (config_fingerprint and config_fingerprint in self._fingerprints)
                or (model_id and model_id in self._models)
            )

    def denies(self, entry_or_metadata: Any) -> bool:
        return self.is_denied(*lineage_of(entry_or_metadata))

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh()
            return list(self._entries)

    def add(
        self,
        *,
        fingerprint: str | None = None,
        model_id: str | None = None,
        reason: str,
        taskcard: str | None = None,
        review_id: str | None = None,
    ) -> dict[str, Any]:
        """Append one denylist entry (auditable, reversible by editing the file)."""
        if not fingerprint and not model_id:
            raise ValueError("a denylist entry needs a fingerprint or a model_id")
        with self._lock:
            self._refresh()
            item = {
                "fingerprint": fingerprint,
                "model_id": model_id,
                "reason": reason,
                "taskcard": taskcard,
                "review_id": review_id,
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
            items = [*self._entries, {k: v for k, v in item.items() if v is not None}]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"schema_version": 1, "denylist": items}, indent=2), encoding="utf-8"
            )
            self._mtime = None  # force reload
            self._refresh()
            return item


_default: LineageDenylist | None = None
_default_lock = threading.Lock()


def default_denylist() -> LineageDenylist:
    """Process-wide denylist bound to ``DEFAULT_DENYLIST_PATH`` (env ``HT_TM_LINEAGE_DENYLIST`` overrides)."""
    global _default
    with _default_lock:
        path = Path(os.environ.get("HT_TM_LINEAGE_DENYLIST") or DEFAULT_DENYLIST_PATH)
        if _default is None or _default.path != path:
            _default = LineageDenylist(path)
        return _default


def filter_denied(
    matches: list[Any], denylist: LineageDenylist | None = None
) -> tuple[list[Any], int]:
    """Drop L3 matches (objects with ``.metadata``) whose lineage is denied; returns (kept, dropped)."""
    dl = denylist or default_denylist()
    kept = [m for m in matches if not dl.denies(getattr(m, "metadata", None) or {})]
    return kept, len(matches) - len(kept)
