#!/usr/bin/env python3
"""
Repository Reorganization Script - Phase 6.3

This script implements the file organization plan from WI-P6-002.
It supports dry-run mode, phased execution, and comprehensive reporting.

Usage:
    python scripts/reorganize_repo.py --dry-run           # Preview changes
    python scripts/reorganize_repo.py                     # Execute all phases
    python scripts/reorganize_repo.py --phases 1,2,3      # Execute specific phases
    python scripts/reorganize_repo.py --yes               # Auto-confirm prompts

Author: Agent B (Implementation)
Work Item: WI-P6-003
Date: 2026-01-15
"""

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Action:
    """Represents a single migration action."""

    phase: int
    action_type: str  # DELETE, MOVE, CREATE, ARCHIVE
    source: str
    destination: str | None = None
    success: bool = True
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class MigrationReport:
    """Collects and formats migration results."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    dry_run: bool = False
    phases_executed: list[int] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    backup_branch: str | None = None

    def add_action(self, action: Action):
        """Add an action to the report."""
        self.actions.append(action)

    def get_summary(self) -> dict:
        """Generate summary statistics by phase."""
        summary = {}
        for action in self.actions:
            phase = action.phase
            if phase not in summary:
                summary[phase] = {"total": 0, "success": 0, "failed": 0, "skipped": 0}
            summary[phase]["total"] += 1
            if action.skipped:
                summary[phase]["skipped"] += 1
            elif action.success:
                summary[phase]["success"] += 1
            else:
                summary[phase]["failed"] += 1
        return summary

    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            "# Repository Reorganization Report",
            "",
            f"**Timestamp**: {self.timestamp}",
            f"**Mode**: {'DRY-RUN' if self.dry_run else 'LIVE EXECUTION'}",
            f"**Backup Branch**: {self.backup_branch or 'N/A'}",
            "",
            "---",
            "",
            "## Summary",
            "",
            "| Phase | Description | Total | Success | Failed | Skipped |",
            "|-------|-------------|-------|---------|--------|---------|",
        ]

        phase_names = {
            0: "Pre-flight checks",
            1: "Delete empty directories",
            2: "Delete root artifacts",
            3: "Delete cache directories",
            4: "Delete virtual environments",
            5: "Create archive structure",
            6: "Archive legacy code",
            7: "Archive historical reports",
            8: "Archive plans",
            9: "Archive samples",
            10: "Move test files",
            11: "Move scripts",
            12: "Move test fixtures",
            13: "Reorganize scripts",
            14: "Verification",
        }

        summary = self.get_summary()
        for phase in sorted(summary.keys()):
            stats = summary[phase]
            name = phase_names.get(phase, f"Phase {phase}")
            lines.append(
                f"| {phase} | {name} | {stats['total']} | "
                f"{stats['success']} | {stats['failed']} | {stats['skipped']} |"
            )

        # Total row
        total = {"total": 0, "success": 0, "failed": 0, "skipped": 0}
        for stats in summary.values():
            for key in total:
                total[key] += stats[key]
        lines.append(
            f"| **Total** | - | **{total['total']}** | "
            f"**{total['success']}** | **{total['failed']}** | **{total['skipped']}** |"
        )

        lines.extend(
            [
                "",
                "---",
                "",
                "## Detailed Actions",
                "",
            ]
        )

        current_phase = None
        for action in self.actions:
            if action.phase != current_phase:
                current_phase = action.phase
                phase_name = phase_names.get(current_phase, f"Phase {current_phase}")
                lines.extend([f"### Phase {current_phase}: {phase_name}", ""])

            status = "SKIPPED" if action.skipped else ("SUCCESS" if action.success else "FAILED")
            dest = f" -> {action.destination}" if action.destination else ""
            detail = f" ({action.skip_reason})" if action.skip_reason else ""
            detail = f" (ERROR: {action.error})" if action.error else detail
            lines.append(f"- `{action.action_type}`: {action.source}{dest} [{status}]{detail}")

        if self.backup_branch:
            lines.extend(
                [
                    "",
                    "---",
                    "",
                    "## Rollback Commands",
                    "",
                    "If you need to undo these changes:",
                    "",
                    "```bash",
                    f"git checkout {self.backup_branch}",
                    "# Or to reset completely:",
                    f"git reset --hard {self.backup_branch}",
                    "```",
                ]
            )

        lines.extend(
            [
                "",
                "---",
                "",
                f"*Report generated: {self.timestamp}*",
            ]
        )

        return "\n".join(lines)

    def to_json(self) -> str:
        """Generate JSON report."""
        return json.dumps(
            {
                "timestamp": self.timestamp,
                "dry_run": self.dry_run,
                "backup_branch": self.backup_branch,
                "phases_executed": self.phases_executed,
                "summary": self.get_summary(),
                "actions": [
                    {
                        "phase": a.phase,
                        "type": a.action_type,
                        "source": a.source,
                        "destination": a.destination,
                        "success": a.success,
                        "error": a.error,
                        "skipped": a.skipped,
                        "skip_reason": a.skip_reason,
                    }
                    for a in self.actions
                ],
            },
            indent=2,
        )


class RepoReorganizer:
    """Handles repository reorganization operations."""

    def __init__(
        self,
        repo_root: Path,
        dry_run: bool = False,
        phases: set[int] | None = None,
        auto_confirm: bool = False,
    ):
        self.repo_root = repo_root
        self.dry_run = dry_run
        self.phases = phases or set(range(15))  # All phases by default
        self.auto_confirm = auto_confirm
        self.report = MigrationReport(dry_run=dry_run)
        self.report.phases_executed = sorted(self.phases)

    def log(self, message: str, prefix: str = ""):
        """Log a message with optional prefix."""
        dry_run_prefix = "[DRY-RUN] " if self.dry_run else ""
        print(f"{dry_run_prefix}{prefix}{message}")

    def delete_path(self, path: Path, phase: int) -> Action:
        """Delete a file or directory."""
        rel_path = str(path.relative_to(self.repo_root))

        if not path.exists():
            action = Action(
                phase=phase,
                action_type="DELETE",
                source=rel_path,
                skipped=True,
                skip_reason="Does not exist",
            )
            self.log(f"SKIP DELETE: {rel_path} (does not exist)")
            self.report.add_action(action)
            return action

        action = Action(phase=phase, action_type="DELETE", source=rel_path)

        try:
            if not self.dry_run:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            self.log(f"DELETE: {rel_path}")
            action.success = True
        except Exception as e:
            action.success = False
            action.error = str(e)
            self.log(f"ERROR DELETE: {rel_path} - {e}")

        self.report.add_action(action)
        return action

    def move_path(self, source: Path, destination: Path, phase: int) -> Action:
        """Move a file or directory."""
        rel_source = str(source.relative_to(self.repo_root))
        rel_dest = str(destination.relative_to(self.repo_root))

        if not source.exists():
            action = Action(
                phase=phase,
                action_type="MOVE",
                source=rel_source,
                destination=rel_dest,
                skipped=True,
                skip_reason="Source does not exist",
            )
            self.log(f"SKIP MOVE: {rel_source} (does not exist)")
            self.report.add_action(action)
            return action

        action = Action(phase=phase, action_type="MOVE", source=rel_source, destination=rel_dest)

        try:
            if not self.dry_run:
                # Ensure parent directory exists
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Try git mv first, fall back to shutil
                try:
                    subprocess.run(
                        ["git", "mv", str(source), str(destination)],
                        cwd=self.repo_root,
                        check=True,
                        capture_output=True,
                    )
                except subprocess.CalledProcessError:
                    # Fall back to regular move
                    shutil.move(str(source), str(destination))
            self.log(f"MOVE: {rel_source} -> {rel_dest}")
            action.success = True
        except Exception as e:
            action.success = False
            action.error = str(e)
            self.log(f"ERROR MOVE: {rel_source} - {e}")

        self.report.add_action(action)
        return action

    def create_directory(self, path: Path, phase: int) -> Action:
        """Create a directory."""
        rel_path = str(path.relative_to(self.repo_root))

        if path.exists():
            action = Action(
                phase=phase,
                action_type="CREATE",
                source=rel_path,
                skipped=True,
                skip_reason="Already exists",
            )
            self.log(f"SKIP CREATE: {rel_path} (already exists)")
            self.report.add_action(action)
            return action

        action = Action(phase=phase, action_type="CREATE", source=rel_path)

        try:
            if not self.dry_run:
                path.mkdir(parents=True, exist_ok=True)
            self.log(f"CREATE: {rel_path}")
            action.success = True
        except Exception as e:
            action.success = False
            action.error = str(e)
            self.log(f"ERROR CREATE: {rel_path} - {e}")

        self.report.add_action(action)
        return action

    def write_file(self, path: Path, content: str, phase: int) -> Action:
        """Write content to a file."""
        rel_path = str(path.relative_to(self.repo_root))
        action = Action(phase=phase, action_type="WRITE", source=rel_path)

        try:
            if not self.dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            self.log(f"WRITE: {rel_path}")
            action.success = True
        except Exception as e:
            action.success = False
            action.error = str(e)
            self.log(f"ERROR WRITE: {rel_path} - {e}")

        self.report.add_action(action)
        return action

    def confirm(self, message: str) -> bool:
        """Ask for user confirmation."""
        if self.auto_confirm or self.dry_run:
            return True
        response = input(f"{message} (y/n): ").strip().lower()
        return response in ("y", "yes")

    def run(self) -> MigrationReport:
        """Execute all requested phases."""
        self.log("=" * 60)
        self.log("Repository Reorganization Script")
        self.log(f"Repository: {self.repo_root}")
        self.log(f"Mode: {'DRY-RUN' if self.dry_run else 'LIVE'}")
        self.log(f"Phases: {sorted(self.phases)}")
        self.log("=" * 60)

        phase_methods = {
            0: self.phase_0_preflight,
            1: self.phase_1_delete_empty,
            2: self.phase_2_delete_artifacts,
            3: self.phase_3_delete_cache,
            4: self.phase_4_delete_venvs,
            5: self.phase_5_create_archive,
            6: self.phase_6_archive_legacy,
            7: self.phase_7_archive_reports,
            8: self.phase_8_archive_plans,
            9: self.phase_9_archive_samples,
            10: self.phase_10_move_tests,
            11: self.phase_11_move_scripts,
            12: self.phase_12_move_fixtures,
            13: self.phase_13_reorganize_scripts,
            14: self.phase_14_verification,
        }

        for phase_num in sorted(self.phases):
            if phase_num in phase_methods:
                self.log("")
                self.log(f"=== Phase {phase_num} ===")
                phase_methods[phase_num]()

        return self.report

    def phase_0_preflight(self):
        """Pre-flight checks: backup branch, git status."""
        # Create backup branch
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_branch = f"pre-reorganization-backup-{timestamp}"

        action = Action(phase=0, action_type="BACKUP", source=f"Create branch: {backup_branch}")

        try:
            if not self.dry_run:
                # Create backup branch from current HEAD
                subprocess.run(
                    ["git", "branch", backup_branch],
                    cwd=self.repo_root,
                    check=True,
                    capture_output=True,
                )
            self.report.backup_branch = backup_branch
            self.log(f"BACKUP: Created branch {backup_branch}")
            action.success = True
        except subprocess.CalledProcessError as e:
            action.success = False
            action.error = (
                f"Failed to create backup branch: {e.stderr.decode() if e.stderr else str(e)}"
            )
            self.log(f"WARNING: {action.error}")

        self.report.add_action(action)

        # Check git status
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                self.log("WARNING: Uncommitted changes detected")
                if not self.confirm("Continue with uncommitted changes?"):
                    sys.exit(1)
        except subprocess.CalledProcessError as e:
            self.log(f"WARNING: Could not check git status: {e}")

    def phase_1_delete_empty(self):
        """Delete empty/malformed directories."""
        empty_dirs = [
            "testsunitobservability",
            "reportsagentsagent_f_test02tc_test_02",
            "inventories",
            "prompts",
            "MagicMock",
        ]

        for dir_name in empty_dirs:
            path = self.repo_root / dir_name
            self.delete_path(path, phase=1)

    def phase_2_delete_artifacts(self):
        """Delete root-level artifacts."""
        artifacts = [
            "=0.1.99",
            "nul",
            ".coverage",
            "test_benchmark_profile.db",
            "cache_integrity_report.txt",
            "cli_test_output.txt",
            "cuda_translation_attempt2.log",
            "e2e_test.log",
            "metrics.ndjson",
            "metrics_current.json",
            "metrics_test.ndjson",
            "metrics_test_current.json",
            "m2m100_test_output.txt",
            "run_inline_tests.bat",
        ]

        for artifact in artifacts:
            path = self.repo_root / artifact
            self.delete_path(path, phase=2)

    def phase_3_delete_cache(self):
        """Delete cache/build directories."""
        cache_dirs = [
            ".mypy_cache",
            ".pytest_cache",
            ".benchmarks",
            ".cache",
            "htmlcov",
            "hugo_translation_system.egg-info",
            "telemetry_buffer",
            ".translation_progress",
        ]

        for dir_name in cache_dirs:
            path = self.repo_root / dir_name
            self.delete_path(path, phase=3)

    def phase_4_delete_venvs(self):
        """Delete virtual environments."""
        self.log("WARNING: This phase will delete virtual environment directories.")
        self.log("These directories total approximately 13.5 GB.")

        if not self.confirm("Proceed with virtual environment deletion?"):
            self.log("SKIP: Virtual environment deletion skipped by user")
            return

        venvs = [
            "venv",
            "venv_wsl",
            "venv-cuda",
            "venv-cuda312",
            "venv-sonnet-test",
            ".venv",
            ".venv-user-guide",
        ]

        for venv_name in venvs:
            path = self.repo_root / venv_name
            if path.exists():
                # Check if tracked in git
                try:
                    result = subprocess.run(
                        ["git", "ls-files", venv_name, "--error-unmatch"],
                        cwd=self.repo_root,
                        capture_output=True,
                    )
                    if result.returncode == 0:
                        self.log(f"NOTE: {venv_name} is tracked in git")
                        if not self.dry_run:
                            subprocess.run(
                                ["git", "rm", "-r", "--cached", venv_name],
                                cwd=self.repo_root,
                                capture_output=True,
                            )
                except Exception:
                    pass
            self.delete_path(path, phase=4)

    def phase_5_create_archive(self):
        """Create archive directory structure."""
        archive_dirs = [
            "archive/legacy",
            "archive/plans",
            "archive/reports/phases",
            "archive/reports/research",
            "archive/reports/taskcards",
            "archive/reports/healing",
            "archive/samples",
        ]

        for dir_path in archive_dirs:
            path = self.repo_root / dir_path
            self.create_directory(path, phase=5)

        # Create archive README
        readme_content = """# Archive Directory

