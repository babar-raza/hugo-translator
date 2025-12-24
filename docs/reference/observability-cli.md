# CLI Observability: Progress Tracking & Metrics

Hugo Translator includes production-grade progress tracking and real-time metrics for monitoring translation jobs.

## Features

- **Real-time progress updates** with ETA calculation
- **Rolling throughput** using exponential moving average (EMA)
- **Cache hit rate** tracking (L1/L2/L3)
- **Two-terminal support** for separate logs and metrics views
- **Metrics file output** (JSON snapshot + NDJSON stream)
- **Windows-compatible** terminal utilities

## CLI Flags

### `--metrics-file <PATH>`

Write metrics to file. Creates two files:
- `<PATH>_current.json` - Overwritten snapshot (latest state)
- `<PATH>.ndjson` - Append-only stream (one JSON object per line)

```powershell
python -m src.cli --site mysite --metrics-file ./metrics
```

### `--metrics-interval <SECS>`

Metrics update interval in seconds (default: 2.0).

```powershell
python -m src.cli --site mysite --metrics-interval 1.0
```

### `--metrics-only`

Suppress normal logs, emit only compact metrics line. Useful for a dedicated metrics terminal.

```powershell
python -m src.cli --site mysite --metrics-only
```

### `--no-progress`

Disable progress tracking and ETA display entirely.

```powershell
python -m src.cli --site mysite --no-progress
```

## Two-Terminal Setup

Run translation with verbose logs in one terminal while monitoring metrics in another.

### Windows PowerShell

**Terminal A** - Run translation with metrics enabled:
```powershell
python -m src.cli --site mysite --input ./content --metrics-file ./metrics --log-level INFO
```

**Terminal B** - Follow metrics stream (compact mode):
```powershell
python -m src.observability.metrics_tail ./metrics.ndjson --compact
```

Or for detailed output:
```powershell
python -m src.observability.metrics_tail ./metrics.ndjson
```

### Unix/Linux/macOS

**Terminal A** - Run translation:
```bash
python -m src.cli --site mysite --input ./content --metrics-file ./metrics
```

**Terminal B** - Tail metrics stream:
```bash
tail -f ./metrics.ndjson | jq .
```

Or use the Python utility:
```bash
python -m src.observability.metrics_tail ./metrics.ndjson --compact
```

## Metrics Reference

### Overall Progress

| Field | Description |
|-------|-------------|
| `percent_complete_files` | Percentage of files completed |
| `percent_complete_segments` | Percentage of segments completed |
| `elapsed_s` | Time elapsed in seconds |
| `eta_s` | Estimated time remaining in seconds |
| `eta_formatted` | Human-readable ETA (e.g., "2m 30s") |

### Files

| Field | Description |
|-------|-------------|
| `files.total` | Total files to process |
| `files.done` | Successfully completed files |
| `files.failed` | Files that failed translation |
| `files.skipped` | Files skipped (already translated, etc.) |
| `files.current` | Currently processing file name |

### Segments

| Field | Description |
|-------|-------------|
| `segments.total` | Total segments to translate |
| `segments.done` | Segments completed |
| `segments.failed` | Segments that failed |

### Batches

| Field | Description |
|-------|-------------|
| `batches.total` | Total batches planned |
| `batches.done` | Batches completed |
| `batches.current_size` | Current batch size |

### Performance

| Field | Description |
|-------|-------------|
| `segments_per_sec_rolling` | Rolling throughput (EMA smoothed) |
| `segments_per_sec_lifetime` | Overall throughput since start |
| `files_per_min` | Files completed per minute |
| `avg_segment_ms` | Average milliseconds per segment |
| `avg_batch_s` | Average seconds per batch |

### Cache

| Field | Description |
|-------|-------------|
| `cache.hits` | Total cache hits (all layers) |
| `cache.misses` | Cache misses (required model translation) |
| `cache.hit_rate` | Hit rate (0.0 to 1.0) |
| `cache.l1_hits` | L1 in-memory cache hits |
| `cache.l2_hits` | L2 persistent (LMDB) hits |
| `cache.l3_hits` | L3 semantic search hits |

### Translation

| Field | Description |
|-------|-------------|
| `translation.model` | Model name/ID being used |
| `translation.device` | Device (cpu, cuda) |
| `translation.tokens_in` | Input tokens processed |
| `translation.tokens_out` | Output tokens generated |
| `translation.retries` | Retry attempts made |

### Errors

| Field | Description |
|-------|-------------|
| `errors.count` | Total error count |
| `errors.last_error` | Most recent error message |
| `errors.last_failed_file` | Most recently failed file |
| `errors.by_type` | Error counts by type |

## Example Metrics Output

### Compact Line (--metrics-only)

```
[45.2%] files=12/25 segs=452/1000 rate=8.5/s cache=67% ETA=1m 5s err=0
```

### JSON Snapshot

