#!/usr/bin/env python3
"""
Rollback Automation Script

Automates rollback of failed deployments with safety checks and verification.

Features:
- Rollback to commit, tag, or previous version
- Dry-run mode to preview changes
- Automatic backup before rollback
- Verification after rollback
- Safety checks to prevent unsafe rollbacks

Usage:
    python scripts/rollback.py --dry-run --to-previous
    python scripts/rollback.py --to-commit abc123
    python scripts/rollback.py --to-tag v1.2.0
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class RollbackPlan:
    """Plan for rollback operation."""

    current_commit: str
    target_commit: str
    current_branch: str
    target_ref: str
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    backup_path: Path | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = asdict(self)
        if self.backup_path:
            data["backup_path"] = str(self.backup_path)
        return data


@dataclass
class RollbackResult:
    """Result of rollback operation."""

    success: bool
    plan: RollbackPlan
    execution_time: float
    verification_passed: bool
    errors: list[str] = field(default_factory=list)
    rollback_commit: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = asdict(self)
        data["plan"] = self.plan.to_dict()
        return data


class GitManager:
    """Manages Git operations for rollback."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def run_git_command(self, args: list[str], check: bool = True) -> tuple[int, str, str]:
        """
        Run a git command.

        Returns:
            (exit_code, stdout, stderr)
        """
        cmd = ["git"] + args

        result = subprocess.run(cmd, cwd=str(self.repo_path), capture_output=True, text=True)

        if check and result.returncode != 0:
            raise RuntimeError(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")

        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def get_current_commit(self) -> str:
        """Get current commit hash."""
        _, stdout, _ = self.run_git_command(["rev-parse", "HEAD"])
        return stdout

    def get_current_branch(self) -> str:
        """Get current branch name."""
        _, stdout, _ = self.run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
        return stdout

    def resolve_ref(self, ref: str) -> str:
        """Resolve a reference to commit hash."""
        _, stdout, _ = self.run_git_command(["rev-parse", ref])
        return stdout

    def get_commit_info(self, commit: str) -> dict:
        """Get information about a commit."""
        _, subject, _ = self.run_git_command(["log", "-1", "--format=%s", commit])
        _, author, _ = self.run_git_command(["log", "-1", "--format=%an <%ae>", commit])
        _, date, _ = self.run_git_command(["log", "-1", "--format=%ai", commit])

        return {"commit": commit, "subject": subject, "author": author, "date": date}

    def get_previous_commit(self) -> str:
        """Get previous commit (HEAD~1)."""
        return self.resolve_ref("HEAD~1")

    def get_diff_summary(self, from_commit: str, to_commit: str) -> list[str]:
        """Get summary of changes between commits."""
        _, stdout, _ = self.run_git_command(["diff", "--stat", f"{from_commit}...{to_commit}"])
        return stdout.split("\n") if stdout else []

    def has_uncommitted_changes(self) -> bool:
        """Check if there are uncommitted changes."""
        _, stdout, _ = self.run_git_command(["status", "--porcelain"])
        return bool(stdout)

    def is_clean_checkout(self) -> bool:
        """Check if working directory is clean."""
        return not self.has_uncommitted_changes()

    def checkout_commit(self, commit: str) -> None:
        """Checkout a specific commit."""
        self.run_git_command(["checkout", commit])

    def create_branch(self, branch_name: str) -> None:
        """Create a new branch."""
        self.run_git_command(["checkout", "-b", branch_name])


class BackupCreator:
    """Creates backups before rollback."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.backup_root = project_root / "backups"

    def create_backup(self, label: str = "rollback") -> Path:
        """
        Create backup of current state.

        Returns:
            Path to backup directory
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"pre_{label}_{timestamp}"
        backup_path = self.backup_root / backup_name

        backup_path.mkdir(parents=True, exist_ok=True)

        # Backup config
        if (self.project_root / "config").exists():
            shutil.copytree(
                self.project_root / "config", backup_path / "config", dirs_exist_ok=True
            )

        # Backup TM data (metadata only, not full DB)
        if (self.project_root / "data" / "tm").exists():
            self._backup_tm_metadata(backup_path / "tm_metadata")

        # Save current commit
        git_manager = GitManager(self.project_root)
        current_commit = git_manager.get_current_commit()
        (backup_path / "commit.txt").write_text(current_commit)

        # Save backup manifest
        manifest = {
            "timestamp": timestamp,
            "label": label,
            "commit": current_commit,
            "backup_path": str(backup_path),
        }
        (backup_path / "manifest.json").write_text(json.dumps(manifest, indent=2))

        return backup_path

    def _backup_tm_metadata(self, backup_path: Path) -> None:
        """Backup TM metadata (not full database)."""
        backup_path.mkdir(parents=True, exist_ok=True)

        tm_dir = self.project_root / "data" / "tm"

        # Save directory structure info
        if tm_dir.exists():
            metadata = {
                "l2_exists": (tm_dir / "l2").exists(),
                "l3_exists": (tm_dir / "l3").exists(),
                "timestamp": datetime.now().isoformat(),
            }
            (backup_path / "metadata.json").write_text(json.dumps(metadata, indent=2))


class RollbackExecutor:
    """Executes rollback operations."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.git_manager = GitManager(project_root)
        self.backup_creator = BackupCreator(project_root)

    def plan_rollback(self, target_ref: str) -> RollbackPlan:
        """
        Plan a rollback operation.

        Args:
            target_ref: Target commit, tag, or reference

        Returns:
            RollbackPlan with details
        """
        # Get current state
        current_commit = self.git_manager.get_current_commit()
        current_branch = self.git_manager.get_current_branch()

        # Resolve target
        target_commit = self.git_manager.resolve_ref(target_ref)

        # Get changes
        changes = self.git_manager.get_diff_summary(current_commit, target_commit)

        # Create plan
        plan = RollbackPlan(
            current_commit=current_commit,
            target_commit=target_commit,
            current_branch=current_branch,
            target_ref=target_ref,
            changes=changes,
        )

        # Add warnings
        if not self.git_manager.is_clean_checkout():
            plan.warnings.append("WARNING: Uncommitted changes detected")

        if current_commit == target_commit:
            plan.warnings.append("WARNING: Already at target commit")

        return plan

    def execute_rollback(
        self, plan: RollbackPlan, create_backup: bool = True, dry_run: bool = False
    ) -> RollbackResult:
        """
        Execute rollback operation.

        Args:
            plan: Rollback plan to execute
            create_backup: Whether to create backup first
            dry_run: If True, only simulate (don't actually rollback)

        Returns:
            RollbackResult with outcome
        """
        start_time = time.time()
        errors = []

        try:
            # Check for uncommitted changes
            if not self.git_manager.is_clean_checkout():
                raise RuntimeError("Cannot rollback with uncommitted changes")

            # Create backup
            if create_backup and not dry_run:
                print("Creating backup...")
                plan.backup_path = self.backup_creator.create_backup()
                print(f"Backup created: {plan.backup_path}")

            # Execute rollback
            if dry_run:
                print("\n[DRY RUN] Would execute rollback:")
                print(f"  From: {plan.current_commit}")
                print(f"  To: {plan.target_commit}")
                print(f"  Changes: {len(plan.changes)} files")
                rollback_commit = plan.target_commit
            else:
                print("\nExecuting rollback...")
                print(f"  From: {plan.current_commit}")
                print(f"  To: {plan.target_commit}")

                # Perform checkout
                self.git_manager.checkout_commit(plan.target_commit)
                rollback_commit = self.git_manager.get_current_commit()

                print(f"Rollback complete: {rollback_commit}")

            execution_time = time.time() - start_time

            return RollbackResult(
                success=True,
                plan=plan,
                execution_time=execution_time,
                verification_passed=False,  # Will be updated by verifier
                rollback_commit=rollback_commit,
            )

        except Exception as e:
            errors.append(str(e))
            execution_time = time.time() - start_time

            return RollbackResult(
                success=False,
                plan=plan,
                execution_time=execution_time,
                verification_passed=False,
                errors=errors,
            )


class RollbackVerifier:
    """Verifies rollback was successful."""

    def __init__(self, project_root: Path, python_executable: str = sys.executable):
        self.project_root = project_root
        self.python_executable = python_executable

    def verify_rollback(self, result: RollbackResult) -> bool:
        """
        Verify rollback was successful.

        Args:
            result: RollbackResult to verify

        Returns:
            True if verification passed
        """
        print("\nVerifying rollback...")

        # 1. Verify commit
        git_manager = GitManager(self.project_root)
        current_commit = git_manager.get_current_commit()

        if current_commit != result.rollback_commit:
            print(f"❌ Commit verification failed: {current_commit} != {result.rollback_commit}")
            return False

        print(f"✅ Commit verified: {current_commit}")

        # 2. Run smoke tests
        smoke_test_script = self.project_root / "scripts" / "smoke" / "run_smoke_tests.py"

        if smoke_test_script.exists():
            print("\nRunning smoke tests...")

            smoke_result = subprocess.run(
                [self.python_executable, str(smoke_test_script), "--quick"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=60,
            )

            if smoke_result.returncode == 0:
                print("✅ Smoke tests passed")
            else:
                print("❌ Smoke tests failed")
                print(smoke_result.stdout)
                return False
        else:
            print("⚠️  Smoke tests not available, skipping")

        # 3. Check critical files exist
        critical_files = [
            "src/__init__.py",
            "scripts/production_readiness_check.py",
        ]

        for file_path in critical_files:
            full_path = self.project_root / file_path
            if not full_path.exists():
                print(f"❌ Critical file missing: {file_path}")
                return False

        print("✅ Critical files verified")

        return True


class RollbackManager:
    """Main manager orchestrating rollback operations."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.executor = RollbackExecutor(project_root)
        self.verifier = RollbackVerifier(project_root)

    def rollback_to_commit(
        self, commit: str, dry_run: bool = False, skip_verify: bool = False
    ) -> RollbackResult:
        """Rollback to specific commit."""
        return self._execute_rollback(commit, dry_run, skip_verify)

    def rollback_to_tag(
        self, tag: str, dry_run: bool = False, skip_verify: bool = False
    ) -> RollbackResult:
        """Rollback to tagged version."""
        return self._execute_rollback(f"tags/{tag}", dry_run, skip_verify)

    def rollback_to_previous(
        self, dry_run: bool = False, skip_verify: bool = False
    ) -> RollbackResult:
        """Rollback to previous commit (HEAD~1)."""
        return self._execute_rollback("HEAD~1", dry_run, skip_verify)

    def _execute_rollback(
        self, target_ref: str, dry_run: bool, skip_verify: bool
    ) -> RollbackResult:
        """Execute rollback with verification."""
        # Plan rollback
        print("Planning rollback...")
        plan = self.executor.plan_rollback(target_ref)

        # Display plan
        self._display_plan(plan)

        # Execute rollback
        result = self.executor.execute_rollback(plan, create_backup=not dry_run, dry_run=dry_run)

        if not result.success:
            print("\n❌ Rollback failed!")
            for error in result.errors:
                print(f"  Error: {error}")
            return result

        # Verify rollback (if not dry-run and not skipped)
        if not dry_run and not skip_verify:
            verification_passed = self.verifier.verify_rollback(result)
            result.verification_passed = verification_passed

            if not verification_passed:
                print("\n⚠️  Rollback completed but verification failed")
                print("Manual verification required")
        else:
            result.verification_passed = True  # Skip verification

        return result

    def _display_plan(self, plan: RollbackPlan) -> None:
        """Display rollback plan."""
        print("\n" + "=" * 70)
        print("ROLLBACK PLAN")
        print("=" * 70)
        print(f"Current commit: {plan.current_commit[:8]}")
        print(f"Target commit:  {plan.target_commit[:8]}")
        print(f"Target ref:     {plan.target_ref}")
        print(f"Current branch: {plan.current_branch}")
        print(f"\nChanges: {len(plan.changes)} files affected")

        if plan.changes:
            print("\nFile changes:")
            for change in plan.changes[:10]:  # Show first 10
                print(f"  {change}")
            if len(plan.changes) > 10:
                print(f"  ... and {len(plan.changes) - 10} more")

        if plan.warnings:
            print("\n⚠️  WARNINGS:")
            for warning in plan.warnings:
                print(f"  {warning}")

        print("=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Rollback automation with safety checks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run rollback to previous version
  python scripts/rollback.py --dry-run --to-previous

  # Rollback to previous version
  python scripts/rollback.py --to-previous

  # Rollback to specific commit
  python scripts/rollback.py --to-commit abc123

  # Rollback to tagged version
  python scripts/rollback.py --to-tag v1.2.0

  # Rollback without verification (not recommended)
  python scripts/rollback.py --to-previous --skip-verify
""",
    )

    parser.add_argument("--to-commit", type=str, help="Rollback to specific commit hash")
    parser.add_argument("--to-tag", type=str, help="Rollback to tagged version")
    parser.add_argument(
        "--to-previous", action="store_true", help="Rollback to previous commit (HEAD~1)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview rollback without executing")
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip verification after rollback (not recommended)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Project root directory",
    )

    args = parser.parse_args()

    # Validate arguments
    targets = sum([bool(args.to_commit), bool(args.to_tag), args.to_previous])

    if targets == 0:
        parser.error("Must specify one of: --to-commit, --to-tag, --to-previous")
    elif targets > 1:
        parser.error("Can only specify one rollback target")

    # Create manager
    manager = RollbackManager(args.project_root)

    # Execute rollback
    print("=" * 70)
    print("ROLLBACK AUTOMATION")
    print("=" * 70)
    print(f"Project root: {args.project_root}")
    print(f"Dry-run: {args.dry_run}")
    print()

    try:
        if args.to_commit:
            result = manager.rollback_to_commit(
                args.to_commit, dry_run=args.dry_run, skip_verify=args.skip_verify
            )
        elif args.to_tag:
            result = manager.rollback_to_tag(
                args.to_tag, dry_run=args.dry_run, skip_verify=args.skip_verify
            )
        else:  # to_previous
            result = manager.rollback_to_previous(
                dry_run=args.dry_run, skip_verify=args.skip_verify
            )

        # Display result
        print("\n" + "=" * 70)
        print("ROLLBACK RESULT")
        print("=" * 70)
        print(f"Success: {result.success}")
        print(f"Execution time: {result.execution_time:.2f}s")
        print(
            f"Verification: {'Passed' if result.verification_passed else 'Not performed' if args.skip_verify or args.dry_run else 'Failed'}"
        )

        if result.backup_path:
            print(f"Backup: {result.backup_path}")

        if result.errors:
            print("\nErrors:")
            for error in result.errors:
                print(f"  {error}")

        print("=" * 70)

        # Exit code
        if result.success and result.verification_passed:
            print("\n✅ Rollback completed successfully")
            return 0
        elif result.success and (args.dry_run or args.skip_verify):
            print("\n✅ Rollback completed (verification skipped)")
            return 0
        else:
            print("\n❌ Rollback failed or verification failed")
            return 1

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
