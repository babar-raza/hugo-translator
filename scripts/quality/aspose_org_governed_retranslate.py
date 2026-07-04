#!/usr/bin/env python3
"""Site-profile driven governed validation/retranslation for Aspose.org subdomains."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Windows structured-exception codes that indicate a hard CUDA/CTranslate2 crash.
# On these codes we automatically retry on CPU.
_CUDA_CRASH_CODES = {
    3221225477,  # 0xC0000005  STATUS_ACCESS_VIOLATION
    3221226091,  # 0xC000026B  STATUS_GUARD_PAGE_VIOLATION
    3221226505,  # 0xC0000409  STATUS_STACK_BUFFER_OVERRUN
}

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.quality.products_org_governed_retranslate import (  # noqa: E402
    baseline_file,
    checkpoint_file,
    current_file,
    get_path_value,
    is_preserved_existing_translation,
    load_checkpoint,
    load_dotenv,
    merge_shard_checkpoints,
    overlay_main_checkpoint_for_items,
    parse_locale_filter,
    parse_doc,
    repair_extra_code_blocks_with_source_order,
    looks_like_prose,
    repair_target_code_blocks,
    repair_target_material_copy_fields,
    repair_target_product_identities,
    safe_shard_id,
    set_path_value,
    sha256_file,
    summary_file,
    verify_pair as products_verify_pair,
    write_json,
)
from src.translation_engine.parser.hugo_parser import HugoParser  # noqa: E402
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.models import FrontmatterMode  # noqa: E402

SUPPORTED_SITES = {
    "kb.aspose.org",
    "blog.aspose.org",
    "reference.aspose.org",
    "docs.aspose.org",
}
VERIFIER_POLICY_VERSION = "aspose-org-multisite-governed-v1"
ALL_LANG_CODES = {
    "af",
    "ar",
    "az",
    "bg",
    "ca",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "fa",
    "fi",
    "fr",
    "ga",
    "he",
    "hi",
    "hr",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "lt",
    "lv",
    "ms",
    "nb",
    "nl",
    "no",
    "pl",
    "pt",
    "ro",
    "ru",
    "sk",
    "sl",
    "sr",
    "sv",
    "th",
    "tr",
    "uk",
    "vi",
    "zh",
}
SHORTCODE_PATTERN = re.compile(r"\{\{[<%].*?[>%]\}\}", re.DOTALL)
INLINE_CODE_PATTERN = re.compile(r"`[^`\n]+`")
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_TAG_PATTERN = re.compile(r"</?[A-Za-z][^>]*>")
URL_PATTERN = re.compile(r"https?://[^\s)\"']+")
ANCHOR_PATTERN = re.compile(r"#[A-Za-z0-9][A-Za-z0-9_-]+")
FILE_PATH_PATTERN = re.compile(
    r"(?<!\w)(?:\.{1,2}[\\/])?[\w.+#-]+(?:[\\/][\w.+#-]+)+\.[A-Za-z0-9]{1,8}\b"
)
FENCED_CODE_PATTERN = re.compile(r"```[^\n`]*\n.*?```", re.DOTALL)
API_IDENTIFIER_PATTERN = re.compile(
    # Use (?<![a-zA-Z0-9_]) instead of \b so that Arabic/RTL conjunctions (e.g. وGltfExporter)
    # don't prevent matching — Arabic letters are \w in Python Unicode regex, so \b fails there.
    r"(?<![a-zA-Z0-9_])(?:[A-Z][A-Za-z0-9_]*\.)+[A-Z][A-Za-z0-9_]*(?![a-zA-Z0-9_])"
    r"|(?<![a-zA-Z0-9_])I[A-Z][A-Za-z0-9_]{2,}(?![a-zA-Z0-9_])"
    r"|(?<![a-zA-Z0-9_])[A-Z][a-zA-Z0-9_]+(?:Exception|Options|Builder|Factory|Collection|Renderer|Exporter|Importer|Constants)(?![a-zA-Z0-9_])"
)
REFERENCE_IDENTIFIER_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9_]*(?:\.[A-Z][A-Za-z0-9_]*)*$")
LANGUAGE_MIXING_FAILURE_TYPES = {
    "REJECT_LANGUAGE_PURITY",
    "REJECT_MIXED_LANGUAGE",
    "REJECT_WRONG_LANGUAGE",
    "REJECT_PARTIAL_TRANSLATION",
}


@dataclass(frozen=True)
class WorkItem:
    work_item_id: str
    source_path: str
    target_path: str
    locale: str
    relative_path: str
    source_hash: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def runtime_device_metadata(requested_device: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "device_requested": requested_device,
        "device_actual_inferred": "unknown",
        "cuda_available": None,
        "cuda_device_name": None,
        "inference_backend": "src.cli",
    }
    try:
        import torch  # type: ignore
    except Exception as exc:
        metadata["device_probe_error"] = repr(exc)
        metadata["device_actual_inferred"] = "cpu" if requested_device in {"auto", "cpu"} else "unknown"
        return metadata
    try:
        cuda_available = bool(torch.cuda.is_available())
        metadata["cuda_available"] = cuda_available
        if cuda_available:
            metadata["cuda_device_name"] = torch.cuda.get_device_name(0)
        if requested_device == "cuda":
            metadata["device_actual_inferred"] = "cuda" if cuda_available else "unavailable_cuda_requested"
        elif requested_device == "auto":
            metadata["device_actual_inferred"] = "cuda" if cuda_available else "cpu"
        else:
            metadata["device_actual_inferred"] = "cpu"
    except Exception as exc:
        metadata["device_probe_error"] = repr(exc)
    return metadata


def is_file_based_source(path: Path) -> bool:
    parts = path.stem.rsplit(".", 1)
    return not (len(parts) == 2 and parts[1].lower() in ALL_LANG_CODES)


def output_path_for(profile, root: Path, source: Path, locale: str) -> tuple[Path, str]:
    output_layout = getattr(profile, "output_layout", None)
    per_language_folders = bool(getattr(output_layout, "per_language_folders", True))
    if per_language_folders:
        en_root = root / profile.default_source_lang
        rel = source.relative_to(en_root).as_posix()
        return root / locale / rel, rel
    pattern = getattr(output_layout, "pattern", "{filename}.{lang}{ext}")
    rel_parent = source.parent.relative_to(root)
    target_name = pattern.format(
        filename=source.stem,
        lang=locale,
        ext=source.suffix,
        path=source.name,
    )
    rel = (rel_parent / source.name).as_posix() if str(rel_parent) != "." else source.name
    return source.parent / target_name, rel


def validate_target_path(profile, content_root: Path, target: Path, locale: str) -> None:
    output_layout = getattr(profile, "output_layout", None)
    per_language_folders = bool(getattr(output_layout, "per_language_folders", True))
    resolved_root = content_root.resolve()
    resolved_target = target.resolve()
    if per_language_folders:
        locale_root = (content_root / locale).resolve()
        if resolved_target != locale_root and locale_root not in resolved_target.parents:
            raise ValueError(
                f"Target path for locale {locale} must be under {locale_root}: {resolved_target}"
            )
        return
    suffix = f".{locale}{target.suffix}"
    if not target.name.endswith(suffix):
        raise ValueError(
            f"File-layout target for locale {locale} must end with {suffix}: {target.name}"
        )
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise ValueError(
            f"File-layout target must stay under content root {resolved_root}: {resolved_target}"
        )


def target_path_collisions(items: list[WorkItem]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for item in items:
        key = str(Path(item.target_path).resolve()).lower()
        seen.setdefault(key, []).append(item.work_item_id)
    return {path: ids for path, ids in seen.items() if len(ids) > 1}


def build_inventory_for_site(profile, content_root: Path, locales: list[str]) -> list[WorkItem]:
    output_layout = getattr(profile, "output_layout", None)
    per_language_folders = bool(getattr(output_layout, "per_language_folders", True))
    if per_language_folders:
        source_root = content_root / profile.default_source_lang
        sources = sorted(source_root.rglob("*.md"), key=lambda p: p.relative_to(source_root).as_posix())
    else:
        sources = sorted(
            [path for path in content_root.rglob("*.md") if is_file_based_source(path)],
            key=lambda p: p.relative_to(content_root).as_posix(),
        )

    items: list[WorkItem] = []
    for source in sources:
        source_hash = sha256_file(source)
        for locale in locales:
            target, rel = output_path_for(profile, content_root, source, locale)
            validate_target_path(profile, content_root, target, locale)
            item_id = hashlib.sha256(
                f"{profile.site_id}:{rel}:{locale}:{source_hash}".encode("utf-8")
            ).hexdigest()[:16]
            items.append(
                WorkItem(
                    work_item_id=item_id,
                    source_path=str(source),
                    target_path=str(target),
                    locale=locale,
                    relative_path=rel,
                    source_hash=source_hash,
                )
            )
    collisions = target_path_collisions(items)
    if collisions:
        preview = ", ".join(sorted(collisions)[:5])
        raise ValueError(f"Duplicate target path collision(s) detected: {preview}")
    return items


def estimated_item_size(item: WorkItem) -> int:
    try:
        return Path(item.source_path).stat().st_size
    except OSError:
        return 0


def size_bucket(item: WorkItem) -> str:
    size = estimated_item_size(item)
    if size < 2_000:
        return "short"
    if size < 10_000:
        return "medium"
    return "long"


def sort_items_for_work_order(
    items: list[WorkItem],
    failed: dict[str, Any],
    accepted: dict[str, Any],
    failed_first: bool,
    work_order: str,
) -> list[WorkItem]:
    failed_ids = set(failed)

    def base_key(item: WorkItem) -> tuple[int, int, str, str]:
        return (
            0 if failed_first and item.work_item_id in failed_ids else 1,
            int((failed.get(item.work_item_id) or {}).get("attempt_count", 0))
            if item.work_item_id in failed_ids
            else 0,
            item.locale,
            item.relative_path,
        )

    def failed_priority(item: WorkItem) -> tuple[int, int]:
        return (
            0 if failed_first and item.work_item_id in failed_ids else 1,
            int((failed.get(item.work_item_id) or {}).get("attempt_count", 0))
            if item.work_item_id in failed_ids
            else 0,
        )

    if work_order == "short-first":
        return sorted(
            items,
            key=lambda item: (*failed_priority(item), estimated_item_size(item), item.locale, item.relative_path),
        )
    if work_order != "balanced":
        return sorted(items, key=base_key)

    ordered = sorted(items, key=lambda item: (*base_key(item), estimated_item_size(item)))
    buckets = {"short": [], "medium": [], "long": []}
    for item in ordered:
        buckets[size_bucket(item)].append(item)
    balanced: list[WorkItem] = []
    while any(buckets.values()):
        for bucket_name in ("short", "medium", "long"):
            if buckets[bucket_name]:
                balanced.append(buckets[bucket_name].pop(0))
    return balanced


def count_failure_types(checkpoint: dict[str, Any], scoped_ids: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item_id, failure in (checkpoint.get("failed") or {}).items():
        if item_id not in scoped_ids or not isinstance(failure, dict):
            continue
        failure_type = str(failure.get("failure_type", "UNKNOWN"))
        counts[failure_type] = counts.get(failure_type, 0) + 1
    return counts


def source_hash_snapshot(profile, content_root: Path) -> dict[str, str]:
    output_layout = getattr(profile, "output_layout", None)
    per_language_folders = bool(getattr(output_layout, "per_language_folders", True))
    if per_language_folders:
        source_root = content_root / profile.default_source_lang
        files = sorted(source_root.rglob("*.md"))
    else:
        files = sorted(path for path in content_root.rglob("*.md") if is_file_based_source(path))
    return {
        str(path.relative_to(content_root)).replace("\\", "/"): sha256_file(path)
        for path in files
    }


_INLINE_CODE_IN_BODY_RE = re.compile(r"`([^`\n]{1,80})`")
_FRONTMATTER_BLOCK_RE = re.compile(r"^\ufeff?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)


def _body_of(text: str) -> tuple[str, int]:
    m = _FRONTMATTER_BLOCK_RE.match(text)
    return (text[m.end():], m.end()) if m else (text, 0)


def restore_body_paragraphs_with_missing_codes(source_text: str, target_text: str) -> str:
    """Restore prose paragraphs dropped by NLLB that contain inline API-name codes.

    When NLLB encounters paragraphs with dense inline-code patterns like
    `` `FVector2`/`FVector3`/`FVector4` `` it sometimes drops the entire paragraph,
    leaving those inline codes missing from the target and causing
    REJECT_IMMUTABLE_TOKEN_CHANGED.

    Strategy: find inline codes in source body missing from target body; if they
    appear in a prose paragraph (not heading/list/table/code-block), copy that
    paragraph verbatim from source into the target after the first section heading.
    """
    src_body, _ = _body_of(source_text)
    tgt_body, tgt_body_start = _body_of(target_text)

    src_codes = set(_INLINE_CODE_IN_BODY_RE.findall(src_body))
    tgt_codes = set(_INLINE_CODE_IN_BODY_RE.findall(tgt_body))
    # Also track plain-text API identifiers (e.g. BaseCollection dropped from overview)
    src_api = set(API_IDENTIFIER_PATTERN.findall(src_body))
    tgt_api = set(API_IDENTIFIER_PATTERN.findall(tgt_body))
    missing_codes = (src_codes - tgt_codes) | (src_api - tgt_api)
    if not missing_codes:
        return target_text

    # Collect source paragraphs that contain missing inline codes and look like prose
    paragraphs = re.split(r"\n\n+", src_body)
    paras_to_restore: list[str] = []
    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        # Skip non-prose blocks: headings, lists, tables, code fences, blockquotes,
        # and bold-label-inline-code lines (handled by restore_body_bold_label_inline_codes)
        first_line = stripped.split("\n")[0]
        if first_line.startswith(("#", "-", "|", "```", ">")):
            continue
        if _BOLD_LABEL_CODE_RE.match(first_line):
            continue
        para_codes = set(_INLINE_CODE_IN_BODY_RE.findall(stripped)) | set(API_IDENTIFIER_PATTERN.findall(stripped))
        if (para_codes & missing_codes) and looks_like_prose(stripped):
            paras_to_restore.append(stripped)

    if not paras_to_restore:
        return target_text

    # Insert after the first ## heading in target body (or at the start)
    result_body = tgt_body
    heading_m = re.search(r"^##[^#][^\n]*\n", result_body, re.MULTILINE)
    insert_pos = heading_m.end() if heading_m else 0
    insert_text = "\n" + "\n\n".join(paras_to_restore) + "\n\n"
    result_body = result_body[:insert_pos] + insert_text + result_body[insert_pos:]

    return target_text[:tgt_body_start] + result_body


def restore_mutated_inline_codes(source_text: str, target_text: str) -> str:
    """Replace inline codes mutated by NLLB (spaces inserted, capitalisation changed).

    Examples of NLLB mutations:
    - ``</extLst>`` → ``</ext Lst >``  (spaces inserted)
    - ``presentation.xml`` → ``presentation.Xml``  (capitalisation)

    Strategy: super-normalise every code by stripping whitespace and lowercasing.
    When a source code is absent from the target but there is a target code whose
    super-normalised form matches, replace the target version with the source
    original.
    """

    def body_of(text: str) -> tuple[str, int]:
        m = _FRONTMATTER_BLOCK_RE.match(text)
        return (text[m.end():], m.end()) if m else (text, 0)

    src_body, _ = body_of(source_text)
    tgt_body, tgt_body_start = body_of(target_text)

    def super_norm(s: str) -> str:
        return re.sub(r"\s+", "", s).lower()

    src_codes = INLINE_CODE_PATTERN.findall(src_body)
    tgt_codes = INLINE_CODE_PATTERN.findall(tgt_body)

    src_by_norm = {super_norm(c): c for c in src_codes}
    tgt_by_norm: dict[str, str] = {}
    for c in tgt_codes:
        n = super_norm(c)
        if n not in tgt_by_norm:
            tgt_by_norm[n] = c

    # Norms present in both source and target but with different actual codes → mutation
    common_norms = set(src_by_norm) & set(tgt_by_norm)
    to_repair = {n for n in common_norms if src_by_norm[n] != tgt_by_norm[n]}

    if not to_repair:
        return target_text

    result_body = tgt_body
    changed = False
    for norm in to_repair:
        tgt_code = tgt_by_norm[norm]
        src_code = src_by_norm[norm]
        result_body = result_body.replace(tgt_code, src_code)
        changed = True

    if not changed:
        return target_text
    return target_text[:tgt_body_start] + result_body


_TABLE_CELL_PSEUDO_CODE_RE = re.compile(r"^`\s*\|.*\|\s*`$", re.DOTALL)


_XML_NAMESPACE_TAG_RE = re.compile(r"^</?[A-Za-z][A-Za-z0-9]*:[^>]*>$")


def immutable_tokens(text: str, site_id: str) -> dict[str, list[str]]:
    # Filter out cross-cell pseudo-codes: `` `| Read |` `` artifacts from malformed table rows
    # where a backtick accidentally spans two table cell boundaries.
    inline_codes = [c for c in INLINE_CODE_PATTERN.findall(text)
                    if not _TABLE_CELL_PSEUDO_CODE_RE.match(c)]
    # Filter out XML namespace tags (e.g. <a:tbl>, <p:grpSpPr>) from html_tags.
    # These appear inside Java-style {@code <ns:tag>} doc comments and are not
    # standalone HTML — NLLB may legitimately translate or drop the surrounding
    # {@code ...} context.
    html_tags = [t for t in HTML_TAG_PATTERN.findall(text)
                 if not _XML_NAMESPACE_TAG_RE.match(t)]
    tokens = {
        "shortcodes": SHORTCODE_PATTERN.findall(text),
        "inline_code": inline_codes,
        "markdown_link_destinations": MARKDOWN_LINK_PATTERN.findall(text),
        "html_tags": html_tags,
        "urls": URL_PATTERN.findall(text),
        "anchors": ANCHOR_PATTERN.findall(text),
        "file_paths": FILE_PATH_PATTERN.findall(text),
    }
    if site_id == "reference.aspose.org":
        tokens["api_identifiers"] = API_IDENTIFIER_PATTERN.findall(text)
    return tokens


def _normalize_inline_code(token: str) -> str:
    """Normalize inline code for comparison: strip/collapse whitespace, unescape pipe chars.

    NLLB and markdown table formatting introduce cosmetic whitespace differences:
    (a) strips leading/trailing spaces inside backtick spans,
    (b) table-column padding adds extra internal spaces (e.g. '| Read   |' vs '| Read |'),
    (c) drops the markdown table-cell escape \\| to |.
    All are cosmetically equivalent so we normalise before comparing.
    """
    if len(token) >= 2 and token[0] == "`" and token[-1] == "`":
        inner = token[1:-1].strip()
        inner = re.sub(r" +", " ", inner)  # collapse multiple spaces to single
        inner = inner.replace("\\|", "|")
        return "`" + inner + "`"
    return token


def token_differences(source_text: str, target_text: str, site_id: str) -> list[dict[str, Any]]:
    source_tokens = immutable_tokens(markdown_body_for_token_scan(source_text), site_id)
    target_tokens = immutable_tokens(markdown_body_for_token_scan(target_text), site_id)
    diffs = []
    for kind, values in source_tokens.items():
        if kind == "inline_code":
            src_set = {_normalize_inline_code(v) for v in values}
            tgt_set = {_normalize_inline_code(v) for v in target_tokens.get(kind, [])}
        elif kind == "file_paths":
            # Compare file paths case-insensitively: NLLB sometimes capitalises path
            # components (e.g. presentation.xml → presentation.Xml).
            src_set = {v.lower() for v in values}
            tgt_set = {v.lower() for v in target_tokens.get(kind, [])}
        elif kind == "html_tags":
            # Compare HTML tags with spaces removed and lowercased:
            # NLLB sometimes inserts spaces inside tags (</extLst> → </ext Lst >).
            src_set = {re.sub(r"\s+", "", v).lower() for v in values}
            tgt_set = {re.sub(r"\s+", "", v).lower() for v in target_tokens.get(kind, [])}
        else:
            src_set = set(values)
            tgt_set = set(target_tokens.get(kind, []))
        missing = sorted(src_set - tgt_set)
        extra = sorted(tgt_set - src_set)
        if missing or extra:
            diffs.append(
                {
                    "kind": kind,
                    "missing_from_target": missing[:50],
                    "extra_in_target": extra[:50],
                    "source_count": len(values),
                    "target_count": len(target_tokens.get(kind, [])),
                }
            )
    return diffs


def markdown_body_for_token_scan(text: str) -> str:
    match = re.match(r"^\ufeff?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if not match:
        return text
    return text[match.end():]


def verify_pair(profile, parser_obj: HugoParser, source: Path, target: Path, locale: str) -> dict[str, Any]:
    comparison = products_verify_pair(profile, parser_obj, source, target, locale)
    comparison = allow_profile_translatable_nested_paths(profile, comparison)
    if comparison["verdict"] != "VERIFIED_ACCEPT":
        return comparison | {"verifier_policy_version": VERIFIER_POLICY_VERSION}
    source_text = source.read_text(encoding="utf-8", errors="replace")
    target_text = target.read_text(encoding="utf-8", errors="replace")
    token_diffs = token_differences(source_text, target_text, profile.site_id)
    comparison["immutable_token_differences"] = token_diffs
    reference_title_diffs = reference_identifier_title_differences(
        profile, parser_obj, source, target
    )
    comparison["reference_identifier_title_differences"] = reference_title_diffs
    comparison["verifier_policy_version"] = VERIFIER_POLICY_VERSION
    placeholder_leaks = _detect_placeholder_leakage(target_text)
    comparison["placeholder_leakage"] = placeholder_leaks
    if token_diffs:
        comparison["verdict"] = "REJECT_IMMUTABLE_TOKEN_CHANGED"
    elif reference_title_diffs:
        comparison["verdict"] = "REJECT_REFERENCE_IDENTIFIER_TITLE_CHANGED"
    elif placeholder_leaks:
        comparison["verdict"] = "REJECT_PLACEHOLDER_LEAKAGE"
    return comparison


_PLACEHOLDER_LEAK_RE = re.compile(
    r"\{PLACEHOLDER_\d+\}"                           # unreplaced {PLACEHOLDER_N}
    r"|\{[A-Z_]{4,}\d*\}"                           # unreplaced {UPPERCASE_TOKEN}
    r"|\{\\?pos\s+\([^)]+\)\s*\}"                   # subtitle pos tags {\pos (x,y)}
    r"|\{[\u0600-\u06FF\u064B-\u065F\u0670]{2,}\}"  # Arabic text inside {} (corrupted)
    r"|\(\u0645[\u064B-\u065F]?\u062D\u0645[\u064B-\u065F]?\u0644\u0629\s+\u0645\u0643\u0627\u0646\)",  # (مُحملة مكان) NLLB placeholder artifact
    re.UNICODE,
)


def _detect_placeholder_leakage(target_text: str) -> list[str]:
    """Detect untranslated placeholder tokens or corrupted placeholders in translated text."""
    body_start = target_text.find("\n---\n", target_text.find("---"))
    body = target_text[body_start:] if body_start != -1 else target_text
    matches = _PLACEHOLDER_LEAK_RE.findall(body)
    return list(dict.fromkeys(matches))  # deduplicated


def reference_identifier_title_differences(
    profile, parser_obj: HugoParser, source: Path, target: Path
) -> list[dict[str, Any]]:
    if profile.site_id != "reference.aspose.org":
        return []
    source_doc = parse_doc(parser_obj, source)
    target_doc = parse_doc(parser_obj, target)
    diffs = []
    for path in ("title", "linkTitle"):
        src_value = get_path_value(source_doc.frontmatter, path)
        tgt_value = get_path_value(target_doc.frontmatter, path)
        if (
            isinstance(src_value, str)
            and REFERENCE_IDENTIFIER_PATTERN.fullmatch(src_value)
            and tgt_value != src_value
        ):
            diffs.append({"path": path, "source": src_value, "target": tgt_value})
    return diffs


def allow_profile_translatable_nested_paths(profile, comparison: dict[str, Any]) -> dict[str, Any]:
    protected = comparison.get("protected_path_differences") or []
    if not protected:
        return comparison
    allowed_roots = {
        key for key, rule in profile.frontmatter.items() if rule.mode == FrontmatterMode.TRANSLATE
    }
    frontmatter_translation = getattr(profile, "frontmatter_translation", None)
    configured = getattr(frontmatter_translation, "translatable_fields", None)
    if configured:
        allowed_roots.update(configured)

    def root_key(path: str) -> str:
        return re.split(r"[.\[]", path, maxsplit=1)[0]

    filtered = [diff for diff in protected if root_key(str(diff.get("path", ""))) not in allowed_roots]
    if len(filtered) == len(protected):
        return comparison
    comparison = dict(comparison)
    comparison["protected_path_differences"] = filtered
    if comparison.get("verdict") == "REJECT_PROTECTED_FIELD_CHANGED" and not filtered:
        comparison["verdict"] = recompute_verdict_from_comparison(comparison)
    return comparison


def recompute_verdict_from_comparison(comparison: dict[str, Any]) -> str:
    if (
        comparison.get("missing_key_paths")
        or comparison.get("extra_key_paths")
        or comparison.get("type_differences")
        or comparison.get("list_length_differences")
    ):
        return "REJECT_STRUCTURAL_MISMATCH"
    if comparison.get("code_fence_differences"):
        return "REJECT_CODE_FENCE_MISMATCH"
    if comparison.get("code_block_differences"):
        return "REJECT_CODE_BLOCK_MUTATED"
    if comparison.get("protected_path_differences"):
        return "REJECT_PROTECTED_FIELD_CHANGED"
    if comparison.get("product_identity_differences"):
        return "REJECT_PRODUCT_IDENTITY_CHANGED"
    if comparison.get("reference_identifier_title_differences"):
        return "REJECT_REFERENCE_IDENTIFIER_TITLE_CHANGED"
    if comparison.get("repetition_issues"):
        return "REJECT_REPETITION"
    if comparison.get("english_residue_translatable_paths") or comparison.get("untranslated_translatable_paths"):
        return "REJECT_PARTIAL_TRANSLATION"
    return "VERIFIED_ACCEPT"


def policy_document(profile, content_root: Path, locales: list[str]) -> dict[str, Any]:
    return {
        "verifier_policy_version": VERIFIER_POLICY_VERSION,
        "site_id": profile.site_id,
        "source_locale": profile.default_source_lang,
        "source_root": str(content_root),
        "target_locales": locales,
        "frontmatter_rules": {
            key: getattr(rule.mode, "value", str(rule.mode)) for key, rule in profile.frontmatter.items()
        },
        "translatable_keys": [
            key for key, rule in profile.frontmatter.items() if rule.mode == FrontmatterMode.TRANSLATE
        ],
        "protected_keys": [
            key for key, rule in profile.frontmatter.items() if rule.mode == FrontmatterMode.PASSTHROUGH
        ],
        "immutable_token_checks": [
            "shortcodes",
            "inline_code",
            "markdown_links",
            "html_tags",
            "urls",
            "anchors",
            "file_paths",
            "api_identifiers_for_reference",
        ],
        "unknown_field_policy": "implicit_protected_copy_through",
    }


def build_translate_cmd(args, item: WorkItem, log_path: Path) -> list[str]:
    cmd = [
        str(args.python),
        "-m",
        "src.cli",
        "--site",
        args.site,
        "--input",
        item.source_path,
        "--target-langs",
        item.locale,
        "--force-retranslate",
        "--force-restart",
        "--no-commit",
        "--disable-validation",
        "--force-accept",
        "--model",
        args.model,
        "--max-files",
        "0",
        "--log-level",
        "INFO",
        "--metrics-file",
        str(log_path.with_suffix(".metrics")),
    ]
    if args.device:
        cmd.extend(["--device", args.device])
    if getattr(args, "model_batch_size", 0):
        cmd.extend(["--batch-size", str(args.model_batch_size)])
    return cmd


def run_translate(args, item: WorkItem, log_path: Path) -> subprocess.CompletedProcess[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_translate_cmd(args, item, log_path)
    with log_path.open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=args.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            log.write(f"\nTranslation timed out after {args.timeout_seconds} seconds\n")
            return subprocess.CompletedProcess(cmd, 124)

    # CPU fallback: NLLB's CTranslate2 CUDA backend can crash with Windows structured
    # exceptions (access violation, guard page, stack overrun) on certain inputs or when
    # GPU memory is fragmented.  Retry on CPU which has no such constraints.
    if result.returncode in _CUDA_CRASH_CODES and getattr(args, "device", "cuda") == "cuda":
        log_path_cpu = log_path.with_name(log_path.stem + ".cpu.log")
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                f"\n[cpu-fallback] CUDA crash (exit={result.returncode:#010x}), retrying on CPU\n"
            )
        cpu_args = copy.copy(args)
        cpu_args.device = "cpu"
        cmd_cpu = build_translate_cmd(cpu_args, item, log_path_cpu)
        log_path_cpu.parent.mkdir(parents=True, exist_ok=True)
        with log_path_cpu.open("w", encoding="utf-8") as cpu_log:
            try:
                result = subprocess.run(
                    cmd_cpu,
                    cwd=ROOT,
                    text=True,
                    stdout=cpu_log,
                    stderr=subprocess.STDOUT,
                    timeout=args.timeout_seconds * 3,  # CPU is ~3× slower
                )
            except subprocess.TimeoutExpired:
                cpu_log.write(f"\nCPU fallback timed out\n")
                result = subprocess.CompletedProcess(cmd_cpu, 124)

    return result


def repair_target(profile, parser_obj: HugoParser, source: Path, target: Path) -> dict[str, Any]:
    repairs = {
        "material_copy": repair_target_material_copy_fields(profile, parser_obj, source, target),
        "product_identity": repair_target_product_identities(parser_obj, source, target),
        "code_blocks": repair_target_code_blocks(profile, parser_obj, source, target),
        "reference_identifier_titles": repair_reference_identifier_titles(
            profile, parser_obj, source, target
        ),
    }
    if target.exists():
        before = target.read_text(encoding="utf-8", errors="replace")
        after = repair_extra_code_blocks_with_source_order(
            source.read_text(encoding="utf-8", errors="replace"), before
        )
        if after != before:
            target.write_text(after, encoding="utf-8")
            repairs["extra_code_block_order"] = {"changed": True}
            before = after
        after = restore_body_code_blocks_exact(
            source.read_text(encoding="utf-8", errors="replace"), before
        )
        if after != before:
            target.write_text(after, encoding="utf-8")
            repairs["body_code_blocks_exact"] = {"changed": True}
            before = after
        after = restore_body_bold_label_inline_codes(
            source.read_text(encoding="utf-8", errors="replace"), before
        )
        if after != before:
            target.write_text(after, encoding="utf-8")
            repairs["body_bold_label_inline_codes"] = {"changed": True}
            before = after
        after = restore_body_dropped_link_list_items(
            source.read_text(encoding="utf-8", errors="replace"), before
        )
        if after != before:
            target.write_text(after, encoding="utf-8")
            repairs["body_dropped_link_list_items"] = {"changed": True}
            before = after
        after = restore_spurious_table_code_fences(
            source.read_text(encoding="utf-8", errors="replace"), before
        )
        if after != before:
            target.write_text(after, encoding="utf-8")
            repairs["spurious_table_code_fences"] = {"changed": True}
            before = after
        after = restore_body_paragraphs_with_missing_codes(
            source.read_text(encoding="utf-8", errors="replace"), before
        )
        if after != before:
            target.write_text(after, encoding="utf-8")
            repairs["body_paragraphs_with_missing_codes"] = {"changed": True}
            before = after
        after = restore_mutated_inline_codes(
            source.read_text(encoding="utf-8", errors="replace"), before
        )
        if after != before:
            target.write_text(after, encoding="utf-8")
            repairs["mutated_inline_codes"] = {"changed": True}
    repairs["changed"] = any(
        bool(value.get("changed")) for value in repairs.values() if isinstance(value, dict)
    )
    return repairs


def repair_reference_identifier_titles(
    profile, parser_obj: HugoParser, source: Path, target: Path
) -> dict[str, Any]:
    if profile.site_id != "reference.aspose.org" or not target.exists():
        return {"changed": False, "repairs": []}
    source_doc = parse_doc(parser_obj, source)
    module = __import__(
        "scripts.quality.products_org_governed_retranslate",
        fromlist=["load_target_frontmatter", "write_target_frontmatter"],
    )
    loaded = module.load_target_frontmatter(target)
    if loaded is None:
        return {"changed": False, "repairs": [], "reason": "missing_frontmatter"}
    target_frontmatter, target_body = loaded
    repairs = []
    for path in ("title", "linkTitle"):
        src_value = get_path_value(source_doc.frontmatter, path)
        tgt_value = get_path_value(target_frontmatter, path)
        if (
            isinstance(src_value, str)
            and REFERENCE_IDENTIFIER_PATTERN.fullmatch(src_value)
            and tgt_value != src_value
            and set_path_value(target_frontmatter, path, src_value)
        ):
            repairs.append({"path": path, "reason": "reference_identifier_title_restored"})
    if not repairs:
        return {"changed": False, "repairs": []}
    module.write_target_frontmatter(target, target_frontmatter, target_body)
    return {"changed": True, "repairs": repairs}


def restore_body_code_blocks_exact(source_text: str, target_text: str) -> str:
    source_blocks = FENCED_CODE_PATTERN.findall(source_text)
    target_blocks = FENCED_CODE_PATTERN.findall(target_text)
    if not source_blocks or len(source_blocks) != len(target_blocks):
        return target_text
    iterator = iter(source_blocks)
    return FENCED_CODE_PATTERN.sub(lambda _match: next(iterator), target_text)


# Matches "**Label**: `code`" lines in markdown body (Python reference page "Package" etc.)
_BOLD_LABEL_CODE_RE = re.compile(r"^\*\*[^*]+\*\*:\s+`[^`]+`\s*$", re.MULTILINE)
# Line that starts a bold-label section but has no inline code, or has mutated inline code
_BOLD_LABEL_ANY_RE = re.compile(r"^\*\*[^*]+\*\*:\s*", re.MULTILINE)


def restore_body_bold_label_inline_codes(source_text: str, target_text: str) -> str:
    """Restore bold-label lines that NLLB mutated or dropped inline code from.

    Pattern: ``**Label**: `value` `` — e.g. ``**Package**: `aspose.threed` ``.
    NLLB sometimes:
      - Drops bold markers: ``**Package**`` → ``Package``
      - Mutates the inline code content: `` `aspose.threed` `` → `` `til form—l` ``
      - Drops the inline code entirely

    Since these lines are non-translatable metadata, we restore the full source line
    at the matching position in the target.
    """
    src_lines = [m.group(0).rstrip() for m in _BOLD_LABEL_CODE_RE.finditer(source_text)]
    if not src_lines:
        return target_text

    # Check if target already has all source bold-label-code lines verbatim
    already_present = all(sl in target_text for sl in src_lines)
    if already_present:
        return target_text

    # Find positions of bold-label-code lines in source and corresponding lines in target
    source_all_lines = source_text.splitlines(keepends=True)
    target_all_lines = target_text.splitlines(keepends=True)

    # Map source line index → source bold-label-code line for each occurrence
    src_bold_positions = [
        i for i, l in enumerate(source_all_lines)
        if _BOLD_LABEL_CODE_RE.match(l.rstrip("\n\r"))
    ]
    if not src_bold_positions:
        return target_text

    # For each source bold-label-code line, find the best matching target line
    # by proximity (same relative position in document)
    src_total = len(source_all_lines)
    tgt_total = len(target_all_lines)
    changed = False

    for src_idx in src_bold_positions:
        src_line_content = source_all_lines[src_idx].rstrip("\n\r")
        # If already verbatim in target at this position, skip
        tgt_idx = round(src_idx * tgt_total / src_total) if src_total else src_idx
        tgt_idx = max(0, min(tgt_idx, tgt_total - 1))

        # Search ±5 lines for a line that starts a bold-label or plain-label
        search_window = range(max(0, tgt_idx - 5), min(tgt_total, tgt_idx + 6))
        best = None
        for ti in search_window:
            tl = target_all_lines[ti].rstrip("\n\r")
            if _BOLD_LABEL_ANY_RE.match(tl) or re.match(r"^\w[\w ]+:\s*", tl):
                best = ti
                break

        if best is not None and target_all_lines[best].rstrip("\n\r") != src_line_content:
            nl = "\n" if target_all_lines[best].endswith("\n") else ""
            target_all_lines[best] = src_line_content + nl
            changed = True

    return "".join(target_all_lines) if changed else target_text


_LINK_LIST_ITEM_RE = re.compile(r"^- \[.*?\]\((/[^)]+)\)\s*$", re.MULTILINE)


def restore_body_dropped_link_list_items(source_text: str, target_text: str) -> str:
    """Restore markdown list-item links that NLLB dropped from the target body.

    NLLB sometimes omits entire list items that contain internal markdown links,
    e.g. ``- [Aspose.3D Python API Reference home](/3d/python/)``.
    We detect missing link destinations and append the corresponding source lines.
    """
    src_items = {m.group(1): m.group(0).rstrip() for m in _LINK_LIST_ITEM_RE.finditer(source_text)}
    if not src_items:
        return target_text

    tgt_destinations = set(m.group(1) for m in _LINK_LIST_ITEM_RE.finditer(target_text))
    missing = {dest: line for dest, line in src_items.items() if dest not in tgt_destinations}
    if not missing:
        return target_text

    # Append missing list items after the last "---" separator or at end of body
    separator_pos = target_text.rfind("\n---\n")
    if separator_pos != -1:
        insert_after = separator_pos + 4  # after "\n---\n"
        append_block = "\n".join(missing.values())
        return target_text[:insert_after] + "\n" + append_block + "\n" + target_text[insert_after:]
    else:
        append_block = "\n".join(missing.values())
        return target_text.rstrip("\n") + "\n\n" + append_block + "\n"


_FENCE_OPEN_RE = re.compile(r"^```[^\n`]*$", re.MULTILINE)
_FENCE_CLOSE_RE = re.compile(r"^```\s*$", re.MULTILINE)


def restore_spurious_table_code_fences(source_text: str, target_text: str) -> str:
    """Remove code fences that NLLB spuriously inserts in the translated body.

    Two patterns handled:

    1. Table-adjacent fences: source table cell contains a multi-line TypeScript/JSON
       type (e.g. ```: {\n    foo?: number;\n}```) → NLLB wraps it in ``` fences.
       Strategy: remove fences where the preceding non-empty line is a table row.

    2. Hallucinated import blocks: NLLB adds a ``python / from module import X `` block
       that has no counterpart in the source.  When source body has 0 code fences, ALL
       target fences are NLLB hallucinations — remove the markers and their content.
    """

    def body_of(text: str) -> tuple[str, int]:
        # Find the END of Hugo frontmatter (the closing '---' after the opening one).
        # Use the second '---\n' occurrence (first closes frontmatter); rfind would
        # incorrectly match a horizontal-rule '---' deeper in the markdown body.
        stripped = text.lstrip("\n")
        if stripped.startswith("---"):
            # Skip the opening --- line then find the next ---
            rest_start = text.index("---") + 3
            # Skip any trailing \n/\r after opening ---
            while rest_start < len(text) and text[rest_start] in "\r\n":
                rest_start += 1
            close_pos = text.find("\n---\n", rest_start)
            if close_pos != -1:
                return (text[close_pos + 5 :], close_pos + 5)
        # Fallback: no frontmatter found — treat entire text as body
        return (text, 0)

    src_body, _ = body_of(source_text)
    tgt_body, tgt_body_start = body_of(target_text)

    if src_body.count("```") > 0:
        return target_text  # Source already has fences — not this pattern
    if tgt_body.count("```") == 0:
        return target_text  # Nothing to do

    lines = tgt_body.splitlines(keepends=True)
    result = []
    i = 0
    changed = False
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip("\r\n")
        if _FENCE_OPEN_RE.match(stripped):
            # Check if the previous non-empty line is a table row
            prev_content = ""
            for r in reversed(result):
                rs = r.rstrip("\r\n")
                if rs:
                    prev_content = rs
                    break
            if "|" in prev_content:
                # Pattern 1: table-adjacent spurious fence — keep content, strip markers
                changed = True
                i += 1
                while i < len(lines):
                    cl = lines[i]
                    if _FENCE_CLOSE_RE.match(cl.rstrip("\r\n")):
                        i += 1  # skip closing fence marker too
                        break
                    result.append(cl)
                    i += 1
                continue
            else:
                # Pattern 2: hallucinated non-table fence — drop markers AND content
                changed = True
                i += 1
                while i < len(lines):
                    cl = lines[i]
                    if _FENCE_CLOSE_RE.match(cl.rstrip("\r\n")):
                        i += 1  # skip closing fence marker
                        break
                    i += 1  # drop content too
                continue
        result.append(line)
        i += 1

    if not changed:
        return target_text

    new_body = "".join(result)
    return target_text[:tgt_body_start] + new_body


