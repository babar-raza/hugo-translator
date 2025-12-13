#!/usr/bin/env python3
"""
Tests for Rollback Automation

Tests the rollback script and its components.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import after path setup
from scripts.rollback import (
    BackupCreator,
    GitManager,
    RollbackExecutor,
    RollbackManager,
    RollbackPlan,
    RollbackResult,
    RollbackVerifier
)


# ============================================================================
# GitManager Tests
# ============================================================================


def test_git_manager_initialization():
    """Test GitManager can be initialized."""
    repo_path = Path(__file__).parent.parent.parent
    git_manager = GitManager(repo_path)

    assert git_manager is not None
    assert git_manager.repo_path == repo_path


@patch('subprocess.run')
def test_git_manager_get_current_commit(mock_run):
    """Test getting current commit."""
    # Mock git rev-parse HEAD
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "abc123def456\n"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    repo_path = Path(__file__).parent.parent.parent
    git_manager = GitManager(repo_path)

    commit = git_manager.get_current_commit()

    assert commit == "abc123def456"
    mock_run.assert_called_once()


@patch('subprocess.run')
def test_git_manager_get_current_branch(mock_run):
    """Test getting current branch."""
    # Mock git rev-parse --abbrev-ref HEAD
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "main\n"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    repo_path = Path(__file__).parent.parent.parent
    git_manager = GitManager(repo_path)

    branch = git_manager.get_current_branch()

    assert branch == "main"


@patch('subprocess.run')
def test_git_manager_resolve_ref(mock_run):
    """Test resolving reference to commit."""
    # Mock git rev-parse
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "abc123def456\n"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    repo_path = Path(__file__).parent.parent.parent
    git_manager = GitManager(repo_path)

    commit = git_manager.resolve_ref('HEAD~1')

    assert commit == "abc123def456"


@patch('subprocess.run')
def test_git_manager_has_uncommitted_changes(mock_run):
    """Test checking for uncommitted changes."""
    # Mock git status --porcelain with changes
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "M file.py\n"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    repo_path = Path(__file__).parent.parent.parent
    git_manager = GitManager(repo_path)

    has_changes = git_manager.has_uncommitted_changes()

    assert has_changes is True


@patch('subprocess.run')
def test_git_manager_is_clean_checkout(mock_run):
    """Test checking if checkout is clean."""
    # Mock git status --porcelain with no changes
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    repo_path = Path(__file__).parent.parent.parent
    git_manager = GitManager(repo_path)

    is_clean = git_manager.is_clean_checkout()

    assert is_clean is True


# ============================================================================
# BackupCreator Tests
# ============================================================================


def test_backup_creator_initialization():
    """Test BackupCreator can be initialized."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        backup_creator = BackupCreator(project_root)

        assert backup_creator is not None
        assert backup_creator.project_root == project_root


def test_backup_creator_create_backup():
    """Test creating backup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # Create dummy config
        config_dir = project_root / 'config'
        config_dir.mkdir()
        (config_dir / 'test.yaml').write_text('test: value')

        # Create backup
        backup_creator = BackupCreator(project_root)

        with patch.object(GitManager, 'get_current_commit', return_value='abc123'):
            backup_path = backup_creator.create_backup('test')

        # Verify backup
        assert backup_path.exists()
        assert (backup_path / 'config' / 'test.yaml').exists()
        assert (backup_path / 'commit.txt').exists()
        assert (backup_path / 'manifest.json').exists()

        # Verify manifest
        manifest = json.loads((backup_path / 'manifest.json').read_text())
        assert manifest['label'] == 'test'
        assert manifest['commit'] == 'abc123'


# ============================================================================
# RollbackExecutor Tests
# ============================================================================


def test_rollback_executor_initialization():
    """Test RollbackExecutor can be initialized."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        executor = RollbackExecutor(project_root)

        assert executor is not None
        assert executor.project_root == project_root


