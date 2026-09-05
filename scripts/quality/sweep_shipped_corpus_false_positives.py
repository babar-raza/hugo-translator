"""TC-APT-081: bulk false-positive discovery over the shipped corpus.

Every recent validator/pipeline FP class (TC-APT-069, 073, 075, 076, 077, 078,
079) was found the same way -- one live page-cycle at a time, a day of wall clock
each. Gate-3's TC-APT-010 applied that calibration discipline to the write-gates
but never to the ValidationSuite layer, which is where all of those classes live.

The insight this script exploits: a cell that is already SHIPPED -- committed to
the content repo after review approval -- is by construction acceptable output.
So any flag the suite raises on it is a false positive, and thousands of them can
be discovered in one CPU-only pass instead of one per page-cycle.

Handles both content layouts, which is not optional: blog/products/websites use
``index.<lang>.md`` beside ``index.md``, while docs/kb/reference use per-language
FOLDERS (``content/<site>/<lang>/...`` against ``content/<site>/en/...``). An
earlier terminology search missed three of six subdomains by assuming the suffix
layout, so this enumerates both.

Only the 8 default CPU validators run; the model-backed ones (semantic
similarity, fidelity judge) are deliberately excluded so the sweep stays cheap
enough to run over the whole corpus.

Output: a JSON report grouping every flag by (validator, signature) with counts,
locales and example paths -- the classes, not the instances.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.translation_engine.validation.validation_suite import ValidationSuite  # noqa: E402

CONTENT_REPO = Path("D:/onedrive/Documents/GitHub/aspose.org")
SUFFIX_RE = re.compile(r"^(?P<stem>.+)\.(?P<lang>[a-z]{2}(?:-[A-Za-z]+)?)\.md$")
EXCLUDED_LOCALES = {"bg", "ca", "da", "fi", "hr", "lt", "lv", "ms", "no", "sk", "sr"}


def tracked_markdown(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "content/*.md"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def pair_up(paths: list[str]) -> list[tuple[str, str, str]]:
    """Return (source_path, translated_path, lang) for both layouts."""
    known = set(paths)
    pairs: list[tuple[str, str, str]] = []

    for path in paths:
        name = path.rsplit("/", 1)[-1]
        match = SUFFIX_RE.match(name)
        if match:
            lang = match.group("lang")
            if lang in EXCLUDED_LOCALES or lang == "en":
                continue
            source = path[: -len(f".{lang}.md")] + ".md"
            if source in known:
                pairs.append((source, path, lang))
            continue

        parts = path.split("/")
        # content/<site>/<lang>/rest...
        if len(parts) > 3 and len(parts[2]) in (2, 5) and parts[2].islower():
            lang = parts[2]
            if lang in EXCLUDED_LOCALES or lang == "en":
                continue
            source = "/".join([parts[0], parts[1], "en", *parts[3:]])
            if source in known:
                pairs.append((source, path, lang))
    return pairs


def signature_of(issue) -> str:
    """A stable class key: the message with volatile detail stripped."""
    message = str(getattr(issue, "message", ""))[:200]
    message = re.sub(r"\d+", "#", message)
    message = re.sub(r"'[^']*'", "'X'", message)
    return re.sub(r"\s+", " ", message).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="0 = whole corpus")
    parser.add_argument("--out", default="data/summaries/tc-apt-081-fp-sweep.json")
    parser.add_argument("--repo", default=str(CONTENT_REPO))
    args = parser.parse_args()

    repo = Path(args.repo)
    pairs = pair_up(tracked_markdown(repo))
    if args.limit:
        step = max(1, len(pairs) // args.limit)
        pairs = pairs[::step][: args.limit]
    print(f"shipped cells to sweep: {len(pairs)}")

    suite = ValidationSuite()
    classes: dict[tuple[str, str], dict] = {}
    swept = errored = flagged = 0

    for index, (source_path, target_path, lang) in enumerate(pairs, 1):
        try:
            source = (repo / source_path).read_text(encoding="utf-8")
            translation = (repo / target_path).read_text(encoding="utf-8")
        except Exception:
            errored += 1
            continue
        try:
            results = suite.validate(
                source, translation,
                # 'target_lang' is the key the validators actually read; passing
                # 'target_language' made LanguageConsistencyValidator skip on
                # 100% of the pilot sweep and report that as a flag. A sweep
                # harness bug masquerading as the top FP class.
                {"target_lang": lang, "source_lang": "en", "target_language": lang,
                 "source_language": "en", "file_path": target_path},
            )
        except Exception as exc:
            errored += 1
            if errored <= 3:
                print(f"  suite raised on {target_path}: {type(exc).__name__}: {exc}")
            continue
        swept += 1
        had_flag = False
        for result in results:
            for issue in getattr(result, "issues", []) or []:
                severity = str(getattr(issue.severity, "value", issue.severity)).lower()
                if severity not in ("error", "warning"):
                    continue
                had_flag = True
                key = (str(getattr(issue, "validator", "?")), signature_of(issue))
                entry = classes.setdefault(
                    key, {"validator": key[0], "signature": key[1], "count": 0,
                          "severities": collections.Counter(), "locales": collections.Counter(),
                          "examples": []},
                )
                entry["count"] += 1
                entry["severities"][severity] += 1
                entry["locales"][lang] += 1
                if len(entry["examples"]) < 3:
                    entry["examples"].append(target_path)
                entry.setdefault("layouts", collections.Counter())[
                    "folder" if f"/{lang}/" in f"/{target_path}" else "suffix"
                ] += 1
        flagged += 1 if had_flag else 0
        if index % 250 == 0:
            print(f"  {index}/{len(pairs)} swept, {len(classes)} classes so far")

    ranked = sorted(classes.values(), key=lambda entry: -entry["count"])
    for entry in ranked:
        entry["severities"] = dict(entry["severities"])
        entry["locales"] = dict(sorted(entry["locales"].items(), key=lambda kv: -kv[1])[:8])
        entry["layouts"] = dict(entry.get("layouts", {}))

    report = {
        "what_this_is": "Every flag below was raised on a cell that is already shipped and "
                        "review-approved, so each is a false-positive CANDIDATE by construction. "
                        "Caveat worth keeping: some shipped cells predate the current review "
                        "standard, so a class here can occasionally be a real defect that was let "
                        "through -- triage per class, do not bulk-waive.",
        "cells_swept": swept,
        "cells_with_at_least_one_flag": flagged,
        "cells_errored": errored,
        "distinct_classes": len(ranked),
        "validators_run": [type(v).__name__ for v in suite.validators],
        "classes": ranked,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nswept {swept} shipped cells; {flagged} carried at least one flag "
          f"({100 * flagged / swept:.1f}%)" if swept else "nothing swept")
    print(f"distinct FP classes: {len(ranked)}   -> {out}")
    for entry in ranked[:12]:
        print(f"  {entry['count']:>6}  {entry['validator']:<34} {entry['signature'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
