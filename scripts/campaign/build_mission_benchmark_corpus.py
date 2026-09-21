"""Build the mission benchmark corpus from real in-scope sources (TC-APT-006, plan section 6 / 6.1).

Mission ``aspose-org-full-portfolio-translation-20260901``.  The corpus doubles as
TC-APT-004b's qualification sample, so it is drawn from the *real* portfolio (the TC-APT-003
work ledger), stratified by site x content class, deterministically (seeded, sha-sorted).

Content classes (a source may carry several; sampling picks per class):
  short_metadata, technical_prose, api_heavy, marketing, table_heavy, placeholder_heavy,
  mixed_md_html, long_form, rtl_cjk_sensitive (identifier/brand dense -- stresses RTL/CJK targets)

Outputs
  * ``config/benchmark_corpus/aspose_org_mission_sources.json`` (tracked): the sampled source
    files with sha256, site/family/platform, classes, word counts -- consumed by
    ``build_campaign_manifest.py --source-list`` for the qualification manifest.
  * ``data/benchmark_corpus/aspose_org_mission_segments.json``: segment-level samples in the
    existing ``CorpusSample`` schema (id, text_en, domain, tokens, source_path, metadata) for the
    provider comparison (``run_provider_comparison.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.atomic_write import atomic_write
from src.workers.work_ledger import DEFAULT_LEDGER_PATH, WorkLedger

DEFAULT_SOURCES_OUTPUT = Path("config/benchmark_corpus/aspose_org_mission_sources.json")
DEFAULT_SEGMENTS_OUTPUT = Path("data/benchmark_corpus/aspose_org_mission_segments.json")

CLASSES: tuple[str, ...] = (
    "short_metadata",
    "technical_prose",
    "api_heavy",
    "marketing",
    "table_heavy",
    "placeholder_heavy",
    "mixed_md_html",
    "long_form",
    "rtl_cjk_sensitive",
)
MARKETING_SITES = {"products.aspose.org", "websites.aspose.org"}
API_SITES = {"reference.aspose.org"}

_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_FENCE_RE = re.compile(r"^```.*?^```", re.S | re.M)
_SHORTCODE_RE = re.compile(r"\{\{[<%].*?[>%]\}\}", re.S)
_HTML_RE = re.compile(r"<[a-zA-Z][^>]*>")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)
_IDENT_RE = re.compile(r"\b(?:[A-Z][a-z0-9]+){2,}\b|\bAspose\.[A-Za-z0-9.]+|`[^`]+`")


def _split_frontmatter(text: str) -> tuple[str, str]:
    m = _FM_RE.match(text)
    return (m.group(1), text[m.end() :]) if m else ("", text)


def _fm_field(fm: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", fm, re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def classify(site_id: str, text: str) -> dict[str, Any]:
    """Feature-detect content classes for one English source file."""
    fm, body = _split_frontmatter(text)
    body_no_code = _FENCE_RE.sub("", body)
    words = len(body_no_code.split())
    fences = len(_FENCE_RE.findall(body))
    shortcodes = len(_SHORTCODE_RE.findall(body))
    html = len(_HTML_RE.findall(body_no_code))
    table_rows = len(_TABLE_ROW_RE.findall(body))
    idents = len(_IDENT_RE.findall(body_no_code))
    ident_density = idents / max(1, words)
    classes: set[str] = set()
    if words < 80:
        classes.add("short_metadata")
    if 300 <= words <= 1500 and fences <= 1 and site_id not in MARKETING_SITES:
        classes.add("technical_prose")
    if site_id in API_SITES or fences >= 3 or ident_density > 0.12:
        classes.add("api_heavy")
    if site_id in MARKETING_SITES:
        classes.add("marketing")
    if table_rows >= 5:
        classes.add("table_heavy")
    if shortcodes + html >= 4:
        classes.add("placeholder_heavy")
    if html >= 2:
        classes.add("mixed_md_html")
    if words > 1500:
        classes.add("long_form")
    if ident_density > 0.08 and words >= 40:
        classes.add("rtl_cjk_sensitive")
    return {
        "classes": sorted(classes),
        "words": words,
        "fences": fences,
        "shortcodes": shortcodes,
        "html_tags": html,
        "table_rows": table_rows,
        "identifier_density": round(ident_density, 4),
        "title": _fm_field(fm, "title"),
        "description": _fm_field(fm, "description"),
    }


def _paragraphs(body: str) -> list[str]:
    """Translatable prose paragraphs (fenced code removed), tables/shortcodes kept in place."""
    body = _FENCE_RE.sub("", body)
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return [p for p in paras if not p.lstrip().startswith("#") or len(p.split()) > 3]


def sample_sources(
    ledger: WorkLedger,
    content_repo: Path,
    *,
    per_site_per_class: int = 2,
    seed: int = 42,
    sites: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic stratified sample over site x class from the ledger's source set."""
    rng = random.Random(seed)
    # one row per source: the ledger has 36 rows per source; pick target_lang='de' as the key row
    rows = list(ledger.query(target_lang="de"))
    by_site: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if sites and r["site_id"] not in sites:
            continue
        if r["eligibility_state"] == "SOURCE_INVALID":
            continue
        by_site[r["site_id"]].append(r)
    picked: dict[str, dict[str, Any]] = {}
    for site_id in sorted(by_site):
        candidates = sorted(by_site[site_id], key=lambda r: r["source_sha256"])
        rng.shuffle(candidates)
        per_class: dict[str, int] = defaultdict(int)
        for r in candidates:
            if all(per_class[c] >= per_site_per_class for c in CLASSES):
                break
            path = content_repo / r["source_path"]
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            feats = classify(site_id, text)
            wanted = [c for c in feats["classes"] if per_class[c] < per_site_per_class]
            if not wanted:
                continue
            for c in wanted:
                per_class[c] += 1
            picked[r["source_path"]] = {
                "site_id": site_id,
                "family": r["family"],
                "platform": r["platform"],
                "source_path": r["source_path"],
                "source_sha256": r["source_sha256"],
                "sampled_for_classes": wanted,
                **feats,
            }
    return sorted(picked.values(), key=lambda s: (s["site_id"], s["source_path"]))


