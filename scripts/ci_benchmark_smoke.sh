#!/bin/bash
# CI Benchmark Smoke Test
# Purpose: Fast regression check for translation model performance
# Duration: <2 minutes (target)
# Usage: ./scripts/ci_benchmark_smoke.sh [--db PATH]
#
# Exit Codes:
#   0 - Success (performance within acceptable range)
#   1 - Failure (performance regression detected or script error)
#   2 - Skip (dependencies not available)

set -e

# Configuration
DEFAULT_DB_PATH="/tmp/ci_smoke_benchmark.db"
THROUGHPUT_THRESHOLD=5.0  # Minimum tokens/sec for pass
MAX_SAMPLES=5  # Keep test fast
MODEL_ID="m2m100_418m"  # Smallest model for speed
DEVICE="cpu"  # CI runners typically don't have GPU
BATCH_SIZE=4

# Parse arguments
DB_PATH="$DEFAULT_DB_PATH"
while [[ $# -gt 0 ]]; do
  case $1 in
    --db)
      DB_PATH="$2"
      shift 2
      ;;
    --threshold)
      THROUGHPUT_THRESHOLD="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 [--db PATH] [--threshold FLOAT]"
      echo ""
      echo "Options:"
      echo "  --db PATH          Database path (default: /tmp/ci_smoke_benchmark.db)"
      echo "  --threshold FLOAT  Minimum throughput tokens/sec (default: 5.0)"
      echo "  --help             Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "========================================"
echo "CI Benchmark Smoke Test"
echo "========================================"
echo "Model: $MODEL_ID"
echo "Device: $DEVICE"
echo "Samples: $MAX_SAMPLES"
echo "Threshold: $THROUGHPUT_THRESHOLD tokens/sec"
echo "DB Path: $DB_PATH"
echo ""

# Check if benchmarking module is available
if ! python -c "import src.benchmarking.storage" 2>/dev/null; then
  echo "SKIP: Benchmarking module not available (dependencies not installed)"
  exit 2
fi

# Check if model exists
if ! python -c "from pathlib import Path; from src.model_runtime.registry import ModelRegistry; reg = ModelRegistry(Path('config/model_registry.yaml')); assert '$MODEL_ID' in reg.models" 2>/dev/null; then
  echo "SKIP: Model $MODEL_ID not found in registry"
  exit 2
fi

# Run minimal benchmark
echo "Running benchmark..."
if ! python scripts/benchmark_cpu_comprehensive.py \
  --models "$MODEL_ID" \
  --batch-sizes "$BATCH_SIZE" \
  --iterations 1 \
  --save-to-db "$DB_PATH" \
  --corpus tiny \
  --max-samples "$MAX_SAMPLES" \
  2>&1 | tee /tmp/benchmark_output.txt; then
  echo ""
  echo "FAIL: Benchmark script failed"
  cat /tmp/benchmark_output.txt
  exit 1
fi

echo ""
echo "Analyzing results..."

# Extract throughput from database
THROUGHPUT=$(python -c "
from src.benchmarking.storage import BenchmarkDatabase
try:
    db = BenchmarkDatabase('$DB_PATH')
    runs = db.list_runs(limit=1)
    if not runs:
        print('0')
    else:
        run = db.get_run(runs[0][0])
        if not run.results:
            print('0')
        else:
            avg = sum(r.throughput_tokens_per_sec for r in run.results) / len(run.results)
            print(f'{avg:.2f}')
except Exception as e:
    print(f'ERROR: {e}', file=__import__('sys').stderr)
    print('0')
" 2>&1)

# Check if throughput extraction succeeded
if [[ "$THROUGHPUT" == "ERROR:"* ]] || [[ "$THROUGHPUT" == "0" ]]; then
  echo "FAIL: Could not extract throughput from database"
  echo "Output: $THROUGHPUT"
  exit 1
fi

echo "Throughput: $THROUGHPUT tokens/sec"
echo "Threshold: $THROUGHPUT_THRESHOLD tokens/sec"

# Compare throughput to threshold using bc (if available) or awk
if command -v bc &> /dev/null; then
  if (( $(echo "$THROUGHPUT < $THROUGHPUT_THRESHOLD" | bc -l) )); then
    echo ""
    echo "FAIL: Throughput $THROUGHPUT below threshold $THROUGHPUT_THRESHOLD"
    echo "Performance regression detected!"
    exit 1
  fi
else
  # Fallback to awk if bc not available
  if awk "BEGIN {exit !($THROUGHPUT < $THROUGHPUT_THRESHOLD)}"; then
    echo ""
    echo "FAIL: Throughput $THROUGHPUT below threshold $THROUGHPUT_THRESHOLD"
    echo "Performance regression detected!"
    exit 1
  fi
fi

echo ""
echo "========================================"
echo "PASS: Smoke test completed successfully"
echo "========================================"
echo "Performance: $THROUGHPUT tokens/sec (>${THROUGHPUT_THRESHOLD} required)"

# Cleanup temporary database (keep if explicitly specified)
if [[ "$DB_PATH" == "/tmp/"* ]]; then
  rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
fi

exit 0
