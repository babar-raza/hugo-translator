"""Build the TC-APT-004b qualification sample (plan section 6.1).

The sample is fixed, deterministic and small relative to the portfolio (plan: "a fixed,
one-time, small-relative-to-the-portfolio sample -- not the whole 229,000-cell corpus"),
but it must still span **all 6 in-scope sites x all 25 approved locales x every required
content class** (technical prose, marketing prose, API-heavy, short metadata, tables/lists,
RTL, CJK, low-resource/problematic, placeholder-heavy mixed Markdown/HTML).

Construction: the 51 distinct source files behind TC-APT-006's benchmark corpus are each
assigned a deterministic set of target locales drawn from three interleaved cycles --

  1. a *risk* cycle over the RTL and CJK locales, so every file is exercised against at
     least one bidirectional or ideographic target (the classes the corpus flags as
     rtl_cjk_sensitive and the classes TC-APT-023 measured as least reproducible);
  2. a full 25-locale cycle, so every approved locale appears;
  3. the same cycle at a coprime offset, so locale pairs vary per file rather than
     repeating the same two columns.

Files on sites with few sources get an extra locale so no site is under-covered.  The
resulting matrix, its per-locale and per-class counts, and the source sha256 of every
file are written to the sample file so the qualification run is reproducible byte-for-byte
in its *inputs* even though the provider's outputs are not (TC-APT-023).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

APPROVED_LOCALES = [
    "ar", "cs", "de", "el", "es", "fa", "fr", "he", "hi", "hu", "id", "it", "ja",
    "ko", "nl", "pl", "pt", "ro", "ru", "sv", "th", "tr", "uk", "vi", "zh",
]
RISK_LOCALES = ["ar", "ja", "fa", "ko", "he", "zh"]  # RTL + CJK
SCRIPT_GROUP = {
    **{c: "rtl" for c in ("ar", "fa", "he")},
    **{c: "cjk" for c in ("ja", "ko", "zh")},
    **{c: "cyrillic" for c in ("ru", "uk")},
    **{c: "indic_thai" for c in ("hi", "th")},
    "el": "greek",
}
OFFSET = 13  # coprime with 25


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(corpus: list[dict], content_root: Path, per_file: int) -> dict:
    files: dict[str, dict] = {}
    for seg in corpus:
        entry = files.setdefault(
            seg["source_path"],
            {
                "source_path": seg["source_path"],
                "site_id": seg["metadata"]["site_id"],
                "classes": list(seg["metadata"].get("classes", [])),
                "segments": 0,
            },
        )
        entry["segments"] += 1
    ordered = sorted(files.values(), key=lambda e: (e["site_id"], e["source_path"]))

    per_site = collections.Counter(e["site_id"] for e in ordered)
    cells: list[dict] = []
    for index, entry in enumerate(ordered):
        source = content_root / entry["source_path"]
        if not source.is_file():
            raise SystemExit(f"qualification source missing: {source}")
        # under-populated sites get one extra locale so every site still sees breadth
        count = per_file + (1 if per_site[entry["site_id"]] < 4 else 0)
        locales: list[str] = []
        for pick in (
            RISK_LOCALES[index % len(RISK_LOCALES)],
            APPROVED_LOCALES[index % len(APPROVED_LOCALES)],
            APPROVED_LOCALES[(index * OFFSET + 7) % len(APPROVED_LOCALES)],
            APPROVED_LOCALES[(index * OFFSET * 2 + 3) % len(APPROVED_LOCALES)],
        ):
            if pick not in locales:
                locales.append(pick)
            if len(locales) == count:
                break
        # a collision may leave the list short; top up deterministically
        cursor = 0
        while len(locales) < count:
            candidate = APPROVED_LOCALES[(index + cursor) % len(APPROVED_LOCALES)]
            if candidate not in locales:
                locales.append(candidate)
            cursor += 1
        entry_out = dict(entry)
        entry_out["source_sha256"] = sha256_file(source)
        entry_out["locales"] = locales
        cells.append(entry_out)

    locale_counts = collections.Counter(loc for c in cells for loc in c["locales"])
    missing = [loc for loc in APPROVED_LOCALES if loc not in locale_counts]
    class_locale: dict[str, set[str]] = collections.defaultdict(set)
    for cell in cells:
        for klass in cell["classes"]:
            class_locale[klass].update(cell["locales"])
    site_groups: dict[str, set[str]] = collections.defaultdict(set)
    for cell in cells:
        for loc in cell["locales"]:
            site_groups[cell["site_id"]].add(SCRIPT_GROUP.get(loc, "latin"))

    return {
        "taskcard": "TC-APT-004b",
        "purpose": "professionalize_llm production qualification sample (plan 6.1)",
        "content_root": str(content_root),
        "files": len(cells),
        "cells": sum(len(c["locales"]) for c in cells),
        "locales_covered": len(locale_counts),
        "locales_missing": missing,
        "locale_counts": dict(sorted(locale_counts.items())),
        "sites": dict(collections.Counter(c["site_id"] for c in cells)),
        "content_classes": {k: sorted(v) for k, v in sorted(class_locale.items())},
        "script_groups_per_site": {k: sorted(v) for k, v in sorted(site_groups.items())},
        "sample": cells,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-004b qualification sample builder")
    parser.add_argument(
        "--corpus", type=Path, default=Path("data/benchmark_corpus/aspose_org_mission_segments.json")
    )
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--per-file-locales", type=int, default=3)
    parser.add_argument(
        "--out", type=Path, default=Path("data/benchmark_corpus/qualification_sample.json")
    )
    args = parser.parse_args(argv)

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    payload = build(corpus, args.content_root.resolve(), args.per_file_locales)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in payload.items() if k != "sample"}, indent=2))
    if payload["locales_missing"]:
        print(f"FAIL: locales not covered: {payload['locales_missing']}", file=sys.stderr)
        return 1
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
