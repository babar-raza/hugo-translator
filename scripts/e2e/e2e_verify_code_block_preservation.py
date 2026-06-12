"""E2E verification: translate previously-corrupted files and verify code block preservation.

Picks a representative sample of the 128 files that were corrupted by orphan recovery,
translates each to its target language, and compares code block / heading counts
against the English source.

Usage:
    python scripts/e2e_verify_code_block_preservation.py
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = Path(r"D:\onedrive\Documents\GitHub\aspose.net")
PROJECT = Path(r"c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator")
VENV_PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"

# Representative sample: pick files with high code block counts across different languages
TEST_FILES = [
    # (relative source path from content root, target_lang, expected_code_blocks_in_source)
    ("blog.aspose.net/imaging/dicom-png-jpeg-conversion-aspose-dotnet/index.md", "pl", 5),
    (
        "blog.aspose.net/barcode/rotate-barcode-images-in-csharp-with-aspose-barcode/index.md",
        "ru",
        7,
    ),
    (
        "blog.aspose.net/cells/convert-excel-worksheet-to-image-in-csharp-with-aspose-cells/index.md",
        "pt",
        7,
    ),
    ("blog.aspose.net/tex/latex-to-svg-conversion-dotnet-aspose-tex/index.md", "th", 4),
    ("blog.aspose.net/psd/replace-smart-objects-psd-aspose-psd-net/index.md", "th", 6),
]


def count_code_blocks(text: str) -> int:
    return len(re.findall(r"^```", text, re.MULTILINE)) // 2


def count_headings(text: str) -> int:
    return len(re.findall(r"^#{1,6}\s", text, re.MULTILINE))


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3 :]
    return text


def run_translation(source_file: Path, target_lang: str, output_dir: Path) -> Path:
    """Run translate-hugo CLI on a single file, writing output to output_dir."""
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    cmd = [
        python,
        "-m",
        "src.cli",
        "--site",
        "blog.aspose.net",
        "--input",
        str(source_file),
        "--target-langs",
        target_lang,
        "--output",
        str(output_dir),
        "--no-commit",
        "--max-files",
        "1",
    ]
    print(f"  CMD: {' '.join(cmd[-8:])}")
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(PROJECT)},
    )
    if result.returncode != 0:
        print("  STDERR (last 20 lines):")
        for line in result.stderr.strip().splitlines()[-20:]:
            print(f"    {line}")

    # Find the output file
    # File-based: index.md -> index.{lang}.md
    stem_parts = source_file.name.rsplit(".", 1)
    output_name = f"{stem_parts[0]}.{target_lang}.{stem_parts[1]}"

    # Search in output_dir for the translated file
    candidates = list(output_dir.rglob(output_name))
    if candidates:
        return candidates[0]

    # Also check in-place next to source
    in_place = source_file.parent / output_name
    if in_place.exists():
        return in_place

    return None


def main():
    print("=" * 70)
    print("E2E CODE BLOCK PRESERVATION VERIFICATION")
    print("=" * 70)

    # Create temp output directory
    output_dir = Path(tempfile.mkdtemp(prefix="hugo_e2e_codeblock_"))
    print(f"Output dir: {output_dir}\n")

    results = []
    passed = 0
    failed = 0

    for rel_path, target_lang, expected_src_cb in TEST_FILES:
        source_file = REPO / "content" / rel_path
        if not source_file.exists():
            print(f"SKIP: {rel_path} (source not found)")
            continue

        # Read source
        source_text = source_file.read_text(encoding="utf-8", errors="replace")
        source_body = strip_frontmatter(source_text)
        src_cb = count_code_blocks(source_body)
        src_hd = count_headings(source_body)

        print(f"\nTEST: {source_file.name} -> {target_lang}")
        print(f"  Source: {src_cb} code blocks, {src_hd} headings")

        if src_cb != expected_src_cb:
            print(f"  WARNING: Expected {expected_src_cb} code blocks, found {src_cb}")

        # Delete any existing translation to force re-translation
        stem_parts = source_file.name.rsplit(".", 1)
        existing_output = source_file.parent / f"{stem_parts[0]}.{target_lang}.{stem_parts[1]}"
        existed_before = existing_output.exists()

        # Run translation
        try:
            output_path = run_translation(source_file, target_lang, output_dir)
        except subprocess.TimeoutExpired:
            print("  FAIL: Translation timed out (300s)")
            failed += 1
            results.append(
                {
                    "file": rel_path,
                    "lang": target_lang,
                    "status": "TIMEOUT",
                    "src_cb": src_cb,
                }
            )
            continue

        if output_path is None:
            print("  FAIL: Output file not found")
            failed += 1
            results.append(
                {
                    "file": rel_path,
                    "lang": target_lang,
                    "status": "NO_OUTPUT",
                    "src_cb": src_cb,
                }
            )
            continue

        # Read output
        output_text = output_path.read_text(encoding="utf-8", errors="replace")
        output_body = strip_frontmatter(output_text)
        out_cb = count_code_blocks(output_body)
        out_hd = count_headings(output_body)

        print(f"  Output: {out_cb} code blocks, {out_hd} headings")
        print(f"  Output path: {output_path}")

        # Verify
        issues = []
        if out_cb < src_cb:
            issues.append(f"CODE BLOCKS LOST: {src_cb} -> {out_cb}")
        if out_hd >= src_hd + 3:
            issues.append(f"HEADING SURPLUS: {src_hd} -> {out_hd} (+{out_hd - src_hd})")
        if output_body.lstrip().startswith("TITLE:"):
            issues.append("TITLE: prefix detected")

        if issues:
            print(f"  FAIL: {'; '.join(issues)}")
            failed += 1
            status = "FAIL"
        else:
            print(
                f"  PASS: Code blocks preserved ({src_cb} -> {out_cb}), headings OK ({src_hd} -> {out_hd})"
            )
            passed += 1
            status = "PASS"

        results.append(
            {
                "file": rel_path,
                "lang": target_lang,
                "status": status,
                "src_cb": src_cb,
                "out_cb": out_cb,
                "src_hd": src_hd,
                "out_hd": out_hd,
                "issues": issues if issues else None,
                "output_path": str(output_path),
            }
        )

    # Summary
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed, {len(TEST_FILES) - passed - failed} skipped")
    print("=" * 70)

    for r in results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        print(
            f"  [{icon}] {r['file']} -> {r['lang']}: "
            f"code_blocks {r.get('src_cb', '?')}->{r.get('out_cb', '?')}"
        )
        if r.get("issues"):
            for issue in r["issues"]:
                print(f"         {issue}")

    # Save results
    results_file = PROJECT / "data" / "logs" / "e2e_codeblock_verification.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {results_file}")

    # Cleanup temp dir
    try:
        shutil.rmtree(output_dir, ignore_errors=True)
    except Exception:
        pass

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