def write_acceptance(
    evidence_root: Path,
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    item: WorkItem,
    comparison: dict[str, Any],
    policy_hash: str,
    candidate_status: str,
) -> None:
    receipt = {
        "receipt_id": hashlib.sha256(f"{item.work_item_id}:{comparison['target_hash']}".encode()).hexdigest()[:16],
        "queue_id": checkpoint.get("run_id"),
        "work_item_id": item.work_item_id,
        "source_path": item.source_path,
        "target_path": item.target_path,
        "locale": item.locale,
        "source_hash": comparison["source_hash"],
        "target_hash": comparison["target_hash"],
        "config_hash": policy_hash,
        "verifier_policy_version": VERIFIER_POLICY_VERSION,
        "verdict": "VERIFIED_TRANSLATION_ACCEPTED",
        "candidate_status": candidate_status,
        "accepted_at": utc_now(),
    }
    write_json(evidence_root / "per-file" / item.locale / f"{item.work_item_id}.receipt.json", receipt)
    checkpoint.setdefault("accepted", {})[item.work_item_id] = receipt
    checkpoint.setdefault("failed", {}).pop(item.work_item_id, None)
    checkpoint["updated_at"] = utc_now()
    write_json(checkpoint_path, checkpoint)


def write_failure(
    evidence_root: Path,
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    item: WorkItem,
    failure_type: str,
    extra: dict[str, Any] | None = None,
) -> None:
    previous = (checkpoint.get("failed") or {}).get(item.work_item_id, {})
    failure = {
        "failure_id": hashlib.sha256(f"{item.work_item_id}:{failure_type}".encode()).hexdigest()[:16],
        "work_item": asdict(item),
        "failure_type": failure_type,
        "attempt_count": int(previous.get("attempt_count", 0)) + 1 if isinstance(previous, dict) else 1,
        "failed_at": utc_now(),
        "status": "PIPELINE_REPAIR_REQUIRED",
    }
    if extra:
        failure.update(extra)
    checkpoint.setdefault("failed", {})[item.work_item_id] = failure
    checkpoint["updated_at"] = utc_now()
    write_json(evidence_root / "failures" / f"{item.work_item_id}.json", failure)
    write_json(checkpoint_path, checkpoint)


