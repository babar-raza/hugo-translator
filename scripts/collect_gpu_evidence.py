#!/usr/bin/env python3
"""
GPU Evidence Collection Tool

This tool collects comprehensive evidence about GPU availability and capabilities:
- GPU detection results
- CUDA version and availability
- GPU device information (model, VRAM)
- Module import verification
- CLI command execution and validation
- Structured evidence reporting

Usage:
    python scripts/collect_gpu_evidence.py --collect
    python scripts/collect_gpu_evidence.py --verify src.hardware.gpu_manager
    python scripts/collect_gpu_evidence.py --collect --output reports/gpu_evidence.json
"""

import argparse
import importlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ModuleVerificationResult:
    """Result of module verification check."""
    module_name: str
    exists: bool
    importable: bool
    error: Optional[str] = None
    module_path: Optional[str] = None
    attributes: Optional[List[str]] = None


@dataclass
class CLIExecutionResult:
    """Result of CLI command execution."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    execution_time_seconds: float
    timestamp: str


@dataclass
class GPUInfo:
    """GPU device information."""
    device_name: Optional[str] = None
    device_index: Optional[int] = None
    cuda_available: Optional[bool] = None
    cuda_version: Optional[str] = None
    vram_total_mb: Optional[int] = None
    vram_free_mb: Optional[int] = None
    compute_capability: Optional[str] = None


@dataclass
class GPUEvidence:
    """Complete GPU evidence collection."""
    collection_time: str
    system_info: Dict[str, Any]
    module_verification: List[ModuleVerificationResult]
    cli_execution: List[CLIExecutionResult]
    gpu_info: GPUInfo
    has_gpu: bool
    evidence_valid: bool
    errors: List[str]
    warnings: List[str]


class ModuleVerifier:
    """Verifies module existence and importability."""

    @staticmethod
    def verify_module(module_name: str) -> ModuleVerificationResult:
        """
        Verify that a module exists and can be imported.

        Args:
            module_name: Fully qualified module name (e.g., 'src.hardware.gpu_manager')

        Returns:
            ModuleVerificationResult with verification details
        """
        # Convert module name to file path
        module_path = module_name.replace('.', os.sep) + '.py'

        # Check if file exists
        exists = Path(module_path).exists()

        # Try to import
        importable = False
        error = None
        attributes = None
        actual_path = None

        try:
            module = importlib.import_module(module_name)
            importable = True

            # Get module attributes
            attributes = [attr for attr in dir(module) if not attr.startswith('_')]

            # Get actual module path
            if hasattr(module, '__file__'):
                actual_path = str(module.__file__)

        except ImportError as e:
            error = f"ImportError: {str(e)}"
        except ModuleNotFoundError as e:
            error = f"ModuleNotFoundError: {str(e)}"
        except Exception as e:
            error = f"Unexpected error: {type(e).__name__}: {str(e)}"

        return ModuleVerificationResult(
            module_name=module_name,
            exists=exists,
            importable=importable,
            error=error,
            module_path=actual_path,
            attributes=attributes
        )

    @staticmethod
    def verify_multiple_modules(module_names: List[str]) -> List[ModuleVerificationResult]:
        """Verify multiple modules."""
        return [ModuleVerifier.verify_module(name) for name in module_names]


class CLIExecutor:
    """Executes CLI commands and captures output."""

    @staticmethod
    def execute_command(command: List[str], timeout: int = 30) -> CLIExecutionResult:
        """
        Execute a CLI command and capture output.

        Args:
            command: Command and arguments as list
            timeout: Timeout in seconds

        Returns:
            CLIExecutionResult with execution details
        """
        import time

        start_time = time.time()
        timestamp = datetime.now().isoformat()

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='replace'
            )

            execution_time = time.time() - start_time

            return CLIExecutionResult(
                command=' '.join(command),
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time_seconds=execution_time,
                timestamp=timestamp
            )

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            return CLIExecutionResult(
                command=' '.join(command),
                exit_code=-1,
                stdout='',
                stderr=f'Command timed out after {timeout} seconds',
                execution_time_seconds=execution_time,
                timestamp=timestamp
            )

        except Exception as e:
            execution_time = time.time() - start_time
            return CLIExecutionResult(
                command=' '.join(command),
                exit_code=-1,
                stdout='',
                stderr=f'Error executing command: {type(e).__name__}: {str(e)}',
                execution_time_seconds=execution_time,
                timestamp=timestamp
            )


class GPUDetector:
    """Detects GPU availability and capabilities."""

    @staticmethod
    def detect_gpu() -> Tuple[GPUInfo, List[str]]:
        """
        Detect GPU and collect information.

        Returns:
            Tuple of (GPUInfo, list of errors)
        """
        gpu_info = GPUInfo()
        errors = []

        # Try PyTorch CUDA detection
        try:
            import torch
            gpu_info.cuda_available = torch.cuda.is_available()

            if gpu_info.cuda_available:
                gpu_info.device_name = torch.cuda.get_device_name(0)
                gpu_info.device_index = 0

                # Get CUDA version
                if hasattr(torch.version, 'cuda'):
                    gpu_info.cuda_version = torch.version.cuda

                # Get VRAM info
                try:
                    props = torch.cuda.get_device_properties(0)
                    gpu_info.vram_total_mb = int(props.total_memory / (1024 * 1024))

                    # Try to get free memory
                    try:
                        gpu_info.vram_free_mb = int(
                            torch.cuda.mem_get_info(0)[0] / (1024 * 1024)
                        )
                    except:
                        pass

                    # Compute capability
                    gpu_info.compute_capability = f"{props.major}.{props.minor}"

                except Exception as e:
                    errors.append(f"Error getting GPU properties: {e}")

        except ImportError:
            errors.append("PyTorch not available for GPU detection")
            gpu_info.cuda_available = False
        except Exception as e:
            errors.append(f"Error detecting GPU with PyTorch: {e}")
            gpu_info.cuda_available = False

        # If PyTorch failed, try other methods
        if gpu_info.cuda_available is None:
            # Try nvidia-smi
            try:
                result = subprocess.run(
                    ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0 and result.stdout.strip():
                    parts = result.stdout.strip().split(',')
                    if len(parts) >= 1:
                        gpu_info.device_name = parts[0].strip()
                        gpu_info.cuda_available = True
                    if len(parts) >= 2:
                        try:
                            vram_str = parts[1].strip().replace(' MiB', '')
                            gpu_info.vram_total_mb = int(vram_str)
                        except:
                            pass

            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            except Exception as e:
                errors.append(f"Error running nvidia-smi: {e}")

        # Final fallback
        if gpu_info.cuda_available is None:
            gpu_info.cuda_available = False

        return gpu_info, errors


class GPUEvidenceCollector:
    """Main evidence collection orchestrator."""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def collect_system_info(self) -> Dict[str, Any]:
        """Collect system information."""
        import platform

        return {
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
        }

    def collect_evidence(
        self,
        verify_modules: Optional[List[str]] = None,
        execute_commands: Optional[List[List[str]]] = None
    ) -> GPUEvidence:
        """
        Collect complete GPU evidence.

        Args:
            verify_modules: List of module names to verify
            execute_commands: List of commands to execute

        Returns:
            GPUEvidence object with all collected evidence
        """
        # Collect system info
        system_info = self.collect_system_info()

        # Module verification
        module_results = []
        if verify_modules:
            module_results = ModuleVerifier.verify_multiple_modules(verify_modules)

            # Check for import failures
            for result in module_results:
                if not result.importable:
                    self.warnings.append(
                        f"Module {result.module_name} not importable: {result.error}"
                    )

        # CLI execution
        cli_results = []
        if execute_commands:
            for command in execute_commands:
                result = CLIExecutor.execute_command(command)
                cli_results.append(result)

                if result.exit_code != 0:
                    self.warnings.append(
                        f"Command '{result.command}' failed with exit code {result.exit_code}"
                    )

        # GPU detection
        gpu_info, gpu_errors = GPUDetector.detect_gpu()
        self.errors.extend(gpu_errors)

        # Determine if evidence is valid
        evidence_valid = len(self.errors) == 0

        evidence = GPUEvidence(
            collection_time=datetime.now().isoformat(),
            system_info=system_info,
            module_verification=module_results,
            cli_execution=cli_results,
            gpu_info=gpu_info,
            has_gpu=gpu_info.cuda_available or False,
            evidence_valid=evidence_valid,
            errors=self.errors,
            warnings=self.warnings
        )

        return evidence


class EvidenceReporter:
    """Generates evidence reports."""

    @staticmethod
    def save_evidence(evidence: GPUEvidence, output_path: str):
        """Save evidence to JSON file."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, 'w', encoding='utf-8') as f:
            json.dump(asdict(evidence), f, indent=2, ensure_ascii=False)

        print(f"Evidence saved to: {output}")

    @staticmethod
    def print_evidence_summary(evidence: GPUEvidence):
        """Print a summary of collected evidence."""
        print("\nGPU Evidence Collection Summary")
        print("=" * 60)
        print(f"Collection time: {evidence.collection_time}")
        print(f"System: {evidence.system_info['platform']}")
        print(f"Python: {evidence.system_info['python_version']}")
        print()

        # GPU status
        print("GPU Detection:")
        if evidence.has_gpu:
            print(f"  ✓ GPU available: {evidence.gpu_info.device_name}")
            if evidence.gpu_info.cuda_version:
                print(f"  CUDA version: {evidence.gpu_info.cuda_version}")
            if evidence.gpu_info.vram_total_mb:
                print(f"  VRAM: {evidence.gpu_info.vram_total_mb} MB")
            if evidence.gpu_info.compute_capability:
                print(f"  Compute capability: {evidence.gpu_info.compute_capability}")
        else:
            print("  ✗ No GPU detected (CPU-only mode)")
        print()

        # Module verification
        if evidence.module_verification:
            print(f"Module Verification ({len(evidence.module_verification)} modules):")
            for result in evidence.module_verification:
                status = "✓" if result.importable else "✗"
                print(f"  {status} {result.module_name}")
                if not result.importable and result.error:
                    print(f"    Error: {result.error}")
            print()

        # CLI execution
        if evidence.cli_execution:
            print(f"CLI Execution ({len(evidence.cli_execution)} commands):")
            for result in evidence.cli_execution:
                status = "✓" if result.exit_code == 0 else "✗"
                print(f"  {status} {result.command}")
                print(f"    Exit code: {result.exit_code}")
                print(f"    Duration: {result.execution_time_seconds:.2f}s")
                if result.exit_code != 0 and result.stderr:
                    print(f"    Error: {result.stderr[:100]}")
            print()

        # Errors and warnings
        if evidence.errors:
            print(f"Errors ({len(evidence.errors)}):")
            for error in evidence.errors:
                print(f"  ✗ {error}")
            print()

        if evidence.warnings:
            print(f"Warnings ({len(evidence.warnings)}):")
            for warning in evidence.warnings:
                print(f"  ⚠ {warning}")
            print()

        # Overall status
        print("Overall Status:")
        if evidence.evidence_valid:
            print("  ✓ Evidence collection successful")
        else:
            print("  ✗ Evidence collection had errors")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="GPU Evidence Collection Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect GPU evidence
  python scripts/collect_gpu_evidence.py --collect

  # Verify GPU module
  python scripts/collect_gpu_evidence.py --verify src.hardware.gpu_manager

  # Collect with output file
  python scripts/collect_gpu_evidence.py --collect --output reports/gpu_evidence.json

  # Execute GPU detection command
  python scripts/collect_gpu_evidence.py --collect --execute "python -m src.hardware.gpu_manager --detect"
        """
    )

    parser.add_argument('--collect', action='store_true',
                       help='Collect GPU evidence')
    parser.add_argument('--verify', metavar='MODULE', action='append',
                       help='Verify module import (can be specified multiple times)')
    parser.add_argument('--execute', metavar='COMMAND', action='append',
                       help='Execute command and collect output (can be specified multiple times)')
    parser.add_argument('--output', '-o', metavar='FILE',
                       help='Output file path (default: reports/gpu_evidence.json)')
    parser.add_argument('--format', choices=['json', 'summary'],
                       default='summary',
                       help='Output format (default: summary)')

    args = parser.parse_args()

    if not (args.collect or args.verify):
        parser.print_help()
        sys.exit(1)

    # Prepare collector
    collector = GPUEvidenceCollector()

    # Default modules to verify if --collect is used
    verify_modules = args.verify or []
    if args.collect and not verify_modules:
        verify_modules = ['src.hardware.gpu_manager']

    # Parse execute commands
    execute_commands = []
    if args.execute:
        for cmd_str in args.execute:
            # Split command string into list
            execute_commands.append(cmd_str.split())

    # Collect evidence
    evidence = collector.collect_evidence(
        verify_modules=verify_modules,
        execute_commands=execute_commands
    )

    # Output
    if args.format == 'json':
        output_path = args.output or 'reports/gpu_evidence.json'
        EvidenceReporter.save_evidence(evidence, output_path)
    else:
        EvidenceReporter.print_evidence_summary(evidence)

        if args.output:
            EvidenceReporter.save_evidence(evidence, args.output)

    # Exit with appropriate code
    if evidence.has_gpu:
        sys.exit(0)
    else:
        # CPU-only is not an error, just different state
        sys.exit(0)


if __name__ == '__main__':
    main()
