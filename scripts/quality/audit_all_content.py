"""
Comprehensive quality audit of all aspose.org localized content.
Scans every translated file against its English source and reports issues by type and severity.
"""
import sys
import re
import io
import json
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# HT-QUALITY-GATES-001 Part 22 (plan Part 6 item 5 / Phase 7): reuse the REAL
# write_gate.py gate methods directly for the checks added this session,
# rather than a third, independently-drifting reimplementation (this script
# already had its own simplified re-derivations of several older checks --
# not repeating that mistake for the new ones). These 5 gates don't read
# self._detector/self._config, so a minimal, dependency-free evaluator
# instance is sufficient and safe to share across the whole scan.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult  # noqa: E402
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import (  # noqa: E402
    discover_source_files,
    resolve_source_root,
    resolve_translated_path,
)

_GATE_EVALUATOR = WriteGateEvaluator(
    detector=None, similarity_tracker=None, config=None, force_accept=True,
)

def safe(s):
    """Return ASCII-safe version of string for display."""
    if isinstance(s, bytes):
        s = s.decode("utf-8", errors="replace")
    return s.encode("ascii", errors="replace").decode("ascii")

_CONFIG = ConfigService(_PROJECT_ROOT / "config")

# Durable-fix (see plan: "stop treating file-suffix-layout sites as
# exceptions"): site list and content root are now DERIVED from the
# registry (config/site_profiles/*.yaml via ConfigService), not hardcoded.
# TC-AUD-007 fixed a hardcoded 3-site list by hand-expanding to 5; that
# still silently excluded 13 real aspose.net/websites/www site profiles.
# `autonomous_enabled` (already set correctly on every profile: false on
# the 11 test/fixture profiles, true/default on the 18 real production
# ones) is exactly the field that already exists to make this distinction
# -- deriving from it means a future new site profile is automatically
# covered without anyone needing to remember to edit this list.
SITES = _CONFIG.list_sites(autonomous_only=True)

# Detection patterns
NLLB_ARTIFACTS = re.compile(
    r"مُحملة مكان"                # Arabic "placeholder" literal
    r"|\u3010.{1,20}\u3011"       # 【ポストハウス】 style NLLB artifacts
    r"|\[Pr[eé]c[eé]dent\]\s*\d+"  # [Précédent] 0
    r"|\[Previous\]\s*\d+"
    r"|IHeadingPair\{/i:"
    r"|\{[^\x00-\x7F]{1,10}\}"    # {non-ASCII} artifact wrapper
)
SHORTCODE_LEAK = re.compile(r"\{\{[<%]")
EU_HALLUCINATION = re.compile(
    r"cookie|GDPR|General Data Protection|privacy policy|Datenschutz|European Union",
    re.IGNORECASE,
)
NON_LATIN = {
    "ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh",
}
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
DOUBLE_PERIOD = re.compile(r"(?<!\.)\.\.(?!\.)")
EN_WORD_LINE = re.compile(r"^[A-Za-z0-9\s.,;:!\?\-'\"()\[\]{}|#*`~_>]+$")
# New detectors (TC-AUD-001)
_MOJIBAKE_RE = re.compile(r'â€[""''\u2014\u2013]|Ã[©è¼½¾\xa0¿]|â€\x9c|â€\x9d')
_LINK_RE = re.compile(r'(\[(?:[^\[\]]*)\])\(([^)]+)\)')
_EN_PROSE_RE = re.compile(r'^[A-Za-z][a-z ,.\-;:\'"()]{15,}$')


def get_frontmatter(content):
    m = FM_RE.match(content)
    return m.group(1) if m else ""


def get_body(content):
    m = FM_RE.match(content)
    return content[m.end():] if m else content


def fm_field(fm, key):
    m = re.search(rf"^{key}:\s*(.+)$", fm, re.M)
    return m.group(1).strip().strip("\"'") if m else None


