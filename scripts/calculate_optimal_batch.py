#!/usr/bin/env python3
"""
Calculate optimal batch size for GPU translation based on available VRAM.
Target: 85% VRAM utilization

Usage:
    python scripts/calculate_optimal_batch.py --model facebook/nllb-200-3.3B --precision fp16
"""

import argparse
import torch
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.hardware.gpu_manager import GPUManager


# VRAM requirements per batch item (empirical estimates in MB)
VRAM_PER_ITEM = {
    # Model size: {precision: MB per batch item}
    "600M": {"fp32": 50, "fp16": 25, "int8": 15},
    "1.3B": {"fp32": 80, "fp16": 40, "int8": 20},
    "3.3B": {"fp32": 150, "fp16": 75, "int8": 35},
}

# Model base memory (loaded model weights + buffers)
MODEL_BASE_VRAM = {
    "600M": {"fp32": 2400, "fp16": 1200, "int8": 600},
    "1.3B": {"fp32": 5200, "fp16": 2600, "int8": 1300},
    "3.3B": {"fp32": 13200, "fp16": 6600, "int8": 3300},
}

# Reserve memory for CUDA overhead
CUDA_RESERVED_MB = 500


def extract_model_size(model_name: str) -> str:
    """Extract model size from model name."""
    if "600M" in model_name or "distilled-600M" in model_name:
        return "600M"
    elif "1.3B" in model_name:
        return "1.3B"
    elif "3.3B" in model_name:
        return "3.3B"
    else:
        # Default to 3.3B for unknown models (conservative)
        return "3.3B"


