"""
Unit tests for CLI output path validation (SR-02c).

Tests the early validation logic for --output argument to ensure:
1. Fail fast before model loading (performance critical)
2. Clear error messages for common issues
3. Both CLI and engine-level validation
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli import validate_output_path
from src.translation_engine.engine import TranslationEngine


class TestCLIOutputValidation:
    """Test suite for CLI output path validation."""

    def test_validate_output_path_with_valid_directory(self, tmp_path):
        """Valid directory passes validation without error."""
        valid_dir = tmp_path / "output"
        valid_dir.mkdir()

        # Should not raise any exception
        validate_output_path(valid_dir)

    def test_validate_output_path_with_nonexistent_directory(self, tmp_path):
        """Non-existent directory with existing parent passes validation."""
        valid_parent = tmp_path
        nonexistent_dir = valid_parent / "new_output"

        # Should not raise (parent exists and is writable)
        validate_output_path(nonexistent_dir)

    def test_validate_output_path_fails_if_path_is_file(self, tmp_path):
        """Output path that is a file (not directory) fails with clear error."""
        file_path = tmp_path / "output.txt"
        file_path.write_text("test")

        with pytest.raises(SystemExit) as exc_info:
            validate_output_path(file_path)

        assert exc_info.value.code == 1

    def test_validate_output_path_fails_if_parent_does_not_exist(self):
        """Output path with non-existent parent fails with clear error."""
        invalid_path = Path("/nonexistent/deep/nested/path")

        with pytest.raises(SystemExit) as exc_info:
            validate_output_path(invalid_path)

        assert exc_info.value.code == 1

    @patch("os.access")
    def test_validate_output_path_fails_if_not_writable(self, mock_access, tmp_path):
        """Output path without write permissions fails with clear error."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()

        # Mock os.access to return False (not writable)
        mock_access.return_value = False

        with pytest.raises(SystemExit) as exc_info:
            validate_output_path(readonly_dir)

        assert exc_info.value.code == 1
        mock_access.assert_called_once()

    def test_validate_output_path_error_message_for_file(self, tmp_path, capsys):
        """Error message clearly explains path is a file."""
        file_path = tmp_path / "output.txt"
        file_path.write_text("test")

        with pytest.raises(SystemExit):
            validate_output_path(file_path)

        captured = capsys.readouterr()
        assert "ERROR: Output path is a file, not directory" in captured.err
        assert str(file_path) in captured.err

    def test_validate_output_path_error_message_for_missing_parent(self, capsys):
        """Error message clearly explains parent does not exist."""
        invalid_path = Path("/nonexistent/deep/path")

        with pytest.raises(SystemExit):
            validate_output_path(invalid_path)

        captured = capsys.readouterr()
        assert "ERROR: Output path parent does not exist" in captured.err

    @patch("os.access")
    def test_validate_output_path_error_message_for_no_write_permission(
        self, mock_access, tmp_path, capsys
    ):
        """Error message clearly explains path is not writable."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        mock_access.return_value = False

        with pytest.raises(SystemExit):
            validate_output_path(readonly_dir)

        captured = capsys.readouterr()
        assert "ERROR: Output path not writable" in captured.err


class TestEngineOutputValidation:
    """Test suite for engine-level output_dir_override validation."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for TranslationEngine initialization."""
        config_service = MagicMock()
        tm = MagicMock()
        model_loader = MagicMock()
        return config_service, tm, model_loader

    def test_engine_accepts_valid_path_object(self, mock_dependencies):
        """Engine accepts valid Path object for output_dir_override."""
        config_service, tm, model_loader = mock_dependencies

        # Should not raise any exception
        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("/tmp/output"),
        )

        assert engine.output_dir_override == Path("/tmp/output")

    def test_engine_accepts_none_for_output_dir_override(self, mock_dependencies):
        """Engine accepts None for output_dir_override (no override)."""
        config_service, tm, model_loader = mock_dependencies

        # Should not raise any exception
        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None,
        )

        assert engine.output_dir_override is None

    def test_engine_raises_valueerror_for_invalid_type_string(self, mock_dependencies):
        """Engine raises ValueError if output_dir_override is a string (not Path)."""
        config_service, tm, model_loader = mock_dependencies

        with pytest.raises(ValueError) as exc_info:
            TranslationEngine(
                config_service=config_service,
                tm=tm,
                model_loader=model_loader,
                output_dir_override="/tmp/output",  # String instead of Path
            )

        assert "output_dir_override must be Path or None" in str(exc_info.value)
        assert "str" in str(exc_info.value)

    def test_engine_raises_valueerror_for_invalid_type_int(self, mock_dependencies):
        """Engine raises ValueError if output_dir_override is an integer."""
        config_service, tm, model_loader = mock_dependencies

        with pytest.raises(ValueError) as exc_info:
            TranslationEngine(
                config_service=config_service,
                tm=tm,
                model_loader=model_loader,
                output_dir_override=123,  # Integer instead of Path
            )

        assert "output_dir_override must be Path or None" in str(exc_info.value)
        assert "int" in str(exc_info.value)

    def test_engine_raises_valueerror_for_invalid_type_dict(self, mock_dependencies):
        """Engine raises ValueError if output_dir_override is a dict."""
        config_service, tm, model_loader = mock_dependencies

        with pytest.raises(ValueError) as exc_info:
            TranslationEngine(
                config_service=config_service,
                tm=tm,
                model_loader=model_loader,
                output_dir_override={"path": "/tmp/output"},  # Dict instead of Path
            )

        assert "output_dir_override must be Path or None" in str(exc_info.value)
        assert "dict" in str(exc_info.value)

    def test_engine_error_message_includes_actual_type(self, mock_dependencies):
        """ValueError message includes the actual type that was passed."""
        config_service, tm, model_loader = mock_dependencies

        with pytest.raises(ValueError) as exc_info:
            TranslationEngine(
                config_service=config_service,
                tm=tm,
                model_loader=model_loader,
                output_dir_override=["/tmp/output"],  # List instead of Path
            )

        error_message = str(exc_info.value)
        assert "output_dir_override must be Path or None" in error_message
        assert "list" in error_message


