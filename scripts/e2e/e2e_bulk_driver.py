#!/usr/bin/env python
"""
E2E Bulk Driver Script.

Translates and verifies each file immediately.
Stops on first failure.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import resolve_translated_path  # noqa: E402

_CONFIG = ConfigService(REPO_ROOT / "config")
REPORTS_DIR = REPO_ROOT / "reports"
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
TRANSLATOR_CLI = REPO_ROOT / "src" / "cli.py"
VERIFIER_SCRIPT = REPO_ROOT / "scripts" / "e2e_verify_single_file.py"

# Output paths
PROGRESS_LOG = REPORTS_DIR / "E2E_BULK_progress.ndjson"
CONSOLE_LOG = REPORTS_DIR / "E2E_BULK_translate_console.txt"
VERIFY_DIR = REPORTS_DIR / "E2E_BULK_verify"
LOGS_DIR = REPORTS_DIR / "E2E_BULK_logs"


def detect_site_profile(file_path: Path) -> str:
    """
    Detect site profile from file path.

    Args:
        file_path: Absolute path to source file

    Returns:
        Site profile name (e.g., 'docs.aspose.net')
    """
    # Convert to string for pattern matching
    path_str = str(file_path)

    # Check for site-specific patterns
    if "docs.aspose.net" in path_str:
        return "docs.aspose.net"
    elif "kb.aspose.net" in path_str:
        return "kb.aspose.net"
    elif "reference.aspose.net" in path_str:
        return "reference.aspose.net"
    elif "blog.aspose.net" in path_str:
        return "blog.aspose.net"
    else:
        raise ValueError(f"Cannot detect site profile for: {file_path}")


def compute_target_path(source_path: Path, lang: str, site_profile: str) -> Path:
    """
    Compute where the translated file will be written.

    Durable-fix consolidation (TC-CD-017): previously hand-rolled both the
    per_language_folders `/en/` -> `/{lang}/` swap AND a blog-specific
    file-suffix special case, hardcoded to the `CONTENT_ROOT` constant.
    Delegates to `content_discovery.resolve_translated_path`, which reads
    each site's real `output_layout` from the registry instead -- no
    per-site special-casing needed here anymore.

    Args:
        source_path: Source file path
        lang: Target language (fr/de)
        site_profile: Site profile name

    Returns:
        Expected target file path
    """
    profile = _CONFIG.get_site_profile(site_profile)
    return resolve_translated_path(profile, source_path, lang)


def run_translation(source_path: Path, lang: str, site_profile: str) -> tuple[bool, str]:
    """
    Run force translation for a single file.

    Args:
        source_path: Source file to translate
        lang: Target language
        site_profile: Site profile to use

    Returns:
        (success: bool, output: str)
    """
    cmd = [
        str(VENV_PYTHON),
        "-m",
        "src.cli",
        "--site",
        site_profile,
        "--input",
        str(source_path),
        "--target-langs",
        lang,
        "--force-retranslate",
        "--cache-write-mode",
        "always",
        "--enable-production-metrics",
        "--no-commit",  # We'll commit manually later
        "--log-level",
        "INFO",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",  # Replace invalid UTF-8 with placeholder
            timeout=600,  # 10 minutes per file
        )

        output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"

        success = result.returncode == 0
        return (success, output)

    except subprocess.TimeoutExpired:
        return (False, "Translation timed out after 10 minutes")
    except Exception as e:
        return (False, f"Translation failed with exception: {e}")


def run_verification(source_path: Path, target_path: Path, lang: str) -> tuple[bool, dict]:
    """
    Run verification on translated file.

    Args:
        source_path: Source file
        target_path: Translated file
        lang: Target language

    Returns:
        (passed: bool, result_dict: dict)
    """
    json_output = VERIFY_DIR / f"{source_path.stem}_{lang}_verify.json"

    cmd = [
        str(VENV_PYTHON),
        str(VERIFIER_SCRIPT),
        "--source",
        str(source_path),
        "--target",
        str(target_path),
        "--lang",
        lang,
        "--json-output",
        str(json_output),
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",  # Replace invalid UTF-8 with placeholder
            timeout=60,
        )

        # Read JSON output
        if json_output.exists():
            result_data = json.loads(json_output.read_text(encoding="utf-8"))
        else:
            result_data = {"passed": False, "errors": ["Verification did not produce JSON output"]}

        passed = result.returncode == 0

        return (passed, result_data)

    except subprocess.TimeoutExpired:
        return (False, {"passed": False, "errors": ["Verification timed out"]})
    except Exception as e:
        return (False, {"passed": False, "errors": [f"Verification exception: {e}"]})


def log_progress(data: dict):
    """Append progress entry to NDJSON log."""
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")


def write_failure_report(file_path: Path, lang: str, failure_type: str, details: dict):
    """Write detailed failure report."""
    failure_report = REPORTS_DIR / "E2E_BULK_failure.md"

    with open(failure_report, "w", encoding="utf-8") as f:
        f.write("# E2E BULK VERIFICATION FAILURE\n\n")
        f.write(f"**Timestamp:** {datetime.now().isoformat()}\n\n")
        f.write(f"**Failure Type:** {failure_type}\n\n")
        f.write(f"**Source File:** {file_path}\n\n")
        f.write(f"**Target Language:** {lang}\n\n")
        f.write("## Details\n\n")
        f.write("```json\n")
        f.write(json.dumps(details, indent=2))
        f.write("\n```\n")

    print(f"\nFailure report written to: {failure_report}")


def main():
    """Main bulk driver logic."""
    parser = argparse.ArgumentParser(description="E2E bulk driver")
    parser.add_argument(
        "--filelist",
        default=str(REPORTS_DIR / "E2E_BULK_filelist.txt"),
        help="File list to process",
    )
    parser.add_argument("--langs", nargs="+", default=["fr", "de"], help="Target languages")

    args = parser.parse_args()

    # Read file list
    filelist_path = Path(args.filelist)
    if not filelist_path.exists():
        print(f"ERROR: File list not found: {filelist_path}", file=sys.stderr)
        return 1

    print("=" * 60)
    print("E2E BULK DRIVER")
    print("=" * 60)

    # Parse file list (extract lines starting with D:)
    with open(filelist_path, encoding="utf-8") as f:
        lines = f.readlines()

    # Was hardcoded to lines starting with "D:" -- broke the moment the
    # producing e2e_select_*.py scripts' content root moved off that drive
    # (see TC-CD-017). Any absolute path line is a real candidate now.
    files_to_process = [
        Path(line.strip()) for line in lines
        if line.strip() and Path(line.strip()).is_absolute()
    ]

    print(f"Files to process: {len(files_to_process)}")
    print(f"Target languages: {', '.join(args.langs)}")
    print(f"Total translations: {len(files_to_process) * len(args.langs)}")
    print()

    # Initialize progress log
    PROGRESS_LOG.write_text("", encoding="utf-8")

    # Initialize console log
    with open(CONSOLE_LOG, "w", encoding="utf-8") as f:
        f.write("E2E BULK TRANSLATION CONSOLE LOG\n")
        f.write(f"Started: {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n\n")

    # Process each file
    total_count = 0
    success_count = 0
    failure_count = 0

    for file_idx, source_path in enumerate(files_to_process, 1):
        if not source_path.exists():
            print(f"WARNING: Source file not found: {source_path}")
            continue

        # Detect site profile
        try:
            site_profile = detect_site_profile(source_path)
        except ValueError as e:
            print(f"ERROR: {e}")
            continue

        print(f"\n[{file_idx}/{len(files_to_process)}] Processing: {source_path.name}")
        print(f"  Site: {site_profile}")

        for lang in args.langs:
            total_count += 1
            start_time = time.time()

            print(f"  > Translating to {lang}...")

            # Run translation
            translate_success, translate_output = run_translation(source_path, lang, site_profile)

            # Log translation output
            with open(CONSOLE_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(f"File: {source_path.name}\n")
                f.write(f"Language: {lang}\n")
                f.write(f"Site: {site_profile}\n")
                f.write(f"{'=' * 60}\n")
                f.write(translate_output)
                f.write("\n\n")

            if not translate_success:
                print("  [FAIL] Translation FAILED")
                failure_count += 1

                log_progress(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "file": str(source_path),
                        "lang": lang,
                        "site": site_profile,
                        "stage": "translate",
                        "success": False,
                        "duration_sec": time.time() - start_time,
                    }
                )

                write_failure_report(source_path, lang, "translation", {"output": translate_output})

                print("\nSTOPPING: Translation failed (stop-the-line policy)")
                return 1

            # Compute target path
            target_path = compute_target_path(source_path, lang, site_profile)

            print(f"  > Verifying {target_path.name}...")

            # Run verification
            verify_success, verify_result = run_verification(source_path, target_path, lang)

            duration = time.time() - start_time

            if not verify_success:
                print("  [FAIL] Verification FAILED")
                failure_count += 1

                log_progress(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "file": str(source_path),
                        "lang": lang,
                        "site": site_profile,
                        "stage": "verify",
                        "success": False,
                        "duration_sec": duration,
                        "errors": verify_result.get("errors", []),
                    }
                )

                write_failure_report(source_path, lang, "verification", verify_result)

                print("\nSTOPPING: Verification failed (stop-the-line policy)")
                return 1

            # Success!
            print("  [PASS] Verified successfully")
            success_count += 1

            log_progress(
                {
                    "timestamp": datetime.now().isoformat(),
                    "file": str(source_path),
                    "lang": lang,
                    "site": site_profile,
                    "stage": "complete",
                    "success": True,
                    "duration_sec": duration,
                }
            )

    # Final summary
    print("\n" + "=" * 60)
    print("E2E BULK DRIVER COMPLETE")
    print("=" * 60)
    print(f"Total translations: {total_count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failure_count}")
    print(f"Progress log: {PROGRESS_LOG}")
    print(f"Console log: {CONSOLE_LOG}")
    print("=" * 60)

    if failure_count > 0:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