def calculate_optimal_batch_size(
    total_vram_mb: float,
    model_size: str,
    precision: str,
    target_utilization: float = 0.85,
    min_batch: int = 1,
    max_batch: int = 64,
) -> dict:
    """
    Calculate optimal batch size to target specific VRAM utilization.

    Args:
        total_vram_mb: Total available VRAM in MB
        model_size: Model size (600M, 1.3B, 3.3B)
        precision: Loading precision (fp32, fp16, int8)
        target_utilization: Target VRAM utilization (default 0.85 = 85%)
        min_batch: Minimum batch size
        max_batch: Maximum batch size

    Returns:
        dict with batch_size, estimated_vram_mb, utilization_percent
    """

    # Get model parameters
    base_vram = MODEL_BASE_VRAM[model_size][precision]
    vram_per_item = VRAM_PER_ITEM[model_size][precision]

    # Calculate available VRAM for batching
    target_vram = total_vram_mb * target_utilization
    available_for_batch = target_vram - base_vram - CUDA_RESERVED_MB

    if available_for_batch <= 0:
        return {
            "batch_size": min_batch,
            "estimated_vram_mb": base_vram + CUDA_RESERVED_MB + (vram_per_item * min_batch),
            "utilization_percent": ((base_vram + CUDA_RESERVED_MB + (vram_per_item * min_batch)) / total_vram_mb) * 100,
            "warning": f"Model base VRAM ({base_vram}MB) + reserved ({CUDA_RESERVED_MB}MB) exceeds target. Using minimum batch size.",
        }

    # Calculate batch size
    optimal_batch = int(available_for_batch / vram_per_item)

    # Apply bounds
    batch_size = max(min_batch, min(optimal_batch, max_batch))

    # Calculate actual estimated usage
    estimated_vram = base_vram + CUDA_RESERVED_MB + (vram_per_item * batch_size)
    utilization = (estimated_vram / total_vram_mb) * 100

    return {
        "batch_size": batch_size,
        "estimated_vram_mb": estimated_vram,
        "utilization_percent": utilization,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Calculate optimal batch size for GPU translation"
    )
    parser.add_argument(
        "--model",
        default="facebook/nllb-200-3.3B",
        help="Model name or path",
    )
    parser.add_argument(
        "--precision",
        choices=["fp32", "fp16", "int8"],
        default="fp16",
        help="Model loading precision (default: fp16)",
    )
    parser.add_argument(
        "--target-utilization",
        type=float,
        default=0.85,
        help="Target VRAM utilization as decimal (default: 0.85 = 85%%)",
    )
    parser.add_argument(
        "--min-batch",
        type=int,
        default=1,
        help="Minimum batch size (default: 1)",
    )
    parser.add_argument(
        "--max-batch",
        type=int,
        default=64,
        help="Maximum batch size (default: 64)",
    )
    parser.add_argument(
        "--gpu-id",
        type=int,
        default=0,
        help="GPU device ID (default: 0)",
    )

    args = parser.parse_args()

    # Extract model size
    model_size = extract_model_size(args.model)

    # Get GPU memory info
    if not torch.cuda.is_available():
        print("ERROR: No CUDA-capable GPU detected", file=sys.stderr)
        sys.exit(1)

    gpu_manager = GPUManager()
    gpu_info = gpu_manager.get_gpu_memory(args.gpu_id)

    if gpu_info is None:
        print(f"ERROR: Could not access GPU {args.gpu_id}", file=sys.stderr)
        sys.exit(1)

    total_vram_mb = gpu_info.total_mb
    free_vram_mb = gpu_info.free_mb

    print(f"\n{'='*70}")
    print(f"GPU VRAM Analysis (Device {args.gpu_id})")
    print(f"{'='*70}")
    print(f"Total VRAM:      {total_vram_mb:,.0f} MB ({total_vram_mb/1024:.1f} GB)")
    print(f"Currently Free:  {free_vram_mb:,.0f} MB ({free_vram_mb/1024:.1f} GB)")
    print(f"Currently Used:  {gpu_info.used_mb:,.0f} MB ({gpu_info.used_mb/1024:.1f} GB)")
    print(f"\nModel:           {args.model}")
    print(f"Model Size:      {model_size}")
    print(f"Precision:       {args.precision}")
    print(f"Target Util:     {args.target_utilization*100:.0f}%")
    print(f"{'='*70}\n")

    # Calculate optimal batch size
    result = calculate_optimal_batch_size(
        total_vram_mb=total_vram_mb,
        model_size=model_size,
        precision=args.precision,
        target_utilization=args.target_utilization,
        min_batch=args.min_batch,
        max_batch=args.max_batch,
    )

    # Display results
    print(f"RECOMMENDED BATCH SIZE: {result['batch_size']}")
    print(f"\nEstimated VRAM Usage:")
    print(f"  - Base Model:    {MODEL_BASE_VRAM[model_size][args.precision]:,.0f} MB")
    print(f"  - CUDA Reserved: {CUDA_RESERVED_MB:,.0f} MB")
    print(f"  - Batch Data:    {VRAM_PER_ITEM[model_size][args.precision] * result['batch_size']:,.0f} MB "
          f"({result['batch_size']} items × {VRAM_PER_ITEM[model_size][args.precision]} MB)")
    print(f"  - Total:         {result['estimated_vram_mb']:,.0f} MB ({result['estimated_vram_mb']/1024:.1f} GB)")
    print(f"\nEstimated Utilization: {result['utilization_percent']:.1f}%")

    if "warning" in result:
        print(f"\n⚠️  WARNING: {result['warning']}")

    # Generate command example
    print(f"\n{'='*70}")
    print("Example Command:")
    print(f"{'='*70}")

    # Determine load_mode from precision
    load_mode_map = {"fp32": "fp32", "fp16": "fp16", "int8": "int8"}
    load_mode = load_mode_map.get(args.precision, "fp16")

    print(f"\npython -m src.cli \\")
    print(f"  --site kb.aspose.net \\")
    print(f'  --input "D:\\onedrive\\Documents\\GitHub\\aspose.net\\content\\kb.aspose.net\\slides\\en" \\')
    print(f"  --target-langs ar bg cs da de el es et fa fi fr he hi hr hu id it ja ko lt lv nl pl pt ro ru sk sl sr sv th tr uk vi zh \\")
    print(f"  --enable-terminology \\")
    print(f"  --terminology-mode both \\")
    print(f"  --load-mode {load_mode} \\")
    print(f"  --batch-size {result['batch_size']} \\")
    print(f"  --sort-segments-by-length")
    print()

    # Additional recommendations
    print(f"{'='*70}")
    print("Recommendations:")
    print(f"{'='*70}")
    print("1. Monitor actual VRAM during first few batches")
    print("2. If you see OOM errors, reduce batch size by 20-30%")
    print("3. If utilization is much lower than expected, you can increase batch size")
    print("4. Use --sort-segments-by-length for more efficient batching")
    print("5. Consider --enable-terminology-dedup to reduce memory usage")
    print()


if __name__ == "__main__":
    main()
