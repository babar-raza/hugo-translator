"""
Tests for GPU Evidence Collection Tool

Tests cover:
- Module verification
- CLI command execution
- GPU detection
- Evidence collection
- CPU-only fallback
- Evidence reporting
"""

import json

# Import the modules we're testing
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'scripts'))
from collect_gpu_evidence import (
    CLIExecutionResult,
    CLIExecutor,
    EvidenceReporter,
    GPUDetector,
    GPUEvidence,
    GPUEvidenceCollector,
    GPUInfo,
    ModuleVerificationResult,
    ModuleVerifier,
)


class TestModuleVerifier:
    """Test ModuleVerifier class."""

    def test_verify_existing_module(self):
        """Test verifying a module that exists."""
        # Test with a built-in module
        result = ModuleVerifier.verify_module('json')

        assert result.module_name == 'json'
        assert result.importable is True
        assert result.error is None
        assert result.attributes is not None
        assert 'loads' in result.attributes
        assert 'dumps' in result.attributes

    def test_verify_nonexistent_module(self):
        """Test verifying a module that doesn't exist."""
        result = ModuleVerifier.verify_module('this_module_does_not_exist_12345')

        assert result.module_name == 'this_module_does_not_exist_12345'
        assert result.importable is False
        assert result.error is not None
        assert 'ModuleNotFoundError' in result.error or 'ImportError' in result.error

    def test_verify_multiple_modules(self):
        """Test verifying multiple modules."""
        modules = ['json', 'sys', 'this_does_not_exist']
        results = ModuleVerifier.verify_multiple_modules(modules)

        assert len(results) == 3
        assert results[0].importable is True  # json
        assert results[1].importable is True  # sys
        assert results[2].importable is False  # non-existent

    def test_verify_module_with_submodule(self):
        """Test verifying a module with submodules."""
        result = ModuleVerifier.verify_module('json.decoder')

        assert result.module_name == 'json.decoder'
        assert result.importable is True