def count_table_rows(text):
    """Count complete table rows (start and end with |), skipping code blocks."""
    in_code = False
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        if s.startswith("|") and s.endswith("|") and "---" not in s:
            count += 1
    return count


def check_english_headings_nonlatin(tr_body: str) -> list[str]:
    """Return up to all English-looking headings found outside code fences.

    Fence-aware (TC-DCF-007): a Python/YAML/bash comment line inside a code
    fence (e.g. "# Read full text") matches the same #-prefixed pattern
    `HEADING_RE` uses for real markdown headings. Without excluding fenced
    content, these get misreported as untranslated English document
    headings in non-Latin locales -- confirmed on real files (e.g.
    kb.aspose.org/ar/words/python/how-to-build-ldm-builder-python.md, where
    Python comments "# Read full text" / "# Iterate sections" inside code
    blocks were the only "headings" ever flagged).
    """
    fence_spans = [(m.start(), m.end()) for m in re.finditer(r"```[\s\S]*?```", tr_body)]

    def in_fence(pos):
        return any(s <= pos < e for s, e in fence_spans)

    en_heads = []
    for m in HEADING_RE.finditer(tr_body):
        if in_fence(m.start()):
            continue
        heading_text = m.group(2)
        if re.match(r"^[A-Za-z][A-Za-z0-9 ]{1,30}$", heading_text.strip()):
            en_heads.append(heading_text)
    return en_heads


def check_purity(body, target_lang):
    """Return (has_issue, ratio) for English content in non-Latin body.

    Fence-aware (TC-DCF-004): splits on fence boundaries first, then blank
    lines within each non-fence chunk -- mirrors check_duplicate_content()'s
    convention below. Splitting on blank lines first (the prior behavior)
    let a fenced code block with an internal blank line leak into `paras` as
    extra non-fence-looking chunks, which both inflated false positives (code
    identifiers matching EN_WORD_LINE) and diluted the ratio's denominator
    with code content, masking genuinely high English-prose files that carry
    large code blocks. Fence-first splitting also avoids the opposite bug:
    naively excluding any paragraph whose byte range merely overlaps a fence
    span would swallow prose directly adjacent to a fence (no blank line
    before it) into the fence and drop it from consideration entirely.
    """
    paras = []
    for chunk in re.split(r"(```[\s\S]*?```)", body):
        if chunk.startswith("```"):
            continue
        for seg in re.split(r"\n{2,}", chunk):
            stripped = seg.strip()
            if len(stripped) > 30:
                paras.append(stripped)
    if not paras:
        return False, 0.0
    en_count = 0
    for p in paras:
        # Skip shortcodes, tables (fenced code already excluded above)
        if "{{<" in p or p.startswith("|"):
            continue
        words = p.split()
        if len(words) >= 5 and EN_WORD_LINE.match(p):
            en_count += 1
    ratio = en_count / len(paras) if paras else 0
    return ratio > 0.10, ratio


_LOWER_EN_WORD = re.compile(r"^[a-z]{3,}$")


def check_table_desc_not_translated(body):
    """Return (has_issue, detail) for English table description cells in non-Latin files."""
    in_code = False
    en_cells = 0
    total_cells = 0
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
        if in_code or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        # Skip separator rows
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        desc = cells[-1]
        # Strip inline code spans
        desc_clean = re.sub(r"`[^`]+`", "", desc).strip()
        if len(desc_clean) < 20:
            continue
        total_cells += 1
        words = desc_clean.split()
        lower_en = sum(1 for w in words if _LOWER_EN_WORD.match(w))
        if len(words) >= 4 and lower_en / len(words) >= 0.4 and EN_WORD_LINE.match(desc_clean):
            en_cells += 1
    if total_cells < 3:
        return False, ""
    ratio = en_cells / total_cells
    return ratio >= 0.5, f"{en_cells}/{total_cells} desc cells English"


