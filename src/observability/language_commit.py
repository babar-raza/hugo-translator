"""
Per-Language Incremental Git Commits.

Provides functions to create git commits after each language completes successfully.
Enables incremental progress saving and reduces work loss on failures.

Integration with existing git_commit_helper.py for consistent commit messages.
"""

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def commit_language_translations(
    target_lang: str,
    translated_files: list[Path],
    stats: dict[str, Any],
    config: dict[str, Any],
    auto_push: bool = False,
    git_repo_root: Path | None = None,
    validation_passed: bool = True,
) -> bool:
    """
    Create git commit for single language completion.

    Commit message format:
    ```
    chore(translate): complete {target_lang} - {file_count} files

    - Model: {model_id}
    - Duration: {duration_str}
    - TM hits: {tm_hit_rate:.1%}

    Co-Authored-By: Hugo Translator <noreply@aspose.com>
    ```

    Args:
        target_lang: Target language code (e.g., 'ca', 'bg', 'de')
        translated_files: List of translated file paths
        stats: Translation statistics dictionary with keys:
            - model_used: Model ID
            - duration_seconds: Translation duration
            - tm_hit_rate: TM hit rate (0.0-1.0)
            - segments_total: Total segments translated
        config: Global configuration dictionary
        auto_push: Automatically push to remote after commit
        git_repo_root: Git repository root directory (defaults to CWD if not specified)
        validation_passed: Whether validation passed (default: True). If False, commit is skipped.

    Returns:
        True if commit succeeded, False otherwise
    """
    # CRITICAL FIX: Check validation status before committing
    if not validation_passed:
        logger.warning(f"Skipping commit for {target_lang} - validation failed")
        return False

    if not translated_files:
        logger.warning(f"No files to commit for language {target_lang}")
        return False

    try:
        # Stage files
        logger.debug(f"Staging {len(translated_files)} files for {target_lang}")
        file_paths_str = [str(f) for f in translated_files]

        # Git add with timeout
        timeout = config.get("git_commit", {}).get("timeout_seconds", 60)

        result = subprocess.run(
            ["git", "add"] + file_paths_str,
            cwd=git_repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Count files actually staged (git add on unchanged file returns 0 but stages nothing)
        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=git_repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        staged_count = len([l for l in diff_result.stdout.splitlines() if l.strip()])
        if staged_count == 0:
            logger.info(f"No files actually staged for {target_lang} (all unchanged)")
            return False

        # Generate commit message using actual staged count
        message = _generate_commit_message(target_lang, staged_count, stats, config)

        # Create commit with HEREDOC-style message
        logger.debug(f"Creating commit for {target_lang}")
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=git_repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        logger.info(f"✓ Committed {staged_count} files for language {target_lang}")

        # Push if enabled
        if auto_push:
            logger.debug(f"Pushing commit for {target_lang} to remote")
            result = subprocess.run(
                ["git", "push"],
                cwd=git_repo_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            logger.info(f"✓ Pushed commit for {target_lang} to remote")

        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Git operation timed out for {target_lang} (timeout={timeout}s)")
        return False

    except subprocess.CalledProcessError as e:
        logger.error(
            f"Git operation failed for {target_lang}: {e}\n"
            f"stdout: {e.stdout}\n"
            f"stderr: {e.stderr}"
        )
        return False

    except Exception as e:
        logger.error(f"Unexpected error during commit for {target_lang}: {e}")
        return False


def _generate_commit_message(
    target_lang: str,
    file_count: int,
    stats: dict[str, Any],
    config: dict[str, Any],
) -> str:
    """
    Generate commit message for language completion.

    Args:
        target_lang: Target language code
        file_count: Number of files translated
        stats: Translation statistics
        config: Global configuration

    Returns:
        Formatted commit message string
    """
    # Extract model ID
    model_id = stats.get("model_used", "unknown")

    # Format duration
    duration_seconds = stats.get("duration_seconds", 0)
    duration_str = _format_duration(duration_seconds)

    # Extract TM hit rate
    tm_hit_rate = stats.get("tm_hit_rate", 0.0)

    # Get co-author info from config
    co_author_name = config.get("git_commit", {}).get("co_author_name", "Hugo Translator")
    co_author_email = config.get("git_commit", {}).get("co_author_email", "noreply@aspose.com")

    # Build message
    message_parts = [
        f"chore(translate): complete {target_lang} - {file_count} file{'s' if file_count != 1 else ''}",
        "",  # Empty line before body
    ]

    # Add details if available
    if model_id and model_id != "unknown":
        message_parts.append(f"- Model: {model_id}")

    if duration_str:
        message_parts.append(f"- Duration: {duration_str}")

    if tm_hit_rate > 0:
        message_parts.append(f"- TM hits: {tm_hit_rate:.1%}")

    # Add segments count if available
    segments_total = stats.get("segments_total", 0)
    if segments_total > 0:
        message_parts.append(f"- Segments: {segments_total}")

    # Add co-author
    message_parts.append("")  # Empty line before co-author
    message_parts.append(f"Co-Authored-By: {co_author_name} <{co_author_email}>")

    return "\n".join(message_parts)


def _format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "5m 30s", "1h 15m", "45s")
    """
    if seconds <= 0:
        return ""

    td = timedelta(seconds=int(seconds))

    hours = td.seconds // 3600
    minutes = (td.seconds % 3600) // 60
    secs = td.seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def save_failure_report(
    target_lang: str,
    subprocess_result: subprocess.CompletedProcess,
    failure_dir: Path,
    duration_seconds: float = 0,
    last_file_processed: str | None = None,
) -> bool:
    """
    Save detailed failure report for failed language translation.

    Args:
        target_lang: Target language code
        subprocess_result: CompletedProcess from subprocess.run()
        failure_dir: Directory to save failure reports
        duration_seconds: Translation duration before failure
        last_file_processed: Path to last file that was being processed

    Returns:
        True if report saved successfully, False otherwise
    """
    try:
        # Ensure failure directory exists
        failure_dir.mkdir(parents=True, exist_ok=True)

        # Generate report filename with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_path = failure_dir / f"failure_{target_lang}_{timestamp}.json"

        # Build report
        import json

        report = {
            "language": target_lang,
            "timestamp": datetime.now().isoformat(),
            "exit_code": subprocess_result.returncode,
            "duration_seconds": duration_seconds,
            "last_file_processed": last_file_processed or "unknown",
            "stderr": subprocess_result.stderr[-2000:] if subprocess_result.stderr else "",  # Last 2000 chars
            "stdout_lines": len(subprocess_result.stdout.splitlines()) if subprocess_result.stdout else 0,
            "probable_cause": _diagnose_failure(subprocess_result),
            "retry_command": f"python -m src.cli --target-langs {target_lang} --site <site_name>",
        }

        # Write report
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Failure report saved: {report_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to save failure report for {target_lang}: {e}")
        return False


def _diagnose_failure(result: subprocess.CompletedProcess) -> str:
    """
    Diagnose probable cause of failure based on subprocess result.

    Args:
        result: CompletedProcess from subprocess.run()

    Returns:
        Probable cause string
    """
    stderr = result.stderr or ""
    stdout = result.stdout or ""

    # Check for common failure patterns
    if "cuda out of memory" in stderr.lower() or "oom" in stderr.lower():
        return "CUDA OOM (out of memory)"
    elif "timeout" in stderr.lower():
        return "Translation timeout"
    elif "language purity" in stderr.lower():
        return "Language purity check failure"
    elif "no such file" in stderr.lower():
        return "File not found"
    elif "permission denied" in stderr.lower():
        return "Permission denied"
    elif result.returncode == -9 or result.returncode == 137:
        return "Process killed (likely OOM or timeout)"
    elif result.returncode == 1:
        return "General error (check stderr for details)"
    else:
        return f"Unknown error (exit_code={result.returncode})"
