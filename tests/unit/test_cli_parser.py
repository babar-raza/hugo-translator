"""
Unit tests for CLI parser without full dependency chain (CFG-03).

Tests the argument parser in isolation.
"""
import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Import just the parser creation function by mocking dependencies
@pytest.fixture
def mock_dependencies():
    """Mock all CLI dependencies for isolated parser testing."""
    with patch.dict('sys.modules', {
        'src.translation_engine': MagicMock(),
        'src.translation_engine.models': MagicMock(),
        'src.tm': MagicMock(),
        'src.model_runtime': MagicMock(),
        'src.utils.config_loader': MagicMock(),
        'src.utils.models': MagicMock(),
    }):
        yield


def test_parser_imports(mock_dependencies):
    """Test that CLI module can be imported with mocked dependencies."""
    from src.cli import create_parser
    assert create_parser is not None


def test_parser_creation(mock_dependencies):
    """Test that parser is created with correct program name."""
    from src.cli import create_parser
    parser = create_parser()
    assert parser is not None
    assert parser.prog == "translate-hugo"


def test_parser_required_site_arg(mock_dependencies):
    """Test that --site argument is required."""
    from src.cli import create_parser
    parser = create_parser()

    # Missing --site should fail
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_validation_mode_choices(mock_dependencies):
    """Test validation-mode accepts valid choices."""
    from src.cli import create_parser
    parser = create_parser()

    # Valid choices
    for mode in ["strict", "normal", "lenient", "off"]:
        args = parser.parse_args(["--site", "test", "--validation-mode", mode])
        assert args.validation_mode == mode

    # Invalid choice should fail
    with pytest.raises(SystemExit):
        parser.parse_args(["--site", "test", "--validation-mode", "invalid"])


def test_parser_terminology_mode_choices(mock_dependencies):
    """Test terminology-mode accepts valid choices."""
    from src.cli import create_parser
    parser = create_parser()

    # Valid choices
    for mode in ["protect", "validate", "both", "none"]:
        args = parser.parse_args(["--site", "test", "--terminology-mode", mode])
        assert args.terminology_mode == mode

    # Invalid choice should fail
    with pytest.raises(SystemExit):
        parser.parse_args(["--site", "test", "--terminology-mode", "invalid"])


def test_parser_max_retries_type(mock_dependencies):
    """Test max-retries accepts integer values."""
    from src.cli import create_parser
    parser = create_parser()

    args = parser.parse_args(["--site", "test", "--max-retries", "5"])
    assert args.max_retries == 5
    assert isinstance(args.max_retries, int)

    # Non-integer should fail
    with pytest.raises(SystemExit):
        parser.parse_args(["--site", "test", "--max-retries", "invalid"])


def test_parser_boolean_flags(mock_dependencies):
    """Test boolean flags are properly parsed."""
    from src.cli import create_parser
    parser = create_parser()

    # Test disable-validation
    args = parser.parse_args(["--site", "test", "--disable-validation"])
    assert args.disable_validation is True

    # Without flag, should be False
    args = parser.parse_args(["--site", "test"])
    assert args.disable_validation is False

    # Test enable-terminology
    args = parser.parse_args(["--site", "test", "--enable-terminology"])
    assert args.enable_terminology is True

    # Test disable-terminology
    args = parser.parse_args(["--site", "test", "--disable-terminology"])
    assert args.disable_terminology is True

    # Test dry-run
    args = parser.parse_args(["--site", "test", "--dry-run"])
    assert args.dry_run is True

    # Test save-rejected
    args = parser.parse_args(["--site", "test", "--save-rejected"])
    assert args.save_rejected is True


def test_parser_config_path_arguments(mock_dependencies):
    """Test custom config path arguments."""
    from src.cli import create_parser
    parser = create_parser()

    args = parser.parse_args([
        "--site", "test",
        "--validation-config", "/custom/validation.yaml",
        "--terminology-config", "/custom/terminology.yaml"
    ])
    assert args.validation_config == "/custom/validation.yaml"
    assert args.terminology_config == "/custom/terminology.yaml"


def test_parser_target_langs_list(mock_dependencies):
    """Test that target-langs accepts multiple values."""
    from src.cli import create_parser
    parser = create_parser()

    args = parser.parse_args([
        "--site", "test",
        "--target-langs", "de", "es", "fr"
    ])
    assert args.target_langs == ["de", "es", "fr"]


