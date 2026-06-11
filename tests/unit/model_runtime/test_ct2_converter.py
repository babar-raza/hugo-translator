"""
Unit tests for CTranslate2 model converter.

Tests marked with @pytest.mark.slow require downloading real models.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock ctranslate2 module for testing
sys.modules["ctranslate2"] = MagicMock()
sys.modules["ctranslate2.converters"] = MagicMock()


@pytest.fixture
def temp_model_dir(tmp_path):
    """Create temporary model directory."""
    model_dir = tmp_path / "test_model"
    model_dir.mkdir()
    return model_dir


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create temporary output directory."""
    output_dir = tmp_path / "ct2_model"
    return output_dir


@pytest.fixture
def mock_ct2_import():
    """Mock ctranslate2 import for tests."""
    with patch.dict("sys.modules", {"ctranslate2": MagicMock()}):
        yield


class TestCT2ConversionPipeline:
    """Test suite for CT2ConversionPipeline."""

    def test_init_without_ctranslate2(self):
        """Test that pipeline initialization fails when ctranslate2 is not installed."""
        # Remove the mock temporarily to test import error
        original_ct2 = sys.modules.pop("ctranslate2", None)

        try:
            # Reload the module to trigger import check
            import importlib

            import src.model_runtime.ct2_converter

            importlib.reload(src.model_runtime.ct2_converter)

            with pytest.raises(ImportError, match="ctranslate2 is not installed"):
                src.model_runtime.ct2_converter.CT2ConversionPipeline()
        finally:
            # Restore the mock
            if original_ct2:
                sys.modules["ctranslate2"] = original_ct2
            else:
                sys.modules["ctranslate2"] = MagicMock()

    def test_convert_model_success(self, temp_model_dir, temp_output_dir):
        """Test successful model conversion."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Mock ctranslate2 converter
        mock_converter = MagicMock()
        mock_converter.convert = MagicMock()

        with patch("ctranslate2.converters.TransformersConverter") as mock_conv_class:
            mock_conv_class.return_value = mock_converter

            pipeline = CT2ConversionPipeline()
            success = pipeline.convert_model(
                model_path=temp_model_dir,
                output_path=temp_output_dir,
                quantization="int8",
                force=False,
            )

            assert success is True
            assert temp_output_dir.exists()
            mock_conv_class.assert_called_once_with(str(temp_model_dir))
            mock_converter.convert.assert_called_once_with(
                output_dir=str(temp_output_dir),
                quantization="int8",
                force=False,
            )

    def test_convert_model_output_exists_no_force(self, temp_model_dir, temp_output_dir):
        """Test conversion fails when output exists and force=False."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Create existing output directory
        temp_output_dir.mkdir()

        pipeline = CT2ConversionPipeline()
        success = pipeline.convert_model(
            model_path=temp_model_dir,
            output_path=temp_output_dir,
            quantization="int8",
            force=False,
        )

        assert success is False

    def test_convert_model_output_exists_with_force(self, temp_model_dir, temp_output_dir):
        """Test conversion succeeds when output exists and force=True."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Create existing output directory with a file
        temp_output_dir.mkdir()
        (temp_output_dir / "old_file.txt").write_text("old content")

        # Mock ctranslate2 converter
        mock_converter = MagicMock()
        mock_converter.convert = MagicMock()

        with patch("ctranslate2.converters.TransformersConverter") as mock_conv_class:
            mock_conv_class.return_value = mock_converter

            pipeline = CT2ConversionPipeline()
            success = pipeline.convert_model(
                model_path=temp_model_dir,
                output_path=temp_output_dir,
                quantization="int8",
                force=True,
            )

            assert success is True
            assert temp_output_dir.exists()
            # Old file should be removed
            assert not (temp_output_dir / "old_file.txt").exists()

    def test_convert_model_failure_cleanup(self, temp_model_dir, temp_output_dir):
        """Test that conversion cleans up on failure."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Mock converter to raise exception
        with patch(
            "ctranslate2.converters.TransformersConverter",
            side_effect=Exception("Conversion error"),
        ):
            pipeline = CT2ConversionPipeline()
            success = pipeline.convert_model(
                model_path=temp_model_dir,
                output_path=temp_output_dir,
                quantization="int8",
                force=False,
            )

            assert success is False
            # Output directory should be cleaned up
            assert not temp_output_dir.exists()

    def test_validate_ct2_model_missing_path(self, tmp_path):
        """Test validation fails for non-existent path."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        pipeline = CT2ConversionPipeline()
        result = pipeline.validate_ct2_model(tmp_path / "nonexistent")

        assert result is False

    def test_validate_ct2_model_not_directory(self, tmp_path):
        """Test validation fails for file instead of directory."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Create a file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        pipeline = CT2ConversionPipeline()
        result = pipeline.validate_ct2_model(test_file)

        assert result is False

    def test_validate_ct2_model_missing_required_files(self, tmp_path):
        """Test validation fails when required files are missing."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Create directory without required files
        model_dir = tmp_path / "incomplete_model"
        model_dir.mkdir()

        pipeline = CT2ConversionPipeline()
        result = pipeline.validate_ct2_model(model_dir)

        assert result is False

    def test_validate_ct2_model_success(self, tmp_path):
        """Test validation succeeds for valid model."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Create directory with required files
        model_dir = tmp_path / "valid_model"
        model_dir.mkdir()
        (model_dir / "model.bin").write_bytes(b"fake model data")
        (model_dir / "config.json").write_text('{"test": "config"}')

        # Mock ctranslate2.Translator
        mock_translator = MagicMock()

        with patch("ctranslate2.Translator") as mock_trans_class:
            mock_trans_class.return_value = mock_translator

            pipeline = CT2ConversionPipeline()
            result = pipeline.validate_ct2_model(model_dir)

            assert result is True
            mock_trans_class.assert_called_once_with(str(model_dir), device="cpu")

    def test_validate_ct2_model_load_failure(self, tmp_path):
        """Test validation fails when model loading fails."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Create directory with required files
        model_dir = tmp_path / "invalid_model"
        model_dir.mkdir()
        (model_dir / "model.bin").write_bytes(b"corrupt data")

        # Mock ctranslate2.Translator to raise exception
        with patch(
            "ctranslate2.Translator",
            side_effect=Exception("Failed to load model"),
        ):
            pipeline = CT2ConversionPipeline()
            result = pipeline.validate_ct2_model(model_dir)

            assert result is False

    def test_get_model_info_invalid_model(self, tmp_path):
        """Test get_model_info returns None for invalid model."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        pipeline = CT2ConversionPipeline()
        result = pipeline.get_model_info(tmp_path / "nonexistent")

        assert result is None

    def test_get_model_info_success(self, tmp_path):
        """Test get_model_info returns correct information."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Create directory with files
        model_dir = tmp_path / "valid_model"
        model_dir.mkdir()
        (model_dir / "model.bin").write_bytes(b"x" * 1024 * 100)  # 100KB
        (model_dir / "config.json").write_text('{"version": "1.0"}')

        # Mock validation and ctranslate2
        mock_translator = MagicMock()

        with patch("ctranslate2.Translator") as mock_trans_class:
            mock_trans_class.return_value = mock_translator

            pipeline = CT2ConversionPipeline()
            info = pipeline.get_model_info(model_dir)

            assert info is not None
            assert "model_path" in info
            assert "size_mb" in info
            assert "files" in info
            assert "config" in info
            assert info["model_path"] == str(model_dir)
            assert info["size_mb"] > 0
            assert "model.bin" in info["files"]
            assert "config.json" in info["files"]
            assert info["config"]["version"] == "1.0"

    def test_check_disk_space_sufficient(self, tmp_path):
        """Test disk space check passes when sufficient space available."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        pipeline = CT2ConversionPipeline()

        # Use small requirement that should always pass
        result = pipeline.check_disk_space(tmp_path, required_mb=1)

        assert result is True

    def test_check_disk_space_insufficient(self, tmp_path):
        """Test disk space check fails when insufficient space."""
        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        pipeline = CT2ConversionPipeline()

        # Use unrealistic requirement
        result = pipeline.check_disk_space(tmp_path, required_mb=999999999)

        assert result is False

    @pytest.mark.slow
    def test_real_model_conversion(self, tmp_path):
        """
        Test actual model conversion with a real model.

        This test requires:
        1. ctranslate2 installed
        2. transformers installed
        3. Internet connection (may download model)
        4. Sufficient disk space (~500MB)

        Run with: pytest -m slow
        """
        pytest.importorskip("ctranslate2")
        pytest.importorskip("transformers")

        from src.model_runtime.ct2_converter import CT2ConversionPipeline

        # Use a small test model (can be replaced with actual model if available)
        # For now, skip if model not available locally
        test_model = Path("models/m2m100_418M")
        if not test_model.exists():
            pytest.skip("Test model not available. Download first with download_m2m100_model.py")

        output_dir = tmp_path / "ct2_test_output"

        pipeline = CT2ConversionPipeline()

        # Check disk space
        assert pipeline.check_disk_space(output_dir, required_mb=500)

        # Convert model
        success = pipeline.convert_model(
            model_path=test_model,
            output_path=output_dir,
            quantization="int8",
            force=False,
        )

        assert success is True
        assert output_dir.exists()

        # Validate converted model
        assert pipeline.validate_ct2_model(output_dir)

        # Get model info
        info = pipeline.get_model_info(output_dir)
        assert info is not None
        assert info["size_mb"] > 0
        assert "model.bin" in info["files"]

        # Verify INT8 quantization resulted in smaller size
        # Original model is ~500MB, INT8 should be significantly smaller
        assert info["size_mb"] < 500
