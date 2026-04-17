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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    gpu_model: str | None = None
    gpu_memory_gb: float | None = None
    gpu_compute_capability: str | None = None
    has_cuda: bool = False
    cuda_version: str | None = None

    # Platform
    os_name: str = ""
    os_version: str = ""
    platform_system: str = ""
    platform_release: str = ""

    # Python environment
    python_version: str = ""
    python_implementation: str = ""

    # PyTorch
    torch_version: str | None = None
    torch_cuda_available: bool = False

    # BM-09: Extended hardware context for better learning
    cpu_frequency_mhz: float | None = None  # Current CPU frequency
    cpu_frequency_max_mhz: float | None = None  # Max CPU frequency
    cpu_tdp_watts: float | None = None  # Thermal Design Power
    memory_bandwidth_gbps: float | None = None  # Memory bandwidth
    numa_nodes: int = 1  # NUMA node count

    gpu_driver_version: str | None = None  # GPU driver version

    power_management_state: str | None = None  # "performance", "balanced", "power_saver"

    # Metadata
    collected_at_utc: str = ""
    collector_version: str = "1.0.1"  # BM-09: Bumped for new fields

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SystemInfo":
        """Create from dictionary."""
        return cls(**data)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "SystemInfo":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))


class SystemInfoCollector:
    """
    Collect system information for benchmark metadata.

    Reuses HardwareDetector from src/model_runtime/hardware.py for
    hardware detection and adds path sanitization to prevent PII leakage.
    """

    def __init__(self):
        """Initialize collector with HardwareDetector."""
        self.hardware_detector = HardwareDetector()

    @staticmethod
    def get_available_gpu_memory_mb(device_id: int = 0) -> float | None:
        """Get currently available GPU memory in MB.

        Args:
            device_id: CUDA device index (default: 0)

        Returns:
            Available GPU memory in MB, or None if CUDA unavailable or error

        Note:
            Returns free memory (not allocated), useful for OOM prevention.
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return None

            if device_id < 0 or device_id >= torch.cuda.device_count():
                logger.error(f"Invalid device_id: {device_id} (available: {torch.cuda.device_count()})")
                return None

            # Get memory info for specified device
            mem_free, mem_total = torch.cuda.mem_get_info(device_id)
            return mem_free / (1024 ** 2)  # bytes to MB

        except ImportError:
            logger.debug("torch not available for GPU memory query")
            return None
        except Exception as e:
            logger.error(f"Failed to get GPU memory for device {device_id}: {e}")
            return None

    @staticmethod
    def get_gpu_memory_stats(device_id: int = 0) -> dict[str, float] | None:
        """Get comprehensive GPU memory statistics.

        Args:
            device_id: CUDA device index (default: 0)

        Returns:
            Dictionary with memory stats in MB:
                - total_mb: Total GPU memory
                - free_mb: Currently free memory
                - used_mb: Currently used memory
                - allocated_mb: Memory allocated by PyTorch
                - reserved_mb: Memory reserved by PyTorch caching allocator
            Returns None if CUDA unavailable or error

        Note:
            Provides full memory breakdown for monitoring and debugging.
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return None

            if device_id < 0 or device_id >= torch.cuda.device_count():
                logger.error(f"Invalid device_id: {device_id} (available: {torch.cuda.device_count()})")
                return None

            # Get memory info
            mem_free, mem_total = torch.cuda.mem_get_info(device_id)
            mem_allocated = torch.cuda.memory_allocated(device_id)
            mem_reserved = torch.cuda.memory_reserved(device_id)

            return {
                'total_mb': mem_total / (1024 ** 2),
                'free_mb': mem_free / (1024 ** 2),
                'used_mb': (mem_total - mem_free) / (1024 ** 2),
                'allocated_mb': mem_allocated / (1024 ** 2),
                'reserved_mb': mem_reserved / (1024 ** 2),
            }

        except ImportError:
            logger.debug("torch not available for GPU memory stats")
            return None
        except Exception as e:
            logger.error(f"Failed to get GPU memory stats for device {device_id}: {e}")
            return None

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

        # BM-09: Collect extended hardware context
        extended_info = self._collect_extended_hardware_info()

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
            # BM-09: Extended hardware context
            cpu_frequency_mhz=extended_info.get("cpu_frequency_mhz"),
            cpu_frequency_max_mhz=extended_info.get("cpu_frequency_max_mhz"),
            cpu_tdp_watts=extended_info.get("cpu_tdp_watts"),
            memory_bandwidth_gbps=extended_info.get("memory_bandwidth_gbps"),
            numa_nodes=extended_info.get("numa_nodes", 1),
            gpu_driver_version=extended_info.get("gpu_driver_version"),
            power_management_state=extended_info.get("power_management_state"),
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

    def _collect_gpu_info(self, hardware_info) -> dict[str, Any | None]:
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

    def _collect_platform_info(self) -> dict[str, str]:
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

    def _collect_python_info(self) -> dict[str, str]:
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

    def _collect_torch_info(self) -> dict[str, Any | None]:
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

    def _collect_extended_hardware_info(self) -> dict[str, Any | None]:
        """
        Collect extended hardware information (BM-09).

        Returns:
            Dictionary with extended hardware context

        Gracefully handles missing dependencies (psutil).
        """
        extended_info = {
            "cpu_frequency_mhz": None,
            "cpu_frequency_max_mhz": None,
            "cpu_tdp_watts": None,
            "memory_bandwidth_gbps": None,
            "numa_nodes": 1,
            "gpu_driver_version": None,
            "power_management_state": None,
        }

        # Try to use psutil for detailed CPU info
        try:
            import psutil

            # CPU frequency
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                extended_info["cpu_frequency_mhz"] = round(cpu_freq.current, 2) if cpu_freq.current else None
                extended_info["cpu_frequency_max_mhz"] = round(cpu_freq.max, 2) if cpu_freq.max else None

            # Power management state (very rough heuristic)
            if cpu_freq and cpu_freq.max and cpu_freq.current:
                freq_ratio = cpu_freq.current / cpu_freq.max
                if freq_ratio > 0.9:
                    extended_info["power_management_state"] = "performance"
                elif freq_ratio < 0.5:
                    extended_info["power_management_state"] = "power_saver"
                else:
                    extended_info["power_management_state"] = "balanced"

        except ImportError:
            logger.debug("psutil not available; extended CPU info unavailable")
        except Exception as e:
            logger.warning(f"Failed to collect extended CPU info: {e}")

        # GPU driver version (CUDA only)
        try:
            import torch
            if torch.cuda.is_available():
                # Get CUDA driver version
                try:
                    from torch.utils.collect_env import get_nvidia_driver_version
                    driver_version = get_nvidia_driver_version(torch.utils.collect_env.run)
                    if driver_version:
                        extended_info["gpu_driver_version"] = driver_version
                except Exception:
                    # Fallback: use nvidia-smi if available
                    pass
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Could not get GPU driver version: {e}")

        return extended_info

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
