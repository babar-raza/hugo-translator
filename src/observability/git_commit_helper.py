"""
Reusable git commit helper for all translation workflows.

Provides a unified function to auto-commit translation outputs across:
- CLI single file translations
- CLI directory translations
- Worker job processor
- MCP translation workers
- Orchestrator batches

Key Features:
- Works with both TranslationResult (single file) and DirectoryResult (batch)
- Loads config from site profiles or global defaults
- Graceful degradation (never fails translation)
- Telemetry integration
- Supports --no-commit flag
- Signal blocking during commit to prevent partial commits

Usage:
    from src.observability.git_commit_helper import auto_commit_translations

    success = auto_commit_translations(
        result=translation_result,
        site_id="example.com",
        target_langs=["de", "fr"],
        run_id="abc123",
        config_service=config_service,
    )
"""
import logging
import platform
import signal
import subprocess
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


class _SignalBlocker:
    """
    Context manager to temporarily block signals during critical git operations.

    Blocks SIGINT, SIGTERM, and SIGBREAK (Windows) to prevent interruption of
    git commits, which could leave the repository in an inconsistent state
    (e.g., files staged but not committed).

    Signals blocked:
    - SIGINT (CTRL+C) - All platforms
    - SIGTERM (termination signal) - All platforms
    - SIGBREAK (CTRL+BREAK) - Windows only

    Features:
    - Conflict detection: Warns if overwriting custom signal handlers
    - Platform-aware: Only blocks SIGBREAK on Windows
    - Error-tolerant: Continues if some signals can't be blocked
    - Safe restoration: All handlers restored in __exit__, even on exception
    - Observability: Records metrics for production monitoring (TC-OBS-01)
    """

    def __init__(self):
        self.old_handlers = {}  # Dict[signal.Signals, Any]
        self.platform = platform.system()
        self._start_time = None  # Track duration for metrics

        # Note: We don't register metrics in __init__ because get_metrics()
        # may return a different instance if init_metrics() is called later.
        # Instead, we register on first use in the helper methods.

    @staticmethod
    def _register_metrics():
        """
        Register signal blocking metrics with MetricsCollector (TC-OBS-01).

        Registers 5 metrics for observability:
        1. Activation counter - how often signal blocking is used
        2. Signals blocked count gauge - number of signals currently blocked
        3. Signal reception counter - CTRL+C events during commits
        4. Duration histogram - how long commits are protected
        5. Custom handler conflict counter - conflicts with other handlers

        Idempotent: Safe to call multiple times (MetricsCollector handles duplicates).
        Graceful: Never fails if metrics unavailable.
        """
        try:
            from src.observability.metrics import get_metrics
            metrics = get_metrics()

            # Note: Don't include worker_id in labels - it's added automatically by MetricsCollector
            # We register metrics without extra labels, they'll get worker_id added

            # Metric 1: Activation counter
            metrics.register_counter(
                "git_commit_signal_blocking_started",
                "Number of times signal blocking was activated for git commits",
                {}  # Empty labels - worker_id will be added automatically
            )

            # Metric 2: Signals blocked count gauge
            metrics.register_gauge(
                "git_commit_signals_blocked_count",
                "Number of signals currently blocked during git commit",
                {}  # Empty labels - worker_id will be added automatically
            )

            # Metric 3: Signal reception counter (per signal type)
            # Will be registered dynamically when first signal is received
            # (Can't pre-register all signal types)

            # Metric 4: Duration histogram
            metrics.register_histogram(
                "git_commit_signal_blocking_duration_seconds",
                "Duration of signal blocking for git commits (seconds)",
                {},  # Empty labels - worker_id will be added automatically
                buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
            )

            # Metric 5: Custom handler conflict counter (per signal type)
            # Will be registered dynamically when first conflict is detected
            # (Can't pre-register all signal types)

            logger.debug("Registered signal blocking metrics")
        except Exception as e:
            # Graceful degradation - metrics failures never block operations
            logger.debug(f"Failed to register signal blocking metrics: {e}", exc_info=True)

    @staticmethod
    def _record_metric_counter(name: str, labels: dict = None, amount: float = 1.0):
        """
        Record a counter metric with graceful degradation (TC-OBS-01).

        For metrics with labels (like signal_name), dynamically registers them
        on first use since we can't pre-register all possible label values.

        Args:
            name: Metric name
            labels: Optional labels dict (without worker_id - added automatically)
            amount: Amount to increment (default: 1.0)
        """
        try:
            from src.observability.metrics import get_metrics
            metrics = get_metrics()

            # Always try to register - it's idempotent
            # CRITICAL: Must include worker_id in registration labels to match increment() lookup
            try:
                registration_labels = {"worker_id": metrics.worker_id}
                if labels:
                    registration_labels.update(labels)
                metrics.register_counter(name, f"Counter for {name}", registration_labels)
            except Exception:
                pass  # Already registered or can't register

            metrics.increment(name, amount=amount, labels=labels)
        except Exception as e:
            logger.debug(f"Failed to record counter metric {name}: {e}", exc_info=True)

    @staticmethod
    def _record_metric_gauge(name: str, value: float, labels: dict = None):
        """
        Record a gauge metric with graceful degradation (TC-OBS-01).

        Args:
            name: Metric name
            value: Gauge value
            labels: Optional labels dict (without worker_id - added automatically)
        """
        try:
            from src.observability.metrics import get_metrics
            metrics = get_metrics()

            # Always try to register - it's idempotent
            # CRITICAL: Must include worker_id in registration labels to match set_gauge() lookup
            try:
                registration_labels = {"worker_id": metrics.worker_id}
                if labels:
                    registration_labels.update(labels)
                metrics.register_gauge(name, f"Gauge for {name}", registration_labels)
            except Exception:
                pass  # Already registered or can't register

            metrics.set_gauge(name, value=value, labels=labels)
        except Exception as e:
            logger.debug(f"Failed to record gauge metric {name}: {e}", exc_info=True)

    @staticmethod
    def _record_metric_histogram(name: str, value: float, labels: dict = None):
        """
        Record a histogram observation with graceful degradation (TC-OBS-01).

        Args:
            name: Metric name
            value: Observation value
            labels: Optional labels dict (without worker_id - added automatically)
        """
        try:
            from src.observability.metrics import get_metrics
            metrics = get_metrics()

            # Always try to register - it's idempotent
            # CRITICAL: Must include worker_id in registration labels to match observe() lookup
            try:
                registration_labels = {"worker_id": metrics.worker_id}
                if labels:
                    registration_labels.update(labels)
                metrics.register_histogram(
                    name,
                    f"Histogram for {name}",
                    registration_labels,
                    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
                )
            except Exception:
                pass  # Already registered or can't register

            metrics.observe(name, value=value, labels=labels)
        except Exception as e:
            logger.debug(f"Failed to record histogram metric {name}: {e}", exc_info=True)

    def __enter__(self):
        """Block SIGINT, SIGTERM, and SIGBREAK (Windows) by setting no-op handlers."""
        # Record start time for duration metric (TC-OBS-01)
        import time
        self._start_time = time.perf_counter()

        # Define signals to block
        signals_to_block = [signal.SIGINT, signal.SIGTERM]

        # Add Windows-specific signal
        if self.platform == "Windows" and hasattr(signal, 'SIGBREAK'):
            signals_to_block.append(signal.SIGBREAK)

        # Register handlers for each signal
        for sig in signals_to_block:
            try:
                old_handler = signal.signal(sig, self._ignore_signal)
                self.old_handlers[sig] = old_handler

                # Conflict detection: warn if overwriting custom handler
                if old_handler not in (signal.SIG_DFL, signal.SIG_IGN):
                    signal_name = sig.name if hasattr(sig, 'name') else str(sig)
                    logger.warning(
                        f"Signal blocking is overwriting custom {signal_name} handler. "
                        f"This may interfere with graceful shutdown or other signal handling."
                    )

                    # Record conflict metric (TC-OBS-01 Metric 5)
                    self._record_metric_counter(
                        "git_commit_custom_handler_conflict",
                        labels={"signal_name": signal_name}
                    )

                signal_name = sig.name if hasattr(sig, 'name') else str(sig)
                logger.debug(f"Blocked {signal_name} for git commit operations")
            except (ValueError, OSError) as e:
                # Some platforms/contexts don't allow signal handling
                signal_name = sig.name if hasattr(sig, 'name') else str(sig)
                logger.debug(f"Could not block {signal_name}: {e}")

        # Record activation metric (TC-OBS-01 Metric 1)
        self._record_metric_counter(
            "git_commit_signal_blocking_started",
            labels=None  # No extra labels, just worker_id
        )

        # Record count of successfully blocked signals (TC-OBS-01 Metric 2)
        self._record_metric_gauge(
            "git_commit_signals_blocked_count",
            value=float(len(self.old_handlers)),
            labels=None  # No extra labels, just worker_id
        )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore all original signal handlers."""
        # Record duration metric (TC-OBS-01 Metric 4)
        if self._start_time is not None:
            import time
            duration = time.perf_counter() - self._start_time
            self._record_metric_histogram(
                "git_commit_signal_blocking_duration_seconds",
                value=duration,
                labels=None  # No extra labels, just worker_id
            )

        for sig, old_handler in self.old_handlers.items():
            try:
                signal.signal(sig, old_handler)
                signal_name = sig.name if hasattr(sig, 'name') else str(sig)
                logger.debug(f"Restored {signal_name} handler after git commit")
            except (ValueError, OSError) as e:
                signal_name = sig.name if hasattr(sig, 'name') else str(sig)
                logger.debug(f"Could not restore {signal_name} handler: {e}")

        self.old_handlers.clear()
        return False

    @staticmethod
    def _ignore_signal(signum, frame):
        """No-op signal handler to ignore signals during commit."""
        # Try to get human-readable signal name
        try:
            signal_name = signal.Signals(signum).name
        except (ValueError, AttributeError):
            signal_name = f"signal_{signum}"

        logger.info(
            f"Received {signal_name} during git commit - waiting for commit to complete..."
        )

        # Record signal reception metric (TC-OBS-01 Metric 3)
        _SignalBlocker._record_metric_counter(
            "git_commit_signal_received",
            labels={"signal_name": signal_name}
        )


def collect_modified_files_from_git(
    output_dir: Path,
    dir_result: "DirectoryResult",
    content_root: Path | None = None,
) -> list[Path]:
    """
    Fallback: Collect uncommitted .md files using git status.

    Used when collect_output_files() returns empty but we know translations succeeded.
    Catches modified, added, AND untracked files (previous fallback missed untracked).

    Args:
        output_dir: Narrow directory fallback (single language subdir)
        dir_result: DirectoryResult for context
        content_root: Wide scan directory (site content root). Preferred over output_dir.

    Returns:
        List of uncommitted .md files found via git status, or empty list if failed
    """
    try:
        from .git_context import find_git_root

        # Prefer content_root (site-wide scan) over output_dir (single subdir)
        scan_dir = content_root if content_root else output_dir

        git_root = find_git_root(scan_dir)
        if not git_root:
            logger.warning("[Fallback] Could not find git root from scan directory")
            return []

        try:
            rel_path = scan_dir.resolve().relative_to(git_root.resolve())
        except ValueError:
            logger.warning(f"[Fallback] Scan dir {scan_dir} not relative to git root {git_root}")
            rel_path = "."

        logger.info(f"[Fallback] Scanning {rel_path} (git root: {git_root})")

        result = subprocess.run(
            ["git", "status", "--porcelain", str(rel_path)],
            cwd=str(git_root),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"[Fallback] Git status failed: {result.stderr}")
            return []

        # Parse ALL uncommitted files: modified (M), added (A), untracked (??)
        modified_files = []
        for line in result.stdout.splitlines():
            status_code = line[:2]
            file_rel_path = line[3:].strip()

            if 'M' in status_code or 'A' in status_code or status_code == '??':
                file_path = git_root / file_rel_path
                # Only collect .md files (translation outputs)
                if file_path.suffix == '.md' and file_path.exists():
                    modified_files.append(file_path)
                    logger.debug(f"[Fallback] Found uncommitted file [{status_code.strip()}]: {file_path}")
                elif file_path.is_dir() and status_code == '??':
                    # Untracked directories: git shows "?? dir/" — recurse for .md files
                    md_in_dir = list(file_path.rglob("*.md"))
                    for md_file in md_in_dir:
                        modified_files.append(md_file)
                    if md_in_dir:
                        logger.debug(f"[Fallback] Found {len(md_in_dir)} .md files in untracked dir: {file_path}")

        logger.info(f"[Fallback] Found {len(modified_files)} uncommitted .md files via git status in {rel_path}")
        return modified_files

    except Exception as e:
        logger.warning(f"[Fallback] git status collection failed: {e}")
        return []


def _write_pending_commit_fallback(
    output_files: list[Path],
    git_root: Path,
    site_id: str,
    target_langs: list[str],
) -> bool:
    """Write .pending_commit.json for SEO-PendingCommitWatcher to pick up within 30s.

    Called only when the direct git commit fails. The watcher (Watch-PendingCommit.ps1)
    removes stale index.lock files itself before staging, polls every 30 seconds, and has
    a noop-safety check (git diff --cached) that prevents double-commits if a later run
    already committed the same files.
    """
    import json
    from datetime import datetime, timezone

    try:
        rel_files = []
        for f in output_files:
            try:
                rel_files.append(str(f.relative_to(git_root)).replace("\\", "/"))
            except ValueError:
                pass  # file outside git root — skip

        if not rel_files:
            logger.warning("[pending_commit] No files within git root — cannot write fallback")
            return False

        lang_list = ", ".join(target_langs[:6])
        if len(target_langs) > 6:
            lang_list += f" +{len(target_langs) - 6} more"
        commit_msg = f"chore({site_id}): translate {len(rel_files)} files to {lang_list}"

        payload = {
            "files": rel_files,
            "commit_message": commit_msg,
            "author_name": "Hugo Translator",
            "author_email": "hugo-translator@aspose.net",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        pending_path = git_root / ".pending_commit.json"
        pending_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.warning(
            "[pending_commit] Direct commit failed — wrote .pending_commit.json "
            f"({len(rel_files)} files). SEO-PendingCommitWatcher will commit within ~30s."
        )
        return True
    except Exception as exc:
        logger.warning(f"[pending_commit] Failed to write .pending_commit.json: {exc}")
        return False


def recover_pending_commits(git_root: Path) -> int:
    """Scan git_root for .pending_commit.json and .pending_commit.json.stale_* files
    and attempt to commit the files they describe.

    Called automatically by the worker after each translation run. Handles two cases:
    - .pending_commit.json older than 2 minutes (watcher never picked it up)
    - .pending_commit.json.stale_* (watcher staged the files but git commit timed out)

    Returns the number of commits successfully recovered.
    """
    import json
    import time

    # Collect candidates
    candidates: list[Path] = []
    active = git_root / ".pending_commit.json"
    if active.exists():
        age = time.time() - active.stat().st_mtime
        if age > 120:  # give the external watcher 2 minutes to act first
            candidates.append(active)
    candidates.extend(sorted(git_root.glob(".pending_commit.json.stale_*")))

    if not candidates:
        return 0

    logger.info(
        f"[pending_commit_recovery] Found {len(candidates)} pending commit file(s) in {git_root}"
    )

    recovered = 0
    for pf in candidates:
        try:
            payload = json.loads(pf.read_text(encoding="utf-8"))
            rel_files: list[str] = payload.get("files", [])
            commit_msg: str = (payload.get("commit_message") or "").strip()
            author_name: str = payload.get("author_name") or "Hugo Translator"
            author_email: str = payload.get("author_email") or "hugo-translator@aspose.net"

            if not rel_files or not commit_msg:
                logger.warning(
                    f"[pending_commit_recovery] {pf.name}: missing files or message — removing"
                )
                pf.unlink(missing_ok=True)
                continue

            # Determine which files still need staging
            cached_result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            staged_set = set(cached_result.stdout.splitlines())

            to_add = [
                r for r in rel_files
                if r not in staged_set and (git_root / r).exists()
            ]
            if to_add:
                add_result = subprocess.run(
                    ["git", "add", "--"] + to_add,
                    cwd=str(git_root),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if add_result.returncode != 0:
                    logger.warning(
                        f"[pending_commit_recovery] git add failed for {pf.name}: "
                        f"{add_result.stderr.strip()}"
                    )

            # Re-check what's staged from our list
            cached_result2 = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            staged_now = set(cached_result2.stdout.splitlines())
            our_staged = [r for r in rel_files if r in staged_now]

            if not our_staged:
                logger.info(
                    f"[pending_commit_recovery] {pf.name}: no staged changes "
                    "— files may already be committed. Removing."
                )
                pf.unlink(missing_ok=True)
                continue

            # Commit with original author preserved
            author_str = f"{author_name} <{author_email}>"
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_msg, "--author", author_str],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=90,
            )

            combined_out = (commit_result.stdout + commit_result.stderr).lower()
            if commit_result.returncode == 0:
                logger.info(
                    f"[pending_commit_recovery] ✓ Recovered {len(our_staged)} file(s) "
                    f"from {pf.name}"
                )
                pf.unlink(missing_ok=True)
                recovered += 1
            elif "nothing to commit" in combined_out:
                logger.info(
                    f"[pending_commit_recovery] {pf.name}: nothing to commit "
                    "— already committed. Removing."
                )
                pf.unlink(missing_ok=True)
            else:
                logger.warning(
                    f"[pending_commit_recovery] {pf.name}: commit failed — "
                    f"{(commit_result.stderr or commit_result.stdout).strip()[:200]}. "
                    "Will retry next run."
                )
                # Leave stale file in place; next run will retry

        except subprocess.TimeoutExpired:
            logger.warning(
                f"[pending_commit_recovery] {pf.name}: timed out — will retry next run"
            )
        except Exception as exc:
            logger.warning(f"[pending_commit_recovery] {pf.name}: error — {exc}")

    return recovered


def auto_commit_translations(
    result: Union["TranslationResult", "DirectoryResult"],
    site_id: str,
    target_langs: list[str],
    run_id: str,
    config_service: "ConfigService",
    commit_message_override: str | None = None,
    no_commit: bool = False,
    require_verification_pass: bool = True,
    require_telemetry_success: bool = False,
) -> bool:
    """
    Auto-commit translation outputs if enabled and all quality gates pass.

    Works with both TranslationResult (single file) and DirectoryResult (batch).
    Handles all git commit logic including:
    - Config loading (site profile -> global -> defaults)
    - Git repo detection
    - Quality gates (verification pass, telemetry success)
    - File staging and committing
    - Push to remote
    - Telemetry recording
    - Commit hash persistence to reports/

    Quality Gates (STOP-THE-LINE):
    - All files must pass verification (if require_verification_pass=True)
    - Telemetry must succeed with 2xx (if require_telemetry_success=True)
    - Working tree must have changes

    Args:
        result: Translation result (single file or directory)
        site_id: Site identifier for config lookup
        target_langs: Target languages translated
        run_id: Translation run ID for tracking
        config_service: Config service for loading git settings
        commit_message_override: Optional commit message template override
        no_commit: If True, skip commit (respects --no-commit flag)
        require_verification_pass: If True, require all files to pass verification
        require_telemetry_success: If True, require telemetry post to succeed (2xx)

    Returns:
        True if commit succeeded or was skipped gracefully, False if failed
    """
    if no_commit:
        logger.warning("Git commit SKIPPED: --no-commit flag set")
        return True

    try:
        # Import here to avoid circular dependencies
        from ..benchmarking.storage import BenchmarkDatabase
        from ..translation_engine.models import DirectoryResult, TranslationResult
        from .git_commit import GitCommitConfig, GitCommitter, collect_output_files

        # Wrap TranslationResult in DirectoryResult if needed
        if isinstance(result, TranslationResult):
            if not result.success:
                logger.error(f"Git commit SKIPPED: Translation failed (success={result.success})")
                return True

            # Create DirectoryResult wrapper for single file
            dir_result = DirectoryResult(
                success=result.success,
                directory=result.file_path.parent,
                file_results=[result],
                total_files=1,
                successful_files=1 if result.success else 0,
                failed_files=0 if result.success else 1,
            )
        else:
            dir_result = result

        # Quality gates only apply when there are files from THIS run
        if dir_result.successful_files > 0:
            # QUALITY GATE 1: Verification Pass (STOP-THE-LINE)
            if require_verification_pass:
                verification_failed = _check_verification_failures(dir_result)
                if verification_failed:
                    logger.error(
                        f"STOP-THE-LINE: Cannot commit - {verification_failed} file(s) failed verification. "
                        f"Fix verification errors before committing."
                    )
                    return False

            # QUALITY GATE 2: Telemetry Success (STOP-THE-LINE)
            if require_telemetry_success:
                telemetry_failed = _check_telemetry_failure(dir_result)
                if telemetry_failed:
                    logger.error(
                        f"STOP-THE-LINE: Cannot commit - telemetry post failed. "
                        f"Error: {telemetry_failed}"
                    )
                    return False

        # Collect output files (only files that were actually written/modified)
        output_files = collect_output_files(dir_result)
        if not output_files:
            if dir_result.successful_files > 0:
                logger.error("Git commit: collect_output_files() returned empty list")
                logger.error(f"  - DirectoryResult.successful_files: {dir_result.successful_files}")
                logger.error(f"  - DirectoryResult.file_results count: {len(dir_result.file_results) if hasattr(dir_result, 'file_results') else 'N/A'}")
            else:
                logger.info("No files from this run; scanning for orphans from previous runs...")

            # Fallback: scan for uncommitted .md files via git status.
            # This catches orphans from previous runs AND files missed by collect_output_files.
            if hasattr(dir_result, 'file_results') and dir_result.file_results:
                logger.info("Attempting fallback: collecting uncommitted files from git status...")
                try:
                    # Get output directory from first file result
                    first_output = list(dir_result.file_results[0].outputs.values())[0]
                    output_dir = first_output.parent

                    # Use dir_result.directory (site content root) for wide scan
                    content_root = getattr(dir_result, 'directory', None)
                    logger.info(f"  - Content root: {content_root}, output_dir fallback: {output_dir}")

                    output_files = collect_modified_files_from_git(output_dir, dir_result, content_root=content_root)

                    if output_files:
                        logger.info(f"Fallback successful: collected {len(output_files)} files from git status")
                        # Continue with commit using fallback files
                    else:
                        logger.error("Fallback failed: no modified files found in git status either")
                        return True  # Graceful skip
                except Exception as e:
                    logger.error(f"Fallback collection failed with exception: {e}")
                    return True  # Graceful skip
            else:
                return True  # Graceful skip (no files to commit)
        else:
            # Orphan sweep: augment current-run files with any modified .md files left
            # uncommitted from previous failed runs (timeout, git error, etc.).
            # Without this, only the current run's files get committed and older orphans
            # accumulate indefinitely across runs.
            content_root = getattr(dir_result, 'directory', None)
            if content_root:
                try:
                    orphaned = collect_modified_files_from_git(
                        output_files[0].parent, dir_result, content_root=content_root
                    )
                    existing_paths = set(output_files)
                    new_orphans = [f for f in orphaned if f not in existing_paths]
                    if new_orphans:
                        logger.info(
                            f"[orphan_sweep] Sweeping {len(new_orphans)} orphaned file(s) "
                            "from previous failed commits into this commit"
                        )
                        output_files = list(output_files) + new_orphans
                except Exception as e:
                    logger.warning(f"[orphan_sweep] Failed to collect orphaned files: {e}")

        # Only continue if we have files to commit (either from primary or fallback collection)
        if not output_files:
            return True

        # Load git commit config
        git_config = _load_git_config(
            config_service,
            site_id,
            commit_message_override
        )

        if not git_config.enabled:
            logger.warning("Git commit SKIPPED: disabled in configuration")
            # Try to identify config source for debugging
            config_source = "unknown"
            if config_service:
                try:
                    site_profile = config_service.get_site_profile(site_id) if site_id else None
                    if site_profile and hasattr(site_profile, 'git_commit'):
                        config_source = "site profile"
                    elif hasattr(config_service, 'global_config'):
                        config_source = "global config"
                except Exception:
                    pass
            logger.warning(f"  - Config source: {config_source}")
            return True

        # Create committer and check git repo
        committer = GitCommitter(git_config)
        if not committer.is_git_repo(output_files[0]):
            logger.error("Git commit FAILED: Output directory is not a git repository")
            logger.error(f"  - Attempted path: {output_files[0]}")
            logger.error(f"  - Resolved path: {output_files[0].resolve()}")
            logger.error(f"  - Parent directory: {output_files[0].parent}")
            return False  # Return FALSE - this is an error condition, not graceful skip

        # Extract additional metadata for enhanced commit messages
        # D2: Pass config to enable 3-tier fallback for model_id

        # VALIDATE config extraction (WS2: COMMIT-FIX-02-MODEL)
        config_dict = None
        if hasattr(config_service, 'global_config') and config_service.global_config:
            try:
                config_dict = config_service.global_config.__dict__
                if not config_dict:
                    logger.warning("[auto_commit] config_dict is empty after extraction from global_config.__dict__")
                else:
                    logger.debug(f"[auto_commit] config_dict extracted successfully, keys: {list(config_dict.keys())[:5]}...")

                    # Validate model_defaults is present
                    if "model_defaults" not in config_dict:
                        logger.error("[auto_commit] config_dict missing 'model_defaults' key! Tier 3 fallback may fail!")
                    else:
                        model_defaults = config_dict["model_defaults"]
                        logger.debug(f"[auto_commit] model_defaults found, type: {type(model_defaults).__name__}")
                        # Check if it's a dict or Pydantic model
                        if isinstance(model_defaults, dict):
                            if "fallback_model" not in model_defaults:
                                logger.error("[auto_commit] config_dict.model_defaults missing 'fallback_model' key!")
                        elif not hasattr(model_defaults, "fallback_model"):
                            logger.error("[auto_commit] config_dict.model_defaults has no 'fallback_model' attribute!")
            except Exception as e:
                logger.error(f"[auto_commit] Failed to extract config_dict: {e}", exc_info=True)
                config_dict = None
        else:
            logger.warning("[auto_commit] config_service has no global_config attribute - Tier 3 fallback will fail!")

        model_id = _extract_model_id(dir_result, config=config_dict)

        if not model_id:
            logger.error("[auto_commit] model_id is None after _extract_model_id - commit message will lack model info!")
        tm_stats = _extract_tm_stats(dir_result)

        # Commit translations (optionally block SIGINT to prevent partial commits)
        logger.info(f"Auto-committing {len(output_files)} translation outputs...")
        if git_config.block_signals:
            logger.debug("Signal blocking enabled - CTRL+C will wait for commit to complete")
            with _SignalBlocker():
                commit_result = committer.commit_translation_outputs(
                    output_files=output_files,
                    site_id=site_id,
                    target_langs=target_langs,
                    run_id=run_id,
                    translation_result=dir_result,
                    model_id=model_id,
                    tm_stats=tm_stats,
                )
        else:
            logger.debug("Signal blocking disabled - CTRL+C can interrupt commit")
            commit_result = committer.commit_translation_outputs(
                output_files=output_files,
                site_id=site_id,
                target_langs=target_langs,
                run_id=run_id,
                translation_result=dir_result,
                model_id=model_id,
                tm_stats=tm_stats,
            )

        if commit_result.success:
            push_status = "OK" if commit_result.push_success else "FAILED"
            logger.info(
                f"Committed {commit_result.files_committed} files: "
                f"{commit_result.commit_hash_short} (push: {push_status})"
            )

            # Save commit hash to reports/ for external review
            _save_commit_hash_to_reports(commit_result)

            # Save telemetry
            _save_commit_telemetry(run_id, site_id, commit_result, target_langs)

            # TC-GIT-01: Associate git commit with telemetry run
            if hasattr(result, 'telemetry_context') and result.telemetry_context:
                try:
                    from src.observability.telemetry_integration import TranslationTelemetry
                    telemetry = TranslationTelemetry()
                    telemetry.associate_commit(
                        result.telemetry_context,
                        commit_result.commit_hash,
                        commit_source="llm",
                        commit_author=getattr(commit_result, 'commit_author', None),
                        commit_timestamp=getattr(commit_result, 'commit_timestamp', None)
                    )
                    logger.debug(f"Associated commit {commit_result.commit_hash[:7]} with telemetry run")
                except Exception as e:
                    # TC-GIT-01: Graceful degradation - don't fail translation on telemetry error
                    logger.warning(f"Failed to associate commit with telemetry: {e}")

            return True
        else:
            logger.error(f"Auto-commit failed: {commit_result.error}")
            # Fallback: signal the SEO-PendingCommitWatcher (polls every 30s)
            try:
                from .git_context import find_git_root
                git_root = find_git_root(output_files[0])
                if git_root:
                    _write_pending_commit_fallback(
                        output_files=output_files,
                        git_root=git_root,
                        site_id=site_id,
                        target_langs=target_langs,
                    )
            except Exception as _fb_exc:
                logger.warning(f"[pending_commit] Fallback write skipped: {_fb_exc}")
            return False

    except ImportError as e:
        logger.error(f"Git commit module not available: {e}")
        return False
    except Exception as e:
        logger.error(f"Auto-commit failed: {e}")
        logger.debug("Full traceback:", exc_info=True)
        return False


def _load_git_config(
    config_service: "ConfigService",
    site_id: str,
    commit_message_override: str | None,
) -> "GitCommitConfig":
    """
    Load git config from site profile or global defaults.

    Priority order:
    1. Site profile git_commit section
    2. Global config git_commit section
    3. Hardcoded defaults

    Args:
        config_service: Config service
        site_id: Site identifier
        commit_message_override: Optional commit message override from CLI

    Returns:
        GitCommitConfig with loaded settings
    """
    from .git_commit import GitCommitConfig

    # Start with hardcoded defaults
    git_config = GitCommitConfig()

    # Try to load site profile
    try:
        site_profile = config_service.get_site_profile(site_id)
        if site_profile and hasattr(site_profile, 'git_commit') and site_profile.git_commit:
            git_config = GitCommitConfig(
                enabled=site_profile.git_commit.enabled,
                auto_push=site_profile.git_commit.auto_push,
                commit_template=site_profile.git_commit.commit_template,
                co_author_email=site_profile.git_commit.co_author_email,
                co_author_name=site_profile.git_commit.co_author_name,
                timeout_seconds=site_profile.git_commit.timeout_seconds,
                block_signals=getattr(site_profile.git_commit, 'block_signals', False),
            )
            logger.debug(f"Loaded git commit config from site profile: {site_id}")
    except Exception as e:
        logger.debug(f"Could not load site profile for git config: {e}")

    # Try global config fallback (only if site profile didn't set it)
    try:
        global_config = config_service.global_config
        if global_config and hasattr(global_config, 'git_commit') and global_config.git_commit:
            # Only use global if site profile didn't have git_commit
            # (Check if we're still using default template as indicator)
            if git_config.commit_template == "chore: translate {file_count} files to {languages}":
                git_config = GitCommitConfig(
                    enabled=global_config.git_commit.enabled,
                    auto_push=global_config.git_commit.auto_push,
                    commit_template=global_config.git_commit.commit_template,
                    co_author_email=global_config.git_commit.co_author_email,
                    co_author_name=global_config.git_commit.co_author_name,
                    timeout_seconds=global_config.git_commit.timeout_seconds,
                    block_signals=getattr(global_config.git_commit, 'block_signals', False),
                )
                logger.debug("Loaded git commit config from global config")
    except Exception as e:
        logger.debug(f"Could not load global config for git config: {e}")

    # Override commit message from CLI parameter if provided
    if commit_message_override:
        git_config.commit_template = commit_message_override
        logger.debug(f"Using commit message override: {commit_message_override}")

    return git_config


def _save_commit_telemetry(
    run_id: str,
    site_id: str,
    commit_result: "GitCommitResult",
    target_langs: list[str],
) -> None:
    """
    Save commit telemetry to benchmark database.

    Args:
        run_id: Translation run ID
        site_id: Site identifier
        commit_result: Git commit result
        target_langs: Target languages
    """
    try:
        from ..benchmarking.storage import BenchmarkDatabase

        db_path = Path("data/benchmarks/benchmarks.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = BenchmarkDatabase(db_path)
        db.save_translation_commit(
            run_id=run_id,
            site_id=site_id,
            commit_result=commit_result,
            languages=target_langs,
        )
        logger.debug(f"Saved commit telemetry for run {run_id}")
    except Exception as e:
        logger.debug(f"Commit telemetry save failed: {e}")


def _extract_model_id(dir_result: "DirectoryResult", config: dict | None = None) -> str | None:
    """
    Extract model ID from translation result with 3-tier fallback.

    D2: Implements robust model_id extraction to ensure 100% of commits have model info.

    Fallback tiers:
    1. Check dir_result.aggregate_stats.model_used (preferred)
    2. Check dir_result.file_results[0].stats.model_used (legacy)
    3. Return config["model_defaults"]["fallback_model"] (guaranteed)

    Args:
        dir_result: DirectoryResult from translation
        config: Optional config dict with model_defaults.fallback_model

    Returns:
        Model ID string (never returns None with config provided)
    """
    logger.debug(f"[_extract_model_id] Called with config={'present' if config else 'MISSING'}")

    try:
        # Tier 1: Check aggregate_stats.model_used (most reliable)
        if hasattr(dir_result, "aggregate_stats") and dir_result.aggregate_stats:
            agg_stats = dir_result.aggregate_stats
            logger.debug(f"[Tier 1] aggregate_stats exists: {type(agg_stats).__name__}")
            if hasattr(agg_stats, "model_used"):
                model_value = agg_stats.model_used
                logger.debug(f"[Tier 1] model_used attribute exists, value: {repr(model_value)}, type: {type(model_value).__name__}")
                if model_value:
                    logger.info(f"[Tier 1] SUCCESS - Extracted model_id from aggregate_stats: {model_value}")
                    return model_value
                else:
                    logger.debug(f"[Tier 1] model_used is falsy (None or empty string): {repr(model_value)}")
            else:
                logger.debug("[Tier 1] aggregate_stats exists but has no model_used attribute")
        else:
            logger.debug("[Tier 1] dir_result has no aggregate_stats or it is None")

        # Tier 2: Check file_results[0].stats.model_used (legacy path)
        if dir_result.file_results and len(dir_result.file_results) > 0:
            first_result = dir_result.file_results[0]
            logger.debug(f"[Tier 2] file_results[0] exists: {type(first_result).__name__}")
            if hasattr(first_result, "stats") and first_result.stats:
                logger.debug(f"[Tier 2] file_results[0].stats exists: {type(first_result.stats).__name__}")
                if hasattr(first_result.stats, "model_used"):
                    model_value = first_result.stats.model_used
                    logger.debug(f"[Tier 2] model_used attribute exists, value: {repr(model_value)}, type: {type(model_value).__name__}")
                    if model_value:
                        logger.info(f"[Tier 2] SUCCESS - Extracted model_id from file_results: {model_value}")
                        return model_value
                    else:
                        logger.debug(f"[Tier 2] model_used is falsy (None or empty string): {repr(model_value)}")
                else:
                    logger.debug("[Tier 2] file_results[0].stats exists but has no model_used attribute")
            else:
                logger.debug("[Tier 2] file_results[0] has no stats or it is None")
        else:
            logger.debug(f"[Tier 2] dir_result has no file_results or empty list (len={len(dir_result.file_results) if hasattr(dir_result, 'file_results') and dir_result.file_results else 0})")

        # Tier 3: Fallback to config default (guaranteed to work)
        if config:
            logger.debug(f"[Tier 3] Config present, attempting fallback. Config keys: {list(config.keys())[:10]}")
            if "model_defaults" in config:
                model_defaults = config["model_defaults"]
                logger.debug(f"[Tier 3] model_defaults key found, type: {type(model_defaults).__name__}")
                if isinstance(model_defaults, dict):
                    logger.debug(f"[Tier 3] model_defaults is dict, keys: {list(model_defaults.keys())}")
                    fallback = model_defaults.get("fallback_model", "m2m100_418m")
                else:
                    # Handle case where model_defaults is a Pydantic model
                    logger.debug("[Tier 3] model_defaults is not dict, attempting attribute access")
                    fallback = getattr(model_defaults, "fallback_model", "m2m100_418m")
            else:
                logger.warning("[Tier 3] Config missing 'model_defaults' key - using hardcoded default")
                fallback = "m2m100_418m"

            logger.warning(
                f"[Tier 3] SUCCESS - No model_id found in results, using fallback: {fallback} "
                f"(from config.model_defaults.fallback_model)"
            )
            return fallback
        else:
            logger.error("[Tier 3] FAILURE - No config provided - cannot use fallback! This is a bug!")
            return None

    except Exception as e:
        logger.error(f"[_extract_model_id] Exception: {e}", exc_info=True)
        # Try config fallback even on exception
        if config:
            try:
                if "model_defaults" in config:
                    model_defaults = config["model_defaults"]
                    if isinstance(model_defaults, dict):
                        fallback = model_defaults.get("fallback_model", "m2m100_418m")
                    else:
                        fallback = getattr(model_defaults, "fallback_model", "m2m100_418m")
                else:
                    fallback = "m2m100_418m"
                logger.warning(f"[Tier 3] Using fallback due to exception: {fallback}")
                return fallback
            except Exception as fallback_error:
                logger.error(f"[Tier 3] Exception during fallback extraction: {fallback_error}", exc_info=True)
                return "m2m100_418m"  # Ultimate hardcoded fallback
        return None


def _extract_tm_stats(dir_result: "DirectoryResult") -> dict | None:
    """
    Extract TM statistics from translation result.

    TM stats are accessed via the aggregate_stats property (not a field).
    Access path: dir_result.aggregate_stats.{l1_hits, l2_hits, l3_hits, total_segments}

    Args:
        dir_result: DirectoryResult from translation

    Returns:
        TM statistics dict with hit rates, or None if unavailable
    """
    try:
        # Use aggregate_stats property (not tm_stats field - that doesn't exist)
        if hasattr(dir_result, "aggregate_stats"):
            agg = dir_result.aggregate_stats
            if agg and hasattr(agg, "total_segments"):
                total_lookups = getattr(agg, "total_lookups", 0) or agg.total_segments
                l1_hits = getattr(agg, "l1_hits", 0)
                l2_hits = getattr(agg, "l2_hits", 0)
                l3_hits = getattr(agg, "l3_hits", 0)

                if total_lookups > 0:
                    total_hits = l1_hits + l2_hits + l3_hits
                    hit_rate = total_hits / total_lookups

                    result = {
                        "total_lookups": total_lookups,
                        "l1_hits": l1_hits,
                        "l2_hits": l2_hits,
                        "l3_hits": l3_hits,
                        "hit_rate": hit_rate,
                    }

                    logger.info(f"Extracted TM stats for commit message: {hit_rate:.1%} hit rate ({total_hits}/{total_lookups} hits)")
                    return result

        logger.info("No TM stats found - commit message will not include cache metrics")
        return None

    except Exception as e:
        logger.debug(f"Failed to extract TM stats: {e}")
        return None


def _check_verification_failures(dir_result: "DirectoryResult") -> int:
    """
    Check if any files failed verification.

    Args:
        dir_result: DirectoryResult from translation

    Returns:
        Number of files that failed verification, 0 if all passed
    """
    failed_count = 0

    try:
        if hasattr(dir_result, "file_results") and dir_result.file_results:
            for file_result in dir_result.file_results:
                # Check if verification result exists and passed
                if hasattr(file_result, "verification_result") and file_result.verification_result:
                    if not file_result.verification_result.get("passed", True):
                        failed_count += 1
                        errors = file_result.verification_result.get("errors", [])
                        logger.warning(
                            f"Verification failed for {file_result.file_path}: {len(errors)} errors"
                        )

        logger.debug(f"Verification check: {failed_count} file(s) failed")

    except Exception as e:
        logger.debug(f"Failed to check verification failures: {e}")

    return failed_count


def _check_telemetry_failure(dir_result: "DirectoryResult") -> str | None:
    """
    Check if telemetry post failed.

    Args:
        dir_result: DirectoryResult from translation

    Returns:
        Error message if telemetry failed, None if succeeded or not available
    """
    try:
        # Check if telemetry context exists and has status
        if hasattr(dir_result, "telemetry_context") and dir_result.telemetry_context:
            telemetry = dir_result.telemetry_context

            # Check HTTP status code
            if hasattr(telemetry, "http_status_code"):
                status = telemetry.http_status_code
                if status and not (200 <= status < 300):
                    return f"HTTP {status}"

            # Check error flag
            if hasattr(telemetry, "post_failed") and telemetry.post_failed:
                error_msg = getattr(telemetry, "error_message", "Unknown error")
                return error_msg

        # No telemetry context or no errors
        logger.debug("Telemetry check: OK or not available")
        return None

    except Exception as e:
        logger.debug(f"Failed to check telemetry status: {e}")
        return None


def recover_orphaned_commit_manifests(
    git_root: "Path",
    stale_ready_seconds: int = 300,
) -> int:
    """Stub: orphan-manifest recovery is currently disabled.

    The worker calls this function before each run to commit any translation
    files that were written but not committed in a prior interrupted run.
    The active implementation was disabled (commit c784792) pending root-cause
    investigation into corrupted file writes.

    Returns:
        0  (no manifests processed)
    """
    return 0


def _save_commit_hash_to_reports(commit_result: "GitCommitResult") -> None:
    """
    Save commit hash to reports/CONTENT_COMMIT.txt for external review.

    Creates or appends to reports/CONTENT_COMMIT.txt with:
    - Commit hash (full and short)
    - Timestamp
    - Files committed
    - Push status

    Args:
        commit_result: Git commit result with hash and metadata
    """
    try:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)

        commit_file = reports_dir / "CONTENT_COMMIT.txt"

        # Build commit info
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        commit_info = (
            f"Timestamp: {timestamp}\n"
            f"Commit Hash: {commit_result.commit_hash}\n"
            f"Short Hash: {commit_result.commit_hash_short}\n"
            f"Files Committed: {commit_result.files_committed}\n"
            f"Push Success: {commit_result.push_success}\n"
            f"{'='*70}\n\n"
        )

        # Append to file (preserves history)
        with open(commit_file, "a", encoding="utf-8") as f:
            f.write(commit_info)

        logger.info(f"Commit hash saved to: {commit_file}")

    except Exception as e:
        logger.debug(f"Failed to save commit hash to reports: {e}")