@patch.object(GitManager, 'get_current_commit', return_value='abc123')
@patch.object(GitManager, 'get_current_branch', return_value='main')
@patch.object(GitManager, 'resolve_ref', return_value='def456')
@patch.object(GitManager, 'get_diff_summary', return_value=['file1.py | 10 +++', 'file2.py | 5 ---'])
@patch.object(GitManager, 'is_clean_checkout', return_value=True)
def test_rollback_executor_plan_rollback(
    mock_clean,
    mock_diff,
    mock_resolve,
    mock_branch,
    mock_commit
):
    """Test planning rollback."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        executor = RollbackExecutor(project_root)

        plan = executor.plan_rollback('HEAD~1')

        assert plan is not None
        assert plan.current_commit == 'abc123'
        assert plan.target_commit == 'def456'
        assert plan.current_branch == 'main'
        assert plan.target_ref == 'HEAD~1'
        assert len(plan.changes) == 2


@patch.object(GitManager, 'get_current_commit', return_value='abc123')
@patch.object(GitManager, 'get_current_branch', return_value='main')
@patch.object(GitManager, 'resolve_ref', return_value='def456')
@patch.object(GitManager, 'get_diff_summary', return_value=[])
@patch.object(GitManager, 'is_clean_checkout', return_value=False)
def test_rollback_executor_plan_with_uncommitted_changes(
    mock_clean,
    mock_diff,
    mock_resolve,
    mock_branch,
    mock_commit
):
    """Test plan includes warning for uncommitted changes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        executor = RollbackExecutor(project_root)

        plan = executor.plan_rollback('HEAD~1')

        assert any('uncommitted' in w.lower() for w in plan.warnings)


@patch.object(GitManager, 'is_clean_checkout', return_value=True)
@patch.object(GitManager, 'checkout_commit')
@patch.object(GitManager, 'get_current_commit', side_effect=['abc123', 'def456'])
@patch.object(BackupCreator, 'create_backup')
def test_rollback_executor_execute_rollback(
    mock_backup,
    mock_commit,
    mock_checkout,
    mock_clean
):
    """Test executing rollback."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        mock_backup.return_value = project_root / 'backups' / 'test'

        executor = RollbackExecutor(project_root)

        plan = RollbackPlan(
            current_commit='abc123',
            target_commit='def456',
            current_branch='main',
            target_ref='HEAD~1',
            changes=[]
        )

        result = executor.execute_rollback(plan, create_backup=True, dry_run=False)

        assert result.success is True
        assert result.rollback_commit == 'def456'
        mock_checkout.assert_called_once_with('def456')


def test_rollback_executor_dry_run():
    """Test dry-run doesn't actually rollback."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        executor = RollbackExecutor(project_root)

        plan = RollbackPlan(
            current_commit='abc123',
            target_commit='def456',
            current_branch='main',
            target_ref='HEAD~1',
            changes=[]
        )

        with patch.object(GitManager, 'is_clean_checkout', return_value=True):
            with patch.object(GitManager, 'checkout_commit') as mock_checkout:
                result = executor.execute_rollback(plan, create_backup=False, dry_run=True)

                assert result.success is True
                mock_checkout.assert_not_called()


# ============================================================================
# RollbackVerifier Tests
# ============================================================================


def test_rollback_verifier_initialization():
    """Test RollbackVerifier can be initialized."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        verifier = RollbackVerifier(project_root)

        assert verifier is not None
        assert verifier.project_root == project_root


@patch.object(GitManager, 'get_current_commit', return_value='def456')
@patch('subprocess.run')
def test_rollback_verifier_verify_success(mock_run, mock_commit):
    """Test verification when rollback successful."""
    # Mock smoke test success
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "All tests passed"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # Create required files
        (project_root / 'src').mkdir()
        (project_root / 'src' / '__init__.py').touch()
        (project_root / 'scripts').mkdir()
        (project_root / 'scripts' / 'production_readiness_check.py').touch()
        (project_root / 'scripts' / 'run_smoke_tests.py').write_text('print("test")')

        verifier = RollbackVerifier(project_root)

        plan = RollbackPlan(
            current_commit='abc123',
            target_commit='def456',
            current_branch='main',
            target_ref='HEAD~1'
        )

        result = RollbackResult(
            success=True,
            plan=plan,
            execution_time=5.0,
            verification_passed=False,
            rollback_commit='def456'
        )

        verified = verifier.verify_rollback(result)

        assert verified is True


@patch.object(GitManager, 'get_current_commit', return_value='wrong_commit')
def test_rollback_verifier_verify_wrong_commit(mock_commit):
    """Test verification fails if commit doesn't match."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        verifier = RollbackVerifier(project_root)

        plan = RollbackPlan(
            current_commit='abc123',
            target_commit='def456',
            current_branch='main',
            target_ref='HEAD~1'
        )

        result = RollbackResult(
            success=True,
            plan=plan,
            execution_time=5.0,
            verification_passed=False,
            rollback_commit='def456'
        )

        verified = verifier.verify_rollback(result)

        assert verified is False


