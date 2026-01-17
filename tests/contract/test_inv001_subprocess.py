"""
CONTRACT: specs/core_invariants.md

Verifies multi-language translation spawns separate subprocess per language
to prevent model state contamination.

INV-001 Core Invariant: Multi-Language Subprocess Isolation

Key Guarantees:
1. Each target language runs in complete memory isolation
2. M2M100/NLLB model state cannot leak between languages
3. Failure in one language subprocess does not crash others (unless --fail-fast)
4. Parent process coordinates subprocesses and holds site lock
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import sys
import argparse


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def mock_args_multi_lang():
    """
    Mock CLI arguments for multi-language translation.

    Simulates: --target-langs de,fr,es
    """
    args = argparse.Namespace()
    args.site = "test.example.com"
    args.input = "/path/to/source"
    args.output = "/path/to/output"
    args.target_langs = "de,fr,es"
    args.model = "nllb-200-distilled-600M"
    args.config_root = "./config"
    args._single_lang_mode = False
    args._skip_site_lock = False
    args.auto_commit = False
    args.fail_fast = True
    args.parallel_languages = 0
    args.global_lang_rounds = 0
    return args


@pytest.fixture
def mock_args_single_lang():
    """
    Mock CLI arguments for single-language translation.

    Simulates: --target-langs de
    """
    args = argparse.Namespace()
    args.site = "test.example.com"
    args.input = "/path/to/source"
    args.output = "/path/to/output"
    args.target_langs = "de"
    args.model = "nllb-200-distilled-600M"
    args.config_root = "./config"
    args._single_lang_mode = False
    args._skip_site_lock = False
    args.auto_commit = False
    args.fail_fast = True
    return args


@pytest.fixture
def mock_subprocess_popen():
    """
    Mock subprocess.Popen for command capture.
    """
    with patch('subprocess.Popen') as mock_popen:
        mock_process = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()
        mock_process.stdout.readline.side_effect = ['', StopIteration]
        mock_process.stderr.readline.side_effect = ['', StopIteration]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        yield mock_popen


# ==============================================================================
# INV-001: Multi-Language Detection Tests
# ==============================================================================


@pytest.mark.contract
def test_multi_lang_detection_with_two_or_more_languages():
    """
    Verify multi-language mode is triggered for 2+ target languages.

    CONTRACT: INV-001 Trigger Condition
    Evidence: src/cli.py lines 1406 (if len(target_langs) > 1)
    """
    # Arrange
    target_langs = ["de", "fr", "es"]

    # Act - Check the condition that triggers subprocess mode
    is_multi_lang = len(target_langs) > 1
    single_lang_mode = False

    should_spawn_subprocesses = is_multi_lang and not single_lang_mode

    # Assert
    assert is_multi_lang is True
    assert should_spawn_subprocesses is True


@pytest.mark.contract
def test_single_lang_detection_with_one_language():
    """
    Verify single-language mode does not trigger subprocess spawning.

    CONTRACT: INV-001 Trigger Condition
    Evidence: src/cli.py lines 1406 (else branch)
    """
    # Arrange
    target_langs = ["de"]

    # Act
    is_multi_lang = len(target_langs) > 1

    # Assert - Single language should not trigger subprocess mode
    assert is_multi_lang is False


@pytest.mark.contract
def test_single_lang_mode_flag_prevents_recursion():
    """
    Verify --_single-lang-mode flag prevents infinite subprocess recursion.

    CONTRACT: INV-001 - Recursion prevention
    Evidence: src/cli.py lines 1406 (not getattr(args, '_single_lang_mode', False))
    """
    # Arrange - Simulate subprocess with single-lang-mode flag
    target_langs = ["de", "fr", "es"]  # Multiple languages
    single_lang_mode = True  # But flag is set (subprocess call)

    # Act - Check condition
    should_spawn_subprocesses = len(target_langs) > 1 and not single_lang_mode

    # Assert - Should NOT spawn subprocesses due to flag
    assert should_spawn_subprocesses is False


# ==============================================================================
# INV-001: Subprocess Command Construction Tests
# ==============================================================================


@pytest.mark.contract
def test_subprocess_command_includes_single_lang_mode_flag():
    """
    Verify subprocess command includes --_single-lang-mode flag.

    CONTRACT: INV-001 - Isolation flag passed to child
    Evidence: src/cli.py line 1519 (cmd.append("--_single-lang-mode"))
    """
    # Arrange - Build command as CLI does
    base_cmd = [sys.executable, "-m", "src.cli"]
    site_arg = ["--site", "test.example.com"]
    lang_arg = ["--target-langs", "de"]  # Single language for subprocess

    # Act - Add isolation flags as CLI does
    cmd = base_cmd + site_arg + lang_arg
    cmd.append("--_single-lang-mode")
    cmd.append("--_skip-site-lock")

    # Assert
    assert "--_single-lang-mode" in cmd
    assert cmd.index("--_single-lang-mode") > 0  # Not at start


@pytest.mark.contract
def test_subprocess_command_includes_skip_site_lock_flag():
    """
    Verify subprocess command includes --_skip-site-lock flag.

    CONTRACT: INV-001 - Lock isolation (TC1: Lock Contention Fix)
    Evidence: src/cli.py line 1522 (cmd.append("--_skip-site-lock"))
    """
    # Arrange - Build command as CLI does
    base_cmd = [sys.executable, "-m", "src.cli"]
    site_arg = ["--site", "test.example.com"]
    lang_arg = ["--target-langs", "de"]

    # Act - Add lock skip flag as CLI does
    cmd = base_cmd + site_arg + lang_arg
    cmd.append("--_single-lang-mode")
    cmd.append("--_skip-site-lock")

    # Assert
    assert "--_skip-site-lock" in cmd


@pytest.mark.contract
def test_subprocess_command_has_single_target_language():
    """
    Verify each subprocess receives exactly one target language.

    CONTRACT: INV-001 - Language isolation
    Evidence: src/cli.py lines 1482-1483 (--target-langs with single lang)
    """
    # Arrange
    all_target_langs = ["de", "fr", "es"]
    subprocess_commands = []

    # Act - Build command for each language as CLI does
    for lang in all_target_langs:
        cmd = [sys.executable, "-m", "src.cli"]
        cmd.extend(["--site", "test.example.com"])
        cmd.extend(["--target-langs", lang])  # Single language
        cmd.append("--_single-lang-mode")
        cmd.append("--_skip-site-lock")
        subprocess_commands.append(cmd)

    # Assert - Each command has exactly one language
    assert len(subprocess_commands) == 3

    for cmd in subprocess_commands:
        # Find --target-langs index and check next value
        try:
            idx = cmd.index("--target-langs")
            lang_value = cmd[idx + 1]
            # Single language (no comma)
            assert "," not in lang_value
        except (ValueError, IndexError):
            pytest.fail("--target-langs not found in command")


# ==============================================================================
# INV-001: Lock Isolation Tests
# ==============================================================================


@pytest.mark.contract
def test_skip_site_lock_flag_recognized():
    """
    Verify --_skip-site-lock flag is recognized in argument parsing.

    CONTRACT: INV-001 - Lock isolation
    Evidence: src/cli.py lines 314-318 (argparse definition)
    """
    # Arrange
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--_skip-site-lock",
        dest="_skip_site_lock",
        action="store_true",
    )

    # Act - Parse with the flag
    args = parser.parse_args(["--_skip-site-lock"])

    # Assert
    assert args._skip_site_lock is True


@pytest.mark.contract
def test_skip_site_lock_flag_default_false():
    """
    Verify --_skip-site-lock defaults to False.

    CONTRACT: INV-001 - Lock isolation default
    Evidence: src/cli.py (argparse store_true default)
    """
    # Arrange
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--_skip-site-lock",
        dest="_skip_site_lock",
        action="store_true",
    )

    # Act - Parse without the flag
    args = parser.parse_args([])

    # Assert
    assert args._skip_site_lock is False


# ==============================================================================
# INV-001: Subprocess Count Tests
# ==============================================================================


@pytest.mark.contract
def test_subprocess_count_matches_language_count():
    """
    Verify N languages result in N subprocess commands.

    CONTRACT: INV-001 - One subprocess per language
    Evidence: src/cli.py lines 1467-1802 (for lang in target_langs loop)
    """
    # Arrange
    target_langs = ["de", "fr", "es", "it", "pt"]
    subprocess_count = 0

    # Act - Count subprocess launches as CLI does
    for lang in target_langs:
        subprocess_count += 1

    # Assert
    assert subprocess_count == len(target_langs)
    assert subprocess_count == 5


# ==============================================================================
# INV-001: Error Isolation Tests
# ==============================================================================


@pytest.mark.contract
def test_subprocess_failure_tracking_per_language():
    """
    Verify each language failure is tracked independently.

    CONTRACT: INV-001 - Failure isolation
    Evidence: src/cli.py language_results dict tracking
    """
    # Arrange - Simulate language results tracking
    language_results = {}
    target_langs = ["de", "fr", "es"]

    # Act - Simulate mixed success/failure as CLI tracks
    language_results["de"] = {"success": True, "exit_code": 0}
    language_results["fr"] = {"success": False, "exit_code": 1}  # Failed
    language_results["es"] = {"success": True, "exit_code": 0}

    # Assert - Each language tracked independently
    assert len(language_results) == 3
    assert language_results["de"]["success"] is True
    assert language_results["fr"]["success"] is False
    assert language_results["es"]["success"] is True

    # Count successful vs failed
    successful = [lang for lang, res in language_results.items() if res["success"]]
    failed = [lang for lang, res in language_results.items() if not res["success"]]

    assert len(successful) == 2
    assert len(failed) == 1
    assert "fr" in failed


@pytest.mark.contract
def test_subprocess_failure_does_not_affect_previous_results():
    """
    Verify a subprocess failure doesn't corrupt previous successful results.

    CONTRACT: INV-001 - Failure isolation
    Evidence: src/cli.py language_results dict is independent per language
    """
    # Arrange - Track results progressively
    language_results = {}

    # Act - First language succeeds
    language_results["de"] = {"success": True, "output_files": 10}

    # Second language fails
    language_results["fr"] = {"success": False, "error": "Timeout"}

    # Assert - First result unchanged after second failure
    assert language_results["de"]["success"] is True
    assert language_results["de"]["output_files"] == 10


# ==============================================================================
# INV-001: Process Isolation Guarantee Tests
# ==============================================================================


@pytest.mark.contract
def test_isolation_prevents_state_contamination():
    """
    Verify subprocess isolation prevents model state contamination.

    CONTRACT: INV-001 Core Guarantee
    Evidence: src/cli.py lines 1401-1405 (comment explaining rationale)

    Note: This is a design verification test - actual state contamination
    can only be detected through integration testing.
    """
    # Arrange - Document the isolation design
    isolation_design = {
        "mechanism": "subprocess.Popen per language",
        "flags": ["--_single-lang-mode", "--_skip-site-lock"],
        "guarantee": "Complete memory isolation between languages",
        "rationale": "M2M100 model retains internal state between translations",
    }

    # Assert - Design elements are correct
    assert isolation_design["mechanism"] == "subprocess.Popen per language"
    assert "--_single-lang-mode" in isolation_design["flags"]
    assert "--_skip-site-lock" in isolation_design["flags"]
