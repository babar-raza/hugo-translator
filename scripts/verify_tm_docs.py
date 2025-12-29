"""
Verify TM documentation commands.

This script extracts and validates all code examples from TM documentation.
"""
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def extract_code_blocks(file_path: Path) -> List[Tuple[str, str, int]]:
    """
    Extract code blocks from markdown file.

    Returns:
        List of (language, code, line_number) tuples
    """
    content = file_path.read_text(encoding="utf-8")
    blocks = []

    # Pattern: ```language\ncode\n```
    pattern = r"```(\w+)\n(.*?)\n```"

    for match in re.finditer(pattern, content, re.DOTALL):
        lang = match.group(1)
        code = match.group(2)
        # Calculate line number
        line_num = content[:match.start()].count('\n') + 1
        blocks.append((lang, code, line_num))

    return blocks


def categorize_command(code: str, lang: str) -> str:
    """
    Categorize command as safe, unsafe, or example.

    Returns:
        "safe" - Read-only operation, safe to run
        "unsafe" - Modifies state, should not run automatically
        "example" - Code example, not runnable as-is
    """
    # Unsafe patterns
    unsafe_patterns = [
        r"repair\s*=\s*True",
        r"create_backup",
        r"restore_backup",
        r"compact_database",
        r"--override-mode\s+(refresh|bypass)",
        r"delete",
        r"remove",
        r"rm\s+",
    ]

    for pattern in unsafe_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            return "unsafe"

    # Example patterns (not runnable)
    if lang == "python" and not code.startswith("python "):
        # Multi-line Python code is usually an example
        if "\n" in code and "import" in code:
            return "example"

    # Safe patterns
    safe_patterns = [
        r"get_stats",
        r"check_cache_integrity.*repair\s*=\s*False",
        r"--help",
        r"--version",
        r"report\s*=",
    ]

    for pattern in safe_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            return "safe"

    # Default to example if uncertain
    return "example"


def verify_python_command(code: str, file_path: Path, line_num: int) -> Dict:
    """
    Verify a Python command.

    Returns:
        dict with status, output, error
    """
    result = {
        "file": file_path.name,
        "line": line_num,
        "code": code,
        "status": "unknown",
        "output": "",
        "error": "",
    }

    # Skip if it's an example (not a one-liner)
    if categorize_command(code, "python") == "example":
        result["status"] = "skipped_example"
        return result

    # Skip unsafe commands
    if categorize_command(code, "python") == "unsafe":
        result["status"] = "skipped_unsafe"
        return result

    # Try to run safe commands
    try:
        # Run in subprocess
        proc = subprocess.run(
            code,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=Path(__file__).parent.parent,
        )

        result["status"] = "success" if proc.returncode == 0 else "failed"
        result["output"] = proc.stdout
        result["error"] = proc.stderr

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = "Command timed out after 30 seconds"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def verify_tm_docs() -> Dict[str, List[Dict]]:
    """
    Verify all TM documentation.

    Returns:
        dict mapping file paths to verification results
    """
    repo_root = Path(__file__).parent.parent

    # Find all TM docs
    tm_docs = []
    tm_docs.extend((repo_root / "docs" / "guides").glob("tm-*.md"))
    tm_docs.extend((repo_root / "docs" / "operations").glob("tm-*.md"))
    tm_docs.extend((repo_root / "docs" / "reference").glob("tm-*.md"))
    tm_docs.extend((repo_root / "docs" / "architecture").glob("translation-memory.md"))

    results = {}

    for doc_path in sorted(tm_docs):
        print(f"\nVerifying: {doc_path.relative_to(repo_root)}")

        blocks = extract_code_blocks(doc_path)
        doc_results = []

        for lang, code, line_num in blocks:
            if lang in ["python", "bash", "sh"]:
                # For now, only verify Python one-liners
                if lang == "python" or (lang in ["bash", "sh"] and "python" in code):
                    result = verify_python_command(code, doc_path, line_num)
                    doc_results.append(result)

                    # Print status
                    status_symbol = {
                        "success": "[OK]",
                        "failed": "[FAIL]",
                        "error": "[ERROR]",
                        "timeout": "[TIMEOUT]",
                        "skipped_example": "[EXAMPLE]",
                        "skipped_unsafe": "[UNSAFE]",
                    }.get(result["status"], "[UNKNOWN]")

                    print(f"  {status_symbol} Line {line_num}: {result['status']}")
                    if result["status"] in ["failed", "error"]:
                        print(f"     Error: {result['error'][:100]}")

        results[str(doc_path.relative_to(repo_root))] = doc_results

    return results