# ============================================================================
# RollbackManager Integration Tests
# ============================================================================


def test_rollback_manager_initialization():
    """Test RollbackManager can be initialized."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        manager = RollbackManager(project_root)

        assert manager is not None
        assert manager.project_root == project_root


@patch.object(RollbackExecutor, 'plan_rollback')
@patch.object(RollbackExecutor, 'execute_rollback')
@patch.object(RollbackVerifier, 'verify_rollback', return_value=True)
def test_rollback_manager_rollback_to_commit(mock_verify, mock_execute, mock_plan):
    """Test rollback to specific commit."""
    # Setup mocks
    plan = RollbackPlan(
        current_commit='abc123',
        target_commit='def456',
        current_branch='main',
        target_ref='def456'
    )
    mock_plan.return_value = plan

    result = RollbackResult(
        success=True,
        plan=plan,
        execution_time=5.0,
        verification_passed=False,
        rollback_commit='def456'
    )
    mock_execute.return_value = result

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        manager = RollbackManager(project_root)

        rollback_result = manager.rollback_to_commit('def456', dry_run=False, skip_verify=False)

        assert rollback_result.success is True
        assert rollback_result.verification_passed is True
        mock_plan.assert_called_once_with('def456')
        mock_verify.assert_called_once()


@patch.object(RollbackExecutor, 'plan_rollback')
@patch.object(RollbackExecutor, 'execute_rollback')
def test_rollback_manager_dry_run(mock_execute, mock_plan):
    """Test dry-run mode."""
    # Setup mocks
    plan = RollbackPlan(
        current_commit='abc123',
        target_commit='def456',
        current_branch='main',
        target_ref='HEAD~1'
    )
    mock_plan.return_value = plan

    result = RollbackResult(
        success=True,
        plan=plan,
        execution_time=0.1,
        verification_passed=True,
        rollback_commit='def456'
    )
    mock_execute.return_value = result

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        manager = RollbackManager(project_root)

        rollback_result = manager.rollback_to_previous(dry_run=True, skip_verify=False)

        assert rollback_result.success is True
        mock_execute.assert_called_once()
        assert mock_execute.call_args[1]['dry_run'] is True


def test_rollback_plan_to_dict():
    """Test RollbackPlan serialization."""
    plan = RollbackPlan(
        current_commit='abc123',
        target_commit='def456',
        current_branch='main',
        target_ref='HEAD~1',
        changes=['file1.py', 'file2.py'],
        warnings=['warning1']
    )

    plan_dict = plan.to_dict()

    assert plan_dict['current_commit'] == 'abc123'
    assert plan_dict['target_commit'] == 'def456'
    assert len(plan_dict['changes']) == 2
    assert len(plan_dict['warnings']) == 1


def test_rollback_result_to_dict():
    """Test RollbackResult serialization."""
    plan = RollbackPlan(
        current_commit='abc123',
        target_commit='def456',
        current_branch='main',
        target_ref='HEAD~1'
    )

    result = RollbackResult(
        success=True,
        plan=plan,
        execution_time=5.5,
        verification_passed=True,
        rollback_commit='def456'
    )

    result_dict = result.to_dict()

    assert result_dict['success'] is True
    assert result_dict['execution_time'] == 5.5
    assert result_dict['verification_passed'] is True
    assert result_dict['plan']['current_commit'] == 'abc123'
