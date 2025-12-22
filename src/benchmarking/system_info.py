"""
System information collector for benchmark metadata.

Reuses HardwareDetector from src/model_runtime/hardware.py and adds
sanitization for path-based PII leakage.
"""
import argparse
import json
import logging
import platform
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.model_runtime.hardware import HardwareDetector

logger = logging.getLogger(__name__)


@dataclass
class SystemInfo:
    """
    Complete system information snapshot for benchmarking.

    All paths are sanitized to prevent username/homedir leakage.
    """

    # Hardware
    cpu_model: str
    cpu_cores: int
    total_ram_gb: float

    # GPU (optional)
    gpu_model: Optional[str] = None
    gpu_memory_gb: Optional[float] = None
    gpu_compute_capability: Optional[str] = None
    has_cuda: bool = False
    cuda_version: Optional[str] = None

    # Platform
    os_name: str = ""
    os_version: str = ""
    platform_system: str = ""
    platform_release: str = ""

    # Python environment
    python_version: str = ""
    python_implementation: str = ""

    # PyTorch
    torch_version: Optional[str] = None
    torch_cuda_available: bool = False

    # Metadata
    collected_at_utc: str = ""
    collector_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemInfo":
        """Create from dictionary."""
        return cls(**data)


class SystemInfoCollector:
    """
    Collect system information for benchmark metadata.

    Reuses HardwareDetector from src/model_runtime/hardware.py for
    hardware detection and adds path sanitization to prevent PII leakage.
    """

    def __init__(self):
        """Initialize collector with HardwareDetector."""
        self.hardware_detector = HardwareDetector()

    def collect(self) -> SystemInfo:
        """
        Collect complete system information.

        Returns:
            SystemInfo object with all available hardware and platform data

        Logs warnings if optional components (CUDA, torch) are unavailable.
        """
        logger.info("Collecting system information for benchmarking...")

        # Detect hardware using existing HardwareDetector
        hardware_info = self.hardware_detector.detect()

        # Get CPU model
        cpu_model = self._get_cpu_model()

        # Collect GPU information
        gpu_info = self._collect_gpu_info(hardware_info)

        # Collect platform information
        platform_info = self._collect_platform_info()

        # Collect Python environment
        python_info = self._collect_python_info()

        # Collect PyTorch information
        torch_info = self._collect_torch_info()

        system_info = SystemInfo(
            # Hardware
            cpu_model=cpu_model,
            cpu_cores=hardware_info.cpu_count,
            total_ram_gb=hardware_info.total_ram_gb,
            # GPU
            gpu_model=gpu_info.get("gpu_model"),
            gpu_memory_gb=gpu_info.get("gpu_memory_gb"),
            gpu_compute_capability=gpu_info.get("gpu_compute_capability"),
            has_cuda=hardware_info.has_cuda,
            cuda_version=gpu_info.get("cuda_version"),
            # Platform
            os_name=platform_info["os_name"],
            os_version=platform_info["os_version"],
            platform_system=platform_info["platform_system"],
            platform_release=platform_info["platform_release"],
            # Python
            python_version=python_info["python_version"],
            python_implementation=python_info["python_implementation"],
            # PyTorch
            torch_version=torch_info.get("torch_version"),
            torch_cuda_available=torch_info.get("torch_cuda_available", False),
            # Metadata
            collected_at_utc=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(f"System info collected: {cpu_model}, {hardware_info.cpu_count} cores, {hardware_info.total_ram_gb}GB RAM")
        if system_info.gpu_model:
            logger.info(f"GPU detected: {system_info.gpu_model} ({system_info.gpu_memory_gb}GB)")

        return system_info

    def _get_cpu_model(self) -> str:
        """
        Get CPU model name.

        Returns:
            Sanitized CPU model string
        """
        try:
            cpu_model = platform.processor()
            if not cpu_model or cpu_model.strip() == "":
                # Fallback for some platforms
                cpu_model = platform.machine()
            return self._sanitize_string(cpu_model)
        except Exception as e:
            logger.warning(f"Failed to get CPU model: {e}")
            return "Unknown CPU"

    def _collect_gpu_info(self, hardware_info) -> Dict[str, Optional[Any]]:
        """
        Collect GPU information from hardware detection.

        Args:
            hardware_info: HardwareInfo from HardwareDetector

        Returns:
            Dictionary with gpu_model, gpu_memory_gb, gpu_compute_capability, cuda_version
        """
        gpu_info = {
            "gpu_model": None,
            "gpu_memory_gb": None,
            "gpu_compute_capability": None,
            "cuda_version": None,
        }

        if not hardware_info.has_cuda or not hardware_info.cuda_devices:
            return gpu_info

        try:
            # Use first GPU device
            primary_gpu = hardware_info.cuda_devices[0]
            gpu_info["gpu_model"] = self._sanitize_string(primary_gpu["name"])
            gpu_info["gpu_memory_gb"] = round(primary_gpu["total_memory_gb"], 2)
            gpu_info["gpu_compute_capability"] = primary_gpu["compute_capability"]

            # Get CUDA version
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_info["cuda_version"] = torch.version.cuda
            except ImportError:
                logger.warning("torch not available for CUDA version detection")
        except Exception as e:
            logger.warning(f"Failed to collect GPU info: {e}")

        return gpu_info

    def _collect_platform_info(self) -> Dict[str, str]:
        """
        Collect platform and OS information.

        Returns:
            Dictionary with sanitized platform information
        """
        try:
            platform_str = platform.platform()
            system = platform.system()
            release = platform.release()

            return {
                "os_name": self._sanitize_string(system),
                "os_version": self._sanitize_string(release),
                "platform_system": self._sanitize_string(system),
                "platform_release": self._sanitize_string(release),
            }
        except Exception as e:
            logger.warning(f"Failed to collect platform info: {e}")
            return {
                "os_name": "Unknown",
                "os_version": "Unknown",
                "platform_system": "Unknown",
                "platform_release": "Unknown",
            }

    def _collect_python_info(self) -> Dict[str, str]:
        """
        Collect Python environment information.

        Returns:
            Dictionary with Python version and implementation
        """
        try:
            return {
                "python_version": platform.python_version(),
                "python_implementation": platform.python_implementation(),
            }
        except Exception as e:
            logger.warning(f"Failed to collect Python info: {e}")
            return {
                "python_version": "Unknown",
                "python_implementation": "Unknown",
            }

    def _collect_torch_info(self) -> Dict[str, Optional[Any]]:
        """
        Collect PyTorch information.

        Returns:
            Dictionary with torch_version and torch_cuda_available

        Gracefully handles ImportError when torch is not installed.
        """
        torch_info = {
            "torch_version": None,
            "torch_cuda_available": False,
        }

        try:
            import torch
            torch_info["torch_version"] = torch.__version__
            torch_info["torch_cuda_available"] = torch.cuda.is_available()
        except ImportError:
            logger.warning("torch not installed, PyTorch info unavailable")
        except Exception as e:
            logger.warning(f"Failed to collect torch info: {e}")

        return torch_info

    def _sanitize_string(self, value: str) -> str:
        """
        Sanitize string to remove potential PII (usernames, paths).

        Args:
            value: String to sanitize

        Returns:
            Sanitized string with paths normalized to forward slashes

        Security requirement: No username or homedir leakage in output.
        """
        if not value:
            return value

        # Replace Windows paths with forward slashes for portability
        sanitized = value.replace("\\", "/")

        # Remove common username patterns in paths
        # Match patterns like C:/Users/username or /home/username
        sanitized = re.sub(r"(?i)([/\\]Users[/\\])[^/\\]+", r"\1<user>", sanitized)
        sanitized = re.sub(r"(?i)([/\\]home[/\\])[^/\\]+", r"\1<user>", sanitized)

        # Remove OneDrive paths (common Windows user path)
        sanitized = re.sub(r"(?i)(OneDrive[/\\]Documents)", r"<user>/Documents", sanitized)

        return sanitized


def main():
    """
    CLI entry point for system info collection.

    Usage:
        python -m src.benchmarking.system_info [--out FILE] [--pretty]
    """
    parser = argparse.ArgumentParser(
        description="Collect system information for benchmarking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Print to stdout
  python -m src.benchmarking.system_info

  # Save to file
  python -m src.benchmarking.system_info --out reports/benchmarking/system_info.json

  # Pretty-print JSON
  python -m src.benchmarking.system_info --pretty
        """,
    )

    parser.add_argument(
        "--out",
        type=str,
        help="Output file path (default: stdout)",
    )

    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Collect system info
    try:
        collector = SystemInfoCollector()
        system_info = collector.collect()

        # Convert to JSON
        json_data = system_info.to_dict()
        indent = 2 if args.pretty else None
        json_output = json.dumps(json_data, indent=indent)

        # Write to file or stdout
        if args.out:
            output_path = Path(args.out)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json_output)
            logger.info(f"System info written to {output_path}")
        else:
            print(json_output)

        return 0

    except Exception as e:
        logger.error(f"Failed to collect system info: {e}", exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
