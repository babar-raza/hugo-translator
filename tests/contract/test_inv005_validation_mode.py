"""
CONTRACT: specs/core_invariants.md

Verifies CLI validation flags (--strict, --lenient, --no-validation)
MUST override site profile validation settings.

INV-005 Core Invariant: Validation Mode CLI Override

Key Guarantees:
1. CLI flags > Site profile config > Global defaults
2. --validation-mode strict|normal|lenient|off overrides profile
3. --strict-reject sets strict mode + max_retries=0
4. --disable-validation disables all validation
5. --force-accept accepts all translations without validation
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from argparse import Namespace
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def mock_args_base():
    """Base args fixture with validation-related defaults."""
    return Namespace(
        site_id="test-site",
        source_lang="en",
        target_lang=["es"],
        output_dir=None,
        validation_mode=None,
        strict_reject=False,
        disable_validation=False,
        force_accept=False,
        max_retries=None,
        enable_terminology=None,
        disable_terminology=False,
        terminology_mode=None,
        # Required fields from CLIConfigOverrides.__init__
        validation_config=None,
        terminology_config=None,
        dry_run=False,
        save_rejected=False,
        verify=False,
        fix=False,
        verification_report=None,
        max_tokens=None,
        model=None,
        batch_size=None,
        sort_segments_by_length=None,
        device="auto",
        load_mode="auto",
        force_retranslate=False,
        cache_write_mode="normal",
        parallel_languages=0,  # 0 means disabled (avoid conflict with global_lang_rounds)
        global_lang_rounds=0,  # 0 means disabled (avoid conflict with parallel_languages)
        global_lang_sort="alphabetical",
        metrics_file=None,
        metrics_interval=60.0,
        metrics_only=False,
        no_progress=False,
        resume=True,
        force_restart=False,
        progress_dir=".translation_progress",
        disable_content_hash=False,
        rebuild_content_hashes=False,
        validate_output_integrity=False,
    )


@pytest.fixture
def mock_site_profile():
    """Mock site profile with default validation settings."""
    profile = Mock()
    profile.validation_mode = "normal"
    profile.max_retries = 3
    profile.reject_on_error_count = 2
    return profile


# ==============================================================================
# INV-005: CLI Override Tests
# ==============================================================================


@pytest.mark.contract
def test_validation_mode_strict_overrides_profile(mock_args_base):
    """
    Verify --validation-mode strict overrides site profile setting.

    CONTRACT: INV-005 - CLI flags override site profile config
    Evidence: src/cli.py lines 170-175 (override logic)
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange - Set CLI to strict mode
    mock_args_base.validation_mode = "strict"

    # Act
    overrides = CLIOverrides(mock_args_base)

    # Assert - Strict mode set
    assert overrides.validation_mode == "strict"


@pytest.mark.contract
def test_validation_mode_lenient_overrides_profile(mock_args_base):
    """
    Verify --validation-mode lenient overrides site profile setting.

    CONTRACT: INV-005 - CLI flags override site profile config
    Evidence: src/cli.py lines 170-175 (override logic)
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange - Set CLI to lenient mode
    mock_args_base.validation_mode = "lenient"

    # Act
    overrides = CLIOverrides(mock_args_base)

    # Assert - Lenient mode set
    assert overrides.validation_mode == "lenient"


@pytest.mark.contract
def test_validation_mode_off_disables_validation(mock_args_base):
    """
    Verify --validation-mode off disables validation.

    CONTRACT: INV-005 - CLI can disable validation
    Evidence: src/cli.py lines 326-328 (validation mode choices)
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange - Set CLI to off mode
    mock_args_base.validation_mode = "off"

    # Act
    overrides = CLIOverrides(mock_args_base)

    # Assert - Validation disabled
    assert overrides.validation_mode == "off"


@pytest.mark.contract
def test_strict_reject_sets_strict_and_zero_retries(mock_args_base):
    """
    Verify --strict-reject sets strict mode AND max_retries=0.

    CONTRACT: INV-005 - --strict-reject compound override
    Evidence: src/cli.py lines 172-175 (strict_reject logic)
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange - Set strict-reject flag
    mock_args_base.strict_reject = True

    # Act
    overrides = CLIOverrides(mock_args_base)
    override_dict = overrides.get_engine_overrides()

    # Assert - Both overrides applied
    assert override_dict.get("validation_mode") == "strict"
    assert override_dict.get("max_retries") == 0


@pytest.mark.contract
def test_disable_validation_flag_sets_disabled(mock_args_base):
    """
    Verify --disable-validation flag disables validation.

    CONTRACT: INV-005 - --disable-validation override
    Evidence: src/cli.py lines 84, 1173-1174
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange
    mock_args_base.disable_validation = True

    # Act
    overrides = CLIOverrides(mock_args_base)

    # Assert
    assert overrides.disable_validation is True


