#!/usr/bin/env python3
"""
File Inventory and Verification Tool

This tool provides comprehensive file inventory capabilities including:
- Recursive file scanning with categorization
- Line counting (total, code, comments, blank)
- File size tracking with human-readable formatting
- Modification time tracking
- Inventory comparison and diff generation
- JSON-based inventory format with schema validation

Usage:
    python scripts/inventory_files.py --scan
    python scripts/inventory_files.py --verify data/file_inventory.json
    python scripts/inventory_files.py --diff baseline.json current.json
    python scripts/inventory_files.py --scan --format markdown
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class FileInfo:
    """Information about a single file."""

    path: str
    category: str
    size_bytes: int
    size_human: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    modified_time: str
    hash: str | None = None


@dataclass
class InventoryStats:
    """Statistics for the entire inventory."""

    total_files: int
    total_size_bytes: int
    total_size_human: str
    total_lines: int
    total_code_lines: int
    total_comment_lines: int
    total_blank_lines: int
    files_by_category: dict[str, int]
    lines_by_category: dict[str, int]
    scan_time: str


@dataclass
class Inventory:
    """Complete file inventory."""

    project_root: str
    files: list[FileInfo]
    stats: InventoryStats
    version: str = "1.0"


class FileScanner:
    """Scans directory tree and categorizes files."""

    # Directories and patterns to exclude from scanning
    EXCLUDE_DIRS = {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".pytest_cache",
        "htmlcov",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "*.egg-info",
    }

    EXCLUDE_PATTERNS = {
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.so",
        "*.dll",
        "*.dylib",
        ".DS_Store",
        "Thumbs.db",
        "*.swp",
        "*.swo",
        "*~",
    }

    # Category mapping based on directory patterns
    CATEGORY_PATTERNS = {
        "scripts": ["scripts/", "script/"],
        "tests": ["tests/", "test/"],
        "src": ["src/", "lib/", "app/"],
        "docs": ["docs/", "documentation/", "doc/"],
        "config": ["config/", "conf/", ".github/", "docker/"],
        "requirements": ["requirements/", "requirements.txt"],
        "plans": ["plans/", "planning/"],
        "reports": ["reports/", "report/"],
        "data": ["data/", "datasets/"],
        "implementation": ["implementation/", "impl/"],
        "legacy": ["legacy/", "deprecated/"],
        "samples": ["samples/", "examples/"],
    }

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    def should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded from scanning."""
        # Check if any parent directory matches exclude patterns
        for part in path.parts:
            if part in self.EXCLUDE_DIRS:
                return True
            for pattern in self.EXCLUDE_PATTERNS:
                if self._match_pattern(part, pattern):
                    return True
        return False

    def _match_pattern(self, name: str, pattern: str) -> bool:
        """Match a name against a glob-style pattern."""
        if pattern.startswith("*") and pattern.endswith("*"):
            return pattern[1:-1] in name
        elif pattern.startswith("*"):
            return name.endswith(pattern[1:])
        elif pattern.endswith("*"):
            return name.startswith(pattern[:-1])
        else:
            return name == pattern

    def categorize_file(self, file_path: Path) -> str:
        """Categorize a file based on its path."""
        relative_path = str(file_path.relative_to(self.root_dir)).replace("\\", "/")

        # Check each category pattern
        for category, patterns in self.CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if relative_path.startswith(pattern) or pattern in relative_path:
                    return category

        # Default category based on location
        if relative_path.count("/") == 0:
            return "root"
        else:
            return "other"

    def scan(self) -> list[tuple[Path, str]]:
        """
        Scan the directory tree and return list of (file_path, category) tuples.

        Returns:
            List of tuples containing file paths and their categories
        """
        files = []

        for root, dirs, filenames in os.walk(self.root_dir):
            root_path = Path(root)

            # Filter out excluded directories (modify dirs in-place)
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]

            for filename in filenames:
                file_path = root_path / filename

                # Skip excluded files
                if self.should_exclude(file_path):
                    continue

                # Skip non-text files by extension (basic check)
                if file_path.suffix in {".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin"}:
                    continue

                category = self.categorize_file(file_path)
                files.append((file_path, category))

        return files