def empty_run_stats() -> dict[str, Any]:
    return {
        "attempted_pairs": 0,
        "accepted_pairs": 0,
        "failed_pairs": 0,
        "failure_type_counts": {},
        "language_mixing_failure_count": 0,
    }


def note_run_accept(stats: dict[str, Any]) -> None:
    stats["accepted_pairs"] = int(stats.get("accepted_pairs", 0) or 0) + 1


def note_run_failure(stats: dict[str, Any], failure_type: str) -> None:
    stats["failed_pairs"] = int(stats.get("failed_pairs", 0) or 0) + 1
    counts = stats.setdefault("failure_type_counts", {})
    counts[failure_type] = int(counts.get(failure_type, 0) or 0) + 1
    if failure_type in LANGUAGE_MIXING_FAILURE_TYPES:
        stats["language_mixing_failure_count"] = (
            int(stats.get("language_mixing_failure_count", 0) or 0) + 1
        )


def select_monitored_samples(items: list[WorkItem], checkpoint: dict[str, Any], sample_size: int) -> list[dict[str, Any]]:
    failed_ids = set((checkpoint.get("failed") or {}).keys())
    accepted_ids = set((checkpoint.get("accepted") or {}).keys())
    ordered = sorted(
        items,
        key=lambda item: (
            0 if item.work_item_id in failed_ids else 1 if item.work_item_id not in accepted_ids else 2,
            category_rank(item.relative_path),
            item.locale,
            item.relative_path,
        ),
    )
    selected: list[WorkItem] = []
    seen_categories: set[str] = set()
    for item in ordered:
        category = classify_sample(item.relative_path)
        if category not in seen_categories:
            selected.append(item)
            seen_categories.add(category)
        if len(selected) >= sample_size:
            break
    for item in ordered:
        if len(selected) >= sample_size:
            break
        if item not in selected:
            selected.append(item)
    return [
        {
            "work_item": asdict(item),
            "sample_category": classify_sample(item.relative_path),
            "checkpoint_status": "failed"
            if item.work_item_id in failed_ids
            else "accepted"
            if item.work_item_id in accepted_ids
            else "unprocessed_or_missing",
        }
        for item in selected
    ]