```json
{
  "timestamp": 1703356800.123,
  "timestamp_iso": "2024-12-23T15:00:00.123456",
  "elapsed_s": 120.5,
  "eta_s": 145.2,
  "eta_formatted": "2m 25s",
  "overall": {
    "percent_complete_files": 48.0,
    "percent_complete_segments": 45.2
  },
  "files": {
    "total": 25,
    "done": 12,
    "failed": 0,
    "skipped": 0,
    "current": "api-reference.md"
  },
  "segments": {
    "total": 1000,
    "done": 452,
    "failed": 0
  },
  "performance": {
    "segments_per_sec_rolling": 8.52,
    "segments_per_sec_lifetime": 3.75,
    "files_per_min": 5.97,
    "avg_segment_ms": 117.35,
    "avg_batch_s": 1.88
  },
  "cache": {
    "hits": 303,
    "misses": 149,
    "hit_rate": 0.67,
    "l1_hits": 45,
    "l2_hits": 258,
    "l3_hits": 0
  },
  "translation": {
    "model": "m2m100_418m",
    "device": "cuda",
    "tokens_in": 45230,
    "tokens_out": 52180,
    "retries": 2
  },
  "errors": {
    "count": 0,
    "last_error": "",
    "last_failed_file": "",
    "by_type": {}
  }
}
```

## Metrics Tail Utility

The `metrics_tail.py` utility provides a Windows-friendly way to follow metrics streams.

### Usage

```bash
# Detailed multi-line output (default)
python -m src.observability.metrics_tail ./metrics.ndjson

# Compact single-line status (updates in place)
python -m src.observability.metrics_tail ./metrics.ndjson --compact

# Raw JSON output (pretty-printed)
python -m src.observability.metrics_tail ./metrics.ndjson --json

# Custom poll interval
python -m src.observability.metrics_tail ./metrics.ndjson --poll 0.25
```

### Output Modes

**Detailed Mode** (default):
```
============================================================
Timestamp: 2024-12-23T15:00:00.123456
Elapsed: 2m 0s | ETA: 2m 25s
============================================================

Progress:
  Files:    48.0% complete
  Segments: 45.2% complete

Files:
  Total:   25
  Done:    12
  Failed:  0
  Skipped: 0
  Current: api-reference.md

Performance:
  Rate (rolling):  8.52 segs/sec
  Rate (lifetime): 3.75 segs/sec
  Files/min:       5.97
  Avg seg time:    117.4 ms
  Avg batch time:  1.880 s

Cache:
  Hit Rate: 67.0%
  Hits:     303 (L1: 45, L2: 258, L3: 0)
  Misses:   149
```

**Compact Mode** (`--compact`):
```
[45.2%] files=12/25 segs=452/1000 rate=8.5/s cache=67% ETA=2m 25s err=0
```

## ETA Calculation

ETA is calculated using:

1. **Exponential Moving Average (EMA)** of recent throughput
2. Alpha factor of 0.3 (configurable)
3. Remaining segments / rolling throughput rate

This provides responsive ETA updates that adapt to changing translation speeds while smoothing out short-term variations.

## Best Practices

1. **Long-running jobs**: Use `--metrics-file` to persist metrics for post-run analysis
2. **Monitoring**: Use `--metrics-only` in a dedicated terminal for clean status display
3. **Debugging**: Use `--log-level DEBUG` in primary terminal, `--metrics-only` in secondary
4. **CI/CD**: Parse `metrics_current.json` for job success/failure metrics

## Troubleshooting

### Metrics not updating

- Ensure `--no-progress` is not set
- Check `--metrics-interval` value (default 2.0 seconds)
- Verify write permissions for `--metrics-file` path

### ETA shows "calculating..."

- ETA requires some completed segments to calculate throughput
- Wait for a few batches to complete

### High cache miss rate

- Normal for first run (cold cache)
- Check L2 persistent cache path permissions
- Verify site_id matches previous runs

## Implementation Notes

### Time Window Performance (OBS-03)

The progress tracker uses `collections.deque` with `maxlen` for O(1) sliding window operations:

```python
from collections import deque

# Segment times: last 100 measurements
self._segment_times: Deque[float] = deque(maxlen=100)

# Batch times: last 50 measurements
self._batch_times: Deque[float] = deque(maxlen=50)

# EMA samples: configurable window size
self._samples: Deque[float] = deque(maxlen=window_size)
```

This replaces the previous `list.pop(0)` pattern which was O(n). The deque auto-evicts oldest items when `maxlen` is exceeded, eliminating manual length checks.

### Thread Safety

All progress tracking operations are thread-safe:

- `threading.RLock()` protects counter updates
- `threading.Lock()` protects EMA calculations
- `deque.append()` is atomic in CPython

### EMA Throughput Calculation

Rolling throughput uses Exponential Moving Average (EMA) with configurable alpha:

```python
ema_value = alpha * new_value + (1 - alpha) * ema_value
```

Default alpha is 0.3, giving ~70% weight to recent measurements for responsive updates while smoothing short-term variations.

### Windows Console Compatibility

Log messages use ASCII characters (`->`) instead of Unicode arrows to avoid `UnicodeEncodeError` on Windows cp1252 consoles. Unicode characters are preserved in comments and docstrings only.