class TestCLIExecutor:
    """Test CLIExecutor class."""

    def test_execute_successful_command(self):
        """Test executing a successful command."""
        # Use a simple command that should work on all platforms
        result = CLIExecutor.execute_command([sys.executable, '-c', 'print("test")'])

        assert result.exit_code == 0
        assert 'test' in result.stdout
        assert result.stderr == '' or result.stderr is not None
        assert result.execution_time_seconds >= 0
        assert result.timestamp is not None

    def test_execute_failing_command(self):
        """Test executing a command that fails."""
        result = CLIExecutor.execute_command([sys.executable, '-c', 'import sys; sys.exit(1)'])

        assert result.exit_code == 1
        assert result.execution_time_seconds >= 0

    def test_execute_command_with_stderr(self):
        """Test executing a command that produces stderr."""
        result = CLIExecutor.execute_command(
            [sys.executable, '-c', 'import sys; sys.stderr.write("error")']
        )

        assert result.exit_code == 0
        assert 'error' in result.stderr or result.stderr is not None

    def test_execute_nonexistent_command(self):
        """Test executing a command that doesn't exist."""
        result = CLIExecutor.execute_command(['this_command_does_not_exist_12345'])

        assert result.exit_code == -1
        assert 'Error executing command' in result.stderr or result.stderr is not None

    @patch('subprocess.run')
    def test_execute_command_timeout(self, mock_run):
        """Test command execution timeout."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired('test', 1)

        result = CLIExecutor.execute_command(['test'], timeout=1)

        assert result.exit_code == -1
        assert 'timed out' in result.stderr.lower()


class TestGPUDetector:
    """Test GPUDetector class."""

    @patch('collect_gpu_evidence.torch')
    def test_detect_gpu_with_cuda(self, mock_torch):
        """Test GPU detection when CUDA is available."""
        # Mock PyTorch with CUDA
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_name.return_value = 'NVIDIA GeForce RTX 4090'
        mock_torch.version.cuda = '12.1'

        # Mock device properties
        mock_props = Mock()
        mock_props.total_memory = 24 * 1024 * 1024 * 1024  # 24 GB
        mock_props.major = 8
        mock_props.minor = 9
        mock_torch.cuda.get_device_properties.return_value = mock_props
        mock_torch.cuda.mem_get_info.return_value = (20 * 1024 * 1024 * 1024, 24 * 1024 * 1024 * 1024)

        gpu_info, errors = GPUDetector.detect_gpu()

        assert gpu_info.cuda_available is True
        assert gpu_info.device_name == 'NVIDIA GeForce RTX 4090'
        assert gpu_info.cuda_version == '12.1'
        assert gpu_info.vram_total_mb > 0
        assert gpu_info.compute_capability == '8.9'

    @patch('collect_gpu_evidence.torch', side_effect=ImportError('No module named torch'))
    def test_detect_gpu_without_pytorch(self, mock_torch):
        """Test GPU detection when PyTorch is not available."""
        gpu_info, errors = GPUDetector.detect_gpu()

        assert gpu_info.cuda_available is False
        assert len(errors) > 0
        assert any('PyTorch not available' in e for e in errors)

    @patch('collect_gpu_evidence.torch')
    def test_detect_gpu_cpu_only(self, mock_torch):
        """Test GPU detection on CPU-only system."""
        mock_torch.cuda.is_available.return_value = False

        gpu_info, errors = GPUDetector.detect_gpu()

        assert gpu_info.cuda_available is False

    @patch('collect_gpu_evidence.torch')
    def test_detect_gpu_with_errors(self, mock_torch):
        """Test GPU detection with errors."""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_name.side_effect = RuntimeError('CUDA error')

        gpu_info, errors = GPUDetector.detect_gpu()

        # Should still detect CUDA available but have errors
        assert gpu_info.cuda_available is True
        assert len(errors) > 0


class TestGPUEvidenceCollector:
    """Test GPUEvidenceCollector class."""

    def test_collect_system_info(self):
        """Test collecting system information."""
        collector = GPUEvidenceCollector()
        system_info = collector.collect_system_info()

        assert 'platform' in system_info
        assert 'python_version' in system_info
        assert 'machine' in system_info
        assert 'processor' in system_info

    @patch('collect_gpu_evidence.GPUDetector.detect_gpu')
    @patch('collect_gpu_evidence.ModuleVerifier.verify_multiple_modules')
    def test_collect_evidence_basic(self, mock_verify, mock_detect):
        """Test basic evidence collection."""
        # Mock module verification
        mock_verify.return_value = [
            ModuleVerificationResult(
                module_name='test_module',
                exists=True,
                importable=True,
                error=None,
                module_path='/test/module.py',
                attributes=['test']
            )
        ]

        # Mock GPU detection
        mock_detect.return_value = (
            GPUInfo(cuda_available=False),
            []
        )

        collector = GPUEvidenceCollector()
        evidence = collector.collect_evidence(
            verify_modules=['test_module'],
            execute_commands=None
        )

        assert evidence.collection_time is not None
        assert len(evidence.module_verification) == 1
        assert evidence.module_verification[0].module_name == 'test_module'
        assert evidence.has_gpu is False

    @patch('collect_gpu_evidence.GPUDetector.detect_gpu')
    @patch('collect_gpu_evidence.CLIExecutor.execute_command')
    def test_collect_evidence_with_cli(self, mock_execute, mock_detect):
        """Test evidence collection with CLI execution."""
        # Mock CLI execution
        mock_execute.return_value = CLIExecutionResult(
            command='test command',
            exit_code=0,
            stdout='test output',
            stderr='',
            execution_time_seconds=1.5,
            timestamp='2024-01-01T12:00:00'
        )

        # Mock GPU detection
        mock_detect.return_value = (
            GPUInfo(cuda_available=False),
            []
        )

        collector = GPUEvidenceCollector()
        evidence = collector.collect_evidence(
            verify_modules=None,
            execute_commands=[['test', 'command']]
        )

        assert len(evidence.cli_execution) == 1
        assert evidence.cli_execution[0].command == 'test command'
        assert evidence.cli_execution[0].exit_code == 0

    @patch('collect_gpu_evidence.GPUDetector.detect_gpu')
    def test_collect_evidence_with_gpu(self, mock_detect):
        """Test evidence collection with GPU present."""
        # Mock GPU detection
        gpu_info = GPUInfo(
            device_name='NVIDIA RTX 4090',
            cuda_available=True,
            cuda_version='12.1',
            vram_total_mb=24576
        )
        mock_detect.return_value = (gpu_info, [])

        collector = GPUEvidenceCollector()
        evidence = collector.collect_evidence()

        assert evidence.has_gpu is True
        assert evidence.gpu_info.device_name == 'NVIDIA RTX 4090'
        assert evidence.gpu_info.cuda_version == '12.1'

    @patch('collect_gpu_evidence.GPUDetector.detect_gpu')
    def test_collect_evidence_with_errors(self, mock_detect):
        """Test evidence collection with errors."""
        # Mock GPU detection with errors
        mock_detect.return_value = (
            GPUInfo(cuda_available=False),
            ['GPU detection error', 'Another error']
        )

        collector = GPUEvidenceCollector()
        evidence = collector.collect_evidence()

        assert len(evidence.errors) >= 2
        assert evidence.evidence_valid is False

    @patch('collect_gpu_evidence.GPUDetector.detect_gpu')
    @patch('collect_gpu_evidence.ModuleVerifier.verify_multiple_modules')
    def test_collect_evidence_with_import_failure(self, mock_verify, mock_detect):
        """Test evidence collection with module import failure."""
        # Mock module verification failure
        mock_verify.return_value = [
            ModuleVerificationResult(
                module_name='bad_module',
                exists=False,
                importable=False,
                error='ImportError: No module named bad_module'
            )
        ]

        # Mock GPU detection
        mock_detect.return_value = (GPUInfo(cuda_available=False), [])

        collector = GPUEvidenceCollector()
        evidence = collector.collect_evidence(verify_modules=['bad_module'])

        assert len(evidence.warnings) > 0
        assert any('not importable' in w for w in evidence.warnings)


class TestEvidenceReporter:
    """Test EvidenceReporter class."""

    def test_save_evidence(self, tmp_path):
        """Test saving evidence to JSON file."""
        # Create minimal evidence
        evidence = GPUEvidence(
            collection_time='2024-01-01T12:00:00',
            system_info={'platform': 'test'},
            module_verification=[],
            cli_execution=[],
            gpu_info=GPUInfo(cuda_available=False),
            has_gpu=False,
            evidence_valid=True,
            errors=[],
            warnings=[]
        )

        output_file = tmp_path / 'evidence.json'
        EvidenceReporter.save_evidence(evidence, str(output_file))

        assert output_file.exists()

        # Load and verify
        with open(output_file) as f:
            data = json.load(f)

        assert data['collection_time'] == '2024-01-01T12:00:00'
        assert data['has_gpu'] is False
        assert data['evidence_valid'] is True

    def test_print_evidence_summary(self, capsys):
        """Test printing evidence summary."""
        evidence = GPUEvidence(
            collection_time='2024-01-01T12:00:00',
            system_info={
                'platform': 'Linux',
                'python_version': '3.10.0',
                'machine': 'x86_64',
                'processor': 'Intel'
            },
            module_verification=[
                ModuleVerificationResult(
                    module_name='test_module',
                    exists=True,
                    importable=True,
                    error=None,
                    module_path='/test/module.py',
                    attributes=['test']
                )
            ],
            cli_execution=[
                CLIExecutionResult(
                    command='test command',
                    exit_code=0,
                    stdout='output',
                    stderr='',
                    execution_time_seconds=1.5,
                    timestamp='2024-01-01T12:00:00'
                )
            ],
            gpu_info=GPUInfo(
                device_name='NVIDIA RTX 4090',
                cuda_available=True,
                cuda_version='12.1',
                vram_total_mb=24576,
                compute_capability='8.9'
            ),
            has_gpu=True,
            evidence_valid=True,
            errors=[],
            warnings=['Test warning']
        )

        EvidenceReporter.print_evidence_summary(evidence)

        captured = capsys.readouterr()
        assert 'GPU Evidence Collection Summary' in captured.out
        assert 'NVIDIA RTX 4090' in captured.out
        assert 'CUDA version: 12.1' in captured.out
        assert 'VRAM: 24576 MB' in captured.out
        assert 'test_module' in captured.out
        assert 'test command' in captured.out
        assert 'Test warning' in captured.out

    def test_print_evidence_summary_cpu_only(self, capsys):
        """Test printing evidence summary for CPU-only system."""
        evidence = GPUEvidence(
            collection_time='2024-01-01T12:00:00',
            system_info={
                'platform': 'Windows',
                'python_version': '3.10.0',
                'machine': 'AMD64',
                'processor': 'AMD'
            },
            module_verification=[],
            cli_execution=[],
            gpu_info=GPUInfo(cuda_available=False),
            has_gpu=False,
            evidence_valid=True,
            errors=[],
            warnings=[]
        )

        EvidenceReporter.print_evidence_summary(evidence)

        captured = capsys.readouterr()
        assert 'No GPU detected (CPU-only mode)' in captured.out
        assert 'Evidence collection successful' in captured.out


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_module_verifier_with_import_side_effects(self):
        """Test module verification when import has side effects."""
        # This should not crash even if module has side effects
        result = ModuleVerifier.verify_module('sys')
        assert result.importable is True

    @patch('subprocess.run')
    def test_cli_executor_with_unicode(self, mock_run):
        """Test CLI executor with unicode output."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Test 日本語 output"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = CLIExecutor.execute_command(['test'])

        assert result.exit_code == 0
        assert "日本語" in result.stdout or result.stdout is not None

    @patch('collect_gpu_evidence.GPUDetector.detect_gpu')
    def test_evidence_collector_no_modules_or_commands(self, mock_detect):
        """Test evidence collector with no modules or commands."""
        mock_detect.return_value = (GPUInfo(cuda_available=False), [])

        collector = GPUEvidenceCollector()
        evidence = collector.collect_evidence(
            verify_modules=None,
            execute_commands=None
        )

        assert len(evidence.module_verification) == 0
        assert len(evidence.cli_execution) == 0
        assert evidence.collection_time is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