def test_parser_log_level_choices(mock_dependencies):
    """Test log-level accepts valid choices."""
    from src.cli import create_parser
    parser = create_parser()

    # Valid choices
    for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
        args = parser.parse_args(["--site", "test", "--log-level", level])
        assert args.log_level == level

    # Invalid choice should fail
    with pytest.raises(SystemExit):
        parser.parse_args(["--site", "test", "--log-level", "INVALID"])


def test_parser_combined_flags(mock_dependencies):
    """Test multiple flags can be used together."""
    from src.cli import create_parser
    parser = create_parser()

    args = parser.parse_args([
        "--site", "test",
        "--validation-mode", "strict",
        "--enable-terminology",
        "--terminology-mode", "both",
        "--max-retries", "5",
        "--dry-run",
        "--log-level", "DEBUG"
    ])

    assert args.site == "test"
    assert args.validation_mode == "strict"
    assert args.enable_terminology is True
    assert args.terminology_mode == "both"
    assert args.max_retries == 5
    assert args.dry_run is True
    assert args.log_level == "DEBUG"


def test_parser_help_text(mock_dependencies):
    """Test that help text is properly formatted."""
    from src.cli import create_parser
    parser = create_parser()

    help_text = parser.format_help()

    # Check for key sections
    assert "Validation Control" in help_text
    assert "Terminology Control" in help_text
    assert "Output Control" in help_text

    # Check for key flags
    assert "--validation-mode" in help_text
    assert "--disable-validation" in help_text
    assert "--enable-terminology" in help_text
    assert "--terminology-mode" in help_text
    assert "--max-retries" in help_text
    assert "--dry-run" in help_text
    assert "--save-rejected" in help_text


def test_cli_config_overrides_initialization(mock_dependencies):
    """Test CLIConfigOverrides initialization."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()
    args = parser.parse_args([
        "--site", "test",
        "--validation-mode", "strict",
        "--max-retries", "5"
    ])

    overrides = CLIConfigOverrides(args)
    assert overrides.validation_mode == "strict"
    assert overrides.max_retries == 5
    assert overrides.disable_validation is False


def test_cli_config_overrides_terminology(mock_dependencies):
    """Test CLIConfigOverrides terminology handling."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()

    # Test enable
    args = parser.parse_args(["--site", "test", "--enable-terminology"])
    overrides = CLIConfigOverrides(args)
    assert overrides.enable_terminology is True

    # Test disable
    args = parser.parse_args(["--site", "test", "--disable-terminology"])
    overrides = CLIConfigOverrides(args)
    assert overrides.enable_terminology is False

    # Test neither (should be None)
    args = parser.parse_args(["--site", "test"])
    overrides = CLIConfigOverrides(args)
    assert overrides.enable_terminology is None


def test_cli_config_overrides_engine_dict(mock_dependencies):
    """Test CLIConfigOverrides.get_engine_overrides()."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()

    # Test strict validation mode
    args = parser.parse_args(["--site", "test", "--validation-mode", "strict"])
    overrides = CLIConfigOverrides(args)
    engine_overrides = overrides.get_engine_overrides()
    assert engine_overrides["enable_validation"] is True
    assert engine_overrides["validation_mode"] == "strict"

    # Test off mode
    args = parser.parse_args(["--site", "test", "--validation-mode", "off"])
    overrides = CLIConfigOverrides(args)
    engine_overrides = overrides.get_engine_overrides()
    assert engine_overrides["enable_validation"] is False

    # Test disable-validation
    args = parser.parse_args(["--site", "test", "--disable-validation"])
    overrides = CLIConfigOverrides(args)
    engine_overrides = overrides.get_engine_overrides()
    assert engine_overrides["enable_validation"] is False


def test_cli_config_overrides_max_retries(mock_dependencies):
    """Test max-retries override."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--max-retries", "5"])
    overrides = CLIConfigOverrides(args)
    engine_overrides = overrides.get_engine_overrides()
    assert engine_overrides["max_retries"] == 5


def test_cli_config_overrides_terminology_mode(mock_dependencies):
    """Test terminology mode override."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()
    args = parser.parse_args([
        "--site", "test",
        "--enable-terminology",
        "--terminology-mode", "both"
    ])
    overrides = CLIConfigOverrides(args)
    engine_overrides = overrides.get_engine_overrides()
    assert engine_overrides["enable_terminology"] is True
    assert engine_overrides["terminology_mode"] == "both"


def test_cli_config_overrides_dry_run(mock_dependencies):
    """Test dry-run and save-rejected flags."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--dry-run", "--save-rejected"])
    overrides = CLIConfigOverrides(args)
    engine_overrides = overrides.get_engine_overrides()
    assert engine_overrides["dry_run"] is True
    assert engine_overrides["save_rejected"] is True


