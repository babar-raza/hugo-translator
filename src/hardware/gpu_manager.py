"""
GPU Manager - Detection, Configuration, and Memory Management.

Provides comprehensive GPU detection, configuration, and memory management
for CUDA, ROCm, and CPU fallback scenarios.
"""
import json
import logging
import os
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psutil
import torch

logger = logging.getLogger(__name__)


@dataclass
class GPUMemoryInfo:
    """GPU memory information."""

    total_mb: float
    used_mb: float
    free_mb: float
    reserved_mb: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class GPUInfo:
    """Detailed GPU device information."""

    id: int
    name: str
    compute_capability: str
    total_memory_mb: float
    cuda_cores: int | None = None
    driver_version: str | None = None
    pci_bus_id: str | None = None
    temperature: float | None = None
    power_limit: float | None = None
    current_memory: GPUMemoryInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        if self.current_memory:
            data["current_memory"] = self.current_memory.to_dict()
        return data


@dataclass
class GPUCapabilities:
    """System GPU capabilities."""

    has_cuda: bool
    has_rocm: bool
    cuda_version: str | None = None
    cudnn_version: str | None = None
    driver_version: str | None = None
    device_count: int = 0
    devices: list[GPUInfo] = field(default_factory=list)
    recommended_device: str = "cpu"
    cpu_count: int = 0
    total_ram_gb: float = 0.0
    platform: str = ""
    python_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data["devices"] = [d.to_dict() for d in self.devices]
        return data


