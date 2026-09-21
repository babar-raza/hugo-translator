"""One-off debug harness (TC-APT-104): translate a single file/language and
print exactly which inline-code spans / fenced-block counts StructureValidator
sees on each side, to distinguish a real dropped-identifier defect from a
counting-methodology false positive (e.g. fenced-block content leaking into
the inline-span count). Extends debug_translate_one.py's pattern. Prints
short backtick-span text to stdout for live diagnosis only -- never persists
candidate text to any tracked file, matching debug_translate_one.py's rule.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_INLINE_RE = re.compile(r"`[^`]+`")
_FENCE_RE = re.compile(r"^```", re.MULTILINE)


def _report(label: str, source: str, translation: str) -> None:
    src_inline = _INLINE_RE.findall(source)
    tgt_inline = _INLINE_RE.findall(translation)
    src_fence = len(_FENCE_RE.findall(source)) // 2
    tgt_fence = len(_FENCE_RE.findall(translation)) // 2
    print(f"=== {label} ===")
    print(f"fenced blocks: source={src_fence} translation={tgt_fence}")
    print(f"inline spans:  source={len(src_inline)} translation={len(tgt_inline)}")
    src_set, tgt_set = set(src_inline), set(tgt_inline)
    only_src = src_set - tgt_set
    only_tgt = tgt_set - src_set
    print(f"spans only in source ({len(only_src)}): {sorted(only_src)[:30]}")
    print(f"spans only in translation ({len(only_tgt)}): {sorted(only_tgt)[:30]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debug harness: inline-code-count diff")
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--source-path", required=True, help="content-repo-relative path")
    parser.add_argument("--target-lang", required=True)
    parser.add_argument("--primary-model", default=None)
    args = parser.parse_args(argv)

    translator_repo = Path.cwd().resolve()

    from src.translation_engine.validation import structure_validator as sv_module
    from scripts.ops.debug_translate_one import build_real_engine

    captured: list[tuple[str, str]] = []
    original = sv_module.StructureValidator._count_code_blocks

    def _patched(self, text: str) -> int:  # noqa: ANN001
        return original(self, text)

    original_check = sv_module.StructureValidator._check_code_blocks

    def _patched_check(self, source: str, translation: str, result):  # noqa: ANN001
        captured.append((source, translation))
        return original_check(self, source, translation, result)

    sv_module.StructureValidator._check_code_blocks = _patched_check

    engine = build_real_engine(translator_repo)
    if args.primary_model:
        engine.model_id_override = args.primary_model

    try:
        result = engine.translate_file(
            args.site_id,
            Path(args.source_path),
            target_langs=[args.target_lang],
            force=False,
            force_overwrite=False,
            validate=True,
            trigger_type="debug_harness",
        )
    finally:
        sv_module.StructureValidator._check_code_blocks = original_check

    print("=== TranslationResult ===")
    print("success:", result.success)
    print("errors:", result.errors)
    print("warnings:", result.warnings)
    print("error:", result.error)
    print("validation_decision:", result.validation_decision)
    print("decision_reason:", result.decision_reason)
    print("retry_attempts:", result.retry_attempts)
    for entry in result.retry_history:
        print("retry_history entry:", entry)

    if not captured:
        print("StructureValidator._check_code_blocks was never invoked (no candidate reached it).")
        return 0

    for i, (source, translation) in enumerate(captured):
        _report(f"attempt {i + 1}", source, translation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