class LineCounter:
    """Counts lines in files, categorizing them as code, comments, or blank."""

    # Comment patterns for different file types
    COMMENT_PATTERNS = {
        ".py": [
            (re.compile(r"^\s*#"), "single"),  # Python single-line
            (re.compile(r'^\s*"""'), "multi"),  # Python docstring
            (re.compile(r"^\s*'''"), "multi"),  # Python docstring
        ],
        ".js": [
            (re.compile(r"^\s*//"), "single"),  # JS single-line
            (re.compile(r"^\s*/\*"), "multi_start"),  # JS multi-line start
            (re.compile(r"\*/\s*$"), "multi_end"),  # JS multi-line end
        ],
        ".yaml": [
            (re.compile(r"^\s*#"), "single"),
        ],
        ".yml": [
            (re.compile(r"^\s*#"), "single"),
        ],
        ".sh": [
            (re.compile(r"^\s*#"), "single"),
        ],
        ".md": [
            (re.compile(r"^\s*<!--"), "multi_start"),
            (re.compile(r"-->\s*$"), "multi_end"),
        ],
    }

    def count_lines(self, file_path: Path) -> tuple[int, int, int, int]:
        """
        Count lines in a file.

        Returns:
            Tuple of (total_lines, code_lines, comment_lines, blank_lines)
        """
        try:
            # Try to read as text file
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            # If we can't read it, treat as binary
            return (0, 0, 0, 0)

        total_lines = len(lines)
        blank_lines = 0
        comment_lines = 0
        in_multiline_comment = False

        comment_patterns = self.COMMENT_PATTERNS.get(file_path.suffix, [])

        for line in lines:
            stripped = line.strip()

            # Blank line
            if not stripped:
                blank_lines += 1
                continue

            # Check for comments
            is_comment = False

            # Check for multi-line comment continuation
            if in_multiline_comment:
                comment_lines += 1
                # Check if multi-line comment ends
                for pattern, ptype in comment_patterns:
                    if ptype == "multi_end" and pattern.search(line):
                        in_multiline_comment = False
                        break
                continue

            # Check for comment start
            for pattern, ptype in comment_patterns:
                if ptype == "single" and pattern.match(line):
                    is_comment = True
                    break
                elif ptype in ("multi", "multi_start") and pattern.search(line):
                    is_comment = True
                    if ptype == "multi_start":
                        in_multiline_comment = True
                    # Check if it's a one-line multi-comment (/* ... */)
                    if ptype == "multi_start":
                        for end_pattern, end_type in comment_patterns:
                            if end_type == "multi_end" and end_pattern.search(line):
                                in_multiline_comment = False
                                break
                    break

            if is_comment:
                comment_lines += 1
            # Note: We don't explicitly count code lines, we calculate them

        code_lines = total_lines - blank_lines - comment_lines

        return (total_lines, code_lines, comment_lines, blank_lines)