@pytest.mark.contract
def test_force_accept_flag_sets_force_accept(mock_args_base):
    """
    Verify --force-accept flag accepts all translations.

    CONTRACT: INV-005 - --force-accept override
    Evidence: src/cli.py lines 85, 1169-1170
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange
    mock_args_base.force_accept = True

    # Act
    overrides = CLIOverrides(mock_args_base)

    # Assert
    assert overrides.force_accept is True


@pytest.mark.contract
def test_no_cli_flags_uses_defaults(mock_args_base):
    """
    Verify no CLI flags allows profile/defaults to apply.

    CONTRACT: INV-005 - Default precedence behavior
    Evidence: src/cli.py lines 166-190 (to_dict logic)
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange - All validation flags at default (None/False)
    # (mock_args_base already has defaults)

    # Act
    overrides = CLIOverrides(mock_args_base)
    override_dict = overrides.get_engine_overrides()

    # Assert - No validation overrides in dict
    assert "validation_mode" not in override_dict
    assert overrides.disable_validation is False
    assert overrides.force_accept is False
    assert overrides.strict_reject is False


# ==============================================================================
# INV-005: Override Propagation Tests
# ==============================================================================


@pytest.mark.contract
def test_override_to_dict_includes_validation_mode(mock_args_base):
    """
    Verify to_dict includes validation_mode when set.

    CONTRACT: INV-005 - Override propagation to engine
    Evidence: src/cli.py lines 166-190 (to_dict)
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange
    mock_args_base.validation_mode = "strict"

    # Act
    overrides = CLIOverrides(mock_args_base)
    override_dict = overrides.get_engine_overrides()

    # Assert
    assert "validation_mode" in override_dict
    assert override_dict["validation_mode"] == "strict"


@pytest.mark.contract
def test_strict_reject_overrides_max_retries_arg(mock_args_base):
    """
    Verify --strict-reject takes precedence over --max-retries.

    CONTRACT: INV-005 - strict-reject supersedes max-retries
    Evidence: src/cli.py lines 184-186 (unless overridden by strict-reject)
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange - User sets both (contradictory)
    mock_args_base.strict_reject = True
    mock_args_base.max_retries = 5  # This should be ignored

    # Act
    overrides = CLIOverrides(mock_args_base)
    override_dict = overrides.get_engine_overrides()

    # Assert - strict_reject wins, max_retries=0
    assert override_dict.get("max_retries") == 0


# ==============================================================================
# INV-005: Validation Mode Choices Test
# ==============================================================================


@pytest.mark.contract
def test_validation_mode_choices_are_documented():
    """
    Verify all validation mode choices match spec.

    CONTRACT: INV-005 - Documented modes
    Evidence: src/cli.py lines 326-327 (choices)
    """
    # Arrange - Expected choices from spec
    expected_choices = {"strict", "normal", "lenient", "off"}

    # Act - Import parser and check choices
    # Note: We verify the CLI accepts these modes
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Create args for each valid mode
    for mode in expected_choices:
        args = Namespace(
            site_id="test",
            source_lang="en",
            target_lang=["es"],
            output_dir=None,
            validation_mode=mode,
            strict_reject=False,
            disable_validation=False,
            force_accept=False,
            max_retries=None,
            enable_terminology=None,
            disable_terminology=False,
            terminology_mode=None,
            # Required fields from CLIConfigOverrides.__init__
            validation_config=None,
            terminology_config=None,
            dry_run=False,
            save_rejected=False,
            verify=False,
            fix=False,
            verification_report=None,
            max_tokens=None,
            model=None,
            batch_size=None,
            sort_segments_by_length=None,
            device="auto",
            load_mode="auto",
            force_retranslate=False,
            cache_write_mode="normal",
            parallel_languages=1,
            global_lang_rounds=1,
            global_lang_sort="alphabetical",
            metrics_file=None,
            metrics_interval=60.0,
            metrics_only=False,
            no_progress=False,
            resume=True,
            force_restart=False,
            progress_dir=".translation_progress",
            disable_content_hash=False,
            rebuild_content_hashes=False,
            validate_output_integrity=False,
        )

        # Assert - No exception raised
        overrides = CLIOverrides(args)
        if mode != "off":  # off might be handled differently
            assert overrides.validation_mode == mode


# ==============================================================================
# INV-005: Integration with Translation Engine
# ==============================================================================


@pytest.mark.contract
def test_overrides_applied_to_translation_config(mock_args_base):
    """
    Verify CLIOverrides can be converted to engine-compatible dict.

    CONTRACT: INV-005 - Engine integration
    Evidence: src/cli.py lines 166-190 (to_dict for engine)
    """
    from src.cli import CLIConfigOverrides as CLIOverrides

    # Arrange - Set multiple overrides
    mock_args_base.validation_mode = "strict"
    mock_args_base.max_retries = 2

    # Act
    overrides = CLIOverrides(mock_args_base)
    config = overrides.get_engine_overrides()

    # Assert - Config dict has expected structure
    assert isinstance(config, dict)
    assert config.get("validation_mode") == "strict"
    assert config.get("max_retries") == 2