def check_code_fence_dropped(en_body, tr_body):
    """Return (has_issue, detail) when translation has fewer code fences than source.

    Only fires when source has ≥4 fences (≥2 code blocks), matching Gate 19.
    """
    def count_fences(body):
        return sum(1 for ln in body.splitlines() if ln.strip().startswith("```"))

    src_fences = count_fences(en_body)
    tgt_fences = count_fences(tr_body)
    if src_fences < 4:
        return False, ""
    if tgt_fences < src_fences - 2:
        return True, f"src={src_fences} fences, tgt={tgt_fences} fences"
    return False, ""


def check_duplicate_content(tr_body: str) -> bool:
    """Return True if a paragraph repeats 3+ times outside code fences,
    excluding legitimate structurally-separated repeats.

    Code-fence content is excluded: distinct code examples on the same page
    routinely share a short boilerplate opening line (an import/#include
    right after the fence), which would otherwise be miscounted as "the same
    paragraph repeated" even though every example is genuinely different.

    A duplicate is also excluded if a heading separates every consecutive
    pair of its occurrences -- the signature of legitimate repetition (e.g.
    a "Returns: same X instance for chaining" note, or a "Key Properties"
    label, repeated once per distinct method/property/class section on a
    reference.aspose.org API-reference page) rather than a genuine MT
    decoding-loop artifact, which has no such intervening structure between
    repeats. A code fence between occurrences is deliberately NOT treated
    as sufficient separation on its own: a decoding-loop repeat could
    plausibly interleave with unrelated code blocks, so only an actual
    section-heading change counts as evidence of distinct structural
    context (verified: all 20 known real legitimate cases from mission
    duplicate-content-fence-fix-20260723 are heading-separated, not merely
    fence-separated).
    """
    heading_spans = [(m.start(), m.end()) for m in re.finditer(r"^#{1,6}[ \t].*$", tr_body, re.M)]

    def has_boundary_between(a, b):
        return any(a <= s < b for s, _ in heading_spans)

    # Split on fence boundaries first, then blank lines within each
    # non-fence chunk. Splitting on blank lines first and only afterward
    # checking fence overlap would silently merge a paragraph that directly
    # abuts a fence with no blank line into the fence itself, losing it
    # from consideration entirely -- missing genuine 3x corruption that
    # happens to sit right after a fence.
    occurrence_starts: dict[str, list[int]] = {}
    offset = 0
    for chunk in re.split(r"(```[\s\S]*?```)", tr_body):
        if chunk.startswith("```"):
            offset += len(chunk)
            continue
        pos = 0
        for seg in re.split(r"(\n{2,})", chunk):
            stripped = seg.strip()
            if len(stripped) > 50:
                occurrence_starts.setdefault(stripped, []).append(offset + pos)
            pos += len(seg)
        offset += len(chunk)

    for key, starts in occurrence_starts.items():
        if len(starts) < 3:
            continue
        starts = sorted(starts)
        if all(has_boundary_between(starts[i], starts[i + 1]) for i in range(len(starts) - 1)):
            continue  # structurally-separated legitimate repeat
        return True
    return False