class InventoryManager:
    """Manages inventory creation, loading, saving, and comparison."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.scanner = FileScanner(root_dir)
        self.counter = LineCounter()

    def create_inventory(self) -> Inventory:
        """Create a complete inventory of the project."""
        print(f"Scanning directory: {self.root_dir}")
        files_data = self.scanner.scan()
        print(f"Found {len(files_data)} files to analyze")

        file_infos = []
        total_size = 0
        total_lines = 0
        total_code = 0
        total_comments = 0
        total_blank = 0
        files_by_category = defaultdict(int)
        lines_by_category = defaultdict(int)

        for idx, (file_path, category) in enumerate(files_data, 1):
            if idx % 100 == 0:
                print(f"Processing file {idx}/{len(files_data)}...")

            # Get file stats
            try:
                stat = file_path.stat()
                size = stat.st_size
                mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except Exception:
                continue

            # Count lines
            t_lines, c_lines, cm_lines, b_lines = self.counter.count_lines(file_path)

            # Create file info
            relative_path = str(file_path.relative_to(self.root_dir)).replace("\\", "/")
            file_info = FileInfo(
                path=relative_path,
                category=category,
                size_bytes=size,
                size_human=self._format_size(size),
                total_lines=t_lines,
                code_lines=c_lines,
                comment_lines=cm_lines,
                blank_lines=b_lines,
                modified_time=mtime,
            )

            file_infos.append(file_info)

            # Update totals
            total_size += size
            total_lines += t_lines
            total_code += c_lines
            total_comments += cm_lines
            total_blank += b_lines
            files_by_category[category] += 1
            lines_by_category[category] += t_lines

        # Create stats
        stats = InventoryStats(
            total_files=len(file_infos),
            total_size_bytes=total_size,
            total_size_human=self._format_size(total_size),
            total_lines=total_lines,
            total_code_lines=total_code,
            total_comment_lines=total_comments,
            total_blank_lines=total_blank,
            files_by_category=dict(files_by_category),
            lines_by_category=dict(lines_by_category),
            scan_time=datetime.now().isoformat(),
        )

        inventory = Inventory(project_root=str(self.root_dir), files=file_infos, stats=stats)

        print(f"\nInventory complete: {stats.total_files} files, {stats.total_lines} lines")
        return inventory

    def save_inventory(self, inventory: Inventory, output_path: str):
        """Save inventory to JSON file."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w", encoding="utf-8") as f:
            json.dump(asdict(inventory), f, indent=2, ensure_ascii=False)

        print(f"Inventory saved to: {output}")

    def load_inventory(self, input_path: str) -> Inventory:
        """Load inventory from JSON file."""
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)

        # Reconstruct dataclasses
        files = [FileInfo(**f) for f in data["files"]]
        stats = InventoryStats(**data["stats"])
        inventory = Inventory(
            project_root=data["project_root"],
            files=files,
            stats=stats,
            version=data.get("version", "1.0"),
        )

        return inventory

    def verify_inventory(self, inventory_path: str) -> bool:
        """Verify that files in inventory still exist and match."""
        inventory = self.load_inventory(inventory_path)
        print(f"Verifying inventory: {inventory_path}")
        print(f"Expected {inventory.stats.total_files} files\n")

        missing_files = []
        changed_files = []

        for file_info in inventory.files:
            file_path = self.root_dir / file_info.path

            if not file_path.exists():
                missing_files.append(file_info.path)
                continue

            # Check if file size changed
            current_size = file_path.stat().st_size
            if current_size != file_info.size_bytes:
                changed_files.append((file_info.path, file_info.size_bytes, current_size))

        # Report results
        if not missing_files and not changed_files:
            print("✓ All files verified successfully")
            return True

        if missing_files:
            print(f"\n✗ Missing files ({len(missing_files)}):")
            for path in missing_files[:10]:
                print(f"  - {path}")
            if len(missing_files) > 10:
                print(f"  ... and {len(missing_files) - 10} more")

        if changed_files:
            print(f"\n⚠ Changed files ({len(changed_files)}):")
            for path, old_size, new_size in changed_files[:10]:
                print(f"  - {path}: {old_size} → {new_size} bytes")
            if len(changed_files) > 10:
                print(f"  ... and {len(changed_files) - 10} more")

        return False

    def compare_inventories(self, baseline_path: str, current_path: str) -> dict:
        """Compare two inventories and generate diff."""
        baseline = self.load_inventory(baseline_path)
        current = self.load_inventory(current_path)

        baseline_files = {f.path: f for f in baseline.files}
        current_files = {f.path: f for f in current.files}

        baseline_paths = set(baseline_files.keys())
        current_paths = set(current_files.keys())

        added = current_paths - baseline_paths
        removed = baseline_paths - current_paths
        common = baseline_paths & current_paths

        modified = []
        for path in common:
            if (
                baseline_files[path].size_bytes != current_files[path].size_bytes
                or baseline_files[path].total_lines != current_files[path].total_lines
            ):
                modified.append(path)

        diff = {
            "baseline": {
                "path": baseline_path,
                "total_files": baseline.stats.total_files,
                "total_lines": baseline.stats.total_lines,
                "scan_time": baseline.stats.scan_time,
            },
            "current": {
                "path": current_path,
                "total_files": current.stats.total_files,
                "total_lines": current.stats.total_lines,
                "scan_time": current.stats.scan_time,
            },
            "changes": {
                "added_files": len(added),
                "removed_files": len(removed),
                "modified_files": len(modified),
                "unchanged_files": len(common) - len(modified),
            },
            "added": sorted(list(added)),
            "removed": sorted(list(removed)),
            "modified": sorted(modified),
        }

        return diff

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format size in human-readable format."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"