class GPUManager:
    """
    GPU Manager for detection, configuration, and memory management.

    Handles:
    - GPU detection (CUDA, ROCm)
    - Multi-GPU selection
    - Memory limit enforcement
    - Graceful CPU fallback
    - Real-time monitoring
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize GPU Manager.

        Args:
            config: Optional configuration dict with keys:
                - enable_gpu: bool (default True)
                - max_gpu_memory_mb: int (default None = no limit)
                - gpu_device_id: int (default -1 = auto-select)
                - allow_cpu_fallback: bool (default True)
        """
        self.config = config or {}
        self.enable_gpu = self.config.get("enable_gpu", True)
        self.max_gpu_memory_mb = self.config.get("max_gpu_memory_mb")
        self.gpu_device_id = self.config.get("gpu_device_id", -1)
        self.allow_cpu_fallback = self.config.get("allow_cpu_fallback", True)

        # Cached capabilities
        self._capabilities: GPUCapabilities | None = None

    def detect(self) -> GPUCapabilities:
        """
        Detect GPU capabilities.

        Returns:
            GPUCapabilities with full system information
        """
        # CPU info
        cpu_count = psutil.cpu_count(logical=True) or 0
        total_ram = psutil.virtual_memory().total / (1024**3)  # GB

        # CUDA detection
        has_cuda = torch.cuda.is_available()
        cuda_version = None
        cudnn_version = None
        driver_version = None
        device_count = 0
        devices = []

        if has_cuda:
            cuda_version = torch.version.cuda
            if torch.backends.cudnn.is_available():
                cudnn_version = str(torch.backends.cudnn.version())

            device_count = torch.cuda.device_count()

            # Get driver version via nvidia-smi
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                driver_version = result.stdout.strip().split("\n")[0]
            except (subprocess.SubprocessError, FileNotFoundError, IndexError):
                driver_version = None

            # Get detailed device info
            for i in range(device_count):
                device_info = self._get_device_info(i)
                devices.append(device_info)

        # ROCm detection (basic)
        has_rocm = False
        if not has_cuda and os.environ.get("ROCM_HOME"):
            has_rocm = True

        # Recommend best device
        recommended_device = self._recommend_device(has_cuda, has_rocm, devices)

        capabilities = GPUCapabilities(
            has_cuda=has_cuda,
            has_rocm=has_rocm,
            cuda_version=cuda_version,
            cudnn_version=cudnn_version,
            driver_version=driver_version,
            device_count=device_count,
            devices=devices,
            recommended_device=recommended_device,
            cpu_count=cpu_count,
            total_ram_gb=round(total_ram, 2),
            platform=platform.platform(),
            python_version=platform.python_version(),
        )

        self._capabilities = capabilities
        return capabilities

    def _get_device_info(self, device_id: int) -> GPUInfo:
        """
        Get detailed information for a specific GPU device.

        Args:
            device_id: CUDA device ID

        Returns:
            GPUInfo with device details
        """
        props = torch.cuda.get_device_properties(device_id)

        # Get current memory usage
        memory_info = self.get_gpu_memory(device_id)

        # Try to get additional info from nvidia-smi
        temperature = None
        power_limit = None
        pci_bus_id = None

        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    f"--id={device_id}",
                    "--query-gpu=temperature.gpu,power.limit,pci.bus_id",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            output = result.stdout.strip()
            if output:
                parts = output.split(",")
                if len(parts) >= 1 and parts[0].strip():
                    try:
                        temperature = float(parts[0].strip())
                    except ValueError:
                        pass
                if len(parts) >= 2 and parts[1].strip():
                    try:
                        power_limit = float(parts[1].strip())
                    except ValueError:
                        pass
                if len(parts) >= 3:
                    pci_bus_id = parts[2].strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return GPUInfo(
            id=device_id,
            name=props.name,
            compute_capability=f"{props.major}.{props.minor}",
            total_memory_mb=props.total_memory / (1024**2),
            cuda_cores=None,  # Not directly available from PyTorch
            driver_version=None,  # Retrieved at system level
            pci_bus_id=pci_bus_id,
            temperature=temperature,
            power_limit=power_limit,
            current_memory=memory_info,
        )

    def _recommend_device(
        self, has_cuda: bool, has_rocm: bool, devices: list[GPUInfo]
    ) -> str:
        """
        Recommend best device for inference.

        Args:
            has_cuda: Whether CUDA is available
            has_rocm: Whether ROCm is available
            devices: List of GPU device info

        Returns:
            Recommended device string: "cuda", "cuda:N", "rocm", or "cpu"
        """
        if not self.enable_gpu:
            return "cpu"

        # If specific device requested
        if self.gpu_device_id >= 0 and has_cuda:
            if self.gpu_device_id < len(devices):
                return f"cuda:{self.gpu_device_id}"
            logger.warning(
                f"Requested GPU device {self.gpu_device_id} not found, "
                f"falling back to auto-select"
            )

        # Auto-select best CUDA device
        if has_cuda and devices:
            # Select device with most free memory
            best_device = max(
                devices,
                key=lambda d: d.current_memory.free_mb
                if d.current_memory
                else d.total_memory_mb,
            )

            # Check if device has sufficient memory
            min_memory_mb = 2048  # 2GB minimum
            available_mb = (
                best_device.current_memory.free_mb
                if best_device.current_memory
                else best_device.total_memory_mb
            )

            if available_mb >= min_memory_mb:
                if best_device.id == 0:
                    return "cuda"
                else:
                    return f"cuda:{best_device.id}"

            logger.warning(
                f"Best GPU has only {available_mb:.0f}MB available "
                f"(need {min_memory_mb}MB), falling back to CPU"
            )

        # ROCm fallback
        if has_rocm:
            return "rocm"

        # CPU fallback
        return "cpu"

    def get_gpu_memory(self, device_id: int = 0) -> GPUMemoryInfo | None:
        """
        Get current GPU memory usage.

        Args:
            device_id: CUDA device ID

        Returns:
            GPUMemoryInfo or None if not available
        """
        if not torch.cuda.is_available():
            return None

        try:
            # Get memory stats for specific device
            total = torch.cuda.get_device_properties(device_id).total_memory / (
                1024**2
            )
            reserved = torch.cuda.memory_reserved(device_id) / (1024**2)
            allocated = torch.cuda.memory_allocated(device_id) / (1024**2)
            free = total - allocated

            return GPUMemoryInfo(
                total_mb=total,
                used_mb=allocated,
                free_mb=free,
                reserved_mb=reserved,
            )
        except Exception as e:
            logger.error(f"Failed to get GPU memory info: {e}")
            return None

    def get_all_gpu_memory(self) -> dict[int, GPUMemoryInfo]:
        """
        Get memory info for all available GPUs.

        Returns:
            Dict mapping device_id to GPUMemoryInfo
        """
        memory_info = {}
        if not torch.cuda.is_available():
            return memory_info

        for i in range(torch.cuda.device_count()):
            mem = self.get_gpu_memory(i)
            if mem:
                memory_info[i] = mem

        return memory_info

    def enforce_memory_limit(self, device: str) -> bool:
        """
        Enforce GPU memory limit if configured.

        Args:
            device: Device string (e.g., "cuda", "cuda:0")

        Returns:
            True if limit set successfully, False otherwise
        """
        if not self.max_gpu_memory_mb:
            return False

        if not device.startswith("cuda"):
            return False

        try:
            # Extract device ID
            device_id = 0
            if ":" in device:
                device_id = int(device.split(":")[1])

            # Set memory fraction
            total_memory = torch.cuda.get_device_properties(
                device_id
            ).total_memory / (1024**2)
            fraction = min(1.0, self.max_gpu_memory_mb / total_memory)

            torch.cuda.set_per_process_memory_fraction(fraction, device_id)
            logger.info(
                f"Set GPU memory limit: {self.max_gpu_memory_mb}MB "
                f"(fraction: {fraction:.2f}) on device {device_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to enforce memory limit: {e}")
            return False

    def clear_cache(self, device: str | None = None) -> None:
        """
        Clear GPU memory cache.

        Args:
            device: Optional device string, clears all if None
        """
        if not torch.cuda.is_available():
            return

        try:
            if device and ":" in device:
                device_id = int(device.split(":")[1])
                with torch.cuda.device(device_id):
                    torch.cuda.empty_cache()
                logger.debug(f"Cleared GPU cache for device {device_id}")
            else:
                torch.cuda.empty_cache()
                logger.debug("Cleared GPU cache for all devices")
        except Exception as e:
            logger.error(f"Failed to clear GPU cache: {e}")

    def get_recommended_device(self, force_detect: bool = False) -> str:
        """
        Get recommended device for inference.

        Args:
            force_detect: Force re-detection even if cached

        Returns:
            Device string: "cuda", "cuda:N", or "cpu"
        """
        if force_detect or self._capabilities is None:
            self.detect()

        return self._capabilities.recommended_device if self._capabilities else "cpu"

    def get_capabilities(self) -> GPUCapabilities | None:
        """
        Get cached GPU capabilities.

        Returns:
            GPUCapabilities or None if not yet detected
        """
        return self._capabilities

    def validate_device(self, device: str) -> bool:
        """
        Validate if a device string is available.

        Args:
            device: Device string to validate

        Returns:
            True if device is available, False otherwise
        """
        if device == "cpu":
            return True

        if device.startswith("cuda"):
            if not torch.cuda.is_available():
                return False

            # Check specific device ID
            if ":" in device:
                try:
                    device_id = int(device.split(":")[1])
                    return device_id < torch.cuda.device_count()
                except (ValueError, IndexError):
                    return False

            return True

        return False

    def auto_select_device(self) -> str:
        """
        Auto-select best available device.

        Returns:
            Device string
        """
        caps = self.detect()
        device = caps.recommended_device

        # Enforce memory limits if GPU selected
        if device.startswith("cuda"):
            self.enforce_memory_limit(device)

        return device

    def generate_report(self, output_path: Path | None = None) -> str:
        """
        Generate detailed GPU capabilities report.

        Args:
            output_path: Optional path to save report

        Returns:
            Report content as string
        """
        caps = self.detect()

        lines = []
        lines.append("# GPU Capabilities Report")
        lines.append("")
        lines.append(f"**Generated:** {platform.node()} - {caps.platform}")
        lines.append(f"**Python:** {caps.python_version}")
        lines.append("")

        # System info
        lines.append("## System Information")
        lines.append("")
        lines.append(f"- CPU Cores: {caps.cpu_count}")
        lines.append(f"- Total RAM: {caps.total_ram_gb:.2f} GB")
        lines.append(f"- Recommended Device: `{caps.recommended_device}`")
        lines.append("")

        # GPU info
        lines.append("## GPU Detection")
        lines.append("")
        lines.append(f"- CUDA Available: {'✓' if caps.has_cuda else '✗'}")
        lines.append(f"- ROCm Available: {'✓' if caps.has_rocm else '✗'}")

        if caps.has_cuda:
            lines.append(f"- CUDA Version: {caps.cuda_version or 'Unknown'}")
            lines.append(f"- cuDNN Version: {caps.cudnn_version or 'N/A'}")
            lines.append(f"- Driver Version: {caps.driver_version or 'Unknown'}")
            lines.append(f"- Device Count: {caps.device_count}")
            lines.append("")

            # Device details
            if caps.devices:
                lines.append("## GPU Devices")
                lines.append("")

                for device in caps.devices:
                    lines.append(f"### Device {device.id}: {device.name}")
                    lines.append("")
                    lines.append(
                        f"- Compute Capability: {device.compute_capability}"
                    )
                    lines.append(
                        f"- Total Memory: {device.total_memory_mb:.0f} MB "
                        f"({device.total_memory_mb / 1024:.2f} GB)"
                    )

                    if device.current_memory:
                        mem = device.current_memory
                        lines.append(
                            f"- Used Memory: {mem.used_mb:.0f} MB "
                            f"({mem.used_mb / mem.total_mb * 100:.1f}%)"
                        )
                        lines.append(f"- Free Memory: {mem.free_mb:.0f} MB")
                        lines.append(f"- Reserved Memory: {mem.reserved_mb:.0f} MB")

                    if device.temperature is not None:
                        lines.append(f"- Temperature: {device.temperature}°C")
                    if device.power_limit is not None:
                        lines.append(f"- Power Limit: {device.power_limit}W")
                    if device.pci_bus_id:
                        lines.append(f"- PCI Bus ID: {device.pci_bus_id}")

                    lines.append("")
        else:
            lines.append("")
            lines.append("No CUDA GPUs detected. Running in CPU mode.")
            lines.append("")

        # Configuration
        lines.append("## Configuration")
        lines.append("")
        lines.append(f"- GPU Enabled: {self.enable_gpu}")
        lines.append(
            f"- Max GPU Memory: "
            f"{self.max_gpu_memory_mb or 'Unlimited'} "
            f"{'MB' if self.max_gpu_memory_mb else ''}"
        )
        lines.append(
            f"- GPU Device ID: "
            f"{self.gpu_device_id if self.gpu_device_id >= 0 else 'Auto-select'}"
        )
        lines.append(f"- CPU Fallback: {self.allow_cpu_fallback}")
        lines.append("")

        # Recommendations
        lines.append("## Recommendations")
        lines.append("")

        if caps.has_cuda and caps.devices:
            best_device = max(
                caps.devices,
                key=lambda d: d.total_memory_mb,
            )
            lines.append(
                f"- Use device `cuda:{best_device.id}` with "
                f"{best_device.total_memory_mb / 1024:.1f} GB VRAM"
            )

            if best_device.total_memory_mb < 4096:
                lines.append(
                    "- Consider using CTranslate2 or quantized models for "
                    "better memory efficiency"
                )
            elif best_device.total_memory_mb >= 8192:
                lines.append(
                    "- Sufficient VRAM for large models and batch processing"
                )

            if self.max_gpu_memory_mb:
                lines.append(
                    f"- Memory limit set to {self.max_gpu_memory_mb}MB prevents OOM"
                )
            else:
                lines.append(
                    "- Consider setting max_gpu_memory_mb to prevent OOM errors"
                )
        else:
            lines.append("- CPU-only mode - consider using CTranslate2 for optimization")
            lines.append(
                f"- With {caps.cpu_count} cores, "
                f"parallel processing can still be effective"
            )

        lines.append("")

        report = "\n".join(lines)

        # Save if path provided
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")
            logger.info(f"GPU report saved to {output_path}")

        return report


