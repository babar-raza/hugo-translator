"""
archive_retired_locale_queue_entries.py — Site-agnostic maintenance tool:
remove queue entries whose locale is no longer in their site's *current*
target_langs, and preserve them in an append-only archive.

Context: data/retranslate_queue.jsonl can accumulate entries for a locale
that was later removed from a site's target_langs (e.g. after a locale-set
policy change). directory_orchestrator.py already ignores queue entries
whose tgt_lang isn't in the current run's target_langs, so these entries
are inert — but proactively archiving them (rather than relying on
inertness) keeps the active queue clean while preserving history.

Fully generic: works for any site, driven entirely by each entry's site's
*live* target_langs (read via ConfigService) — no hardcoded locale list.
A site is identified by matching the entry's output_path against every
configured site_id (any path component equal to a site_id).

This is a maintenance tool, not part of the automated pipeline. Dry-run
by default; pass --apply to actually rewrite the queue file.

Usage:
  python scripts/ops/archive_retired_locale_queue_entries.py            # dry-run
  python scripts/ops/archive_retired_locale_queue_entries.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(_REPO_ROOT / "src"), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.utils.config_loader import ConfigService  # noqa: E402

QUEUE_FILE = _REPO_ROOT / "data" / "retranslate_queue.jsonl"
ARCHIVE_FILE = _REPO_ROOT / "data" / "retranslate_queue_archive_stale_locales.jsonl"
ARCHIVE_REASON = "locale_not_in_current_site_target_langs"


def _site_for_path(output_path: str, site_ids: list[str]) -> str | None:
    """Identify which configured site owns this queue entry's output path.

    Matches any path component equal to a known site_id -- e.g.
    .../aspose.org/content/docs.aspose.org/de/... -> "docs.aspose.org".
    """
    parts = set(Path(output_path).parts)
    for site_id in site_ids:
        if site_id in parts:
            return site_id
    return None


def run(apply: bool) -> dict:
    if not QUEUE_FILE.exists():
        print(f"Queue file not found: {QUEUE_FILE}")
        return {"total": 0, "kept": 0, "archived": 0}

    config_service = ConfigService(_REPO_ROOT / "config")
    site_ids = config_service.list_sites(autonomous_only=False)
    target_langs_by_site: dict[str, set[str]] = {}
    for site_id in site_ids:
        try:
            profile = config_service.get_site_profile(site_id)
            target_langs_by_site[site_id] = set(profile.target_langs) | {
                profile.default_source_lang
            }
        except Exception:
            continue

    lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    archived: list[dict] = []
    by_locale: Counter[str] = Counter()
    by_site: Counter[str] = Counter()
    unresolved_site = 0

    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)  # preserve malformed lines untouched
            continue

        tgt_lang = entry.get("tgt_lang")
        output_path = entry.get("output_path", "")
        site_id = _site_for_path(output_path, site_ids)

        if site_id is None:
            # Can't determine ownership -- never archive, keep as-is.
            unresolved_site += 1
            kept.append(line)
            continue

        allowed = target_langs_by_site.get(site_id)
        if allowed is not None and tgt_lang not in allowed:
            archived.append(entry)
            by_locale[tgt_lang] += 1
            by_site[site_id] += 1
        else:
            kept.append(line)

    print(f"Total entries:      {len(lines):>6}")
    print(f"Kept (active):      {len(kept):>6}")
    print(f"Archived (stale):   {len(archived):>6}")
    if unresolved_site:
        print(f"Unresolved site (kept, not archived): {unresolved_site:>6}")
    if by_locale:
        print("\nArchived by locale:")
        for lang, count in sorted(by_locale.items(), key=lambda x: -x[1]):
            print(f"  {lang:4s} {count:>6}")
    if by_site:
        print("\nArchived by site:")
        for site, count in sorted(by_site.items(), key=lambda x: -x[1]):
            print(f"  {site:24s} {count:>6}")

    if not apply:
        print("\nDRY-RUN complete. Re-run with --apply to write changes.")
        return {"total": len(lines), "kept": len(kept), "archived": len(archived)}

    # Append archived entries (with provenance) to the archive file.
    ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with ARCHIVE_FILE.open("a", encoding="utf-8") as f:
        for entry in archived:
            record = {**entry, "archived_at": now, "reason": ARCHIVE_REASON}
            f.write(json.dumps(record) + "\n")

    # Atomically rewrite the live queue with only the kept entries.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=QUEUE_FILE.parent, delete=False, suffix=".tmp"
    ) as tmp:
        tmp.write("\n".join(kept))
        if kept:
            tmp.write("\n")
        tmp_path = tmp.name
    os.replace(tmp_path, QUEUE_FILE)

    print(f"\nAPPLY complete. {len(archived)} entries archived to {ARCHIVE_FILE}")
    print(f"Live queue now has {len(kept)} entries.")
    return {"total": len(lines), "kept": len(kept), "archived": len(archived)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive queue entries whose locale is no longer in their site's target_langs"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually rewrite the queue and write the archive (default: dry-run report only)",
    )
    args = parser.parse_args()
    run(apply=args.apply)


if __name__ == "__main__":
    main()
