#!/usr/bin/env python3
"""
Generate comprehensive file manifest for repository inventory.

This script analyzes all files in the repository and categorizes them
into defined categories with metadata for each file.

Usage:
    python scripts/generate_file_manifest.py [--repo-root PATH] [--output-dir PATH]

Categories:
    - source_code: src/**/*.py files
    - tests: tests/**/*.py or files starting with test_
    - config: config/**/*, *.yaml, *.yml, *.toml, pyproject.toml
    - data: data/**/*
    - docs: docs/**/*, *.md files
    - scripts: scripts/**/*
    - artifacts: Everything else that's not ignored
    - ignore: .git/, __pycache__/, .pytest_cache/, node_modules/, *.pyc, venv/
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Patterns to ignore (not counted in manifest)
IGNORE_PATTERNS: set[str] = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".mypy_cache",
    ".venv",
    "venv",
    "venv-",
    ".coverage",
    "htmlcov",
    ".benchmarks",
    ".cache",
    "*.pyc",
    "*.pyo",
    "*.egg-info",
    ".env",
}


def should_ignore(path: Path) -> bool:
    """Check if a path should be ignored based on patterns."""
    path_str = str(path)
    path_parts = path.parts

    for part in path_parts:
        # Check direct matches
        if part in IGNORE_PATTERNS:
            return True
        # Check prefix matches (e.g., venv-, .venv-)
        for pattern in IGNORE_PATTERNS:
            if pattern.endswith("-") and part.startswith(pattern):
                return True
            if pattern.startswith("*") and part.endswith(pattern[1:]):
                return True
        # Check for venv variations
        if "venv" in part.lower() and (part.startswith("venv") or part.startswith(".venv")):
            return True

    # Check file extension patterns
    if path.suffix in [".pyc", ".pyo"]:
        return True

    # Check for egg-info directories
    if path_str.endswith(".egg-info") or ".egg-info" in path_str:
        return True

    return False


def analyze_file(path: Path, repo_root: Path) -> dict[str, Any]:
    """Analyze file metadata."""
    try:
        stat = path.stat()
        relative_path = path.relative_to(repo_root)
        return {
            "path": str(relative_path).replace("\\", "/"),
            "absolute_path": str(path),
            "size_bytes": stat.st_size,
            "modified_timestamp": stat.st_mtime,
            "modified_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "extension": path.suffix.lower() if path.suffix else "",
            "directory": str(relative_path.parent).replace("\\", "/"),
            "filename": path.name,
        }
    except (OSError, PermissionError) as e:
        return {
            "path": str(path.relative_to(repo_root)).replace("\\", "/"),
            "error": str(e),
        }


def categorize_file(path: Path, repo_root: Path) -> str:
    """Determine the category for a file."""
    relative_path = path.relative_to(repo_root)
    path_str = str(relative_path).replace("\\", "/")
    parts = relative_path.parts

    # Check if should be ignored first
    if should_ignore(relative_path):
        return "ignore"

    # Tests: tests/**/*.py or files starting with test_
    if len(parts) > 0 and parts[0] == "tests":
        return "tests"
    if path.name.startswith("test_") and path.suffix == ".py":
        return "tests"

    # Source code: src/**/*.py
    if len(parts) > 0 and parts[0] == "src" and path.suffix == ".py":
        return "source_code"

    # Config: config/**/*, *.yaml, *.yml, *.toml, pyproject.toml
    if len(parts) > 0 and parts[0] == "config":
        return "config"
    if path.suffix in [".yaml", ".yml", ".toml"]:
        return "config"
    if path.name == "pyproject.toml":
        return "config"

    # Data: data/**/*
    if len(parts) > 0 and parts[0] == "data":
        return "data"

    # Docs: docs/**/*, *.md files
    if len(parts) > 0 and parts[0] == "docs":
        return "docs"
    if path.suffix == ".md":
        return "docs"

    # Scripts: scripts/**/*
    if len(parts) > 0 and parts[0] == "scripts":
        return "scripts"

    # Everything else is artifacts
    return "artifacts"


def generate_manifest(repo_root: str, verbose: bool = False) -> dict[str, Any]:
    """Generate comprehensive file manifest."""
    root = Path(repo_root).resolve()

    manifest: dict[str, list[dict[str, Any]]] = {
        "source_code": [],
        "tests": [],
        "config": [],
        "data": [],
        "docs": [],
        "scripts": [],
        "artifacts": [],
        "ignore": [],
    }

    # Track statistics
    total_files = 0
    total_size = 0
    errors = []

    if verbose:
        print(f"Scanning repository: {root}")

    for path in root.rglob("*"):
        try:
            # Use try/except for is_file() to handle broken symlinks
            if not path.is_file():
                continue
        except (OSError, PermissionError):
            # Skip files that can't be accessed (broken symlinks, permission issues)
            continue

        total_files += 1

        try:
            file_info = analyze_file(path, root)
            category = categorize_file(path, root)

            if "error" not in file_info:
                total_size += file_info.get("size_bytes", 0)
            else:
                errors.append(file_info)

            manifest[category].append(file_info)

            if verbose and total_files % 100 == 0:
                print(f"  Processed {total_files} files...")

        except Exception as e:
            errors.append(
                {
                    "path": str(path.relative_to(root)),
                    "error": str(e),
                }
            )

    # Add metadata
    result = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "repo_root": str(root),
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_human": format_size(total_size),
            "categories": list(manifest.keys()),
            "error_count": len(errors),
        },
        "categories": manifest,
        "summary": {
            category: {
                "count": len(files),
                "total_bytes": sum(f.get("size_bytes", 0) for f in files if "error" not in f),
            }
            for category, files in manifest.items()
        },
    }

    if errors:
        result["errors"] = errors

    return result


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def generate_summary_markdown(manifest: dict[str, Any]) -> str:
    """Generate human-readable summary in Markdown format."""
    lines = [
        "# File Manifest Summary",
        "",
        f"**Generated:** {manifest['metadata']['generated_at']}",
        f"**Repository:** {manifest['metadata']['repo_root']}",
        "",
        "## Overview",
        "",
        f"- **Total Files:** {manifest['metadata']['total_files']:,}",
        f"- **Total Size:** {manifest['metadata']['total_size_human']}",
        f"- **Categories:** {len(manifest['metadata']['categories'])}",
        "",
        "## Category Breakdown",
        "",
        "| Category | File Count | Total Size | % of Total |",
        "|----------|-----------|------------|------------|",
    ]

    total_files = manifest["metadata"]["total_files"]
    total_bytes = manifest["metadata"]["total_size_bytes"]

    # Sort categories by file count (descending)
    sorted_categories = sorted(
        manifest["summary"].items(), key=lambda x: x[1]["count"], reverse=True
    )

    for category, stats in sorted_categories:
        count = stats["count"]
        size = stats["total_bytes"]
        pct = (count / total_files * 100) if total_files > 0 else 0
        lines.append(f"| {category} | {count:,} | {format_size(size)} | {pct:.1f}% |")

    lines.extend(
        [
            "",
            "## Category Definitions",
            "",
            "- **source_code:** Python source files in `src/` directory",
            "- **tests:** Test files in `tests/` or starting with `test_`",
            "- **config:** Configuration files (YAML, TOML) and `config/` directory",
            "- **data:** Files in `data/` directory",
            "- **docs:** Documentation files (Markdown) and `docs/` directory",
            "- **scripts:** Utility scripts in `scripts/` directory",
            "- **artifacts:** Other files not matching above categories",
            "- **ignore:** System/cache files (`.git/`, `__pycache__/`, `venv/`, etc.)",
            "",
            "## Top 10 Largest Files",
            "",
        ]
    )

    # Find top 10 largest files (excluding ignored)
    all_files = []
    for category, files in manifest["categories"].items():
        if category != "ignore":
            for f in files:
                if "error" not in f and f.get("size_bytes", 0) > 0:
                    all_files.append((f, category))

    all_files.sort(key=lambda x: x[0].get("size_bytes", 0), reverse=True)

    lines.append("| Rank | File | Size | Category |")
    lines.append("|------|------|------|----------|")

    for i, (f, category) in enumerate(all_files[:10], 1):
        path = f["path"]
        size = format_size(f["size_bytes"])
        lines.append(f"| {i} | `{path}` | {size} | {category} |")

    lines.extend(
        [
            "",
            "## File Extensions Summary",
            "",
        ]
    )

    # Count extensions
    ext_counts: dict[str, int] = {}
    ext_sizes: dict[str, int] = {}
    for category, files in manifest["categories"].items():
        if category != "ignore":
            for f in files:
                if "error" not in f:
                    ext = f.get("extension", "") or "(no extension)"
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
                    ext_sizes[ext] = ext_sizes.get(ext, 0) + f.get("size_bytes", 0)

    sorted_exts = sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    lines.append("| Extension | Count | Total Size |")
    lines.append("|-----------|-------|------------|")

    for ext, count in sorted_exts:
        size = format_size(ext_sizes[ext])
        lines.append(f"| `{ext}` | {count:,} | {size} |")

    lines.extend(
        [
            "",
            "---",
            "",
            "*This manifest was generated automatically by `scripts/generate_file_manifest.py`*",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate comprehensive file manifest for repository inventory"
    )
    parser.add_argument(
        "--repo-root",
        type=str,
        default=".",
        help="Path to repository root (default: current directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/autonomous_workers",
        help="Output directory for manifest files",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Only output JSON (skip markdown summary)",
    )

    args = parser.parse_args()

    # Resolve paths
    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating file manifest for: {repo_root}")
    print(f"Output directory: {output_dir}")
    print()

    # Generate manifest
    manifest = generate_manifest(str(repo_root), verbose=args.verbose)

    # Save JSON manifest
    json_path = output_dir / "FILE_MANIFEST.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"JSON manifest saved to: {json_path}")

    # Generate and save markdown summary
    if not args.json_only:
        summary_md = generate_summary_markdown(manifest)
        md_path = output_dir / "FILE_MANIFEST_SUMMARY.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(summary_md)
        print(f"Summary saved to: {md_path}")

    # Print summary to console
    print()
    print("=" * 60)
    print("FILE MANIFEST SUMMARY")
    print("=" * 60)
    print(f"Total files: {manifest['metadata']['total_files']:,}")
    print(f"Total size: {manifest['metadata']['total_size_human']}")
    print()
    print("Category breakdown:")
    for category, stats in sorted(
        manifest["summary"].items(), key=lambda x: x[1]["count"], reverse=True
    ):
        print(
            f"  {category:15} {stats['count']:>6,} files  ({format_size(stats['total_bytes']):>10})"
        )
    print("=" * 60)

    if manifest.get("errors"):
        print(f"\nWarning: {len(manifest['errors'])} files had errors during processing")

    return 0


if __name__ == "__main__":
    sys.exit(main())