class Reporter:
    """Generates reports from inventory data."""

    @staticmethod
    def generate_summary(inventory: Inventory) -> str:
        """Generate a text summary of the inventory."""
        lines = [
            "File Inventory Summary",
            "=" * 60,
            f"Project: {inventory.project_root}",
            f"Scanned: {inventory.stats.scan_time}",
            "",
            "Overall Statistics:",
            f"  Total files: {inventory.stats.total_files}",
            f"  Total size: {inventory.stats.total_size_human} ({inventory.stats.total_size_bytes:,} bytes)",
            f"  Total lines: {inventory.stats.total_lines:,}",
            f"    Code lines: {inventory.stats.total_code_lines:,}",
            f"    Comment lines: {inventory.stats.total_comment_lines:,}",
            f"    Blank lines: {inventory.stats.total_blank_lines:,}",
            "",
            "Files by Category:",
        ]

        for category, count in sorted(
            inventory.stats.files_by_category.items(), key=lambda x: x[1], reverse=True
        ):
            lines_count = inventory.stats.lines_by_category.get(category, 0)
            lines.append(f"  {category:15s}: {count:4d} files, {lines_count:7,d} lines")

        return "\n".join(lines)

    @staticmethod
    def generate_markdown(inventory: Inventory) -> str:
        """Generate a Markdown report of the inventory."""
        lines = [
            "# File Inventory Report",
            "",
            f"**Project:** {inventory.project_root}  ",
            f"**Scanned:** {inventory.stats.scan_time}  ",
            "",
            "## Overall Statistics",
            "",
            f"- **Total files:** {inventory.stats.total_files}",
            f"- **Total size:** {inventory.stats.total_size_human} ({inventory.stats.total_size_bytes:,} bytes)",
            f"- **Total lines:** {inventory.stats.total_lines:,}",
            f"  - Code lines: {inventory.stats.total_code_lines:,}",
            f"  - Comment lines: {inventory.stats.total_comment_lines:,}",
            f"  - Blank lines: {inventory.stats.total_blank_lines:,}",
            "",
            "## Files by Category",
            "",
            "| Category | Files | Lines |",
            "|----------|------:|------:|",
        ]

        for category, count in sorted(
            inventory.stats.files_by_category.items(), key=lambda x: x[1], reverse=True
        ):
            lines_count = inventory.stats.lines_by_category.get(category, 0)
            lines.append(f"| {category} | {count:,} | {lines_count:,} |")

        return "\n".join(lines)

    @staticmethod
    def print_diff(diff: dict):
        """Print a comparison diff."""
        print("\nInventory Comparison")
        print("=" * 60)
        print(f"Baseline: {diff['baseline']['path']}")
        print(
            f"  Files: {diff['baseline']['total_files']}, Lines: {diff['baseline']['total_lines']:,}"
        )
        print(f"Current: {diff['current']['path']}")
        print(
            f"  Files: {diff['current']['total_files']}, Lines: {diff['current']['total_lines']:,}"
        )
        print()
        print("Changes:")
        print(f"  Added files: {diff['changes']['added_files']}")
        print(f"  Removed files: {diff['changes']['removed_files']}")
        print(f"  Modified files: {diff['changes']['modified_files']}")
        print(f"  Unchanged files: {diff['changes']['unchanged_files']}")

        if diff["added"]:
            print(f"\nAdded files ({len(diff['added'])}):")
            for path in diff["added"][:10]:
                print(f"  + {path}")
            if len(diff["added"]) > 10:
                print(f"  ... and {len(diff['added']) - 10} more")

        if diff["removed"]:
            print(f"\nRemoved files ({len(diff['removed'])}):")
            for path in diff["removed"][:10]:
                print(f"  - {path}")
            if len(diff["removed"]) > 10:
                print(f"  ... and {len(diff['removed']) - 10} more")

        if diff["modified"]:
            print(f"\nModified files ({len(diff['modified'])}):")
            for path in diff["modified"][:10]:
                print(f"  ~ {path}")
            if len(diff["modified"]) > 10:
                print(f"  ... and {len(diff['modified']) - 10} more")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="File Inventory and Verification Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create inventory
  python scripts/inventory_files.py --scan --output data/file_inventory.json

  # Verify inventory
  python scripts/inventory_files.py --verify data/file_inventory.json

  # Compare inventories
  python scripts/inventory_files.py --diff baseline.json current.json

  # Generate markdown report
  python scripts/inventory_files.py --scan --format markdown
        """,
    )

    parser.add_argument("--scan", action="store_true", help="Scan project and create inventory")
    parser.add_argument("--verify", metavar="INVENTORY", help="Verify files against inventory")
    parser.add_argument(
        "--diff", nargs=2, metavar=("BASELINE", "CURRENT"), help="Compare two inventories"
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Output file path (default: data/file_inventory.json)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "summary"],
        default="summary",
        help="Output format (default: summary)",
    )
    parser.add_argument(
        "--root", metavar="DIR", help="Project root directory (default: current directory)"
    )

    args = parser.parse_args()

    # Determine root directory
    if args.root:
        root_dir = args.root
    else:
        # Try to find git root, otherwise use current directory
        current = Path.cwd()
        while current != current.parent:
            if (current / ".git").exists():
                root_dir = str(current)
                break
            current = current.parent
        else:
            root_dir = os.getcwd()

    manager = InventoryManager(root_dir)

    # Execute command
    if args.scan:
        inventory = manager.create_inventory()

        if args.format == "json":
            output_path = args.output or "data/file_inventory.json"
            manager.save_inventory(inventory, output_path)
        elif args.format == "markdown":
            print(Reporter.generate_markdown(inventory))
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(Reporter.generate_markdown(inventory))
        else:  # summary
            print(Reporter.generate_summary(inventory))
            if args.output:
                output_path = args.output or "data/file_inventory.json"
                manager.save_inventory(inventory, output_path)

    elif args.verify:
        success = manager.verify_inventory(args.verify)
        sys.exit(0 if success else 1)

    elif args.diff:
        diff = manager.compare_inventories(args.diff[0], args.diff[1])
        Reporter.print_diff(diff)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(diff, f, indent=2)
            print(f"\nDiff saved to: {args.output}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