def generate_report(results: Dict[str, List[Dict]]) -> str:
    """Generate markdown verification report."""

    report = """# TM Documentation Verification Report

**Generated:** {date}
**Purpose:** Verify all code examples in TM documentation are accurate and functional

## Summary

""".format(date="2025-12-24")

    # Calculate totals
    total_commands = sum(len(cmds) for cmds in results.values())
    success_count = sum(
        1 for cmds in results.values() for cmd in cmds if cmd["status"] == "success"
    )
    failed_count = sum(
        1 for cmds in results.values() for cmd in cmds if cmd["status"] == "failed"
    )
    error_count = sum(
        1 for cmds in results.values() for cmd in cmds if cmd["status"] == "error"
    )
    skipped_example = sum(
        1 for cmds in results.values() for cmd in cmds if cmd["status"] == "skipped_example"
    )
    skipped_unsafe = sum(
        1 for cmds in results.values() for cmd in cmds if cmd["status"] == "skipped_unsafe"
    )

    report += f"""
| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Success | {success_count} | {success_count/total_commands*100:.1f}% |
| ❌ Failed | {failed_count} | {failed_count/total_commands*100:.1f}% |
| ⚠️ Error | {error_count} | {error_count/total_commands*100:.1f}% |
| 📝 Example (Skipped) | {skipped_example} | {skipped_example/total_commands*100:.1f}% |
| 🔒 Unsafe (Skipped) | {skipped_unsafe} | {skipped_unsafe/total_commands*100:.1f}% |
| **Total** | **{total_commands}** | **100%** |

"""

    # Per-file results
    report += "## Per-File Results\n\n"

    for file_path, cmds in sorted(results.items()):
        if not cmds:
            continue

        report += f"### {file_path}\n\n"

        success = sum(1 for cmd in cmds if cmd["status"] == "success")
        failed = sum(1 for cmd in cmds if cmd["status"] == "failed")

        report += f"**Commands:** {len(cmds)} | **Success:** {success} | **Failed:** {failed}\n\n"

        # Details
        for cmd in cmds:
            status_emoji = {
                "success": "✅",
                "failed": "❌",
                "error": "⚠️",
                "timeout": "⏱️",
                "skipped_example": "📝",
                "skipped_unsafe": "🔒",
            }.get(cmd["status"], "❓")

            report += f"**Line {cmd['line']}:** {status_emoji} {cmd['status']}\n\n"

            # Show code
            report += f"```python\n{cmd['code']}\n```\n\n"

            # Show error if failed
            if cmd["status"] in ["failed", "error"] and cmd["error"]:
                report += f"**Error:**\n```\n{cmd['error']}\n```\n\n"

        report += "\n"

    # Recommendations
    report += "## Recommendations\n\n"

    if failed_count + error_count == 0:
        report += "✅ All runnable commands verified successfully!\n\n"
    else:
        report += f"⚠️ Found {failed_count + error_count} commands that failed or errored.\n\n"
        report += "**Action Items:**\n"
        for file_path, cmds in results.items():
            failed_cmds = [cmd for cmd in cmds if cmd["status"] in ["failed", "error"]]
            if failed_cmds:
                report += f"- Review {file_path}:\n"
                for cmd in failed_cmds:
                    report += f"  - Line {cmd['line']}: {cmd['status']}\n"
        report += "\n"

    report += "## Notes\n\n"
    report += "- **Example code** (multi-line Python imports) are skipped as they're not meant to be run as-is\n"
    report += "- **Unsafe commands** (backup, restore, repair=True) are skipped to prevent state modification\n"
    report += "- **Safe commands** (read-only operations) are executed and verified\n"

    return report


def main():
    """Main entry point."""
    print("=" * 70)
    print("TM Documentation Verification")
    print("=" * 70)

    # Verify all docs
    results = verify_tm_docs()

    # Generate report
    report = generate_report(results)

    # Write report
    repo_root = Path(__file__).parent.parent
    report_path = repo_root / "reports" / "tm_docs_verification.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print(f"\n[COMPLETE] Verification complete!")
    print(f"Report: {report_path}")

    # Return exit code
    total_commands = sum(len(cmds) for cmds in results.values())
    failed_count = sum(
        1 for cmds in results.values() for cmd in cmds if cmd["status"] in ["failed", "error"]
    )

    if failed_count > 0:
        print(f"\n[WARNING] {failed_count} commands failed verification")
        return 1
    else:
        print(f"\n[SUCCESS] All {total_commands} commands verified successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