def test_parser_max_tokens_type(mock_dependencies):
    """Test max-tokens accepts integer values (TR-01)."""
    from src.cli import create_parser
    parser = create_parser()

    args = parser.parse_args(["--site", "test", "--max-tokens", "1024"])
    assert args.max_tokens == 1024
    assert isinstance(args.max_tokens, int)

    # Non-integer should fail
    with pytest.raises(SystemExit):
        parser.parse_args(["--site", "test", "--max-tokens", "invalid"])


def test_parser_max_tokens_default_none(mock_dependencies):
    """Test that max-tokens defaults to None when not specified."""
    from src.cli import create_parser
    parser = create_parser()

    args = parser.parse_args(["--site", "test"])
    assert args.max_tokens is None


def test_cli_config_overrides_max_tokens(mock_dependencies):
    """Test max-tokens override (TR-01)."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()

    # Test with max-tokens specified
    args = parser.parse_args(["--site", "test", "--max-tokens", "1024"])
    overrides = CLIConfigOverrides(args)
    assert overrides.max_tokens == 1024

    engine_overrides = overrides.get_engine_overrides()
    assert engine_overrides["max_tokens"] == 1024


def test_cli_config_overrides_max_tokens_not_in_dict_when_none(mock_dependencies):
    """Test that max_tokens is not in engine overrides when None."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()

    # Test without max-tokens specified
    args = parser.parse_args(["--site", "test"])
    overrides = CLIConfigOverrides(args)
    assert overrides.max_tokens is None

    engine_overrides = overrides.get_engine_overrides()
    assert "max_tokens" not in engine_overrides


def test_device_flag_auto(mock_dependencies):
    """Test --device auto (default) parses correctly (T101)."""
    from src.cli import create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test"])
    assert args.device == "auto"


def test_device_flag_cpu(mock_dependencies):
    """Test --device cpu parses correctly (T101)."""
    from src.cli import create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cpu"])
    assert args.device == "cpu"


def test_device_flag_cuda(mock_dependencies):
    """Test --device cuda parses correctly (T101)."""
    from src.cli import create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--device", "cuda"])
    assert args.device == "cuda"


def test_load_mode_flag_fp16(mock_dependencies):
    """Test --load-mode fp16 parses correctly (T101)."""
    from src.cli import create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--load-mode", "fp16"])
    assert args.load_mode == "fp16"


def test_load_mode_flag_int8(mock_dependencies):
    """Test --load-mode int8 parses correctly (T101)."""
    from src.cli import create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--load-mode", "int8"])
    assert args.load_mode == "int8"


def test_load_mode_flag_fp32(mock_dependencies):
    """Test --load-mode fp32 parses correctly (T101)."""
    from src.cli import create_parser

    parser = create_parser()
    args = parser.parse_args(["--site", "test", "--load-mode", "fp32"])
    assert args.load_mode == "fp32"


def test_device_override_stores_correctly(mock_dependencies):
    """Test that device override stores None for 'auto' and actual value otherwise (T101)."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()

    # Test auto -> None
    args = parser.parse_args(["--site", "test", "--device", "auto"])
    overrides = CLIConfigOverrides(args)
    assert overrides.device is None

    # Test cpu -> "cpu"
    args = parser.parse_args(["--site", "test", "--device", "cpu"])
    overrides = CLIConfigOverrides(args)
    assert overrides.device == "cpu"

    # Test cuda -> "cuda"
    args = parser.parse_args(["--site", "test", "--device", "cuda"])
    overrides = CLIConfigOverrides(args)
    assert overrides.device == "cuda"


def test_load_mode_override_stores_correctly(mock_dependencies):
    """Test that load_mode override stores None for 'auto' and actual value otherwise (T101)."""
    from src.cli import create_parser, CLIConfigOverrides

    parser = create_parser()

    # Test auto -> None
    args = parser.parse_args(["--site", "test", "--load-mode", "auto"])
    overrides = CLIConfigOverrides(args)
    assert overrides.load_mode is None

    # Test fp16 -> "fp16"
    args = parser.parse_args(["--site", "test", "--load-mode", "fp16"])
    overrides = CLIConfigOverrides(args)
    assert overrides.load_mode == "fp16"

    # Test int8 -> "int8"
    args = parser.parse_args(["--site", "test", "--load-mode", "int8"])
    overrides = CLIConfigOverrides(args)
    assert overrides.load_mode == "int8"

    # Test fp32 -> "fp32"
    args = parser.parse_args(["--site", "test", "--load-mode", "fp32"])
    overrides = CLIConfigOverrides(args)
    assert overrides.load_mode == "fp32"