def main():
    """CLI entry point for GPU detection."""
    import argparse

    parser = argparse.ArgumentParser(description="GPU Detection and Configuration")
    parser.add_argument(
        "--detect",
        action="store_true",
        help="Detect and display GPU capabilities",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    parser.add_argument(
        "--report",
        type=str,
        help="Generate markdown report to file",
    )
    parser.add_argument(
        "--max-memory",
        type=int,
        help="Maximum GPU memory in MB",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create manager
    config = {}
    if args.max_memory:
        config["max_gpu_memory_mb"] = args.max_memory

    manager = GPUManager(config)

    if args.detect or args.json or args.report:
        caps = manager.detect()

        if args.json:
            print(json.dumps(caps.to_dict(), indent=2))
        elif args.report:
            report = manager.generate_report(Path(args.report))
            print(f"Report saved to: {args.report}")
        else:
            # Human-readable output
            print("\n" + "=" * 60)
            print("GPU CAPABILITIES DETECTION")
            print("=" * 60 + "\n")

            print(f"CUDA Available: {caps.has_cuda}")
            if caps.has_cuda:
                print(f"CUDA Version: {caps.cuda_version}")
                print(f"Device Count: {caps.device_count}")
                print(f"Driver Version: {caps.driver_version}\n")

                for device in caps.devices:
                    print(f"Device {device.id}: {device.name}")
                    print(
                        f"  Memory: {device.total_memory_mb:.0f} MB "
                        f"({device.total_memory_mb / 1024:.2f} GB)"
                    )
                    print(f"  Compute Capability: {device.compute_capability}")
                    if device.current_memory:
                        mem = device.current_memory
                        print(
                            f"  Free: {mem.free_mb:.0f} MB, "
                            f"Used: {mem.used_mb:.0f} MB"
                        )
                    print()

            print(f"Recommended Device: {caps.recommended_device}")
            print(f"CPU Cores: {caps.cpu_count}")
            print(f"Total RAM: {caps.total_ram_gb:.2f} GB")
            print()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
