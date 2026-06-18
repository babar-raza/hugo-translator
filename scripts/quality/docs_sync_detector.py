"""docs_sync_detector.py — Advisory docs/source sync checker.

Accepts a list of changed src/ files (from git diff --name-only or CLI args).
For each src/<module>.py, checks if any docs/**/*<module>*.md file exists.
Emits WARNING lines for unmatched source modules.

Always exits 0 — this is an advisory tool, never a blocking gate.

Usage:
    python scripts/quality/docs_sync_detector.py src/workers/supervisor_loop.py
    python scripts/quality/docs_sync_detector.py src/translation_engine/engine.py
    git diff --name-only HEAD~1 HEAD | python scripts/quality/docs_sync_detector.py --stdin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Module name → expected docs path fragment (override for well-known modules)
# These overrides prevent false positives for modules whose docs live under
# a different name than the module file.
_KNOWN_DOC_OVERRIDES: dict[str, str] = {
    "engine": "translation-engine",
    "engine_builder": "translation-engine",
    "file_pipeline": "translation-engine",
    "segment_translator": "translation-engine",
    "write_gate": "translation-engine",
    "translation_memory": "translation-memory",
    "l1_cache": "translation-memory",
    "l2_persistent": "translation-memory",
    "l3_faiss": "translation-memory",
    "l4_llm": "l4-llm",
    "agent_metrics_poster": "agent-metrics-api",
    "agent_metrics_payload": "agent-metrics-api",
    "agent_metrics_integration": "agent-metrics-api",
    "metrics_scope": "agent-metrics-api",
    "supervisor_loop": "autonomous-operation",
    "task_queue": "autonomous-operation",
    "continuation_state": "autonomous-operation",
    "run_signal_emitter": "autonomous-operation",
    "blocker_classifier": "autonomous-operation",
    "contradiction_detector": "autonomous-operation",
    "run_summarizer": "autonomous-operation",
}


def _module_name(src_path: Path) -> str:
    """Extract module stem from a src/ path."""
    return src_path.stem


def _find_docs_for_module(module: str, docs_root: Path) -> list[Path]:
    """Return all docs/**/*.md files whose name contains the doc fragment for module."""
    fragment = _KNOWN_DOC_OVERRIDES.get(module, module.replace("_", "-"))
    matches = [p for p in docs_root.rglob("*.md") if fragment in p.stem]
    return matches


def _is_src_file(path: Path) -> bool:
    """Return True if path is a non-test Python source file under src/."""
    try:
        parts = path.parts
    except Exception:
        return False
    return (
        path.suffix == ".py"
        and "src" in parts
        and not path.stem.startswith("test_")
        and "__pycache__" not in parts
    )


def run(src_files: list[str], docs_root: Path) -> int:
    """Check src files for missing documentation. Returns count of warnings."""
    warnings = 0
    found = 0

    for raw in src_files:
        p = Path(raw.strip())
        if not _is_src_file(p):
            continue

        module = _module_name(p)
        if module in ("__init__", "conftest", "setup"):
            continue

        docs = _find_docs_for_module(module, docs_root)
        if docs:
            found += 1
        else:
            fragment = _KNOWN_DOC_OVERRIDES.get(module, module.replace("_", "-"))
            print(f"WARNING: No docs found for '{module}' (searched docs/**/*{fragment}*.md) — {p}")
            warnings += 1

    print(f"\ndocs-sync-detector: {found} documented, {warnings} undocumented module(s)")
    if warnings:
        print("  Advisory only — create or update docs/ entries for the above modules.")
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Advisory docs/source sync checker. Always exits 0.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Source file paths to check (e.g. src/workers/supervisor_loop.py)",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read file paths from stdin (one per line, e.g. git diff --name-only | ...)",
    )
    parser.add_argument(
        "--docs",
        default="docs",
        metavar="PATH",
        help="Docs root directory (default: docs/)",
    )
    args = parser.parse_args()

    src_files: list[str] = list(args.files)
    if args.stdin:
        src_files.extend(line.strip() for line in sys.stdin if line.strip())

    if not src_files:
        parser.print_help()
        sys.exit(0)

    docs_root = Path(args.docs)
    if not docs_root.exists():
        print(f"ERROR: docs root not found: {docs_root}", file=sys.stderr)
        sys.exit(0)  # advisory — never block

    run(src_files, docs_root)
    sys.exit(0)  # always exit 0 — advisory only


if __name__ == "__main__":
    main()
