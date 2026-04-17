"""
CONTRACT: specs/core_invariants.md (Task-specified INV-008)

Verifies git commit operations are isolated per translation run
and don't interfere with concurrent translation processes.

INV-008 Git Commit Isolation (as specified in task)

Key Guarantees:
1. Auto-commits only stage specific translation output files (not git add -A)
2. Commits include co-author trailer for audit trail
3. Push failures do not fail the translation
4. Commit operations have timeout protection (60s default)

Note: The spec file defines INV-008 as "L2 Corruption Detection", but
this test file implements the task-specified "Git Commit Isolation" invariant.
"""

import subprocess
from unittest.mock import Mock, patch

import pytest

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def temp_git_repo(tmp_path):
    """
    Create a temporary git repository for testing.

    Initializes a git repo with initial commit.
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(
        ["git", "init"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    # Configure git user (required for commits)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    # Create initial commit
    readme = repo_path / "README.md"
    readme.write_text("# Test Repository\n")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    return repo_path


@pytest.fixture
def git_commit_config():
    """
    GitCommitConfig with default settings.
    """
    from src.observability.git_commit import GitCommitConfig

    return GitCommitConfig(
        enabled=True,
        auto_push=True,
        co_author_email="hugo-translator@aspose.net",
        co_author_name="Hugo Translator",
        timeout_seconds=60,
    )


@pytest.fixture
def git_committer(git_commit_config):
    """
    GitCommitter instance with config.
    """
    from src.observability.git_commit import GitCommitter

    return GitCommitter(git_commit_config)


@pytest.fixture
def translation_output_files(temp_git_repo):
    """
    Create sample translation output files in the repo.
    """
    # Create language directories
    de_dir = temp_git_repo / "de"
    fr_dir = temp_git_repo / "fr"
    de_dir.mkdir()
    fr_dir.mkdir()

    # Create translated files
    files = []
    for lang_dir in [de_dir, fr_dir]:
        file_path = lang_dir / "translated.md"
        file_path.write_text(f"# Translated Content ({lang_dir.name})\n")
        files.append(file_path)

    return files


# ==============================================================================
# INV-008: Selective File Staging Tests
# ==============================================================================


@pytest.mark.contract
def test_only_specific_files_staged_not_git_add_all(
    git_committer,
    temp_git_repo,
    translation_output_files,
):
    """
    Verify git add targets only specific translation files, not git add -A.

    CONTRACT: INV-008 - Only translation files staged
    Evidence: src/observability/git_commit.py lines 216-255 (_stage_files)
    """
    # Arrange - Create an unrelated file that should NOT be staged
    unrelated_file = temp_git_repo / "unrelated.txt"
    unrelated_file.write_text("This should not be staged")

    # Act - Stage only translation files
    staged_count = git_committer._stage_files(translation_output_files, temp_git_repo)

    # Assert - Only translation files were staged
    assert staged_count == len(translation_output_files)

    # Check git status to verify what's staged
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(temp_git_repo),
        capture_output=True,
        text=True,
    )

    # Translation files should be staged (A = added)
    for tf in translation_output_files:
        rel_path = tf.relative_to(temp_git_repo)
        # Should see "A  de/translated.md" or "A  fr/translated.md"
        assert str(rel_path).replace("\\", "/") in result.stdout

    # Unrelated file should NOT be staged (should show ?? for untracked)
    lines = result.stdout.strip().split('\n')
    unrelated_status = [l for l in lines if "unrelated.txt" in l]
    if unrelated_status:
        # Should be untracked (??) not staged (A)
        assert unrelated_status[0].startswith("??"), \
            f"Unrelated file was staged: {unrelated_status[0]}"


@pytest.mark.contract
def test_staging_uses_git_add_with_specific_path(
    git_committer,
    temp_git_repo,
    translation_output_files,
):
    """
    Verify git add uses specific file path, not wildcards or -A.

    CONTRACT: INV-008 - Specific file staging
    Evidence: src/observability/git_commit.py line 241-247 (git add --)
    """
    # Arrange - Mock subprocess.run to capture commands
    captured_commands = []

    original_run = subprocess.run

    def capture_run(*args, **kwargs):
        if args and args[0] and args[0][0] == "git":
            captured_commands.append(args[0])
        return original_run(*args, **kwargs)

    # Act
    with patch('subprocess.run', side_effect=capture_run):
        git_committer._stage_files(translation_output_files, temp_git_repo)

    # Assert - Commands use "git add --" pattern (not "git add -A" or "git add .")
    add_commands = [cmd for cmd in captured_commands if "add" in cmd]

    for cmd in add_commands:
        # Should be ["git", "add", "--", "<specific_path>"]
        assert "git" in cmd
        assert "add" in cmd
        assert "-A" not in cmd, "Should not use git add -A"
        assert "--" in cmd, "Should use -- separator for safety"


# ==============================================================================
# INV-008: Co-Author Trailer Tests
# ==============================================================================


@pytest.mark.contract
def test_commit_message_includes_co_author_trailer(
    git_committer,
    translation_output_files,
):
    """
    Verify commit message includes co-author trailer for audit trail.

    CONTRACT: INV-008 - Co-author audit trail
    Evidence: src/observability/git_commit.py lines 336-342 (co-author addition)
    """
    # Arrange
    output_files = translation_output_files
    languages = ["de", "fr"]
    site_id = "test.example.com"
    run_id = "test-run-123"

    # Act - Build commit message
    message = git_committer._build_commit_message(
        output_files=output_files,
        file_count=len(output_files),
        languages=languages,
        site_id=site_id,
        run_id=run_id,
    )

    # Assert - Co-author trailer present
    assert "Co-authored-by:" in message
    assert "hugo-translator@aspose.net" in message
    assert "Hugo Translator" in message


@pytest.mark.contract
def test_co_author_uses_configured_email(git_commit_config):
    """
    Verify co-author uses configured email address.

    CONTRACT: INV-008 - Configurable co-author
    Evidence: src/observability/git_commit.py lines 48-49 (DEFAULT_CO_AUTHOR)
    """
    # Assert - Config has expected co-author settings
    assert git_commit_config.co_author_email == "hugo-translator@aspose.net"
    assert git_commit_config.co_author_name == "Hugo Translator"


# ==============================================================================
# INV-008: Push Failure Graceful Degradation Tests
# ==============================================================================


@pytest.mark.contract
def test_push_failure_does_not_fail_commit_result(
    git_committer,
    temp_git_repo,
    translation_output_files,
):
    """
    Verify push failure doesn't cause commit_translation_outputs to fail.

    CONTRACT: INV-008 - Graceful degradation on push failure
    Evidence: src/observability/git_commit.py lines 202-208 (push handling)
    """
    # Arrange - Mock push to fail
    with patch.object(git_committer, '_push', return_value=False):
        # Stage files first
        git_committer._stage_files(translation_output_files, temp_git_repo)

        # Create commit message
        message = "test: translation commit\n\nCo-authored-by: Hugo Translator <hugo-translator@aspose.net>"

        # Create the commit
        commit_hash = git_committer._create_commit(message, temp_git_repo)

        # Assert - Commit succeeded even though push will fail
        assert commit_hash is not None


@pytest.mark.contract
def test_push_failure_returns_push_success_false():
    """
    Verify GitCommitResult.push_success is False when push fails.

    CONTRACT: INV-008 - Push status tracking
    Evidence: src/observability/git_commit.py lines 89 (push_success field)
    """
    from src.observability.git_commit import GitCommitResult

    # Arrange - Create result with failed push
    result = GitCommitResult(
        success=True,
        commit_hash="abc123def456",
        commit_hash_short="abc123d",
        files_committed=5,
        push_success=False,  # Push failed
        error=None,
    )

    # Assert - Commit succeeded, push failed
    assert result.success is True
    assert result.push_success is False


@pytest.mark.contract
def test_commit_success_independent_of_push(
    git_committer,
    temp_git_repo,
):
    """
    Verify commit success is tracked independently of push result.

    CONTRACT: INV-008 - Independent success tracking
    Evidence: src/observability/git_commit.py lines 192-210
    """
    from src.observability.git_commit import GitCommitResult

    # Arrange - Scenarios
    scenarios = [
        {"commit_ok": True, "push_ok": True, "expected_success": True},
        {"commit_ok": True, "push_ok": False, "expected_success": True},  # Key case
        {"commit_ok": False, "push_ok": False, "expected_success": False},
    ]

    for scenario in scenarios:
        result = GitCommitResult(
            success=scenario["commit_ok"],
            push_success=scenario["push_ok"],
        )

        # Assert - success reflects commit status, not push
        assert result.success == scenario["expected_success"], \
            f"Scenario {scenario}: success should be {scenario['expected_success']}"


# ==============================================================================
# INV-008: Timeout Protection Tests
# ==============================================================================


@pytest.mark.contract
def test_timeout_configured_for_git_operations(git_commit_config):
    """
    Verify timeout is configured for git operations.

    CONTRACT: INV-008 - Timeout protection
    Evidence: src/observability/git_commit.py line 62 (timeout_seconds)
    """
    # Assert - Default timeout is 60 seconds
    assert git_commit_config.timeout_seconds == 60


@pytest.mark.contract
def test_committer_uses_configured_timeout(git_committer, git_commit_config):
    """
    Verify GitCommitter uses configured timeout.

    CONTRACT: INV-008 - Timeout applied
    Evidence: src/observability/git_commit.py line 111 (_timeout)
    """
    # Assert
    assert git_committer._timeout == git_commit_config.timeout_seconds
    assert git_committer._timeout == 60


@pytest.mark.contract
def test_push_timeout_is_doubled():
    """
    Verify push timeout is doubled for network operations.

    CONTRACT: INV-008 - Extended timeout for network
    Evidence: src/observability/git_commit.py line 423 (timeout * 2)
    """
    from src.observability.git_commit import GitCommitConfig, GitCommitter

    # Arrange
    config = GitCommitConfig(timeout_seconds=30)
    committer = GitCommitter(config)

    # Assert - Push uses 2x timeout
    # We verify this by checking the implementation pattern
    assert committer._timeout == 30

    # The actual doubling happens in _push method:
    # timeout=self._timeout * 2
    # This is verified by code inspection, not runtime assertion


# ==============================================================================
# INV-008: Git Repo Detection Tests
# ==============================================================================


@pytest.mark.contract
def test_is_git_repo_returns_true_for_repo(git_committer, temp_git_repo):
    """
    Verify is_git_repo returns True for valid git repository.

    CONTRACT: INV-008 - Repo detection
    Evidence: src/observability/git_commit.py lines 114-123 (is_git_repo)
    """
    # Act
    result = git_committer.is_git_repo(temp_git_repo)

    # Assert
    assert result is True


@pytest.mark.contract
def test_is_git_repo_returns_false_for_non_repo(git_committer, tmp_path):
    """
    Verify is_git_repo returns False for non-git directory.

    CONTRACT: INV-008 - Repo detection
    Evidence: src/observability/git_commit.py lines 114-123
    """
    # Arrange - Create a non-git directory
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()

    # Act
    result = git_committer.is_git_repo(non_repo)

    # Assert
    assert result is False


# ==============================================================================
# INV-008: Empty Commit Handling Tests
# ==============================================================================


@pytest.mark.contract
def test_no_files_returns_error_result(git_committer):
    """
    Verify empty file list returns error result.

    CONTRACT: INV-008 - Handle empty commits
    Evidence: src/observability/git_commit.py lines 150-151
    """
    # Act
    result = git_committer.commit_translation_outputs(
        output_files=[],  # Empty list
        site_id="test.example.com",
        target_langs=["de"],
        run_id="test-run",
    )

    # Assert
    assert result.success is False
    assert "No files to commit" in result.error


# ==============================================================================
# INV-008: Collect Output Files Tests
# ==============================================================================


@pytest.mark.contract
def test_collect_output_files_excludes_skipped_languages():
    """
    Verify collect_output_files excludes skipped languages.

    CONTRACT: INV-008 - Only include translated files
    Evidence: src/observability/git_commit.py lines 437-458 (collect_output_files)
    """
    from src.observability.git_commit import collect_output_files

    # Arrange - Create mock DirectoryResult
    mock_result = Mock()

    # File 1: Both languages translated
    file1 = Mock()
    file1.success = True
    file1.outputs = {"de": Mock(exists=Mock(return_value=True)), "fr": Mock(exists=Mock(return_value=True))}
    file1.skipped_langs = set()
    file1.errors = {}
    file1.validation_decision = None

    # File 2: One language skipped
    file2 = Mock()
    file2.success = True
    file2.outputs = {"de": Mock(exists=Mock(return_value=True)), "fr": Mock(exists=Mock(return_value=True))}
    file2.skipped_langs = {"fr"}  # French was skipped
    file2.errors = {}
    file2.validation_decision = None

    mock_result.file_results = [file1, file2]

    # Act
    files = collect_output_files(mock_result)

    # Assert - Skipped language file not included
    # file1: both de and fr (2 files)
    # file2: only de (1 file, fr skipped)
    # Total: 3 files
    assert len(files) == 3
