"""
Hardware detection for translation model runtime optimization.

Detects CPU, GPU (CUDA), and Apple Silicon (MPS) capabilities.
"""
import platform
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

import torch


@dataclass
class HardwareInfo:
    """Hardware capability information."""

    cpu_count: int
    total_ram_gb: float
    has_cuda: bool
    cuda_devices: List[Dict[str, Any]] = field(default_factory=list)
    has_mps: bool = False
    recommended_device: str = "cpu"
    platform: str = ""
    python_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "cpu_count": self.cpu_count,
            "total_ram_gb": self.total_ram_gb,
            "has_cuda": self.has_cuda,
            "cuda_devices": self.cuda_devices,
            "has_mps": self.has_mps,
            "recommended_device": self.recommended_device,
            "platform": self.platform,
            "python_version": self.python_version,
        }


class HardwareDetector:
    """
    Detect and analyze hardware capabilities.

    Provides recommendations for model device placement.
    """

    def detect(self) -> HardwareInfo:
        """
        Detect current hardware capabilities.

        Returns:
            HardwareInfo with detected capabilities
        """
        # CPU and RAM
        if HAS_PSUTIL:
            cpu_count = psutil.cpu_count(logical=True)
            total_ram = psutil.virtual_memory().total / (1024**3)  # GB
        else:
            # Fallback if psutil not available
            import os
            cpu_count = os.cpu_count() or 4  # Fallback to 4 if unknown
            total_ram = 16.0  # Assume 16GB as safe fallback

        # CUDA detection
        has_cuda = torch.cuda.is_available()
        cuda_devices = []

        if has_cuda:
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                device_info = {
                    "id": i,
                    "name": props.name,
                    "total_memory_gb": props.total_memory / (1024**3),
                    "compute_capability": f"{props.major}.{props.minor}",
                }
                cuda_devices.append(device_info)

        # Apple MPS detection
        has_mps = (
            torch.backends.mps.is_available() if hasattr(torch.backends, "mps") else False
        )

        # Determine recommended device
        recommended_device = self._recommend_device(
            has_cuda=has_cuda,
            has_mps=has_mps,
            cuda_devices=cuda_devices,
        )

        return HardwareInfo(
            cpu_count=cpu_count,
            total_ram_gb=round(total_ram, 2),
            has_cuda=has_cuda,
            cuda_devices=cuda_devices,
            has_mps=has_mps,
            recommended_device=recommended_device,
            platform=platform.platform(),
            python_version=platform.python_version(),
        )

    def _recommend_device(
        self,
        has_cuda: bool,
        has_mps: bool,
        cuda_devices: List[Dict[str, Any]],
    ) -> str:
        """
        Recommend best device for model inference.

        Args:
            has_cuda: Whether CUDA is available
            has_mps: Whether Apple MPS is available
            cuda_devices: List of CUDA device info

        Returns:
            Recommended device string: "cuda", "mps", or "cpu"
        """
        # Prefer CUDA if available with sufficient VRAM
        if has_cuda and cuda_devices:
            # Check if primary GPU has at least 2GB VRAM
            if cuda_devices[0]["total_memory_gb"] >= 2.0:
                return "cuda"

        # Fall back to MPS on Apple Silicon
        if has_mps:
            return "mps"

        # Default to CPU
        return "cpu"

    def benchmark_device(
        self,
        device: str,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        num_iterations: int = 10,
    ) -> Dict[str, float]:
        """
        Benchmark model inference speed on device.

        Args:
            device: Device to benchmark ("cuda", "mps", or "cpu")
            model_name: Model to use for benchmarking
            num_iterations: Number of iterations to average

        Returns:
            Dict with benchmark results (samples_per_sec, avg_time_ms)
        """
        import time

        from sentence_transformers import SentenceTransformer

        # Load model to specified device
        try:
            model = SentenceTransformer(model_name, device=device)
        except Exception as e:
            return {
                "error": str(e),
                "samples_per_sec": 0.0,
                "avg_time_ms": 0.0,
            }

        # Sample texts for benchmarking
        texts = [
            "This is a sample sentence for benchmarking.",
            "Another example text to measure performance.",
            "Hardware detection and model inference speed test.",
        ]

        # Warmup
        model.encode(texts, show_progress_bar=False)

        # Benchmark
        times = []
        for _ in range(num_iterations):
            start = time.perf_counter()
            model.encode(texts, show_progress_bar=False)
            end = time.perf_counter()
            times.append(end - start)

        avg_time = sum(times) / len(times)
        samples_per_sec = len(texts) / avg_time

        return {
            "device": device,
            "model": model_name,
            "samples_per_sec": round(samples_per_sec, 2),
            "avg_time_ms": round(avg_time * 1000, 2),
            "num_iterations": num_iterations,
        }

    def get_recommendations(self, hardware: HardwareInfo) -> Dict[str, Any]:
        """
        Get hardware-specific recommendations.

        Args:
            hardware: HardwareInfo object

        Returns:
            Dict with recommendations
        """
        recommendations = {
            "device": hardware.recommended_device,
            "warnings": [],
            "suggestions": [],
        }

        # RAM warnings
        if hardware.total_ram_gb < 4:
            recommendations["warnings"].append(
                "Low RAM (<4GB). Consider using quantized models or CTranslate2."
            )
        elif hardware.total_ram_gb < 8:
            recommendations["warnings"].append(
                "Moderate RAM (<8GB). Small to medium models recommended."
            )

        # CUDA recommendations
        if hardware.has_cuda:
            if hardware.cuda_devices:
                vram = hardware.cuda_devices[0]["total_memory_gb"]
                if vram < 4:
                    recommendations["warnings"].append(
                        f"Limited VRAM ({vram:.1f}GB). Use small models or CPU."
                    )
                elif vram >= 8:
                    recommendations["suggestions"].append(
                        f"Good VRAM ({vram:.1f}GB). Can run large models on GPU."
                    )
        else:
            if hardware.has_mps:
                recommendations["suggestions"].append(
                    "Apple Silicon detected. MPS acceleration available."
                )
            else:
                recommendations["suggestions"].append(
                    "No GPU detected. Consider CTranslate2 for CPU optimization."
                )

        # CPU recommendations
        if hardware.cpu_count < 4:
            recommendations["warnings"].append(
                f"Limited CPU cores ({hardware.cpu_count}). Performance may be slow."
            )
        elif hardware.cpu_count >= 8:
            recommendations["suggestions"].append(
                f"Good CPU ({hardware.cpu_count} cores). CPU inference viable."
            )

        return recommendations
