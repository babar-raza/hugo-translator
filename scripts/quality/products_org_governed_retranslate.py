#!/usr/bin/env python3
"""
Governed products.aspose.org retranslation runner.

Runs Hugo Translator one source-locale pair at a time and verifies the target
frontmatter against the canonical English source before checkpointing.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import textwrap
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import ScalarString

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.translation_engine.parser.hugo_parser import HugoParser
from src.utils.config_loader import ConfigService
from src.utils.models import FrontmatterMode


VERIFIER_POLICY_VERSION = "products-org-governed-v2-code-identity-repetition"
CODE_BLOCK_PATTERN = re.compile(r"```[^\n`]*\n.*?```", re.DOTALL)
MATERIAL_COPY_ROOTS = {"evidence"}
PRODUCT_IDENTITY_PATTERN = re.compile(
    r"Aspose\.[A-Za-z0-9.+#-]+(?:\s+FOSS)?(?:\s+for\s+[A-Za-z0-9.+#-]+)?"
)
CORE_PRODUCT_PATTERN = re.compile(r"Aspose\.[A-Za-z0-9.+#-]+(?:\s+FOSS)?")
KNOWN_SCALAR_TRANSLATIONS = {
    (
        "th",
        "overview.title",
        "Open-Source Python Library for Word Document Conversion",
    ): "ไลบรารี Python โอเพนซอร์สสำหรับการแปลงเอกสาร Word",
    (
        "th",
        "head_title",
        "Aspose.Words FOSS for Python | Open-Source Word Document Converter",
    ): "Aspose.Words FOSS สำหรับ Python | ตัวแปลงเอกสาร Word แบบโอเพนซอร์ส",
}
YAML_DUMPER = YAML()
YAML_DUMPER.preserve_quotes = True
YAML_DUMPER.width = 4096


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def flatten_paths(value: Any, prefix: str = "") -> dict[str, Any]:
    paths: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            paths[child_path] = child
            paths.update(flatten_paths(child, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            child_path = f"{prefix}[{idx}]"
            paths[child_path] = child
            paths.update(flatten_paths(child, child_path))
    return paths


def scalar_paths(value: Any, prefix: str = "") -> dict[str, Any]:
    paths: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            paths.update(scalar_paths(child, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            paths.update(scalar_paths(child, f"{prefix}[{idx}]"))
    else:
        paths[prefix] = value
    return paths


def normalize_rule_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "", path)


def path_parts(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for chunk in path.split("."):
        match = re.fullmatch(r"([^\[]+)((?:\[\d+\])*)", chunk)
        if not match:
            parts.append(chunk)
            continue
        parts.append(match.group(1))
        for idx in re.findall(r"\[(\d+)\]", match.group(2)):
            parts.append(int(idx))
    return parts


def get_path_value(root: Any, path: str) -> Any:
    cursor = root
    for part in path_parts(path):
        if isinstance(part, int):
            if not isinstance(cursor, list) or part >= len(cursor):
                return None
            cursor = cursor[part]
        else:
            if not isinstance(cursor, dict) or part not in cursor:
                return None
            cursor = cursor[part]
    return cursor


def set_path_value(root: Any, path: str, value: Any) -> bool:
    cursor = root
    parts = path_parts(path)
    for part in parts[:-1]:
        if isinstance(part, int):
            if not isinstance(cursor, list) or part >= len(cursor):
                return False
            cursor = cursor[part]
        else:
            if not isinstance(cursor, dict) or part not in cursor:
                return False
            cursor = cursor[part]
    leaf = parts[-1] if parts else None
    if isinstance(leaf, int):
        if not isinstance(cursor, list) or leaf >= len(cursor):
            return False
        cursor[leaf] = value
        return True
    if isinstance(cursor, dict):
        cursor[leaf] = value
        return True
    return False


def is_audit_path(path: str) -> bool:
    normalized = normalize_rule_path(path)
    return (
        normalized.startswith("provenance.")
        or normalized in {"grade", "grade_reasons", "graded_content_hash"}
        or normalized.startswith("graded_")
    )


def strip_code_blocks(text: str) -> str:
    return CODE_BLOCK_PATTERN.sub(" ", text)


def normalized_code_blocks(text: str) -> list[str]:
    blocks = []
    for match in CODE_BLOCK_PATTERN.finditer(text):
        block = textwrap.dedent(match.group(0)).strip()
        block = "\n".join(line.rstrip() for line in block.splitlines())
        blocks.append(block)
    return blocks


def raw_code_blocks(text: str) -> list[str]:
    return [match.group(0) for match in CODE_BLOCK_PATTERN.finditer(text)]


def document_code_blocks(scalars: dict[str, Any], raw_text: str) -> list[dict[str, Any]]:
    blocks = []
    for path, value in scalars.items():
        if is_audit_path(path) or not isinstance(value, str):
            continue
        for idx, block in enumerate(normalized_code_blocks(value)):
            blocks.append({"path": path, "index": idx, "block": block})
    split = split_frontmatter_text(raw_text)
    body_text = split[1] if split is not None else raw_text
    for idx, block in enumerate(normalized_code_blocks(body_text)):
        blocks.append({"path": "$body", "index": idx, "block": block})
    return blocks


def replace_code_blocks_with_source(src_value: str, tgt_value: str) -> str:
    source_blocks = raw_code_blocks(src_value)
    target_blocks = raw_code_blocks(tgt_value)
    if not source_blocks or len(source_blocks) != len(target_blocks):
        return tgt_value
    cursor = 0

    def replacement(_match):
        nonlocal cursor
        block = source_blocks[cursor]
        cursor += 1
        return block

    return CODE_BLOCK_PATTERN.sub(replacement, tgt_value)


def repair_extra_code_blocks_with_source_order(src_value: str, tgt_value: str) -> str:
    source_blocks = raw_code_blocks(src_value)
    target_blocks = raw_code_blocks(tgt_value)
    if not source_blocks or len(target_blocks) <= len(source_blocks):
        return tgt_value
    chunks = CODE_BLOCK_PATTERN.split(tgt_value)
    if len(chunks) != len(target_blocks) + 1:
        return tgt_value
    rebuilt: list[str] = [chunks[0]]
    for idx, source_block in enumerate(source_blocks):
        rebuilt.append(source_block)
        rebuilt.append(chunks[idx + 1])
    rebuilt.extend(chunks[len(source_blocks) + 1 :])
    return "".join(rebuilt)


def extract_product_requirements(value: Any) -> list[dict[str, str | None]]:
    if not isinstance(value, str):
        return []
    requirements = []
    for match in PRODUCT_IDENTITY_PATTERN.finditer(value):
        identity = match.group(0)
        core_match = CORE_PRODUCT_PATTERN.match(identity)
        if not core_match:
            continue
        platform = None
        platform_match = re.search(r"\s+for\s+([A-Za-z0-9.+#-]+)$", identity)
        if platform_match:
            platform = platform_match.group(1)
        requirements.append({"identity": identity, "core": core_match.group(0), "platform": platform})
    return requirements


def product_identity_violations(src_value: Any, tgt_value: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(src_value, str) or not isinstance(tgt_value, str):
        return []
    violations = []
    for requirement in extract_product_requirements(src_value):
        core = requirement["core"] or ""
        platform = requirement.get("platform")
        missing = []
        if core and core not in tgt_value:
            missing.append(core)
        if platform and platform not in tgt_value:
            missing.append(platform)
        if missing:
            violations.append(
                {
                    "path": path,
                    "source_identity": requirement["identity"],
                    "missing": missing,
                    "target": tgt_value,
                }
            )
    return violations


def repair_product_identity_value(src_value: Any, tgt_value: Any) -> Any:
    if not isinstance(src_value, str) or not isinstance(tgt_value, str):
        return tgt_value
    repaired = tgt_value
    for requirement in extract_product_requirements(src_value):
        core = requirement["core"] or ""
        platform = requirement.get("platform")
        if core and core not in repaired:
            family = core.removeprefix("Aspose.").removesuffix(" FOSS")
            family_pattern = re.escape(family).replace(r"\.", r"[.\s]?")
            if "FOSS" in core:
                approximate = re.compile(
                    rf"(?iu)(?:\bAspose\.?\s*|[\w\u0080-\uffff]+\s+)?{family_pattern}\s+FOSS\b"
                )
            else:
                approximate = re.compile(rf"(?iu)(?:\bAspose\.?\s*)?{family_pattern}\b")
            repaired_once = approximate.sub(core, repaired, count=1)
            repaired = repaired_once if repaired_once != repaired else f"{core} - {repaired}"
        if platform and platform not in repaired:
            repaired = f"{repaired} {platform}"
    return repaired


def split_frontmatter_text(text: str) -> tuple[str, str] | None:
    if not text.startswith("---"):
        return None
    match = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.DOTALL)
    if not match:
        return None
    return match.group(1), text[match.end() :]


def load_target_frontmatter(target: Path) -> tuple[Any, str] | None:
    target_text = target.read_text(encoding="utf-8", errors="replace")
    split = split_frontmatter_text(target_text)
    if split is None:
        return None
    target_yaml, target_body = split
    target_frontmatter = YAML_DUMPER.load(target_yaml) or {}
    if not isinstance(target_frontmatter, dict):
        return None
    return target_frontmatter, target_body


def write_target_frontmatter(target: Path, frontmatter: Any, body: str) -> None:
    out = io.StringIO()
    YAML_DUMPER.dump(frontmatter, out)
    target.write_text(f"---\n{out.getvalue()}---\n{body}", encoding="utf-8")


def repair_target_product_identities(parser: HugoParser, source: Path, target: Path) -> dict[str, Any]:
    if not target.exists():
        return {"changed": False, "repairs": []}
    source_doc = parse_doc(parser, source)
    loaded = load_target_frontmatter(target)
    if loaded is None:
        return {"changed": False, "repairs": [], "reason": "missing_frontmatter"}
    target_frontmatter, target_body = loaded

    repairs = []
    src_scalars = scalar_paths(source_doc.frontmatter)
    for path, src_value in src_scalars.items():
        tgt_value = get_path_value(target_frontmatter, path)
        if not product_identity_violations(src_value, tgt_value, path):
            continue
        repaired = repair_product_identity_value(src_value, tgt_value)
        if repaired == tgt_value:
            continue
        if set_path_value(target_frontmatter, path, repaired):
            repairs.append({"path": path, "before": tgt_value, "after": repaired})

    if not repairs:
        return {"changed": False, "repairs": []}
    write_target_frontmatter(target, target_frontmatter, target_body)
    return {"changed": True, "repairs": repairs}


def repair_target_material_copy_fields(profile, parser: HugoParser, source: Path, target: Path) -> dict[str, Any]:
    if not target.exists():
        return {"changed": False, "repairs": []}
    source_doc = parse_doc(parser, source)
    loaded = load_target_frontmatter(target)
    if loaded is None:
        return {"changed": False, "repairs": [], "reason": "missing_frontmatter"}
    target_frontmatter, target_body = loaded
    repairs = []

    for root in MATERIAL_COPY_ROOTS:
        src_value = get_path_value(source_doc.frontmatter, root)
        tgt_value = get_path_value(target_frontmatter, root)
        if src_value is not None and src_value != tgt_value and set_path_value(target_frontmatter, root, src_value):
            repairs.append({"path": root, "reason": "material_copy_root"})

    for path, rule in profile.frontmatter.items():
        if rule.mode != FrontmatterMode.PASSTHROUGH:
            continue
        src_value = get_path_value(source_doc.frontmatter, path)
        tgt_value = get_path_value(target_frontmatter, path)
        if src_value is not None and src_value != tgt_value and set_path_value(target_frontmatter, path, src_value):
            repairs.append({"path": path, "reason": "configured_passthrough"})

    if not repairs:
        return {"changed": False, "repairs": []}
    write_target_frontmatter(target, target_frontmatter, target_body)
    return {"changed": True, "repairs": repairs}


def repair_target_code_blocks(profile, parser: HugoParser, source: Path, target: Path) -> dict[str, Any]:
    if not target.exists():
        return {"changed": False, "repairs": []}
    source_doc = parse_doc(parser, source)
    loaded = load_target_frontmatter(target)
    if loaded is None:
        return {"changed": False, "repairs": [], "reason": "missing_frontmatter"}
    target_frontmatter, target_body = loaded
    translate_paths = translatable_paths(profile, source_doc)
    repairs = []

    for path in translate_paths:
        src_value = get_path_value(source_doc.frontmatter, path)
        tgt_value = get_path_value(target_frontmatter, path)
        if not isinstance(src_value, str) or not isinstance(tgt_value, str):
            continue
        repaired = replace_code_blocks_with_source(src_value, tgt_value)
        if repaired == tgt_value:
            repaired = repair_extra_code_blocks_with_source_order(src_value, tgt_value)
        if repaired != tgt_value and set_path_value(target_frontmatter, path, repaired):
            repairs.append({"path": path, "reason": "source_code_block_restored"})

    if not repairs:
        return {"changed": False, "repairs": []}
    write_target_frontmatter(target, target_frontmatter, target_body)
    return {"changed": True, "repairs": repairs}


def repair_known_scalar_translations(
    profile,
    parser: HugoParser,
    source: Path,
    target: Path,
    locale: str,
) -> dict[str, Any]:
    if not target.exists():
        return {"changed": False, "repairs": []}
    source_doc = parse_doc(parser, source)
    loaded = load_target_frontmatter(target)
    if loaded is None:
        return {"changed": False, "repairs": [], "reason": "missing_frontmatter"}
    target_frontmatter, target_body = loaded
    translate_paths = set(translatable_paths(profile, source_doc))
    repairs = []

    for path in translate_paths:
        src_value = get_path_value(source_doc.frontmatter, path)
        tgt_value = get_path_value(target_frontmatter, path)
        if not isinstance(src_value, str) or not isinstance(tgt_value, str):
            continue
        known = KNOWN_SCALAR_TRANSLATIONS.get((locale, path, src_value))
        if known is None or tgt_value == known:
            continue
        if src_value == tgt_value or english_residue_violations(src_value, tgt_value, path):
            if set_path_value(target_frontmatter, path, known):
                repairs.append({"path": path, "reason": "known_scalar_translation", "before": tgt_value, "after": known})

    if not repairs:
        return {"changed": False, "repairs": []}
    write_target_frontmatter(target, target_frontmatter, target_body)
    return {"changed": True, "repairs": repairs}


def repeated_token_violations(value: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        return []
    text = strip_code_blocks(value).strip()
    if len(text) < 24:
        return []
    tokens = re.findall(r"[\w.+#-]+", text, flags=re.UNICODE)
    if len(tokens) < 8:
        return []
    lowered = [token.lower() for token in tokens]
    most_common = max(set(lowered), key=lowered.count)
    if lowered.count(most_common) >= 6 and lowered.count(most_common) / len(lowered) >= 0.45:
        return [{"path": path, "token": most_common, "count": lowered.count(most_common), "value": text[:500]}]
    for size in (2, 3, 4):
        if len(lowered) < size * 4:
            continue
        for start in range(0, len(lowered) - size * 3 + 1):
            chunk = lowered[start : start + size]
            repeats = 1
            cursor = start + size
            while lowered[cursor : cursor + size] == chunk:
                repeats += 1
                cursor += size
            if repeats >= 3:
                return [{"path": path, "phrase": " ".join(chunk), "repeats": repeats, "value": text[:500]}]
    if re.search(r"(.{6,60}?)(?:\s*[-–—]\s*\1){3,}", text, flags=re.IGNORECASE):
        return [{"path": path, "pattern": "repeated_phrase", "value": text[:500]}]
    return []


def english_residue_violations(src_value: Any, tgt_value: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(src_value, str) or not isinstance(tgt_value, str):
        return []
    if src_value == tgt_value:
        return []
    source_text = strip_code_blocks(src_value)
    target_text = strip_code_blocks(tgt_value)
    technical_terms = (
        r"Aspose\.[A-Za-z0-9.+#-]+|Aspose|FOSS|API|SDK|\.NET|Java|Python|TypeScript|"
        r"Node\.js|C\+\+|C#|HTML|PDF|CSV|JSON|TSV|XLSX|Excel|Markdown|NuGet|Maven|pip|GitHub|"
        r"Microsoft|Office|Outlook|Visio|AutoCAD|DWG|DXF|DGN|MSG|EML|CFB|GDI"
    )
    source_text = re.sub(technical_terms, " ", source_text)
    target_text = re.sub(technical_terms, " ", target_text)
    source_normalized = re.sub(r"\s+", " ", source_text).lower()
    english_function_words = {
        "the",
        "and",
        "for",
        "with",
        "without",
        "that",
        "which",
        "from",
        "into",
        "your",
        "you",
        "can",
        "are",
        "this",
        "these",
        "using",
        "support",
        "supports",
        "provides",
        "allows",
        "enables",
        "library",
        "developers",
    }
    phrases = [
        match.group(0).strip()
        for match in re.finditer(
            r"\b(?:[A-Z]?[a-z]{3,}\s+){4,}[A-Z]?[a-z]{3,}\b",
            target_text,
        )
    ]
    violations = []
    for phrase in phrases:
        words = re.findall(r"[A-Za-z]{3,}", phrase.lower())
        if len(set(words) & english_function_words) < 2:
            continue
        if re.sub(r"\s+", " ", phrase).lower() not in source_normalized:
            continue
        violations.append({"path": path, "value": phrase[:300]})
    return violations[:5]


def looks_like_prose(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = strip_code_blocks(value).strip()
    if len(text) < 12:
        return False
    if re.fullmatch(r"[\w./:#?&=%+\-]+", text):
        return False
    if re.fullmatch(r"Aspose\.[A-Za-z0-9.+#-]+(\s+FOSS)?", text):
        return False
    if re.fullmatch(
        r"Aspose\.[A-Za-z0-9.+#-]+(\s+FOSS)?\s+for\s+[A-Za-z0-9.+#-]+",
        text,
    ):
        return False
    # Covers all-uppercase acronyms and dotted brand names: "FOSS API SDK .NET"
    if re.fullmatch(r"(Aspose|FOSS|API|SDK|[A-Z0-9.+#-]+)(\s+(Aspose|FOSS|API|SDK|[A-Z0-9.+#-]+))*", text):
        return False
    # Extended brand/acronym boilerplate — adds "Reference", "Documentation", version
    # strings (v0.1.0), and Aspose.X dotted names.  Handles titles like:
    #   "Aspose FOSS API Reference"
    #   "Aspose.3D FOSS Python API Reference"
    #   "Aspose.Email.Foss v0.1.0"
    _BW = r"(?:Aspose(?:\.[A-Za-z0-9.+#-]+)?|FOSS|API|SDK|Hub|Reference|Documentation|v\d[\d.]*[a-z]?|[A-Z0-9][A-Z0-9.+#-]*)"
    if re.fullmatch(rf"{_BW}(?:\s+{_BW})*", text):
        return False
    # Reference API page titles: "ClassName — Aspose.X FOSS Lang API Reference"
    # The entire value is protected content (API identifier + brand template), so NLLB
    # correctly leaves it unchanged.  Do not flag as untranslated.
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]* \u2014 Aspose\.\S+ FOSS .+ API Reference", text):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", text))


def material_type(value: Any) -> type:
    if isinstance(value, ScalarString):
        return str
    return type(value)


def parse_doc(parser: HugoParser, path: Path):
    doc = parser.parse_file(path)
    if not doc.frontmatter:
        raise ValueError(f"No parsed frontmatter: {path}")
    return doc


def translatable_paths(profile, doc) -> set[str]:
    extractor = SegmentExtractor(profile)
    segments = extractor.extract_from_frontmatter(doc.frontmatter, profile.default_source_lang)
    return {
        seg.context.frontmatter_key
        for seg in segments
        if seg.context and seg.context.frontmatter_key
    }


def verify_pair(profile, parser: HugoParser, source: Path, target: Path, locale: str) -> dict[str, Any]:
    source_text = source.read_text(encoding="utf-8", errors="replace")
    target_text = target.read_text(encoding="utf-8", errors="replace")
    source_doc = parse_doc(parser, source)
    target_doc = parse_doc(parser, target)
    src_all = flatten_paths(source_doc.frontmatter)
    tgt_all = flatten_paths(target_doc.frontmatter)
    src_scalars = scalar_paths(source_doc.frontmatter)
    tgt_scalars = scalar_paths(target_doc.frontmatter)
    translate_paths = translatable_paths(profile, source_doc)
    translate_norm = {normalize_rule_path(path) for path in translate_paths}

    missing = sorted(path for path in set(src_all) - set(tgt_all) if not is_audit_path(path))
    extra = sorted(path for path in set(tgt_all) - set(src_all) if not is_audit_path(path))
    type_mismatches = []
    list_length_mismatches = []
    protected_changes = []
    untranslated = []
    product_identity_changes = []
    repetition_issues = []
    english_residue = []

    source_code_blocks = document_code_blocks(src_scalars, source_text)
    target_code_blocks = document_code_blocks(tgt_scalars, target_text)
    code_fence_mismatch = []
    code_block_mutations = []
    if len(source_code_blocks) != len(target_code_blocks):
        code_fence_mismatch.append(
            {
                "source_count": len(source_code_blocks),
                "target_count": len(target_code_blocks),
                "source_paths": [block["path"] for block in source_code_blocks],
                "target_paths": [block["path"] for block in target_code_blocks],
            }
        )
    else:
        for idx, (src_block, tgt_block) in enumerate(zip(source_code_blocks, target_code_blocks, strict=False)):
            if src_block["path"] != tgt_block["path"] or src_block["block"] != tgt_block["block"]:
                code_block_mutations.append(
                    {
                        "index": idx,
                        "source_path": src_block["path"],
                        "target_path": tgt_block["path"],
                        "source_preview": src_block["block"][:300],
                        "target_preview": tgt_block["block"][:300],
                    }
                )

    for path, src_value in src_all.items():
        if path not in tgt_all:
            continue
        tgt_value = tgt_all[path]
        if is_audit_path(path):
            continue
        if material_type(src_value) is not material_type(tgt_value):
            type_mismatches.append(
                {
                    "path": path,
                    "source_type": material_type(src_value).__name__,
                    "target_type": material_type(tgt_value).__name__,
                }
            )
        if isinstance(src_value, list) and len(src_value) != len(tgt_value):
            list_length_mismatches.append(
                {"path": path, "source_len": len(src_value), "target_len": len(tgt_value)}
            )

    for path, src_value in src_scalars.items():
        tgt_value = tgt_scalars.get(path)
        if tgt_value is None:
            continue
        if is_audit_path(path):
            continue
        is_translatable = normalize_rule_path(path) in translate_norm
        if not is_translatable and src_value != tgt_value:
            protected_changes.append({"path": path, "source": src_value, "target": tgt_value})
        if is_translatable and src_value == tgt_value and looks_like_prose(src_value):
            untranslated.append({"path": path, "value": src_value})
        product_identity_changes.extend(product_identity_violations(src_value, tgt_value, path))
        repetition_issues.extend(repeated_token_violations(tgt_value, path))
        if is_translatable:
            english_residue.extend(english_residue_violations(src_value, tgt_value, path))

    verdict = "VERIFIED_ACCEPT"
    if missing or extra or type_mismatches or list_length_mismatches:
        verdict = "REJECT_STRUCTURAL_MISMATCH"
    elif code_fence_mismatch:
        verdict = "REJECT_CODE_FENCE_MISMATCH"
    elif code_block_mutations:
        verdict = "REJECT_CODE_BLOCK_MUTATED"
    elif protected_changes:
        verdict = "REJECT_PROTECTED_FIELD_CHANGED"
    elif product_identity_changes:
        verdict = "REJECT_PRODUCT_IDENTITY_CHANGED"
    elif repetition_issues:
        verdict = "REJECT_REPETITION"
    elif english_residue:
        verdict = "REJECT_PARTIAL_TRANSLATION"
    elif untranslated:
        verdict = "REJECT_PARTIAL_TRANSLATION"

    return {
        "source_file": str(source),
        "target_file": str(target),
        "locale": locale,
        "source_hash": sha256_file(source),
        "target_hash": sha256_file(target),
        "key_paths_source": sorted(src_all),
        "key_paths_target": sorted(tgt_all),
        "translatable_paths": sorted(translate_paths),
        "missing_key_paths": missing,
        "extra_key_paths": extra,
        "type_differences": type_mismatches,
        "list_length_differences": list_length_mismatches,
        "code_fence_differences": code_fence_mismatch,
        "code_block_differences": code_block_mutations,
        "protected_path_differences": protected_changes,
        "product_identity_differences": product_identity_changes,
        "repetition_issues": repetition_issues,
        "english_residue_translatable_paths": english_residue,
        "untranslated_translatable_paths": untranslated,
        "verdict": verdict,
    }


def build_inventory(content_root: Path, locales: list[str]) -> list[WorkItem]:
    en_root = content_root / "en"
    sources = sorted(en_root.rglob("*.md"), key=lambda p: p.relative_to(en_root).as_posix())
    items: list[WorkItem] = []
    for source in sources:
        rel = source.relative_to(en_root).as_posix()
        source_hash = sha256_file(source)
        for locale in locales:
            target = content_root / locale / rel
            item_id = hashlib.sha256(f"{rel}:{locale}:{source_hash}".encode()).hexdigest()[:16]
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
    return items


def parse_locale_filter(value: str | None, available: list[str]) -> list[str]:
    if not value:
        return list(available)
    requested = [part.strip() for part in value.split(",") if part.strip()]
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"Unknown locale(s) for products.aspose.org: {', '.join(unknown)}")
    return [locale for locale in available if locale in set(requested)]


def safe_shard_id(value: str | None) -> str | None:
    if not value:
        return None
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    if not safe:
        raise ValueError("--shard-id must contain at least one alphanumeric character")
    return safe


def checkpoint_file(checkpoint_dir: Path, shard_id: str | None) -> Path:
    if shard_id:
        return checkpoint_dir / f"checkpoint.{shard_id}.json"
    return checkpoint_dir / "checkpoint.json"


def current_file(checkpoint_dir: Path, shard_id: str | None) -> Path:
    if shard_id:
        return checkpoint_dir / f"current.{shard_id}.json"
    return checkpoint_dir / "current.json"


def summary_file(final_dir: Path, shard_id: str | None) -> Path:
    if shard_id:
        return final_dir / f"summary.{shard_id}.json"
    return final_dir / "summary.json"


def baseline_file(baseline_dir: Path, stem: str, shard_id: str | None) -> Path:
    if shard_id:
        return baseline_dir / f"{stem}.{shard_id}.json"
    return baseline_dir / f"{stem}.json"


def overlay_main_checkpoint_for_items(
    checkpoint: dict[str, Any],
    main_checkpoint: dict[str, Any],
    item_ids: set[str],
) -> None:
    if not isinstance(checkpoint.get("accepted"), dict):
        checkpoint["accepted"] = {}
    if not isinstance(checkpoint.get("failed"), dict):
        checkpoint["failed"] = {}
    accepted = checkpoint["accepted"]
    failed = checkpoint["failed"]

    for item_id, receipt in (main_checkpoint.get("accepted") or {}).items():
        if item_id in item_ids:
            accepted.setdefault(item_id, receipt)

    for item_id, failure in (main_checkpoint.get("failed") or {}).items():
        if item_id in item_ids and item_id not in accepted:
            failed.setdefault(item_id, failure)


def merge_shard_checkpoints(evidence_root: Path) -> dict[str, Any]:
    checkpoint_dir = evidence_root / "checkpoints"
    main_path = checkpoint_dir / "checkpoint.json"
    main = load_checkpoint(main_path)
    if not isinstance(main.get("accepted"), dict):
        main["accepted"] = {}
    if not isinstance(main.get("failed"), dict):
        main["failed"] = {}

    shard_paths = sorted(checkpoint_dir.glob("checkpoint.*.json"))
    for shard_path in shard_paths:
        shard = load_checkpoint(shard_path)
        for item_id, receipt in (shard.get("accepted") or {}).items():
            main["accepted"][item_id] = receipt
            main["failed"].pop(item_id, None)
        for item_id, failure in (shard.get("failed") or {}).items():
            if item_id not in main["accepted"]:
                main["failed"][item_id] = failure

    main["updated_at"] = utc_now()
    main["merged_shards_at"] = main["updated_at"]
    main["merged_shard_count"] = len(shard_paths)
    write_json(main_path, main)
    return {
        "checkpoint": str(main_path),
        "merged_shard_count": len(shard_paths),
        "accepted": len(main["accepted"]),
        "failed": len(main["failed"]),
        "updated_at": main["updated_at"],
    }


def write_json(path: Path, data: Any) -> None:
    import time as _time
    import tempfile
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    # Write atomically via temp file to avoid OneDrive sync conflicts
    for attempt in range(5):
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(tmp_path, path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            return
        except OSError:
            if attempt == 4:
                raise
            _time.sleep(1 + attempt)


def load_checkpoint(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"accepted": {}, "failed": None}


def build_translate_cmd(args, item: WorkItem, log_path: Path) -> list[str]:
    cmd = [
        str(args.python),
        "-m",
        "src.cli",
        "--site",
        "products.aspose.org",
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
    if getattr(args, "device", None):
        cmd.extend(["--device", args.device])
    return cmd


def run_translate(args, item: WorkItem, log_path: Path) -> subprocess.CompletedProcess[str]:
    cmd = build_translate_cmd(args, item, log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # On Windows, CREATE_NEW_PROCESS_GROUP detaches the child from the parent's
    # job object so it is NOT killed when this shard process dies unexpectedly.
    # The child completes independently; the next shard restart will fast-accept
    # the finished target via pre-verification.
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    with log_path.open("w", encoding="utf-8") as log:
        try:
            return subprocess.run(
                cmd,
                cwd=ROOT,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=args.timeout_seconds,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired:
            log.write(f"\nTranslation timed out after {args.timeout_seconds} seconds\n")
            return subprocess.CompletedProcess(cmd, 124)


def repair_and_record_product_identities(
    evidence_root: Path,
    profile,
    parser_obj: HugoParser,
    item: WorkItem,
    source: Path,
    target: Path,
    stage: str,
) -> dict[str, Any]:
    repairs = {
        "material_copy": repair_target_material_copy_fields(profile, parser_obj, source, target),
        "product_identity": repair_target_product_identities(parser_obj, source, target),
        "code_blocks": repair_target_code_blocks(profile, parser_obj, source, target),
        "known_scalars": repair_known_scalar_translations(profile, parser_obj, source, target, item.locale),
    }
    changed = any(repair.get("changed") for repair in repairs.values())
    if changed:
        record = {
            "changed": True,
            "stage": stage,
            "work_item": asdict(item),
            "repairs": repairs,
            "repaired_at": utc_now(),
        }
        write_json(evidence_root / "repairs" / item.locale / f"{item.work_item_id}.preverify-repairs.json", record)
        return record
    return {"changed": False, "repairs": repairs}


def is_preserved_existing_translation(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    return "OVERWRITE BLOCKED: Existing file has higher quality" in text


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
        "protected_paths_checked": len(comparison["key_paths_source"]) - len(comparison["translatable_paths"]),
        "translatable_paths_checked": len(comparison["translatable_paths"]),
        "structure_result": "pass",
        "protected_field_result": "pass",
        "completeness_result": "pass",
        "verdict": "VERIFIED_TRANSLATION_ACCEPTED",
        "candidate_status": candidate_status,
        "accepted_at": utc_now(),
    }
    write_json(evidence_root / "per-file" / item.locale / f"{item.work_item_id}.receipt.json", receipt)
    checkpoint.setdefault("accepted", {})[item.work_item_id] = receipt
    checkpoint.setdefault("failed", {}).pop(item.work_item_id, None)
    failure_path = evidence_root / "failures" / f"{item.work_item_id}.json"
    if failure_path.exists():
        resolved_path = evidence_root / "resolved-failures" / f"{item.work_item_id}.json"
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        failure_path.replace(resolved_path)
    checkpoint["updated_at"] = utc_now()
    write_json(checkpoint_path, checkpoint)


def write_failure(
    evidence_root: Path,
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    item: WorkItem,
    failure: dict[str, Any],
) -> None:
    checkpoint.setdefault("failed", {})[item.work_item_id] = failure
    write_json(evidence_root / "failures" / f"{item.work_item_id}.json", failure)
    checkpoint["updated_at"] = utc_now()
    write_json(checkpoint_path, checkpoint)


def verification_failure(item: WorkItem, comparison: dict[str, Any], status: str = "PIPELINE_REPAIR_REQUIRED") -> dict[str, Any]:
    return {
        "failure_id": hashlib.sha256(f"{item.work_item_id}:verify:{comparison['verdict']}".encode()).hexdigest()[:16],
        "work_item": asdict(item),
        "failure_type": comparison["verdict"],
        "first_failing_boundary": "source_target_yaml_comparator",
        "comparison": comparison,
        "failed_at": utc_now(),
        "status": status,
    }


def verification_exception_failure(item: WorkItem, exc: Exception) -> dict[str, Any]:
    return {
        "failure_id": hashlib.sha256(f"{item.work_item_id}:reverify-exception".encode()).hexdigest()[:16],
        "work_item": asdict(item),
        "failure_type": "VERIFY_EXCEPTION",
        "exception": repr(exc),
        "failed_at": utc_now(),
        "status": "PIPELINE_REPAIR_REQUIRED",
    }


def quarantine_accepted_receipt(
    evidence_root: Path,
    checkpoint: dict[str, Any],
    item: WorkItem,
    failure: dict[str, Any],
) -> None:
    accepted = checkpoint.setdefault("accepted", {})
    failed = checkpoint.setdefault("failed", {})
    previous_receipt = accepted.pop(item.work_item_id, None)
    failure["previous_acceptance_receipt"] = previous_receipt
    failure["quarantined_at"] = utc_now()
    failure["status"] = "ACCEPTED_RECEIPT_QUARANTINED_FOR_RETRY"
    failed[item.work_item_id] = failure

    receipt_path = evidence_root / "per-file" / item.locale / f"{item.work_item_id}.receipt.json"
    quarantine_path = evidence_root / "quarantined-accepted" / item.locale / f"{item.work_item_id}.receipt.json"
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        shutil.move(str(receipt_path), str(quarantine_path))
    elif previous_receipt is not None:
        write_json(quarantine_path, previous_receipt)

    write_json(evidence_root / "accepted-reverification-failures" / f"{item.work_item_id}.json", failure)
    write_json(evidence_root / "failures" / f"{item.work_item_id}.json", failure)


def reverify_accepted_items(
    *,
    evidence_root: Path,
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    items: list[WorkItem],
    profile,
    parser_obj: HugoParser,
    policy_hash: str,
    dry_run: bool,
) -> dict[str, Any]:
    accepted = checkpoint.setdefault("accepted", {})
    item_by_id = {item.work_item_id: item for item in items}
    accepted_ids = [item_id for item_id in list(accepted) if item_id in item_by_id]
    verdict_counts: dict[str, int] = {}
    missing_inventory_ids = sorted(set(accepted) - set(item_by_id))
    refreshed = 0
    quarantined = 0
    exceptions = 0

    for item_id in accepted_ids:
        item = item_by_id[item_id]
        try:
            comparison = verify_pair(profile, parser_obj, Path(item.source_path), Path(item.target_path), item.locale)
        except Exception as exc:
            exceptions += 1
            failure = verification_exception_failure(item, exc)
            verdict_counts[failure["failure_type"]] = verdict_counts.get(failure["failure_type"], 0) + 1
            if not dry_run:
                quarantine_accepted_receipt(evidence_root, checkpoint, item, failure)
                checkpoint["updated_at"] = utc_now()
                write_json(checkpoint_path, checkpoint)
            continue

        write_json(
            evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json",
            comparison,
        )
        verdict_counts[comparison["verdict"]] = verdict_counts.get(comparison["verdict"], 0) + 1
        if comparison["verdict"] == "VERIFIED_ACCEPT":
            receipt = accepted.get(item.work_item_id, {})
            receipt_stale = (
                receipt.get("config_hash") != policy_hash
                or receipt.get("verifier_policy_version") != VERIFIER_POLICY_VERSION
                or receipt.get("target_hash") != comparison["target_hash"]
            )
            if receipt_stale and not dry_run:
                write_acceptance(
                    evidence_root,
                    checkpoint_path,
                    checkpoint,
                    item,
                    comparison,
                    policy_hash,
                    "accepted_translation_reverified_policy_refresh",
                )
                refreshed += 1
            continue

        failure = verification_failure(item, comparison, status="ACCEPTED_RECEIPT_FAILED_REVERIFICATION")
        if not dry_run:
            quarantine_accepted_receipt(evidence_root, checkpoint, item, failure)
            checkpoint["updated_at"] = utc_now()
            write_json(checkpoint_path, checkpoint)
        quarantined += 1

    report = {
        "run_id": checkpoint.get("run_id"),
        "verifier_policy_version": VERIFIER_POLICY_VERSION,
        "policy_hash": policy_hash,
        "dry_run": dry_run,
        "accepted_checked": len(accepted_ids),
        "accepted_missing_from_current_inventory": len(missing_inventory_ids),
        "missing_inventory_ids": missing_inventory_ids[:50],
        "verdict_counts": verdict_counts,
        "refreshed_receipts": refreshed,
        "quarantined_accepts": quarantined,
        "verification_exceptions": exceptions,
        "accepted_after": len(checkpoint.get("accepted") or {}),
        "failed_after": len(checkpoint.get("failed") or {}),
        "updated_at": utc_now(),
    }
    write_json(evidence_root / "final" / "accepted-reverification.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="m2m100_418m")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument(
        "--max-work-items",
        type=int,
        default=0,
        help="Limit processed items after retry/failed-first ordering without shrinking the baseline inventory.",
    )
    parser.add_argument(
        "--only-locales",
        help="Comma-separated locale shard to process, e.g. ar,bg,ca. Keeps target files disjoint.",
    )
    parser.add_argument(
        "--shard-id",
        help="Shard checkpoint suffix. Required for safe parallel workers sharing one evidence root.",
    )
    parser.add_argument(
        "--merge-shards",
        action="store_true",
        help="Merge checkpoint.*.json shard checkpoints back into checkpoint.json and exit.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Build shard inventory/evidence metadata and exit without translating or mutating checkpoints.",
    )
    parser.add_argument(
        "--reverify-accepted",
        action="store_true",
        help="Recheck accepted checkpoint receipts under the current verifier policy and quarantine failures.",
    )
    parser.add_argument(
        "--reverify-dry-run",
        action="store_true",
        help="With --reverify-accepted, report re-verification results without changing checkpoint accepted/failed state.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Reprocess failed checkpoint entries instead of treating them as terminal skips.",
    )
    parser.add_argument(
        "--failed-first",
        action="store_true",
        help="When retrying, process active failed checkpoint entries before untouched inventory.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--device",
        default="cuda",
        choices=["auto", "cpu", "cuda"],
        help="Device passed to src.cli for model inference. Defaults to cuda for governed products runs.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=ROOT / ".venv" / "Scripts" / "python.exe",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    evidence_root = ROOT / ".local" / "evidences" / f"hugo-translator-retranslation-{args.run_id}"
    if args.merge_shards:
        print(json.dumps(merge_shard_checkpoints(evidence_root), indent=2))
        return 0

    config_service = ConfigService(config_root=ROOT / "config")
    profile = config_service.get_site_profile("products.aspose.org")
    if profile is None:
        raise SystemExit("products.aspose.org profile not found")

    content_root = Path(os.path.expandvars(profile.content_roots[0]))
    try:
        locales = parse_locale_filter(args.only_locales, list(profile.target_langs))
        shard_id = safe_shard_id(args.shard_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.only_locales and not shard_id:
        raise SystemExit("--shard-id is required when --only-locales is used")

    checkpoint_dir = evidence_root / "checkpoints"
    main_checkpoint_path = checkpoint_dir / "checkpoint.json"
    checkpoint_path = checkpoint_file(checkpoint_dir, shard_id)
    checkpoint = load_checkpoint(checkpoint_path) if args.resume else {"accepted": {}, "failed": {}}
    main_checkpoint = (
        load_checkpoint(main_checkpoint_path)
        if args.resume and shard_id and main_checkpoint_path.exists()
        else checkpoint
    )
    checkpoint["run_id"] = args.run_id
    if shard_id:
        checkpoint["shard_id"] = shard_id
        checkpoint["only_locales"] = locales
    if checkpoint.get("failed") is None:
        checkpoint["failed"] = {}
    elif isinstance(checkpoint.get("failed"), dict) and "work_item" in checkpoint["failed"]:
        previous_failure = checkpoint["failed"]
        previous_work_item = previous_failure.get("work_item", {})
        previous_id = previous_work_item.get("work_item_id")
        checkpoint["failed"] = {previous_id: previous_failure} if previous_id else {}

    items = build_inventory(content_root, locales)
    if args.max_items:
        items = items[: args.max_items]
    if shard_id:
        overlay_main_checkpoint_for_items(
            checkpoint,
            main_checkpoint,
            {item.work_item_id for item in items},
        )
    if args.retry_failed and args.failed_first:
        failed_ids = set(checkpoint.get("failed", {}) or {})
        items = sorted(
            items,
            key=lambda item: (
                0 if item.work_item_id in failed_ids else 1,
                item.relative_path,
                item.locale,
            ),
        )
    if args.max_work_items:
        accepted_ids = set(checkpoint.get("accepted", {}) or {})
        failed_ids = set(checkpoint.get("failed", {}) or {})
        eligible_items = []
        for item in items:
            if item.work_item_id in accepted_ids:
                continue
            if item.work_item_id in failed_ids and not args.retry_failed:
                continue
            eligible_items.append(item)
        items = eligible_items[: args.max_work_items]

    policy = {
        "verifier_policy_version": VERIFIER_POLICY_VERSION,
        "site_id": profile.site_id,
        "source_locale": profile.default_source_lang,
        "source_root": str(content_root / "en"),
        "target_locales": locales,
        "shard_id": shard_id,
        "frontmatter_rules": {
            key: getattr(rule.mode, "value", str(rule.mode)) for key, rule in profile.frontmatter.items()
        },
        "body_preserve_patterns": list(profile.body.preserve_patterns or []),
        "placeholder_syntax": list(profile.body.placeholder_syntax or []),
        "translatable_keys": [
            key for key, rule in profile.frontmatter.items() if rule.mode == FrontmatterMode.TRANSLATE
        ],
        "protected_keys": [
            key for key, rule in profile.frontmatter.items() if rule.mode == FrontmatterMode.PASSTHROUGH
        ],
        "unknown_field_policy": "implicit_protected_copy_through",
    }
    policy_hash = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()

    write_json(
        baseline_file(evidence_root / "baseline", "policy", shard_id),
        policy | {"configuration_hash": policy_hash},
    )
    write_json(
        baseline_file(evidence_root / "baseline", "inventory", shard_id),
        [asdict(item) for item in items],
    )

    if args.plan_only:
        report = {
            "run_id": args.run_id,
            "shard_id": shard_id,
            "target_locales": locales,
            "planned_pairs": len(items),
            "checkpoint_path": str(checkpoint_path),
            "current_path": str(current_file(checkpoint_dir, shard_id)),
            "summary_path": str(summary_file(evidence_root / "final", shard_id)),
            "verifier_policy_version": VERIFIER_POLICY_VERSION,
            "policy_hash": policy_hash,
            "verdict": "PLAN_ONLY_NO_TRANSLATION_STARTED",
        }
        print(json.dumps(report, indent=2))
        return 0

    parser_obj = HugoParser()
    accepted = checkpoint.setdefault("accepted", {})
    failed = checkpoint.setdefault("failed", {})

    if args.reverify_accepted:
        report = reverify_accepted_items(
            evidence_root=evidence_root,
            checkpoint_path=checkpoint_path,
            checkpoint=checkpoint,
            items=items,
            profile=profile,
            parser_obj=parser_obj,
            policy_hash=policy_hash,
            dry_run=args.reverify_dry_run,
        )
        print(json.dumps(report, indent=2))
        return 0

    if args.retry_failed:
        for item in items:
            if item.work_item_id not in failed or item.work_item_id in accepted:
                continue
            source = Path(item.source_path)
            target = Path(item.target_path)
            if not target.exists():
                continue
            try:
                repair_and_record_product_identities(
                    evidence_root,
                    profile,
                    parser_obj,
                    item,
                    source,
                    target,
                    "retry_pre_sweep_existing_target",
                )
                comparison = verify_pair(profile, parser_obj, source, target, item.locale)
            except Exception:
                continue
            write_json(
                evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json",
                comparison,
            )
            if comparison["verdict"] == "VERIFIED_ACCEPT":
                write_acceptance(
                    evidence_root,
                    checkpoint_path,
                    checkpoint,
                    item,
                    comparison,
                    policy_hash,
                    "existing_translation_verified_pre_sweep",
                )
                print(f"ACCEPT: existing target verified in retry pre-sweep for {item.locale} {item.relative_path}")

    for item in items:
        if accepted.get(item.work_item_id):
            continue
        if failed.get(item.work_item_id) and not args.retry_failed:
            continue

        source = Path(item.source_path)
        target = Path(item.target_path)
        current = {
            "work_item": asdict(item),
            "started_at": utc_now(),
            "policy_hash": policy_hash,
            "verifier_policy_version": VERIFIER_POLICY_VERSION,
        }
        write_json(current_file(checkpoint_dir, shard_id), current)

        retrying_failure = bool(failed.get(item.work_item_id))
        if target.exists():
            try:
                repair_and_record_product_identities(
                    evidence_root,
                    profile,
                    parser_obj,
                    item,
                    source,
                    target,
                    "retry_existing_target" if retrying_failure else "pre_translate_existing_target",
                )
                comparison = verify_pair(profile, parser_obj, source, target, item.locale)
                write_json(
                    evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json",
                comparison,
                )
                if comparison["verdict"] == "VERIFIED_ACCEPT":
                    write_acceptance(
                        evidence_root,
                        checkpoint_path,
                        checkpoint,
                        item,
                        comparison,
                        policy_hash,
                        "existing_translation_verified_on_retry"
                        if retrying_failure
                        else "existing_translation_verified_pre_translate",
                    )
                    print(f"ACCEPT: existing target verified before translation for {item.locale} {item.relative_path}")
                    continue
            except Exception as exc:
                failure = {
                    "failure_id": hashlib.sha256(f"{item.work_item_id}:retry-verify-exception".encode()).hexdigest()[:16],
                    "work_item": asdict(item),
                    "failure_type": "VERIFY_EXCEPTION",
                    "exception": repr(exc),
                    "failed_at": utc_now(),
                    "status": "PIPELINE_REPAIR_REQUIRED",
                }
                write_failure(evidence_root, checkpoint_path, checkpoint, item, failure)
                print(f"SKIP: retry verification exception for {item.locale} {item.relative_path}")
                continue

        log_path = evidence_root / "per-file" / item.locale / item.relative_path.replace("/", "__")
        log_path = log_path.with_suffix(".translate.log")
        result = run_translate(args, item, log_path)
        preserved_existing = False
        if result.returncode != 0 and target.exists() and is_preserved_existing_translation(log_path):
            preserved_existing = True

        if (result.returncode != 0 and not preserved_existing) or not target.exists():
            if target.exists():
                try:
                    repair_and_record_product_identities(
                        evidence_root,
                        profile,
                        parser_obj,
                        item,
                        source,
                        target,
                        "translator_reject_existing_target",
                    )
                    comparison = verify_pair(profile, parser_obj, source, target, item.locale)
                    write_json(
                        evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json",
                        comparison,
                    )
                    if comparison["verdict"] == "VERIFIED_ACCEPT":
                        write_acceptance(
                            evidence_root,
                            checkpoint_path,
                            checkpoint,
                            item,
                            comparison,
                            policy_hash,
                            "existing_translation_preserved_after_translator_reject",
                        )
                        print(f"ACCEPT: existing target verified after translator reject for {item.locale} {item.relative_path}")
                        continue
                except Exception as exc:
                    failure = {
                        "failure_id": hashlib.sha256(f"{item.work_item_id}:verify-exception".encode()).hexdigest()[:16],
                        "work_item": asdict(item),
                        "failure_type": "VERIFY_EXCEPTION",
                        "translator_exit_code": result.returncode,
                        "translator_log": str(log_path),
                        "exception": repr(exc),
                        "failed_at": utc_now(),
                        "status": "PIPELINE_REPAIR_REQUIRED",
                    }
                    write_failure(evidence_root, checkpoint_path, checkpoint, item, failure)
                    print(f"SKIP: verification exception for existing target {item.locale} {item.relative_path}")
                    continue
            failure = {
                "failure_id": hashlib.sha256(f"{item.work_item_id}:translate".encode()).hexdigest()[:16],
                "work_item": asdict(item),
                "failure_type": "TRANSLATOR_REJECTED_OR_NO_TARGET",
                "translator_exit_code": result.returncode,
                "translator_log": str(log_path),
                "failed_at": utc_now(),
                "status": "PIPELINE_REPAIR_REQUIRED",
            }
            write_failure(evidence_root, checkpoint_path, checkpoint, item, failure)
            print(f"SKIP: translation failed for {item.locale} {item.relative_path}")
            continue

        try:
            repair_and_record_product_identities(
                evidence_root,
                profile,
                parser_obj,
                item,
                source,
                target,
                "post_translate_candidate",
            )
            comparison = verify_pair(profile, parser_obj, source, target, item.locale)
        except Exception as exc:
            failure = {
                "failure_id": hashlib.sha256(f"{item.work_item_id}:verify-exception".encode()).hexdigest()[:16],
                "work_item": asdict(item),
                "failure_type": "VERIFY_EXCEPTION",
                "translator_exit_code": result.returncode,
                "translator_log": str(log_path),
                "exception": repr(exc),
                "failed_at": utc_now(),
                "status": "PIPELINE_REPAIR_REQUIRED",
            }
            write_failure(evidence_root, checkpoint_path, checkpoint, item, failure)
            print(f"SKIP: verification exception for {item.locale} {item.relative_path}")
            continue
        write_json(evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json", comparison)
        if comparison["verdict"] != "VERIFIED_ACCEPT":
            failure = {
                "failure_id": hashlib.sha256(f"{item.work_item_id}:verify".encode()).hexdigest()[:16],
                "work_item": asdict(item),
                "failure_type": comparison["verdict"],
                "first_failing_boundary": "source_target_yaml_comparator",
                "comparison": comparison,
                "failed_at": utc_now(),
                "status": "PIPELINE_REPAIR_REQUIRED",
            }
            write_failure(evidence_root, checkpoint_path, checkpoint, item, failure)
            print(f"SKIP: verification failed for {item.locale} {item.relative_path}: {comparison['verdict']}")
            continue

        write_acceptance(
            evidence_root,
            checkpoint_path,
            checkpoint,
            item,
            comparison,
            policy_hash,
            "existing_translation_preserved" if preserved_existing else "new_translation_written",
        )
        print(f"ACCEPT: {item.locale} {item.relative_path}")

    scoped_item_ids = {item.work_item_id for item in items}
    scoped_accepted_pairs = sum(1 for item_id in accepted if item_id in scoped_item_ids)
    scoped_failed_pairs = sum(1 for item_id in failed if item_id in scoped_item_ids)
    completed_pairs = scoped_accepted_pairs + scoped_failed_pairs
    report = {
        "run_id": args.run_id,
        "shard_id": shard_id,
        "target_locales": locales,
        "verifier_policy_version": VERIFIER_POLICY_VERSION,
        "policy_hash": policy_hash,
        "required_pairs": len(items),
        "accepted_pairs": scoped_accepted_pairs,
        "failed_pairs": scoped_failed_pairs,
        "remaining_pairs": len(items) - completed_pairs,
        "global_checkpoint_accepted_pairs": len(accepted),
        "global_checkpoint_failed_pairs": len(failed),
        "verdict": "HUGO_TRANSLATION_ACTIVE_NEXT_FILE_READY"
        if completed_pairs < len(items)
        else (
            "SCOPED_TRANSLATION_FAILURES_REMAIN"
            if scoped_failed_pairs
            else "HUGO_TRANSLATIONS_FULLY_REGENERATED_FILE_VERIFIED_AND_PIPELINE_STABLE"
        ),
        "updated_at": utc_now(),
    }
    write_json(summary_file(evidence_root / "final", shard_id), report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
