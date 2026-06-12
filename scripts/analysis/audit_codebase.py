"""Comprehensive codebase audit for incomplete implementations.

Scans for:
- Stubs (functions/methods with only 'pass' or 'return None')
- TODOs (# TODO, # FIXME, # XXX comments)
- Placeholders (raise NotImplementedError, 'TBD', 'PLACEHOLDER')
- Incomplete docstrings ("..." placeholders)
- Empty exception handlers (except: pass)
- Debug remnants (import pdb, breakpoint())
"""

import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Issue:
    """Represents a code quality issue."""

    category: str  # 'stub', 'todo', 'placeholder', 'not_implemented', 'empty_except', 'debug'
    severity: str  # 'critical', 'high', 'medium', 'low'
    file_path: str
    line_number: int
    line_content: str
    context: str  # Function/class name where issue found
    recommendation: str


class CodebaseAuditor:
    """Audits codebase for incomplete implementations."""

    # Patterns to search
    TODO_PATTERNS = [
        r"#\s*TODO",
        r"#\s*FIXME",
        r"#\s*XXX",
        r"#\s*HACK",
        r"#\s*BUG",
    ]

    PLACEHOLDER_PATTERNS = [
        r"TBD",
        r"PLACEHOLDER",
        r"NOT_IMPLEMENTED",
        r"STUB",
        r"\.\.\..*#.*implement",
    ]

    DEBUG_PATTERNS = [
        r"import\s+pdb",
        r"pdb\.set_trace\(",
        r"breakpoint\(",
        r"import\s+ipdb",
        r"print\(.*DEBUG",
    ]

    def __init__(self, root_dir: Path, exclude_patterns: list[str] = None):
        self.root_dir = root_dir
        self.exclude_patterns = exclude_patterns or [
            "*/venv/*",
            "*/venv_wsl/*",
            "*/__pycache__/*",
            "*.pyc",
            "*/.git/*",
            "*/node_modules/*",
            "*/build/*",
            "*/dist/*",
            "*/.pytest_cache/*",
            "*/htmlcov/*",
            "*/audit_report.*",  # Don't audit the audit report
        ]
        self.issues: list[Issue] = []

    def should_exclude(self, file_path: Path) -> bool:
        """Check if file should be excluded from audit."""
        path_str = str(file_path)
        for pattern in self.exclude_patterns:
            if Path(path_str).match(pattern.replace("*", "**")):
                return True
        return False

    def audit(self) -> list[Issue]:
        """Run full audit and return issues."""
        # Scan Python files
        for py_file in self.root_dir.rglob("*.py"):
            if self.should_exclude(py_file):
                continue
            self._audit_python_file(py_file)

        # Scan YAML config files
        for yaml_file in self.root_dir.rglob("*.yaml"):
            if self.should_exclude(yaml_file):
                continue
            self._audit_yaml_file(yaml_file)

        # Scan Markdown files for TODO sections
        for md_file in self.root_dir.rglob("*.md"):
            if self.should_exclude(md_file):
                continue
            self._audit_markdown_file(md_file)

        return self.issues

    def _audit_python_file(self, file_path: Path):
        """Audit a Python file for issues."""
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines()

            # AST-based analysis for stubs and NotImplementedError
            try:
                tree = ast.parse(content, filename=str(file_path))
                self._check_ast_issues(tree, file_path, lines)
            except SyntaxError:
                # File has syntax errors, skip AST analysis
                pass

            # Regex-based analysis for TODOs, placeholders, debug
            for line_num, line in enumerate(lines, start=1):
                self._check_line_issues(line, line_num, file_path)

        except Exception as e:
            print(f"Error auditing {file_path}: {e}", file=sys.stderr)

    def _check_ast_issues(self, tree: ast.AST, file_path: Path, lines: list[str]):
        """Check for AST-level issues (stubs, NotImplementedError)."""
        for node in ast.walk(tree):
            # Check for stub functions/methods
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_stub_function(node):
                    self.issues.append(
                        Issue(
                            category="stub",
                            severity="high",
                            file_path=str(file_path),
                            line_number=node.lineno,
                            line_content=lines[node.lineno - 1]
                            if node.lineno <= len(lines)
                            else "",
                            context=node.name,
                            recommendation=f"Implement {node.name}() or remove if unused",
                        )
                    )

            # Check for NotImplementedError
            if isinstance(node, ast.Raise):
                if isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name):
                    if node.exc.func.id == "NotImplementedError":
                        self.issues.append(
                            Issue(
                                category="not_implemented",
                                severity="critical",
                                file_path=str(file_path),
                                line_number=node.lineno,
                                line_content=lines[node.lineno - 1]
                                if node.lineno <= len(lines)
                                else "",
                                context=self._get_context_name(tree, node),
                                recommendation="Implement this functionality or document as intentionally unimplemented",
                            )
                        )

            # Check for empty except handlers
            if isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    self.issues.append(
                        Issue(
                            category="empty_except",
                            severity="medium",
                            file_path=str(file_path),
                            line_number=node.lineno,
                            line_content=lines[node.lineno - 1]
                            if node.lineno <= len(lines)
                            else "",
                            context=self._get_context_name(tree, node),
                            recommendation="Add logging or specific exception handling (avoid silent failures)",
                        )
                    )

    def _is_stub_function(self, node: ast.FunctionDef) -> bool:
        """Check if function is a stub (only pass or return None)."""
        # Ignore test functions
        if node.name.startswith("test_"):
            return False

        # Ignore __init__, __str__, etc. with minimal implementation
        if node.name.startswith("__") and node.name.endswith("__"):
            return False

        # Check if body is only 'pass' or 'return None'
        if len(node.body) == 1:
            stmt = node.body[0]
            if isinstance(stmt, ast.Pass):
                return True
            if isinstance(stmt, ast.Return) and (
                stmt.value is None
                or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
            ):
                return True

        # Check for docstring + pass
        if len(node.body) == 2:
            if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                if isinstance(node.body[1], ast.Pass):
                    return True

        return False

    def _get_context_name(self, tree: ast.AST, node: ast.AST) -> str:
        """Get the name of the function/class containing this node."""
        # Walk up AST to find enclosing function/class
        for parent in ast.walk(tree):
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for child in ast.walk(parent):
                    if child == node:
                        return parent.name
        return "<module>"

    def _check_line_issues(self, line: str, line_num: int, file_path: Path):
        """Check a single line for issues."""
        # Check for TODOs
        for pattern in self.TODO_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                self.issues.append(
                    Issue(
                        category="todo",
                        severity="low",
                        file_path=str(file_path),
                        line_number=line_num,
                        line_content=line.strip(),
                        context="",
                        recommendation="Address TODO or create a tracking issue and remove comment",
                    )
                )
                break  # Only report once per line

        # Check for placeholders
        for pattern in self.PLACEHOLDER_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                self.issues.append(
                    Issue(
                        category="placeholder",
                        severity="high",
                        file_path=str(file_path),
                        line_number=line_num,
                        line_content=line.strip(),
                        context="",
                        recommendation="Replace placeholder with actual implementation",
                    )
                )
                break

        # Check for debug remnants
        for pattern in self.DEBUG_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                self.issues.append(
                    Issue(
                        category="debug",
                        severity="medium",
                        file_path=str(file_path),
                        line_number=line_num,
                        line_content=line.strip(),
                        context="",
                        recommendation="Remove debug code before production deployment",
                    )
                )
                break

    def _audit_yaml_file(self, file_path: Path):
        """Audit YAML file for placeholders."""
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines()

            for line_num, line in enumerate(lines, start=1):
                # Check for placeholder values
                if re.search(r":\s*(TBD|TODO|FIXME|PLACEHOLDER)", line, re.IGNORECASE):
                    self.issues.append(
                        Issue(
                            category="placeholder",
                            severity="medium",
                            file_path=str(file_path),
                            line_number=line_num,
                            line_content=line.strip(),
                            context="",
                            recommendation="Replace placeholder config value with actual value",
                        )
                    )

        except Exception as e:
            print(f"Error auditing {file_path}: {e}", file=sys.stderr)

    def _audit_markdown_file(self, file_path: Path):
        """Audit Markdown file for TODO sections."""
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines()

            for line_num, line in enumerate(lines, start=1):
                # Check for TODO headings or list items
                if re.search(r"^#+\s*TODO", line, re.IGNORECASE):
                    self.issues.append(
                        Issue(
                            category="todo",
                            severity="low",
                            file_path=str(file_path),
                            line_number=line_num,
                            line_content=line.strip(),
                            context="",
                            recommendation="Complete TODO section or remove heading",
                        )
                    )
                elif re.search(r"^\s*[-*]\s*\[\s*\]\s*TODO", line, re.IGNORECASE):
                    self.issues.append(
                        Issue(
                            category="todo",
                            severity="low",
                            file_path=str(file_path),
                            line_number=line_num,
                            line_content=line.strip(),
                            context="",
                            recommendation="Complete TODO task or remove from list",
                        )
                    )

        except Exception as e:
            print(f"Error auditing {file_path}: {e}", file=sys.stderr)

    def generate_report(self, format: str = "markdown") -> str:
        """Generate audit report in specified format."""
        if format == "json":
            return json.dumps([asdict(issue) for issue in self.issues], indent=2)

        # Markdown report
        report = ["# Codebase Quality Audit Report\n"]
        report.append(f"**Total Issues**: {len(self.issues)}\n")

        # Summary by category
        by_category = defaultdict(list)
        for issue in self.issues:
            by_category[issue.category].append(issue)

        report.append("## Summary by Category\n")
        for category in sorted(by_category.keys()):
            count = len(by_category[category])
            report.append(f"- **{category.replace('_', ' ').title()}**: {count}")
        report.append("")

        # Summary by severity
        by_severity = defaultdict(int)
        for issue in self.issues:
            by_severity[issue.severity] += 1

        report.append("## Summary by Severity\n")
        for severity in ["critical", "high", "medium", "low"]:
            count = by_severity.get(severity, 0)
            report.append(f"- **{severity.title()}**: {count}")
        report.append("")

        # Detailed issues by category
        report.append("## Detailed Issues\n")
        for category in sorted(by_category.keys()):
            issues = by_category[category]
            report.append(f"### {category.replace('_', ' ').title()} ({len(issues)} issues)\n")

            # Group by file
            by_file = defaultdict(list)
            for issue in issues:
                by_file[issue.file_path].append(issue)

            for file_path in sorted(by_file.keys()):
                report.append(f"#### {file_path}\n")
                for issue in sorted(by_file[file_path], key=lambda i: i.line_number):
                    report.append(f"**Line {issue.line_number}** (Severity: {issue.severity})")
                    if issue.context:
                        report.append(f"- Context: `{issue.context}`")
                    report.append(f"- Code: `{issue.line_content}`")
                    report.append(f"- Recommendation: {issue.recommendation}")
                    report.append("")

        return "\n".join(report)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Audit codebase for incomplete implementations")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Root directory to audit")
    parser.add_argument("--output", type=Path, help="Output file path")
    parser.add_argument(
        "--format", choices=["markdown", "json"], default="markdown", help="Output format"
    )
    parser.add_argument("--summary", action="store_true", help="Print summary only")
    args = parser.parse_args()

    auditor = CodebaseAuditor(args.root)
    print(f"Auditing {args.root}...", file=sys.stderr)
    issues = auditor.audit()

    if args.summary:
        # Print summary to stdout
        by_category = defaultdict(int)
        for issue in issues:
            by_category[issue.category] += 1

        print(f"Total issues: {len(issues)}")
        for category in sorted(by_category.keys()):
            print(f"{category.replace('_', ' ').title()}: {by_category[category]}")
        return

    # Generate full report
    report = auditor.generate_report(format=args.format)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
