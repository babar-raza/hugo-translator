"""
Run GPU Pipeline with Monitoring.

Demonstrates end-to-end translation pipeline with GPU monitoring.
"""
import argparse
import logging
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import torch

from src.hardware.gpu_manager import GPUManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def monitor_gpu(gpu_manager: GPUManager, stage: str):
    """Monitor and log GPU status."""
    if torch.cuda.is_available():
        mem = gpu_manager.get_gpu_memory(0)
        if mem:
            logger.info(
                f"[{stage}] GPU Memory: "
                f"{mem.used_mb:.0f}MB used, "
                f"{mem.free_mb:.0f}MB free "
                f"({mem.used_mb/mem.total_mb*100:.1f}% utilization)"
            )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run GPU Translation Pipeline")
    parser.add_argument(
        "--input",
        type=str,
        help="Input directory or file",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Use GPU acceleration",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Monitor GPU memory usage",
    )
    parser.add_argument(
        "--max-memory",
        type=int,
        default=6144,
        help="Maximum GPU memory in MB",
    )

    args = parser.parse_args()

    # Initialize GPU manager
    config = {
        "enable_gpu": args.gpu,
        "max_gpu_memory_mb": args.max_memory if args.gpu else None,
    }
    gpu_manager = GPUManager(config)

    logger.info("=" * 70)
    logger.info("GPU TRANSLATION PIPELINE")
    logger.info("=" * 70)

    # Detect GPU
    caps = gpu_manager.detect()
    logger.info("\nGPU Detection:")
    logger.info(f"  CUDA Available: {caps.has_cuda}")
    if caps.has_cuda:
        logger.info(f"  Device Count: {caps.device_count}")
        logger.info(f"  Recommended Device: {caps.recommended_device}")
        for device in caps.devices:
            logger.info(f"  Device {device.id}: {device.name} ({device.total_memory_mb:.0f}MB)")

    if args.monitor:
        monitor_gpu(gpu_manager, "Initial")

    # Select device
    device = gpu_manager.auto_select_device()
    logger.info(f"\nUsing device: {device}")

    # Demo pipeline stages
    logger.info("\n" + "=" * 70)
    logger.info("PIPELINE STAGES")
    logger.info("=" * 70)

    # Stage 1: Parse
    logger.info("\n[Stage 1] Parsing input files...")
    time.sleep(0.5)
    if args.monitor:
        monitor_gpu(gpu_manager, "After Parsing")

    # Stage 2: TM Lookup (L3 Semantic)
    logger.info("\n[Stage 2] TM lookup with semantic search...")
    logger.info("  Using GPU-accelerated embeddings" if args.gpu else "  Using CPU embeddings")
    time.sleep(0.5)
    if args.monitor:
        monitor_gpu(gpu_manager, "After TM Lookup")

    # Stage 3: Translation
    logger.info("\n[Stage 3] Translating segments...")
    logger.info(f"  Using {device} for translation")
    time.sleep(0.5)
    if args.monitor:
        monitor_gpu(gpu_manager, "After Translation")

    # Stage 4: Reconstruction
    logger.info("\n[Stage 4] Reconstructing output...")
    time.sleep(0.5)
    if args.monitor:
        monitor_gpu(gpu_manager, "After Reconstruction")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 70)

    if args.monitor and torch.cuda.is_available():
        final_mem = gpu_manager.get_gpu_memory(0)
        if final_mem:
            logger.info(f"\nFinal GPU Memory: {final_mem.used_mb:.0f}MB used")

    logger.info("\nTo run actual translation:")
    logger.info("  1. Place markdown files in samples/ directory")
    logger.info("  2. Configure config/sites/your-site.yaml")
    logger.info("  3. Run: python -m src.cli translate --site your-site")

    return 0


if __name__ == "__main__":
    exit(main())
