"""
heal_english_headings.py — Scan and retranslate files with English headings / body issues.

Identifies five categories of files needing GPU content healing:
  1. api_headings        : ## Methods, ## Properties, ## Returns etc.
  2. section_headings    : ## Overview, ## Example, ## Enumerations etc.
  3. table_access        : "Read"/"Write" values in table Access columns (non-Latin only)
  4. body_identical_to_en: Translated body is byte-for-byte identical to English source
  5. empty_body          : Translated body is empty while English source has content

Modes:
  --scan         : Count and list affected files (default)
  --build-queue  : Write a JSONL queue of files to retranslate
  --retranslate  : Load engine and call translate_file(force=True) for each queued file

--sites supports comma-separated site names or 'all' (default: reference.aspose.org).

Usage:
  python scripts/quality/heal_english_headings.py --scan
  python scripts/quality/heal_english_headings.py --scan --locales zh,ru,uk,hi --sites all
  python scripts/quality/heal_english_headings.py --build-queue --locales zh,ru,uk --sites all
  python scripts/quality/heal_english_headings.py --retranslate --model nllb_200_1.3b \\
      --locales ar,bg,el,ja,ko,th,uk,zh --sites all
  python scripts/quality/heal_english_headings.py --retranslate --model m2m100_418m \\
      --locales fa,he,hi,ru --sites all
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure sibling modules (e.g. frontmatter_utils) import correctly regardless
# of invocation mode (direct script run vs. pytest package import).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_SITES = ["reference.aspose.org", "docs.aspose.org", "kb.aspose.org"]
EN_LOCALE = "en"

_API_HEADING_TERMS: frozenset[str] = frozenset({
    "Name", "Type", "Description", "Returns", "Parameters",
    "Properties", "Methods", "Fields", "Constructors", "Events",
    "Exceptions", "Remarks", "Examples", "See Also", "Inheritance",
    "Implements", "Namespace", "Assembly", "Syntax", "Value",
})

_SECTION_HEADING_TERMS: frozenset[str] = frozenset({
    "Overview", "Example", "Notes", "Enumerations", "Deprecated",
    "Requirements", "Installation", "Usage", "Introduction",
    "Output", "Input", "Result", "Results", "Summary", "Details",
    "Options", "Configuration", "Features", "Limitations",
})

_ALL_HEALING_TERMS: frozenset[str] = _API_HEADING_TERMS | _SECTION_HEADING_TERMS

_TABLE_ACCESS_VALUES: frozenset[str] = frozenset({"Read", "Write"})

# Non-Latin locales: these cannot "accidentally" look like English
_NON_LATIN_LOCALES: frozenset[str] = frozenset({
    "ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "zh",
})

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)

# ---------------------------------------------------------------------------
# Content root
# ---------------------------------------------------------------------------


def _resolve_content_root() -> Path:
    env = os.environ.get("ASPOSE_ORG_CONTENT")
    if env:
        p = Path(env)
        if p.exists():
            return p
    for p in [
        Path(r"D:\onedrive\Documents\GitHub\aspose.org\content"),
        Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content"),
    ]:
        if p.exists():
            return p
    raise FileNotFoundError("Cannot find content root. Set ASPOSE_ORG_CONTENT.")


def _get_body(text: str) -> str:
    parts = text.split("---", 2)
    return parts[2] if len(parts) >= 3 else text


# ---------------------------------------------------------------------------
# Per-file detection
# ---------------------------------------------------------------------------


def _check_file(tr_path: Path, locale: str, en_path: Path | None = None) -> dict:
    """Return dict of issue categories for this file, or empty dict if clean."""
    try:
        text = tr_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    body = _get_body(text)
    issues: dict[str, list[str]] = {}

    # 1. English headings
    api_hdgs = []
    sec_hdgs = []
    for m in _HEADING_RE.finditer(body):
        h = m.group(2).strip()
        if h in _API_HEADING_TERMS:
            api_hdgs.append(h)
        elif h in _SECTION_HEADING_TERMS:
            sec_hdgs.append(h)
    if api_hdgs:
        issues["api_headings"] = api_hdgs
    if sec_hdgs:
        issues["section_headings"] = sec_hdgs

    # 2. Table Access column with English "Read"/"Write" (non-Latin only)
    if locale in _NON_LATIN_LOCALES:
        access_cells = []
        for row in _TABLE_ROW_RE.finditer(body):
            cols = [c.strip() for c in row.group(1).split("|")]
            for col in cols:
                if col in _TABLE_ACCESS_VALUES:
                    access_cells.append(col)
        if access_cells:
            issues["table_access"] = access_cells

    # 2b. Table description cells not translated (non-Latin only)
    # Caused by extractor bug: regex ^[A-Z][a-z]+\.[A-Z] (no $ anchor) marked sentences
    # starting with "Header.SectorSize..." as non-translatable.
    if locale in _NON_LATIN_LOCALES and "|" in body:
        _lower_en = re.compile(r"^[a-z]{3,}$")
        _ascii_line = re.compile(r"^[A-Za-z0-9\s.,;:!?\-\'\"()\[\]{}|#*`~_>]+$")
        in_code = False
        en_cells, total_cells = 0, 0
        for line in body.splitlines():
            s = line.strip()
            if s.startswith("```"):
                in_code = not in_code
            if in_code or not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 2:
                continue
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                continue  # separator row
            desc = cells[-1]
            desc_clean = re.sub(r"`[^`]+`", "", desc).strip()
            if len(desc_clean) < 20:
                continue
            total_cells += 1
            words = desc_clean.split()
            lower_en = sum(1 for w in words if _lower_en.match(w))
            if len(words) >= 4 and lower_en / len(words) >= 0.4 and _ascii_line.match(desc_clean):
                en_cells += 1
        if total_cells >= 3 and en_cells / total_cells >= 0.5:
            issues["table_desc_not_translated"] = [f"{en_cells}/{total_cells}"]

    # 3. Body identical to English source OR empty body (requires en_path)
    if en_path is not None and en_path.exists():
        try:
            en_text = en_path.read_text(encoding="utf-8", errors="replace")
            en_body = _get_body(en_text).strip()
            tr_body = body.strip()
            if len(en_body) > 50:
                if tr_body == en_body:
                    issues["body_identical_to_en"] = ["identical"]
                elif len(tr_body) < 20:
                    issues["empty_body"] = ["empty"]

            # 4. Description hallucination — description length ratio too far off source
            # These MUST be GPU-retranslated, not patched with English source text.
            # Parses frontmatter via HugoParser rather than a first-line regex, so
            # multi-line folded/literal scalars compare by full value (TC-HT-001).
            from frontmatter_utils import get_frontmatter_field

            en_desc = get_frontmatter_field(en_text, "description")
            tr_desc = get_frontmatter_field(text, "description")
            if en_desc and tr_desc and len(en_desc) >= 20:
                ratio = len(tr_desc) / len(en_desc)
                if ratio > 3.0 or ratio < 0.3:
                    issues["description_hallucination"] = [f"ratio={ratio:.1f}"]

            # 5. Code fence dropped — translation has fewer ``` fences than source
            def _count_fences(b: str) -> int:
                return sum(1 for ln in b.splitlines() if ln.strip().startswith("```"))

            en_fences = _count_fences(en_body)
            tr_fences = _count_fences(body)
            if en_fences >= 4 and tr_fences < en_fences - 2:
                issues["code_fence_dropped"] = [f"src={en_fences} tgt={tr_fences}"]
        except Exception:
            pass

    return issues


# ---------------------------------------------------------------------------
# Scan mode
# ---------------------------------------------------------------------------


def run_scan(sites: list[str], locales: list[str], categories: set[str], max_files: int) -> None:
    root = _resolve_content_root()

    total: dict[str, int] = defaultdict(int)

    for site in sites:
        site_root = root / site
        if not site_root.exists():
            print(f"  SKIP site {site} (not found)")
            continue
        en_root = site_root / EN_LOCALE
        print(f"\nSite: {site}")
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        site_locales = locales if locales else sorted(
            d.name for d in site_root.iterdir() if d.is_dir() and d.name != EN_LOCALE
        )

        for locale in site_locales:
            locale_dir = site_root / locale
            if not locale_dir.exists():
                continue

            files = list(locale_dir.rglob("*.md"))
            n = 0
            for f in files:
                if max_files and n >= max_files:
                    break
                rel = f.relative_to(locale_dir)
                en_path = en_root / rel
                issues = _check_file(f, locale, en_path)
                for cat, vals in issues.items():
                    if not categories or cat in categories:
                        counts[locale][cat] += 1
                        total[cat] += 1
                n += 1

            print(
                f"  {locale:4s}: {n:6d} scanned  "
                f"api_hdg={counts[locale]['api_headings']:5d}  "
                f"sec_hdg={counts[locale]['section_headings']:5d}  "
                f"tbl_acc={counts[locale]['table_access']:5d}  "
                f"body_id={counts[locale]['body_identical_to_en']:4d}  "
                f"empty={counts[locale]['empty_body']:4d}",
                flush=True,
            )

    print()
    print("TOTALS:")
    for cat, cnt in sorted(total.items()):
        print(f"  {cat:30s} {cnt:>6,}")


# ---------------------------------------------------------------------------
# Build-queue mode
# ---------------------------------------------------------------------------


def run_build_queue(sites: list[str], locales: list[str], categories: set[str],
                    queue_path: Path, max_files: int) -> None:
    root = _resolve_content_root()

    written = 0
    with queue_path.open("w", encoding="utf-8") as fh:
        for site in sites:
            site_root = root / site
            if not site_root.exists():
                print(f"  SKIP site {site} (not found)")
                continue
            en_root = site_root / EN_LOCALE

            site_locales = locales if locales else sorted(
                d.name for d in site_root.iterdir() if d.is_dir() and d.name != EN_LOCALE
            )

            print(f"\nSite: {site}")
            for locale in site_locales:
                locale_dir = site_root / locale
                if not locale_dir.exists():
                    continue
                n = 0
                for f in locale_dir.rglob("*.md"):
                    if max_files and n >= max_files:
                        break
                    rel = f.relative_to(locale_dir)
                    en_path = en_root / rel
                    issues = _check_file(f, locale, en_path)
                    matched = {k: v for k, v in issues.items()
                               if not categories or k in categories}
                    if matched:
                        entry = {
                            "site": site,
                            "locale": locale,
                            "rel": str(rel),
                            "issues": list(matched.keys()),
                        }
                        fh.write(json.dumps(entry) + "\n")
                        written += 1
                    n += 1
                print(f"  {locale}: queued so far: {written}", flush=True)

    print(f"\nQueue written: {queue_path} ({written} entries)")


# ---------------------------------------------------------------------------
# Retranslate mode
# ---------------------------------------------------------------------------


def _build_engine(model_id: str, root: Path):
    """Build TranslationEngine using the same pattern as unified_translate.py."""
    from src.utils.config_loader import ConfigService
    from src.model_runtime.loader import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.tm.translation_memory import TranslationMemory
    from src.tm.l1_cache import L1Cache
    from src.tm.l2_persistent import L2PersistentTM
    from src.translation_engine.engine import TranslationEngine

    config_service = ConfigService(str(root / "config"))
    registry = ModelRegistry(str(root / "config/model_registry.yaml"))
    model_loader = ModelLoader(registry=registry, device="cuda", max_memory_mb=7000)

    l1 = L1Cache(max_size=50000)
    l2 = L2PersistentTM(db_path=root / "data/tm/l2.lmdb")
    from src.tm.translation_memory import TranslationMemory
    tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=None)

    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader,
        enable_validation=True,
        enable_telemetry=False,
        enable_terminology=False,
        batch_size=20,
        force_accept=False,
        model_id=model_id,
    )
    return engine


def run_retranslate(
    queue_path: Path,
    model: str,
    locales: list[str],
    sites_filter: list[str] | None,
    max_files: int,
) -> None:
    """Load engine and retranslate each file from the queue with force=True."""
    if not queue_path.exists():
        print(f"Queue file not found: {queue_path}")
        print("Run --build-queue first.")
        sys.exit(1)

    ROOT = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(ROOT))

    # Progress tracking: done-file records completed (site, locale, rel) tuples
    # so restarts skip already-healed files instead of re-processing them.
    done_path = queue_path.parent / (queue_path.stem + "_done.jsonl")
    done_set: set[tuple[str, str, str]] = set()
    if done_path.exists():
        with done_path.open(encoding="utf-8") as dfh:
            for line in dfh:
                if line.strip():
                    d = json.loads(line)
                    done_set.add((d["site"], d["locale"], d["rel"]))
        print(f"Resuming: {len(done_set)} entries already done (from {done_path.name})")

    print(f"Loading TranslationEngine with model={model} on cuda…")
    engine = _build_engine(model, ROOT)
    print("Engine ready.\n")

    content_root = _resolve_content_root()

    ok = fail = skipped = 0
    locale_filter = set(locales) if locales else None
    site_filter_set = set(sites_filter) if sites_filter else None

    with queue_path.open(encoding="utf-8") as fh:
        entries = [json.loads(line) for line in fh if line.strip()]

    if locale_filter:
        entries = [e for e in entries if e["locale"] in locale_filter]
    if site_filter_set:
        entries = [e for e in entries if e.get("site", "reference.aspose.org") in site_filter_set]

    if max_files:
        entries = entries[:max_files]

    # Deduplicate — same file may appear multiple times across issue types
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for e in entries:
        key = (e.get("site", "reference.aspose.org"), e["locale"], e["rel"])
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    entries = deduped
    print(f"Retranslating {len(entries)} unique files …")

    import time
    t0 = time.time()
    done_fh = done_path.open("a", encoding="utf-8")

    try:
        for i, entry in enumerate(entries, 1):
            site_id = entry.get("site", "reference.aspose.org")
            locale = entry["locale"]
            rel = Path(entry["rel"])
            done_key = (site_id, locale, str(rel))

            if done_key in done_set:
                skipped += 1
                continue

            src_path = content_root / site_id / EN_LOCALE / rel

            if not src_path.exists():
                fail += 1
                continue

            try:
                engine.translate_file(
                    site_id=site_id,
                    file_path=src_path,
                    target_langs=[locale],
                    force=True,
                    force_overwrite=True,
                )
                ok += 1
                done_fh.write(json.dumps({"site": site_id, "locale": locale, "rel": str(rel)}) + "\n")
                done_fh.flush()
            except Exception as e:
                print(f"  [{i}] FAIL {site_id}/{locale}/{rel}: {e!s:.100}", flush=True)
                fail += 1

            if i % 100 == 0:
                elapsed = time.time() - t0
                rate = (ok + fail) / elapsed if elapsed > 0 else 0
                remaining = len(entries) - i - skipped
                eta = remaining / rate if rate > 0 else 0
                print(
                    f"  [{i}/{len(entries)}] {ok} OK, {fail} fail, {skipped} skipped | "
                    f"{rate:.2f} files/s | ETA {eta/60:.0f} min",
                    flush=True,
                )
    finally:
        done_fh.close()

    print(f"\nDone: {ok} OK, {fail} fail, {skipped} skipped out of {len(entries)} unique files.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan and GPU-retranslate files with English headings or body issues"
    )
    parser.add_argument("--scan", action="store_true", help="Scan and count affected files (default)")
    parser.add_argument("--build-queue", action="store_true", help="Write JSONL queue of affected files")
    parser.add_argument("--retranslate", action="store_true", help="Retranslate files from queue using engine")
    parser.add_argument("--sites", type=str, default="reference.aspose.org",
                        help="Comma-separated site names or 'all' (default: reference.aspose.org)")
    parser.add_argument("--locales", type=str, default="", help="Comma-separated locale list (default: all)")
    parser.add_argument("--categories", type=str, default="",
                        help="Filter: api_headings,section_headings,table_access,body_identical_to_en,empty_body,code_fence_dropped,table_desc_not_translated,description_hallucination")
    parser.add_argument("--model", type=str, default="nllb_200_1.3b",
                        help="Model name for --retranslate (nllb_200_1.3b or m2m100_418m)")
    parser.add_argument("--queue-file", type=str,
                        default=".local/heal_headings_queue.jsonl",
                        help="JSONL queue file path")
    parser.add_argument("--max-files", type=int, default=0,
                        help="Stop after N files per locale (for testing)")
    args = parser.parse_args()

    if args.sites.strip().lower() == "all":
        sites = ALL_SITES
    else:
        sites = [s.strip() for s in args.sites.split(",") if s.strip()]

    locales = [loc.strip() for loc in args.locales.split(",") if loc.strip()] if args.locales else []
    categories = {c.strip() for c in args.categories.split(",") if c.strip()}
    queue_path = Path(args.queue_file)

    print(f"Sites: {sites}")
    print(f"Locales: {locales or '(all)'}")
    if categories:
        print(f"Categories: {categories}")
    print()

    if args.retranslate:
        lock_path = queue_path.parent / f"{queue_path.stem}.lock"
        if lock_path.exists():
            try:
                import psutil
                locked_pid = int(lock_path.read_text().strip())
                if psutil.pid_exists(locked_pid):
                    proc = psutil.Process(locked_pid)
                    if "heal_english_headings" in " ".join(proc.cmdline()):
                        print(f"ERROR: Another heal instance is already running as PID {locked_pid}. Exiting.")
                        sys.exit(1)
            except Exception:
                pass  # stale lock or bad pid — overwrite below
        lock_path.write_text(str(os.getpid()))
        import atexit
        atexit.register(lambda: lock_path.unlink(missing_ok=True))
        run_retranslate(queue_path, args.model, locales, sites if args.sites.strip().lower() != "all" else None, args.max_files)
    elif args.build_queue:
        run_build_queue(sites, locales, categories, queue_path, args.max_files)
    else:
        run_scan(sites, locales, categories, args.max_files)


if __name__ == "__main__":
    main()
