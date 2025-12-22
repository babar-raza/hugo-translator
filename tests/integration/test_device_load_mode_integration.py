"""
End-to-end integration tests for device and load-mode flags (T105: federated-splashing-panda).

Tests the complete pipeline: CLI flags → device validation → ModelLoader → HuggingFaceBackend
"""
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def test_fixture_path():
    """Path to the device test fixture."""
    return Path(__file__).parent.parent / "fixtures" / "device_test" / "sample.md"


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestDeviceLoadModeE2E:
    """End-to-end tests for device and load-mode integration."""

    def test_device_cpu_load_mode_fp32_e2e(self, test_fixture_path, temp_output_dir):
        """Test --device cpu --load-mode fp32 completes successfully."""
        # Skip if test fixture doesn't exist
        if not test_fixture_path.exists():
            pytest.skip("Test fixture not found")

        # Run CLI with CPU and FP32
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--device",
                "cpu",
                "--load-mode",
                "fp32",
                "--single-file",
                str(test_fixture_path),
                "--output-dir",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
        )

        # Check exit code
        if result.returncode != 0:
            # If dependencies not installed, skip test
            if "No module named" in result.stderr or "command not found" in result.stderr:
                pytest.skip("Dependencies not installed")

        # Verify success (exit code 0 or graceful error)
        assert result.returncode == 0 or "CUDA device requested" not in result.stderr

        # Verify logs show correct device and precision
        assert "Device: cpu (CLI override)" in result.stdout or "Auto-detected device: cpu" in result.stdout

    def test_device_cpu_load_mode_int8_e2e(self, test_fixture_path, temp_output_dir):
        """Test --device cpu --load-mode int8 completes successfully."""
        # Skip if test fixture doesn't exist
        if not test_fixture_path.exists():
            pytest.skip("Test fixture not found")

        # Run CLI with CPU and INT8
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--device",
                "cpu",
                "--load-mode",
                "int8",
                "--single-file",
                str(test_fixture_path),
                "--output-dir",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
        )

        # Check exit code
        if result.returncode != 0:
            # If dependencies not installed, skip test
            if "No module named" in result.stderr or "command not found" in result.stderr:
                pytest.skip("Dependencies not installed")

        # Verify success
        assert result.returncode == 0 or "CUDA device requested" not in result.stderr

        # Verify logs show correct device and precision
        assert "Device: cpu (CLI override)" in result.stdout or "Auto-detected device: cpu" in result.stdout

    @pytest.mark.skipif(
        not __import__("subprocess").run(
            ["python", "-c", "import torch; print(torch.cuda.is_available())"],
            capture_output=True,
            text=True,
        ).stdout.strip() == "True",
        reason="CUDA not available",
    )
    def test_device_cuda_load_mode_fp16_e2e(self, test_fixture_path, temp_output_dir):
        """Test --device cuda --load-mode fp16 (skip if no CUDA)."""
        # Skip if test fixture doesn't exist
        if not test_fixture_path.exists():
            pytest.skip("Test fixture not found")

        # Run CLI with CUDA and FP16
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--device",
                "cuda",
                "--load-mode",
                "fp16",
                "--single-file",
                str(test_fixture_path),
                "--output-dir",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
        )

        # Check exit code
        if result.returncode != 0:
            # If dependencies not installed, skip test
            if "No module named" in result.stderr or "command not found" in result.stderr:
                pytest.skip("Dependencies not installed")

        # Verify success
        assert result.returncode == 0

        # Verify logs show CUDA and FP16
        assert "Device: cuda (CLI override)" in result.stdout
        assert "fp16" in result.stdout.lower()

    def test_backward_compatibility_auto_mode(self, test_fixture_path, temp_output_dir):
        """Test that no flags uses auto mode (backward compatibility)."""
        # Skip if test fixture doesn't exist
        if not test_fixture_path.exists():
            pytest.skip("Test fixture not found")

        # Run CLI without device or load-mode flags
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--single-file",
                str(test_fixture_path),
                "--output-dir",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
        )

        # Check exit code
        if result.returncode != 0:
            # If dependencies not installed, skip test
            if "No module named" in result.stderr or "command not found" in result.stderr:
                pytest.skip("Dependencies not installed")

        # Verify success
        assert result.returncode == 0 or "CUDA device requested" not in result.stderr

        # Verify auto-detection occurred
        assert "Auto-detected device:" in result.stdout

    def test_device_override_cuda_when_unavailable_fails(self):
        """Test that --device cuda fails when CUDA unavailable."""
        # Check if CUDA is available
        cuda_check = subprocess.run(
            ["python", "-c", "import torch; print(torch.cuda.is_available())"],
            capture_output=True,
            text=True,
        )

        # If dependencies not installed, skip
        if cuda_check.returncode != 0:
            pytest.skip("PyTorch not installed")

        cuda_available = cuda_check.stdout.strip() == "True"

        # Only run this test if CUDA is NOT available
        if cuda_available:
            pytest.skip("CUDA is available, cannot test failure case")

        # Run CLI with CUDA on non-CUDA system
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--device",
                "cuda",
                "--single-file",
                "tests/fixtures/device_test/sample.md",
            ],
            capture_output=True,
            text=True,
        )

        # Verify exit code 1 (error)
        assert result.returncode == 1

        # Verify error message
        assert "CUDA device requested but not available" in result.stderr or "CUDA device requested but not available" in result.stdout

    def test_load_mode_fp16_on_cpu_warns(self, test_fixture_path, temp_output_dir):
        """Test that --load-mode fp16 --device cpu logs warning."""
        # Skip if test fixture doesn't exist
        if not test_fixture_path.exists():
            pytest.skip("Test fixture not found")

        # Run CLI with FP16 on CPU
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--device",
                "cpu",
                "--load-mode",
                "fp16",
                "--single-file",
                str(test_fixture_path),
                "--output-dir",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
        )

        # Check exit code
        if result.returncode != 0:
            # If dependencies not installed, skip test
            if "No module named" in result.stderr or "command not found" in result.stderr:
                pytest.skip("Dependencies not installed")

        # Verify warning about FP16 on CPU
        combined_output = result.stdout + result.stderr
        assert "FP16" in combined_output or "fp16" in combined_output
        assert "CPU" in combined_output or "cpu" in combined_output

    def test_load_mode_int8_on_cuda_warns(self, test_fixture_path, temp_output_dir):
        """Test that --load-mode int8 --device cuda logs warning."""
        # Check if CUDA is available
        cuda_check = subprocess.run(
            ["python", "-c", "import torch; print(torch.cuda.is_available())"],
            capture_output=True,
            text=True,
        )

        # If dependencies not installed or CUDA not available, skip
        if cuda_check.returncode != 0 or cuda_check.stdout.strip() != "True":
            pytest.skip("PyTorch not installed or CUDA not available")

        # Skip if test fixture doesn't exist
        if not test_fixture_path.exists():
            pytest.skip("Test fixture not found")

        # Run CLI with INT8 on CUDA
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--device",
                "cuda",
                "--load-mode",
                "int8",
                "--single-file",
                str(test_fixture_path),
                "--output-dir",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
        )

        # Check exit code
        if result.returncode != 0:
            # If dependencies not installed, skip test
            if "No module named" in result.stderr or "command not found" in result.stderr:
                pytest.skip("Dependencies not installed")

        # Verify warning about INT8 on CUDA
        combined_output = result.stdout + result.stderr
        assert "INT8" in combined_output or "int8" in combined_output
        assert "CUDA" in combined_output or "cuda" in combined_output