def select_monitored_sample_items(
    items: list[WorkItem], checkpoint: dict[str, Any], sample_size: int
) -> list[WorkItem]:
    sample_ids = {
        sample["work_item"]["work_item_id"]
        for sample in select_monitored_samples(items, checkpoint, sample_size)
    }
    return [item for item in items if item.work_item_id in sample_ids]


def classify_sample(relative_path: str) -> str:
    lower = relative_path.lower()
    if lower.endswith("_index.md"):
        return "_index"
    if "faq" in lower:
        return "faq"
    if "how-to" in lower:
        return "how-to"
    if "use-case" in lower or "use-cases" in lower:
        return "use-case"
    if "getting-started" in lower:
        return "getting-started"
    if "developer-guide" in lower:
        return "developer-guide"
    if any(part in lower for part in ["enum", "constant"]):
        return "enum-constants"
    if re.search(r"/[A-Z][A-Za-z0-9_]+\.md$", relative_path):
        return "class"
    if lower in {"archive.md", "_index.md", "index.md"}:
        return "root-archive"
    return "general"


def category_rank(relative_path: str) -> str:
    return classify_sample(relative_path) + ":" + relative_path


def normalize_failed_checkpoint(checkpoint: dict[str, Any]) -> None:
    if checkpoint.get("failed") is None:
        checkpoint["failed"] = {}
    elif isinstance(checkpoint.get("failed"), dict) and "work_item" in checkpoint["failed"]:
        previous = checkpoint["failed"]
        previous_id = previous.get("work_item", {}).get("work_item_id")
        checkpoint["failed"] = {previous_id: previous} if previous_id else {}


