"""Offline, payload-safe resolution of TC-SAS-01 fingerprints.

The campaign ledger deliberately stores only a unit fingerprint.  This module
lets an operator resolve that fingerprint against an immutable source page
without reading a rejected candidate or weakening the same-as-source gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.translation_engine.segment_translator import (
    _has_translatable_residue,
    _is_reviewed_identical_translation,
)
from src.utils.config_loader import ConfigService

from ..parser.hugo_parser import HugoParser
from .text_unit_extractor import TextUnitExtractor


def unit_fingerprint(unit: Any) -> str:
    """Return the candidate-free fingerprint format emitted by TC-SAS-01."""
    kind = getattr(getattr(unit, "kind", ""), "value", getattr(unit, "kind", ""))
    source = str(getattr(unit, "source_text", "") or "")
    return f"{kind}:{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}:{len(source)}"


def classify_unit(unit: Any, *, target_lang: str, preserve_patterns: list[str]) -> tuple[str, str]:
    """Classify an unchanged unit using the shared pre-TC-SAS-01 policy."""
    source = str(getattr(unit, "source_text", "") or "")
    if bool(getattr(unit, "do_not_translate", False)):
        return "allowed_identical", "protected_unit"
    if _is_reviewed_identical_translation(source, target_lang):
        return "allowed_identical", "reviewed_locale_cognate"
    if not _has_translatable_residue(source, preserve_patterns):
        return "allowed_identical", "protected_or_identifier_only"
    return "requires_translation", "natural_language_residue"


def resolve_fingerprint(
    *, source_path: Path, fingerprint: str, site_id: str, target_lang: str, config_root: Path
) -> dict[str, str]:
    """Resolve one TC-SAS-01 fingerprint to a deterministic safe disposition."""
    config = ConfigService(config_root)
    profile = config.get_site_profile(site_id)
    document = HugoParser().parse_file(source_path)
    plan = TextUnitExtractor(
        segmentation_strategy="sentence_only", site_profile=profile, target_lang=target_lang
    ).extract_from_ast(document.ast, document.frontmatter)
    matches = [unit for unit in plan.units if unit_fingerprint(unit) == fingerprint]
    if len(matches) != 1:
        raise ValueError(f"fingerprint resolved to {len(matches)} source units")
    disposition, rationale = classify_unit(
        matches[0], target_lang=target_lang, preserve_patterns=list(profile.body.preserve_patterns or [])
    )
    return {
        "fingerprint": fingerprint,
        "disposition": disposition,
        "rationale": rationale,
        "site_id": site_id,
        "target_lang": target_lang,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve a TC-SAS-01 fingerprint offline")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--target-lang", required=True)
    parser.add_argument("--config-root", type=Path, default=Path("config"))
    args = parser.parse_args(argv)
    print(json.dumps(resolve_fingerprint(
        source_path=args.source, fingerprint=args.fingerprint, site_id=args.site,
        target_lang=args.target_lang, config_root=args.config_root,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
