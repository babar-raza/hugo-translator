# Baseline Summary (CUDA)

Date: 2026-01-17
Run Dir: C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\runs\perf_cuda_2026-01-17_12-21

## Command
```
C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\.venv\Scripts\python.exe -m src.cli --site docs.aspose.net --input "C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\runs\perf_cuda_2026-01-17_12-21\baseline_subset" --target-langs fr --device cuda --log-level INFO --log-file "C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\runs\perf_cuda_2026-01-17_12-21\baseline_translate.log" --no-progress --force-restart --config-root "C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\runs\perf_cuda_2026-01-17_12-21\config_override" --batch-size 4
```

## Dataset
- Input: runs/perf_cuda_2026-01-17_12-21/baseline_subset
- Files: 1 (copied from docs.aspose.net slides)
- Segments extracted: 33
- Segments translated: 31

## Throughput
- Duration: 78.52s (directory translation completed)
- Throughput: 0.39 seg/sec (31 / 78.52)

## Model / GPU
- Model: m2m100_418m (default)
- Batch size: 4
- GPU memory limit: 12000 MB (config override)

## Notes
- Used config override to avoid OOM on default settings:
  - docs.aspose.net profile: use_ast_body_reconstruction=false, ast_batch_size=8
  - global.yaml: hardware.max_gpu_memory_mb=12000
- log-file captured only startup NDJSON entries; metrics derived from CLI output.