def scan(output_path=None, resume=False, sites=None):
    results = defaultdict(lambda: defaultdict(int))   # site -> issue -> count
    examples = defaultdict(list)                       # issue -> list of (site, locale, rel, detail)
    locale_counts = defaultdict(lambda: defaultdict(int))  # locale -> issue -> count
    site_locale_counts = defaultdict(lambda: defaultdict(int))  # site:locale -> issue -> count
    total_files = 0
    total_translated = 0
    total_missing = 0

    # Load already-processed paths for --resume support
    resumed_paths = set()
    if resume and output_path and Path(output_path).exists():
        with open(output_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    resumed_paths.add(entry.get("file_path", ""))
                except Exception:
                    pass
        print(f"[resume] Skipping {len(resumed_paths):,} already-processed files", flush=True)

    # JSONL output file handle
    out_fh = None
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        out_mode = "a" if resume else "w"
        out_fh = open(output_path, out_mode, encoding="utf-8")

    print(f"Starting audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in (sites if sites is not None else SITES):
        try:
            profile = _CONFIG.get_site_profile(site)
        except Exception as e:
            print(f"  Skipping {site} (profile load failed: {e})", flush=True)
            continue

        content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
        if not content_root.exists():
            print(f"  Skipping {site} (content root not found: {content_root})", flush=True)
            continue

        # Registry-driven discovery (src/utils/content_discovery.py): works
        # identically for per_language_folders=True sites (docs/kb/products/
        # reference.aspose.org -- unchanged en_root.rglob walk under the
        # hood) and per_language_folders=False, file-suffix sites (blog.
        # aspose.org, blog.aspose.net, www.aspose.org, www.aspose.net --
        # previously silently skipped here entirely). No per-site branching.
        en_files = discover_source_files(profile, content_root)
        source_root = resolve_source_root(profile, content_root)
        locales = sorted(profile.target_langs)
        print(f"\n{site}: {len(en_files):,} EN files x {len(locales)} locales = {len(en_files)*len(locales):,} expected", flush=True)
        print(f"  Locales: {locales}", flush=True)

        done = 0
        for en_path in en_files:
            done += 1
            if done % 500 == 0:
                print(f"  ... {done}/{len(en_files)} source files scanned", flush=True)

            rel = en_path.relative_to(source_root)
            try:
                en_content = en_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            en_fm = get_frontmatter(en_content)
            en_body = get_body(en_content)
            en_title = fm_field(en_fm, "title") or ""
            en_link_title = fm_field(en_fm, "linkTitle") or ""
            en_rows = count_table_rows(en_body)
            en_lines = en_content.count("\n")
            en_paras = [p for p in en_body.split("\n\n") if len(p.strip()) > 20]

            for locale in locales:
                tr_path = resolve_translated_path(profile, en_path, locale)
                total_files += 1

                if not tr_path.exists():
                    results[site]["missing"] += 1
                    locale_counts[locale]["missing"] += 1
                    site_locale_counts[f"{site}:{locale}"]["missing"] += 1
                    total_missing += 1
                    continue

                try:
                    tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    results[site]["unreadable"] += 1
                    continue

                # --resume: skip already-processed files
                if str(tr_path) in resumed_paths:
                    total_translated += 1
                    continue

                total_translated += 1
                tr_fm = get_frontmatter(tr_content)
                tr_body = get_body(tr_content)
                tr_title = fm_field(tr_fm, "title") or ""
                tr_link_title = fm_field(tr_fm, "linkTitle") or ""

                file_issues = []  # per-file issue list for JSONL output

                def record(issue, detail=""):
                    results[site][issue] += 1
                    locale_counts[locale][issue] += 1
                    site_locale_counts[f"{site}:{locale}"][issue] += 1
                    if len(examples[issue]) < 6:
                        examples[issue].append((site, locale, str(rel), safe(str(detail))))
                    file_issues.append({"type": issue, "detail": safe(str(detail)), "unit_indices": []})

                # 1. Empty body (skeleton file)
                if len(tr_body.strip()) < 20 and len(en_body.strip()) > 50:
                    record("empty_body")
                    # Flush JSONL before continue (other checks skipped)
                    if out_fh and file_issues:
                        out_fh.write(json.dumps({
                            "file_path": str(tr_path), "en_path": str(en_path),
                            "locale": locale, "site_id": site,
                            "issues": [{"type": i["type"], "detail": i["detail"],
                                        "unit_indices": [], "priority": _PRIORITY.get(i["type"], 3)}
                                       for i in file_issues],
                            "max_priority": min(_PRIORITY.get(i["type"], 3) for i in file_issues),
                        }) + "\n")
                    continue

                # 2. Title mismatch. reference.aspose.org: title is passthrough
                # site-wide, so check every file. Other sites translate title on
                # leaf pages legitimately -- only index pages at family/platform
                # depth (lang/family/platform/_index.md) or, on sites confirmed
                # to have root-only families (docs/kb/products -- see
                # is_family_platform_index()'s include_family_root in
                # text_unit_extractor.py / segment_translator.py's
                # _FAMILY_ROOT_SITES), family-root depth (lang/family/_index.md)
                # must stay byte-identical to EN. blog.aspose.org not yet
                # investigated for family-root -- family/platform depth only.
                _FAMILY_ROOT_SITES = {"products.aspose.org", "kb.aspose.org", "docs.aspose.org"}
                _is_index = rel.parts[-1] == "_index.md"
                _is_family_platform_index = _is_index and len(rel.parts) == 3
                _is_family_root_index = (
                    _is_index and len(rel.parts) == 2 and site in _FAMILY_ROOT_SITES
                )
                _title_must_match_en = (
                    _is_family_platform_index
                    or _is_family_root_index
                    or site == "reference.aspose.org"
                )
                if _title_must_match_en and en_title and tr_title and tr_title != en_title:
                    record("title_mismatch", f"EN={en_title!r} TR={tr_title!r}")

                if _title_must_match_en and en_link_title and tr_link_title and tr_link_title != en_link_title:
                    record("linktitle_mismatch", f"EN={en_link_title!r} TR={tr_link_title!r}")

                # 2b. Title untranslated (suspected). Ported from
                # audit_blog_bundle.py (retired -- see durable-fix plan):
                # opposite gate from title_mismatch above -- fires on pages
                # where title SHOULD legitimately translate (leaf/post
                # content), when it's byte-identical to EN and long/specific
                # enough that a coincidental match is unlikely (short brand
                # words like "Aspose.Cells" can legitimately match across
                # languages; len>15 filters those out).
                if (
                    not _title_must_match_en
                    and en_title
                    and tr_title
                    and tr_title == en_title
                    and len(en_title) > 15
                ):
                    record("title_untranslated_suspected", en_title)

                # 3. NLLB/model artifact corruption anywhere in body
                art_m = NLLB_ARTIFACTS.search(tr_body)
                if art_m:
                    record("artifact_corruption", art_m.group()[:60])

                # 4. Shortcode leaked into output body (exclude if also in EN source)
                if SHORTCODE_LEAK.search(tr_body) and not SHORTCODE_LEAK.search(en_body):
                    record("shortcode_leak")

                # 5. EU hallucination in translation but not in source
                if EU_HALLUCINATION.search(tr_body) and not EU_HALLUCINATION.search(en_body):
                    eu_match = EU_HALLUCINATION.search(tr_body)
                    record("eu_hallucination", eu_match.group()[:50] if eu_match else "")

                # 6. English API headings in non-Latin-script locales
                if locale in NON_LATIN:
                    en_heads = check_english_headings_nonlatin(tr_body)
                    if en_heads:
                        record("english_headings_nonlatin", str(en_heads[:2]))

                # 7. High English-paragraph ratio in non-Latin locales
                if locale in NON_LATIN:
                    purity_issue, ratio = check_purity(tr_body, locale)
                    if purity_issue:
                        record("purity_issue", f"{ratio:.0%} English paras")

                # 8. Table row count mismatch
                if en_rows >= 3:
                    tr_rows = count_table_rows(tr_body)
                    if tr_rows > 0 and (tr_rows < en_rows * 0.5 or tr_rows > en_rows * 2.0):
                        record("table_row_corruption", f"EN={en_rows} TR={tr_rows}")

                # 9. Newline explosion (body >2.5x EN line count)
                tr_lines = tr_content.count("\n")
                if tr_lines > en_lines * 2.5 and en_lines > 10:
                    record("newline_explosion", f"EN={en_lines} TR={tr_lines}")

                # 10. Inline code translated (non-ASCII inside backticks where EN is ASCII)
                en_spans = re.findall(r"`([^`]+)`", en_body)
                tr_spans = re.findall(r"`([^`]+)`", tr_body)
                for es, ts in zip(en_spans, tr_spans):
                    if es.isascii() and not ts.isascii():
                        record("inline_code_translated", f"`{es}` -> `{ts[:30]}`")
                        break

                # 11. Double periods in body (outside code)
                # Quick: only check outside fenced blocks
                body_no_code = re.sub(r"```.*?```", "", tr_body, flags=re.S)
                if DOUBLE_PERIOD.search(body_no_code):
                    record("double_period")

                # 12. Duplicate content (paragraph repeated 3+ times, outside code
                # fences and excluding structurally-separated legitimate repeats)
                if check_duplicate_content(tr_body):
                    record("duplicate_content")

                # 13. Body identical to English (completely untranslated)
                if len(tr_body) > 100 and tr_body.strip() == en_body.strip():
                    record("body_identical_to_en")

                # 14b. Table description cells not translated (non-Latin locales)
                if locale in NON_LATIN and "|" in tr_body:
                    tbl_issue, tbl_detail = check_table_desc_not_translated(tr_body)
                    if tbl_issue:
                        record("table_desc_not_translated", tbl_detail)

                # 14c. Code fence dropped (all locales)
                if "```" in en_body:
                    fence_issue, fence_detail = check_code_fence_dropped(en_body, tr_body)
                    if fence_issue:
                        record("code_fence_dropped", fence_detail)

                # 14. Description hallucination (tr description > 3x EN or < 0.3x)
                en_desc = fm_field(en_fm, "description") or ""
                tr_desc = fm_field(tr_fm, "description") or ""
                if en_desc and tr_desc and len(en_desc) > 20:
                    ratio = len(tr_desc) / len(en_desc)
                    if ratio > 3.0 or (ratio < 0.3 and len(tr_desc) < 30):
                        record("description_hallucination", f"EN={len(en_desc)}ch TR={len(tr_desc)}ch ratio={ratio:.1f}x")

                # 15. Encoding corruption / mojibake in body (TC-AUD-001)
                if _MOJIBAKE_RE.search(tr_body):
                    m = _MOJIBAKE_RE.search(tr_body)
                    record("encoding_corruption", m.group()[:30] if m else "")

                # 16. Link path corrupted: relative path changed vs EN source (TC-AUD-001)
                en_links = {m.group(2) for m in _LINK_RE.finditer(en_body) if m.group(2).startswith(("../", "./", "/"))}
                tr_links = {m.group(2) for m in _LINK_RE.finditer(tr_body) if m.group(2).startswith(("../", "./", "/"))}
                if en_links and tr_links and not tr_links.issubset(en_links):
                    corrupted = tr_links - en_links
                    if corrupted:
                        record("link_path_corrupted", str(list(corrupted)[:2]))

                # 17. Description YAML reverted to English (TC-AUD-001)
                # Fires when: non-Latin locale, EN description is non-trivial prose,
                # TR description is pure ASCII prose (not a code identifier)
                if locale in NON_LATIN and en_desc and tr_desc and len(en_desc) > 30:
                    if tr_desc.isascii() and _EN_PROSE_RE.match(tr_desc):
                        record("description_yaml_reverted_to_english", f"desc={tr_desc[:60]!r}")

                # 18-23. HT-QUALITY-GATES-001 Part 22 gates (30-35), reused
                # directly from write_gate.py -- see _GATE_EVALUATOR comment
                # above. Each gets its own disposable WriteGateResult so a
                # hit in one never contaminates the next (mirrors the real
                # pipeline's "warn" dispatch, which uses the same pattern).
                # HT-QUALITY-GATES-001 Part 22 (Gate 29): omitted from the
                # first Phase 7 sweep by oversight -- flagged by the user and
                # fixed for this round. Cheap and structural (no LLM call),
                # so there was no cost reason to have excluded it.
                _wgr = WriteGateResult(passed=True)
                _GATE_EVALUATOR._gate_refusal_artifact(tr_content, tr_path, _wgr, locale)
                if not _wgr.passed:
                    record("refusal_artifact_gate29", (_wgr.error or "")[:150])

                _wgr = WriteGateResult(passed=True)
                _GATE_EVALUATOR._gate_placeholder_leak(tr_content, tr_path, _wgr, locale)
                if not _wgr.passed:
                    record("placeholder_leak_gate30", (_wgr.error or "")[:150])

                _wgr = WriteGateResult(passed=True)
                _GATE_EVALUATOR._gate_partial_script_contamination(tr_content, tr_path, locale, _wgr)
                if not _wgr.passed:
                    record("partial_script_contamination_gate31", (_wgr.error or "")[:150])

                _wgr = WriteGateResult(passed=True)
                _GATE_EVALUATOR._gate_content_hash_staleness(en_content, tr_content, tr_path, _wgr)
                if not _wgr.passed:
                    record("content_hash_stale_gate32", (_wgr.error or "")[:150])

                _wgr = WriteGateResult(passed=True)
                _GATE_EVALUATOR._gate_brand_token_presence(en_content, tr_content, tr_path, _wgr)
                if not _wgr.passed:
                    record("brand_token_missing_gate33", (_wgr.error or "")[:150])

                _wgr = WriteGateResult(passed=True)
                _GATE_EVALUATOR._gate_heading_deficit(en_content, tr_content, tr_path, _wgr)
                if not _wgr.passed:
                    record("heading_deficit_gate34", (_wgr.error or "")[:150])

                _wgr = WriteGateResult(passed=True)
                _GATE_EVALUATOR._gate_dropped_trailing_link(en_content, tr_content, tr_path, _wgr)
                if not _wgr.passed:
                    record("dropped_trailing_link_gate35", (_wgr.error or "")[:150])

                # Write JSONL record for this file if it has issues
                if out_fh and file_issues:
                    en_path_str = str(en_path)
                    record_entry = {
                        "file_path": str(tr_path),
                        "en_path": en_path_str,
                        "locale": locale,
                        "site_id": site,
                        "issues": [
                            {"type": iss["type"], "detail": iss["detail"], "unit_indices": iss["unit_indices"],
                             "priority": _PRIORITY.get(iss["type"], 3)}
                            for iss in file_issues
                        ],
                        "max_priority": min(_PRIORITY.get(iss["type"], 3) for iss in file_issues),
                    }
                    out_fh.write(json.dumps(record_entry) + "\n")

        print(f"\n  {site} results:", flush=True)
        for issue, count in sorted(results[site].items(), key=lambda x: -x[1]):
            print(f"    {issue}: {count:,}", flush=True)

    # Final summary
    print(f"\n\n{'='*70}", flush=True)
    print(f"TOTAL EXPECTED (source x locales): {total_files:,}", flush=True)
    print(f"TRANSLATED (files exist):          {total_translated:,}  ({100*total_translated/total_files:.1f}%)", flush=True)
    print(f"MISSING (no output file):          {total_missing:,}  ({100*total_missing/total_files:.1f}%)", flush=True)

    print(f"\n{'='*70}", flush=True)
    print("ISSUE TOTALS ACROSS ALL SITES (sorted by severity):", flush=True)
    all_issues = defaultdict(int)
    for site_r in results.values():
        for k, v in site_r.items():
            all_issues[k] += v
    for issue, count in sorted(all_issues.items(), key=lambda x: -x[1]):
        print(f"  {issue:<35} {count:>8,}", flush=True)

    print(f"\n{'='*70}", flush=True)
    print("PER-LOCALE ISSUE SUMMARY (all sites combined):", flush=True)
    print(f"  {'locale':<8} {'missing':>8} {'title':>7} {'eng_hd':>7} {'purity':>7} {'table':>7} {'artifact':>8} {'inline':>7} {'body_en':>8}", flush=True)
    for locale in sorted(locale_counts.keys()):
        lc = locale_counts[locale]
        total_loc = sum(lc.values())
        if total_loc > 0:
            print(
                f"  {locale:<8}"
                f"  {lc.get('missing', 0):>7,}"
                f"  {lc.get('title_mismatch', 0) + lc.get('linktitle_mismatch', 0):>6,}"
                f"  {lc.get('english_headings_nonlatin', 0):>6,}"
                f"  {lc.get('purity_issue', 0):>6,}"
                f"  {lc.get('table_row_corruption', 0):>6,}"
                f"  {lc.get('artifact_corruption', 0):>7,}"
                f"  {lc.get('inline_code_translated', 0):>6,}"
                f"  {lc.get('body_identical_to_en', 0):>7,}",
                flush=True,
            )

    print(f"\n{'='*70}", flush=True)
    print("EXAMPLES (up to 5 per issue type):", flush=True)
    for issue, exs in sorted(examples.items()):
        print(f"\n  {issue.upper()}:", flush=True)
        for site, locale, rel, detail in exs[:5]:
            rel_short = rel[:55] if len(rel) > 55 else rel
            print(f"    [{locale}] {rel_short:<55} {safe(detail)}", flush=True)

    print(f"\nAudit complete at {datetime.now().strftime('%H:%M:%S')}", flush=True)
    if out_fh:
        out_fh.close()
        print(f"JSONL output written to: {output_path}", flush=True)


_PRIORITY = {
    "encoding_corruption": 1,
    "body_identical_to_en": 1,
    "empty_body": 1,
    "artifact_corruption": 1,
    # HT-QUALITY-GATES-001 Part 22: a raw internal token is unambiguously,
    # immediately visible as broken to any reader -- same severity class as
    # the other priority-1 checks above (Part 1.1 root cause B).
    "placeholder_leak_gate30": 1,
    # Part 1.6: a raw LLM refusal/conversational response shipped as page
    # content -- write_gate.py registers this "block", same severity tier.
    "refusal_artifact_gate29": 1,
    "content_drift": 2,
    "english_headings_nonlatin": 2,
    "purity_issue": 2,
    "inline_code_translated": 2,
    "shortcode_leak": 2,
    "partial_script_contamination_gate31": 2,
    # Part 7's remediation-triage ordering: brand-name-mistranslated is
    # explicitly "(2) directly reputational, cheap to fix" -- priority 2.
    "brand_token_missing_gate33": 2,
    "link_path_corrupted": 3,
    "table_desc_not_translated": 3,
    "description_hallucination": 3,
    "description_yaml_reverted_to_english": 3,
    "table_row_corruption": 3,
    "code_fence_dropped": 3,
    "content_hash_stale_gate32": 3,
    # Ported from audit_blog_bundle.py during the durable-fix consolidation
    # (script retired -- see plan): a leaf-page title that's byte-identical
    # to EN on a page where title should legitimately translate suggests a
    # skipped/failed field translation, distinct from title_mismatch (which
    # only fires where title must stay IDENTICAL).
    "title_untranslated_suspected": 3,
    "duplicate_content": 4,
    "double_period": 4,
    "newline_explosion": 4,
    "title_mismatch": 4,
    "linktitle_mismatch": 4,
    # Part 7: "(4) systemic dropped trailing sections -- now confirmed as the
    # single most prevalent defect corpus-wide" -- both gates target the same
    # defect class (heading-count deficit / trailing-link-loss), priority 4.
    "heading_deficit_gate34": 4,
    "dropped_trailing_link_gate35": 4,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Structural content audit for aspose.org translations")
    parser.add_argument("--output", default="data/audit/audit_structural.jsonl",
                        help="JSONL output path (default: data/audit/audit_structural.jsonl)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip files already present in the output JSONL")
    parser.add_argument("--no-jsonl", action="store_true",
                        help="Print only, no JSONL output")
    parser.add_argument("--sites", nargs="+", default=SITES,
                        help=f"Sites to scan (default: {SITES})")
    args = parser.parse_args()
    out = None if args.no_jsonl else args.output
    scan(output_path=out, resume=args.resume, sites=args.sites)
