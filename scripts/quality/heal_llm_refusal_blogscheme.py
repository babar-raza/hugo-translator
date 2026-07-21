"""One-off remediation for blog.aspose.org files with confirmed raw LLM
refusal/meta-commentary text (e.g. "VALIDACIJA - Molimo vas...") shipped
into production content -- found by scripts/quality/audit_llm_artifacts.py.

blog.aspose.org uses a page-bundle + filename-suffix multilingual scheme
(index.md + index.<locale>.md in the same directory) that
heal_english_headings.py's queue-driven retranslate mode does not support
(it hardcodes `<site>/en/<rel>` source resolution). TranslationEngine's own
translate_file() resolves output paths from the site profile's
`output_layout` config, which blog.aspose.org.yaml already defines for this
exact scheme, so this script calls it directly with the correct EN source
path (no `en/` prefix) instead of going through the queue-file scanner.

Reads .local/heal_llm_refusal_blogscheme.jsonl (entries:
{"site": "blog.aspose.org", "locale": ..., "rel": ...}) and force-retranslates
each (site, locale) pair.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.quality.heal_english_headings import _build_engine  # noqa: E402

CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.org\content")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=str(ROOT / ".local" / "heal_llm_refusal_blogscheme.jsonl"))
    args = ap.parse_args()
    queue_path = Path(args.queue)
    done_path = queue_path.with_name(queue_path.stem + "_done.jsonl")

    entries = [json.loads(line) for line in queue_path.open(encoding="utf-8") if line.strip()]
    print(f"Retranslating {len(entries)} blog.aspose.org files with confirmed LLM refusal artifacts...")

    engine = _build_engine("m2m100_418m", ROOT)
    print("Engine ready.\n")

    done_fh = done_path.open("a", encoding="utf-8")
    ok = fail = 0
    for i, entry in enumerate(entries, 1):
        locale = entry["locale"]
        rel = entry["rel"]
        # blog.aspose.org EN source: <site>/<rel_dir>/index.md -- no en/ prefix
        src_path = CONTENT_ROOT / "blog.aspose.org" / rel
        if not src_path.exists():
            print(f"  [{i}] MISSING SOURCE: {src_path}")
            fail += 1
            continue
        try:
            engine.translate_file(
                site_id="blog.aspose.org",
                file_path=src_path,
                target_langs=[locale],
                force=True,
                force_overwrite=True,
            )
            ok += 1
            done_fh.write(json.dumps({"site": "blog.aspose.org", "locale": locale, "rel": rel}) + "\n")
            done_fh.flush()
            print(f"  [{i}/{len(entries)}] OK {locale}/{rel}")
        except Exception as e:
            fail += 1
            print(f"  [{i}/{len(entries)}] FAIL {locale}/{rel}: {e!s:.200}")

    print(f"\nDone: {ok} OK, {fail} fail out of {len(entries)}")


if __name__ == "__main__":
    main()