def reverify_accepted(
    evidence_root: Path,
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    items: list[WorkItem],
    profile,
    parser_obj: HugoParser,
    policy_hash: str,
    dry_run: bool,
    shard_id: str | None = None,
) -> dict[str, Any]:
    item_by_id = {item.work_item_id: item for item in items}
    verdict_counts: dict[str, int] = {}
    quarantined = 0
    checked = 0
    for item_id in list((checkpoint.get("accepted") or {}).keys()):
        item = item_by_id.get(item_id)
        if not item:
            continue
        checked += 1
        try:
            comparison = verify_pair(profile, parser_obj, Path(item.source_path), Path(item.target_path), item.locale)
        except Exception as exc:
            comparison = {"verdict": "VERIFY_EXCEPTION", "exception": repr(exc)}
        verdict_counts[comparison["verdict"]] = verdict_counts.get(comparison["verdict"], 0) + 1
        write_json(evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json", comparison)
        if comparison["verdict"] == "VERIFIED_ACCEPT":
            receipt = checkpoint["accepted"][item_id]
            if (
                receipt.get("config_hash") != policy_hash
                or receipt.get("verifier_policy_version") != VERIFIER_POLICY_VERSION
            ) and not dry_run:
                write_acceptance(
                    evidence_root,
                    checkpoint_path,
                    checkpoint,
                    item,
                    comparison,
                    policy_hash,
                    "accepted_translation_reverified_policy_refresh",
                )
            continue
        quarantined += 1
        if not dry_run:
            previous = checkpoint.setdefault("accepted", {}).pop(item_id, None)
            write_failure(
                evidence_root,
                checkpoint_path,
                checkpoint,
                item,
                comparison["verdict"],
                {"comparison": comparison, "previous_acceptance_receipt": previous},
            )
    report = {
        "run_id": checkpoint.get("run_id"),
        "site_id": profile.site_id,
        "verifier_policy_version": VERIFIER_POLICY_VERSION,
        "policy_hash": policy_hash,
        "dry_run": dry_run,
        "accepted_checked": checked,
        "verdict_counts": verdict_counts,
        "quarantined_accepts": quarantined,
        "accepted_after": len(checkpoint.get("accepted") or {}),
        "failed_after": len(checkpoint.get("failed") or {}),
        "updated_at": utc_now(),
    }
    report_name = f"accepted-reverification.{shard_id}.json" if shard_id else "accepted-reverification.json"
    write_json(evidence_root / "final" / report_name, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True, choices=sorted(SUPPORTED_SITES))
    parser.add_argument("--model", default="m2m100_418m")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--content-root", type=Path)
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--max-work-items", type=int, default=0)
    parser.add_argument("--model-batch-size", type=int, default=0)
    parser.add_argument(
        "--work-order",
        choices=["failed-first", "short-first", "balanced"],
        default="failed-first",
    )
    parser.add_argument("--only-locales")
    parser.add_argument("--shard-id")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--sample-plan", action="store_true")
    parser.add_argument(
        "--sample-only",
        action="store_true",
        help="Process only the monitored sample selection for this site/shard.",
    )
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--reverify-accepted", action="store_true")
    parser.add_argument("--reverify-dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--failed-first", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--device", default="cuda", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--python", type=Path, default=ROOT / ".venv" / "Scripts" / "python.exe")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    config_service = ConfigService(config_root=ROOT / "config")
    profile = config_service.get_site_profile(args.site)
    if profile is None:
        raise SystemExit(f"{args.site} profile not found")

    content_root = args.content_root or Path(os.path.expandvars(profile.content_roots[0]))
    locales = parse_locale_filter(args.only_locales, list(profile.target_langs))
    shard_id = safe_shard_id(args.shard_id)
    if args.only_locales and not shard_id:
        raise SystemExit("--shard-id is required when --only-locales is used")

    evidence_root = ROOT / ".local" / "evidences" / args.site / args.run_id
    checkpoint_dir = evidence_root / "checkpoints"
    checkpoint_path = checkpoint_file(checkpoint_dir, shard_id)
    checkpoint = load_checkpoint(checkpoint_path) if args.resume else {"accepted": {}, "failed": {}}
    checkpoint["run_id"] = args.run_id
    checkpoint["site_id"] = args.site
    normalize_failed_checkpoint(checkpoint)

    items = build_inventory_for_site(profile, content_root, locales)
    if args.max_items:
        items = items[: args.max_items]
    run_started_monotonic = time.monotonic()
    device_metadata = runtime_device_metadata(args.device)
    scoped_ids = {item.work_item_id for item in items}
    if args.resume and shard_id:
        main_checkpoint_path = checkpoint_file(checkpoint_dir, None)
        if main_checkpoint_path.exists():
            overlay_main_checkpoint_for_items(
                checkpoint,
                load_checkpoint(main_checkpoint_path),
                scoped_ids,
            )
            write_json(checkpoint_path, checkpoint)

    policy = policy_document(profile, content_root, locales)
    policy_hash = hashlib.sha256(json.dumps(policy, sort_keys=True).encode("utf-8")).hexdigest()
    write_json(baseline_file(evidence_root / "baseline", "policy", shard_id), policy | {"configuration_hash": policy_hash})
    write_json(baseline_file(evidence_root / "baseline", "inventory", shard_id), [asdict(item) for item in items])
    write_json(baseline_file(evidence_root / "baseline", "source-hashes-before", shard_id), source_hash_snapshot(profile, content_root))

    if args.plan_only:
        report = {
            "run_id": args.run_id,
            "site_id": args.site,
            "planned_pairs": len(items),
            "target_locales": locales,
            "verifier_policy_version": VERIFIER_POLICY_VERSION,
            "policy_hash": policy_hash,
            "device": device_metadata,
            "verdict": "PLAN_ONLY_NO_TRANSLATION_STARTED",
        }
        write_json(summary_file(evidence_root / "final", shard_id), report)
        print(json.dumps(report, indent=2))
        return 0

    parser_obj = HugoParser()
    if args.reverify_accepted:
        report = reverify_accepted(
            evidence_root,
            checkpoint_path,
            checkpoint,
            items,
            profile,
            parser_obj,
            policy_hash,
            args.reverify_dry_run,
            shard_id,
        )
        print(json.dumps(report, indent=2))
        return 0

    accepted = checkpoint.setdefault("accepted", {})
    failed = checkpoint.setdefault("failed", {})
    run_stats = empty_run_stats()
    if args.sample_only:
        items = select_monitored_sample_items(items, checkpoint, args.sample_size)
    if args.max_work_items:
        eligible = []
        for item in items:
            if item.work_item_id in accepted:
                continue
            if item.work_item_id in failed and not args.retry_failed:
                continue
            eligible.append(item)
        eligible = sort_items_for_work_order(
            eligible,
            failed=failed,
            accepted=accepted,
            failed_first=args.failed_first or args.work_order == "failed-first",
            work_order=args.work_order,
        )
        items = eligible[: args.max_work_items]
    else:
        items = sort_items_for_work_order(
            items,
            failed=failed,
            accepted=accepted,
            failed_first=args.failed_first or args.work_order == "failed-first",
            work_order=args.work_order,
        )

    for item in items:
        if item.work_item_id in accepted:
            continue
        if item.work_item_id in failed and not args.retry_failed and not args.validate_only:
            continue
        run_stats["attempted_pairs"] = int(run_stats.get("attempted_pairs", 0) or 0) + 1
        source = Path(item.source_path)
        target = Path(item.target_path)
        write_json(current_file(checkpoint_dir, shard_id), {"work_item": asdict(item), "started_at": utc_now()})

        if args.validate_only and not target.exists():
            write_failure(evidence_root, checkpoint_path, checkpoint, item, "MISSING_TARGET")
            note_run_failure(run_stats, "MISSING_TARGET")
            print(f"SKIP: missing target for {item.locale} {item.relative_path}")
            continue

        if target.exists():
            try:
                repairs = {"changed": False} if args.validate_only else repair_target(profile, parser_obj, source, target)
                if repairs.get("changed"):
                    write_json(evidence_root / "repairs" / item.locale / f"{item.work_item_id}.json", {"work_item": asdict(item), "repairs": repairs, "repaired_at": utc_now()})
                comparison = verify_pair(profile, parser_obj, source, target, item.locale)
                write_json(evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json", comparison)
            except Exception as exc:
                write_failure(evidence_root, checkpoint_path, checkpoint, item, "VERIFY_EXCEPTION", {"exception": repr(exc)})
                note_run_failure(run_stats, "VERIFY_EXCEPTION")
                print(f"SKIP: verification exception for {item.locale} {item.relative_path}")
                continue

            if comparison["verdict"] == "VERIFIED_ACCEPT":
                write_acceptance(
                    evidence_root,
                    checkpoint_path,
                    checkpoint,
                    item,
                    comparison,
                    policy_hash,
                    "existing_translation_verified_validate_only" if args.validate_only else "existing_translation_verified_pre_translate",
                )
                note_run_accept(run_stats)
                print(f"ACCEPT: {item.locale} {item.relative_path}")
                continue

            if args.validate_only:
                write_failure(evidence_root, checkpoint_path, checkpoint, item, comparison["verdict"], {"comparison": comparison})
                note_run_failure(run_stats, comparison["verdict"])
                print(f"FAIL: {item.locale} {item.relative_path}: {comparison['verdict']}")
                continue

        log_path = (evidence_root / "per-file" / item.locale / item.relative_path.replace("/", "__")).with_suffix(".translate.log")
        result = run_translate(args, item, log_path)
        preserved_existing = result.returncode != 0 and target.exists() and is_preserved_existing_translation(log_path)
        if result.returncode != 0 and not preserved_existing:
            write_failure(
                evidence_root,
                checkpoint_path,
                checkpoint,
                item,
                "TRANSLATOR_REJECTED_OR_NO_TARGET",
                {"translator_exit_code": result.returncode, "translator_log": str(log_path)},
            )
            note_run_failure(run_stats, "TRANSLATOR_REJECTED_OR_NO_TARGET")
            print(f"SKIP: translation failed for {item.locale} {item.relative_path}")
            continue
        try:
            repairs = repair_target(profile, parser_obj, source, target)
            if repairs.get("changed"):
                write_json(evidence_root / "repairs" / item.locale / f"{item.work_item_id}.json", {"work_item": asdict(item), "repairs": repairs, "repaired_at": utc_now()})
            comparison = verify_pair(profile, parser_obj, source, target, item.locale)
            write_json(evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json", comparison)
        except Exception as exc:
            write_failure(evidence_root, checkpoint_path, checkpoint, item, "VERIFY_EXCEPTION", {"exception": repr(exc)})
            note_run_failure(run_stats, "VERIFY_EXCEPTION")
            continue
        if comparison["verdict"] == "VERIFIED_ACCEPT":
            write_acceptance(evidence_root, checkpoint_path, checkpoint, item, comparison, policy_hash, "new_translation_written")
            note_run_accept(run_stats)
            print(f"ACCEPT: {item.locale} {item.relative_path}")
        else:
            write_failure(evidence_root, checkpoint_path, checkpoint, item, comparison["verdict"], {"comparison": comparison})
            note_run_failure(run_stats, comparison["verdict"])
            print(f"SKIP: verification failed for {item.locale} {item.relative_path}: {comparison['verdict']}")

    after_hashes = source_hash_snapshot(profile, content_root)
    before_hashes = json.loads(baseline_file(evidence_root / "baseline", "source-hashes-before", shard_id).read_text(encoding="utf-8"))
    source_mutations = {
        path: {"before": before_hashes.get(path), "after": after_hashes.get(path)}
        for path in sorted(set(before_hashes) | set(after_hashes))
        if before_hashes.get(path) != after_hashes.get(path)
    }
    write_json(evidence_root / "final" / "source-mutations.json", source_mutations)
    if args.sample_plan:
        write_json(
            evidence_root / "final" / "monitored-sample-plan.json",
            {
                "site_id": args.site,
                "sample_size": args.sample_size,
                "samples": select_monitored_samples(build_inventory_for_site(profile, content_root, locales), checkpoint, args.sample_size),
                "created_at": utc_now(),
            },
        )
    scoped_ids = {item.work_item_id for item in build_inventory_for_site(profile, content_root, locales)}
    failure_type_counts = count_failure_types(checkpoint, scoped_ids)
    report = {
        "run_id": args.run_id,
        "site_id": args.site,
        "verifier_policy_version": VERIFIER_POLICY_VERSION,
        "policy_hash": policy_hash,
        "required_pairs": len(scoped_ids),
        "accepted_pairs": sum(1 for item_id in checkpoint.get("accepted", {}) if item_id in scoped_ids),
        "failed_pairs": sum(1 for item_id in checkpoint.get("failed", {}) if item_id in scoped_ids),
        "failure_type_counts": failure_type_counts,
        "language_mixing_failure_count": sum(
            count
            for failure_type, count in failure_type_counts.items()
            if failure_type in LANGUAGE_MIXING_FAILURE_TYPES
        ),
        "run_attempted_pairs": run_stats["attempted_pairs"],
        "run_accepted_pairs": run_stats["accepted_pairs"],
        "run_failed_pairs": run_stats["failed_pairs"],
        "run_failure_type_counts": run_stats["failure_type_counts"],
        "run_language_mixing_failure_count": run_stats["language_mixing_failure_count"],
        "work_order": args.work_order,
        "model_batch_size": args.model_batch_size,
        "device": device_metadata,
        "shard_id": shard_id,
        "source_mutation_count": len(source_mutations),
        "elapsed_seconds": round(time.monotonic() - run_started_monotonic, 2),
        "verdict": "VALIDATION_COMPLETE" if args.validate_only else "RUN_COMPLETE",
        "updated_at": utc_now(),
    }
    write_json(summary_file(evidence_root / "final", shard_id), report)
    if shard_id:
        write_json(evidence_root / "final" / "checkpoint-merge.json", merge_shard_checkpoints(evidence_root))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not source_mutations else 1


if __name__ == "__main__":
    raise SystemExit(main())