def build_segments(
    sources: list[dict[str, Any]], content_repo: Path, *, per_source: int = 3, max_words: int = 120
) -> list[dict[str, Any]]:
    """Segment-level corpus: frontmatter title/description + up to N paragraphs per source."""
    samples: list[dict[str, Any]] = []
    for s in sources:
        text = (content_repo / s["source_path"]).read_text(encoding="utf-8")
        fm, body = _split_frontmatter(text)
        sid = hashlib.sha256(s["source_path"].encode("utf-8")).hexdigest()[:10]
        meta = {
            "site_id": s["site_id"],
            "family": s["family"],
            "platform": s["platform"],
            "classes": s["classes"],
        }
        for key in ("title", "description"):
            value = _fm_field(fm, key)
            if value:
                samples.append(
                    {
                        "id": f"{sid}_{key}",
                        "text_en": value,
                        "domain": "short_metadata",
                        "tokens": len(value) // 4,
                        "source_path": s["source_path"],
                        "metadata": {**meta, "field": key},
                    }
                )
        paras = _paragraphs(body)
        if not paras:
            continue
        idxs = sorted({0, len(paras) // 2, len(paras) - 1})[:per_source]
        for n, i in enumerate(idxs):
            p = paras[i]
            if len(p.split()) > max_words:
                p = " ".join(p.split()[:max_words])
            domain = (
                "table_heavy"
                if _TABLE_ROW_RE.search(p)
                else "placeholder_heavy"
                if (_SHORTCODE_RE.search(p) or _HTML_RE.search(p))
                else (
                    "api_heavy"
                    if s["site_id"] in API_SITES
                    else "marketing"
                    if s["site_id"] in MARKETING_SITES
                    else "technical_prose"
                )
            )
            samples.append(
                {
                    "id": f"{sid}_p{n}",
                    "text_en": p,
                    "domain": domain,
                    "tokens": len(p) // 4,
                    "source_path": s["source_path"],
                    "metadata": {**meta, "paragraph_index": i},
                }
            )
    return samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-006 mission benchmark corpus builder")
    parser.add_argument(
        "--content-repo", type=Path, default=Path("D:/onedrive/Documents/GitHub/aspose.org")
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--per-site-per-class", type=int, default=2)
    parser.add_argument("--segments-per-source", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--site", action="append", dest="sites")
    parser.add_argument("--sources-output", type=Path, default=DEFAULT_SOURCES_OUTPUT)
    parser.add_argument("--segments-output", type=Path, default=DEFAULT_SEGMENTS_OUTPUT)
    args = parser.parse_args(argv)

    content_repo = args.content_repo.resolve()
    with WorkLedger(args.ledger) as ledger:
        sources = sample_sources(
            ledger,
            content_repo,
            per_site_per_class=args.per_site_per_class,
            seed=args.seed,
            sites=args.sites,
        )
    segments = build_segments(sources, content_repo, per_source=args.segments_per_source)
    by_class: dict[str, int] = defaultdict(int)
    by_site: dict[str, int] = defaultdict(int)
    for s in sources:
        by_site[s["site_id"]] += 1
        for c in s["classes"]:
            by_class[c] += 1
    payload = {
        "schema_version": 1,
        "taskcard": "TC-APT-006",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "per_site_per_class": args.per_site_per_class,
        "content_repo": content_repo.as_posix(),
        "source_count": len(sources),
        "by_site": dict(sorted(by_site.items())),
        "by_class": dict(sorted(by_class.items())),
        "sources": sources,
    }
    atomic_write(
        path=args.sources_output, content=json.dumps(payload, indent=2, ensure_ascii=False)
    )
    atomic_write(
        path=args.segments_output, content=json.dumps(segments, indent=2, ensure_ascii=False)
    )
    print(
        f"sources -> {args.sources_output}: {len(sources)} sources; by_site={dict(by_site)}; by_class={dict(by_class)}"
    )
    print(
        f"segments -> {args.segments_output}: {len(segments)} samples; domains={dict(sorted(defaultdict(int, {d: sum(1 for x in segments if x['domain'] == d) for d in set(x['domain'] for x in segments)}).items()))}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