This directory contains historical artifacts preserved for reference.

## Contents

- `legacy/` - Old translation system (pre-2025)
- `plans/` - Completed implementation plans
- `reports/` - Historical reports and analysis
  - `phases/` - Phase completion reports
  - `research/` - Research documents
  - `taskcards/` - Historical taskcards
  - `healing/` - Healing reports
- `samples/` - Development sample files

## Policy

Files in archive/ are read-only references. Do not modify.
For current work, use the main repository directories.

## Date Archived

Created: 2026-01-15
"""
        readme_path = self.repo_root / "archive" / "README.md"
        self.write_file(readme_path, readme_content, phase=5)

    def phase_6_archive_legacy(self):
        """Archive legacy code."""
        legacy_path = self.repo_root / "legacy"
        if legacy_path.exists() and legacy_path.is_dir():
            # Move contents of legacy to archive/legacy
            archive_legacy = self.repo_root / "archive" / "legacy"
            self.create_directory(archive_legacy, phase=6)

            for item in legacy_path.iterdir():
                dest = archive_legacy / item.name
                self.move_path(item, dest, phase=6)

            # Remove empty legacy directory
            if not self.dry_run and legacy_path.exists():
                try:
                    legacy_path.rmdir()
                except OSError:
                    pass
        else:
            self.log("SKIP: legacy/ directory not found")

    def phase_7_archive_reports(self):
        """Archive historical reports."""
        # Archive phase reports
        for i in range(10):
            phase_dir = self.repo_root / "reports" / f"phase-{i}"
            if phase_dir.exists():
                dest = self.repo_root / "archive" / "reports" / "phases" / f"phase-{i}"
                self.move_path(phase_dir, dest, phase=7)

        # Archive context protection research files
        reports_dir = self.repo_root / "reports"
        if reports_dir.exists():
            for item in reports_dir.iterdir():
                if item.name.startswith("context_protection") and item.suffix == ".md":
                    dest = self.repo_root / "archive" / "reports" / "research" / item.name
                    self.move_path(item, dest, phase=7)

        # Archive taskcards
        claude_taskcards = self.repo_root / "reports" / "claude-taskcards"
        if claude_taskcards.exists():
            dest = self.repo_root / "archive" / "reports" / "taskcards" / "claude-taskcards"
            self.move_path(claude_taskcards, dest, phase=7)

        main_taskcards = self.repo_root / "reports" / "taskcards"
        if main_taskcards.exists():
            dest = self.repo_root / "archive" / "reports" / "taskcards" / "main"
            self.move_path(main_taskcards, dest, phase=7)

        # Archive healing
        healing_dir = self.repo_root / "reports" / "healing"
        if healing_dir.exists():
            dest = self.repo_root / "archive" / "reports" / "healing"
            self.move_path(healing_dir, dest, phase=7)

    def phase_8_archive_plans(self):
        """Archive completed plans."""
        archive_plans = self.repo_root / "plans" / "_archive"
        if archive_plans.exists():
            dest = self.repo_root / "archive" / "plans" / "_archive"
            self.move_path(archive_plans, dest, phase=8)

        implementation = self.repo_root / "plans" / "implementation"
        if implementation.exists():
            dest = self.repo_root / "archive" / "plans" / "implementation"
            self.move_path(implementation, dest, phase=8)

        plan_taskcards = self.repo_root / "plans" / "taskcards"
        if plan_taskcards.exists():
            dest = self.repo_root / "archive" / "plans" / "taskcards"
            self.move_path(plan_taskcards, dest, phase=8)

    def phase_9_archive_samples(self):
        """Archive samples directory."""
        samples_dir = self.repo_root / "samples"
        if samples_dir.exists():
            dest = self.repo_root / "archive" / "samples"
            # Move contents, not the directory itself (since archive/samples already exists)
            for item in samples_dir.iterdir():
                item_dest = dest / item.name
                self.move_path(item, item_dest, phase=9)
            # Remove empty samples directory
            if not self.dry_run and samples_dir.exists():
                try:
                    samples_dir.rmdir()
                except OSError:
                    pass
        else:
            self.log("SKIP: samples/ directory not found")

    def phase_10_move_tests(self):
        """Move root-level test files."""
        # Ensure target directories exist
        self.create_directory(self.repo_root / "tests" / "unit", phase=10)
        self.create_directory(self.repo_root / "tests" / "adhoc", phase=10)

        # Move test files
        test_moves = [
            ("test_adaptive_batch.py", "tests/unit/test_adaptive_batch.py"),
            ("test_ws3_manual.py", "tests/adhoc/test_ws3_manual.py"),
            ("test_ws3_manual_ascii.py", "tests/adhoc/test_ws3_manual_ascii.py"),
        ]

        for source, dest in test_moves:
            src_path = self.repo_root / source
            dst_path = self.repo_root / dest
            self.move_path(src_path, dst_path, phase=10)

    def phase_11_move_scripts(self):
        """Move root-level scripts."""
        # Create diagnostics directory
        self.create_directory(self.repo_root / "scripts" / "diagnostics", phase=11)

        script_moves = [
            ("run_translation.py", "scripts/run_translation.py"),
            ("diagnose_nllb_tokenizer.py", "scripts/diagnostics/diagnose_nllb_tokenizer.py"),
        ]

        for source, dest in script_moves:
            src_path = self.repo_root / source
            dst_path = self.repo_root / dest
            self.move_path(src_path, dst_path, phase=11)

    def phase_12_move_fixtures(self):
        """Move test fixtures."""
        # Create fixtures directory
        fixtures_dir = self.repo_root / "tests" / "fixtures"
        self.create_directory(fixtures_dir, phase=12)

        # Move test_fixtures contents
        test_fixtures = self.repo_root / "test_fixtures"
        if test_fixtures.exists() and test_fixtures.is_dir():
            for item in test_fixtures.iterdir():
                dest = fixtures_dir / item.name
                self.move_path(item, dest, phase=12)
            # Remove empty directory
            if not self.dry_run and test_fixtures.exists():
                try:
                    test_fixtures.rmdir()
                except OSError:
                    pass

        # Move test_phase5_verify
        phase5_verify = self.repo_root / "test_phase5_verify"
        if phase5_verify.exists():
            dest = fixtures_dir / "phase5_verify"
            self.move_path(phase5_verify, dest, phase=12)

    def phase_13_reorganize_scripts(self):
        """Reorganize scripts directory."""
        # Create archived migrations directory
        migrations_dir = self.repo_root / "scripts" / "archived" / "migrations"
        self.create_directory(migrations_dir, phase=13)

        # Move migration scripts
        migration_scripts = [
            "migrate_filters.py",
            "migrate_legacy_cache.py",
            "monitor_migration.py",
            "verify_migration.py",
        ]

        for script in migration_scripts:
            src_path = self.repo_root / "scripts" / script
            dst_path = migrations_dir / script
            self.move_path(src_path, dst_path, phase=13)

        # Move telemetry cleanup
        observability_dir = self.repo_root / "scripts" / "observability"
        self.create_directory(observability_dir, phase=13)

        telemetry_cleanup = self.repo_root / "scripts" / "telemetry_cleanup"
        if telemetry_cleanup.exists():
            dest = observability_dir / "telemetry_cleanup"
            self.move_path(telemetry_cleanup, dest, phase=13)

    def phase_14_verification(self):
        """Verify the reorganization results."""
        self.log("Running verification checks...")

        # Check for import errors
        action = Action(phase=14, action_type="VERIFY", source="Python imports")
        try:
            if not self.dry_run:
                result = subprocess.run(
                    [sys.executable, "-c", "import src"],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    action.success = False
                    action.error = result.stderr[:200] if result.stderr else "Import failed"
                else:
                    action.success = True
            else:
                action.success = True
            self.log(f"VERIFY: Python imports {'OK' if action.success else 'FAILED'}")
        except Exception as e:
            action.success = False
            action.error = str(e)
        self.report.add_action(action)

        # Verify archive structure
        archive_path = self.repo_root / "archive"
        action = Action(phase=14, action_type="VERIFY", source="Archive structure")
        if self.dry_run or archive_path.exists():
            action.success = True
            self.log("VERIFY: Archive structure OK")
        else:
            action.success = False
            action.error = "Archive directory not found"
            self.log("VERIFY: Archive structure MISSING")
        self.report.add_action(action)

        # Summary
        summary = self.report.get_summary()
        total_actions = sum(s["total"] for s in summary.values())
        total_success = sum(s["success"] for s in summary.values())
        total_failed = sum(s["failed"] for s in summary.values())

        self.log("")
        self.log(f"Total actions: {total_actions}")
        self.log(f"Successful: {total_success}")
        self.log(f"Failed: {total_failed}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Repository Reorganization Script - Phase 6.3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Preview all changes (dry-run)
    python scripts/reorganize_repo.py --dry-run

    # Execute all phases
    python scripts/reorganize_repo.py

    # Execute specific phases
    python scripts/reorganize_repo.py --phases 1,2,3

    # Execute with auto-confirm
    python scripts/reorganize_repo.py --yes

    # Save report to specific location
    python scripts/reorganize_repo.py --report-dir reports/migration/
        """,
    )

    parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Preview changes without executing"
    )

    parser.add_argument(
        "--phases", "-p", type=str, help="Comma-separated list of phases to run (e.g., 1,2,3)"
    )

    parser.add_argument("--yes", "-y", action="store_true", help="Auto-confirm all prompts")

    parser.add_argument(
        "--report-dir", type=str, help="Directory to save reports (default: reports/migration/)"
    )

    parser.add_argument(
        "--repo-root", type=str, help="Repository root directory (default: auto-detect)"
    )

    args = parser.parse_args()

    # Determine repo root
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        # Auto-detect: script is in scripts/, so go up one level
        repo_root = Path(__file__).parent.parent.resolve()

    if not (repo_root / ".git").exists():
        print(f"ERROR: {repo_root} is not a git repository")
        sys.exit(1)

    # Parse phases
    phases = None
    if args.phases:
        try:
            phases = set(int(p.strip()) for p in args.phases.split(","))
        except ValueError:
            print(f"ERROR: Invalid phases format: {args.phases}")
            sys.exit(1)

    # Run reorganization
    reorganizer = RepoReorganizer(
        repo_root=repo_root,
        dry_run=args.dry_run,
        phases=phases,
        auto_confirm=args.yes,
    )

    report = reorganizer.run()

    # Determine report directory
    report_dir = Path(args.report_dir) if args.report_dir else repo_root / "reports" / "migration"
    report_dir.mkdir(parents=True, exist_ok=True)

    # Save reports
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "dry_run" if args.dry_run else "live"

    md_path = report_dir / f"migration_report_{mode}_{timestamp}.md"
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    print(f"\nMarkdown report saved: {md_path}")

    json_path = report_dir / f"migration_report_{mode}_{timestamp}.json"
    json_path.write_text(report.to_json(), encoding="utf-8")
    print(f"JSON report saved: {json_path}")

    # Exit code based on failures
    summary = report.get_summary()
    total_failed = sum(s["failed"] for s in summary.values())

    if total_failed > 0:
        print(f"\nWARNING: {total_failed} actions failed. Review report for details.")
        sys.exit(1)

    print("\nReorganization complete!")
    sys.exit(0)


if __name__ == "__main__":
    main()