class TestValidationIntegration:
    """Integration tests for validation workflow."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for TranslationEngine initialization."""
        config_service = MagicMock()
        tm = MagicMock()
        model_loader = MagicMock()
        return config_service, tm, model_loader

    def test_cli_validation_runs_before_engine_creation(self, tmp_path, mock_dependencies):
        """CLI validation catches invalid path before engine is instantiated."""
        config_service, tm, model_loader = mock_dependencies

        # Create a file (not directory) for output
        file_path = tmp_path / "output.txt"
        file_path.write_text("test")

        # CLI validation should catch this
        with pytest.raises(SystemExit) as exc_info:
            validate_output_path(file_path)

        # Engine should never be created (validation fails first)
        assert exc_info.value.code == 1

    def test_engine_validation_catches_type_errors(self, mock_dependencies):
        """Engine validation catches type errors even if CLI validation is bypassed."""
        config_service, tm, model_loader = mock_dependencies

        # Directly pass invalid type to engine (bypassing CLI validation)
        with pytest.raises(ValueError) as exc_info:
            TranslationEngine(
                config_service=config_service,
                tm=tm,
                model_loader=model_loader,
                output_dir_override="/tmp/output",  # String, not Path
            )

        assert "output_dir_override must be Path or None" in str(exc_info.value)

    def test_valid_path_passes_both_validations(self, tmp_path, mock_dependencies):
        """Valid Path passes both CLI and engine validation."""
        config_service, tm, model_loader = mock_dependencies

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # CLI validation should pass
        validate_output_path(output_dir)

        # Engine validation should pass
        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=output_dir,
        )

        assert engine.output_dir_override == output_dir
