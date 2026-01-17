# TM Improvement Worker

**Status:** Implemented
**Type:** Autonomous Worker
**Trigger:** Scheduled (4-5 times/day)

## Overview

The TM Improvement Worker is an autonomous background worker that uses LLM to improve Translation Memory (TM) entries during off-peak hours. It processes queued candidates from normal translation runs and enhances them for future use.

## Problem Statement

During normal translation operations, the system stores many translations in the TM. Some of these translations may be:
- Generated from fuzzy matches (L3 semantic search)
- Suboptimal due to context limitations
- Missing nuanced terminology or style consistency

The TM Improvement Worker addresses this by:
1. **Queue-based selection:** No expensive full-LMDB scans
2. **Scheduled execution:** Runs during off-peak hours (10:00-22:00 PT)
3. **LLM enhancement:** Uses local Ollama (or fallback) to improve translations
4. **VRAM safety:** Respects GPU memory budget with preflight/post-call checks
5. **Validation:** Ensures improvements preserve placeholders and formatting

## Architecture

### Components

1. **ImprovementQueue** (`src/tm/improvement_queue.py`)
   - Append-only JSONL file for candidate storage
   - Deduplication via hash-based seen tracking
   - FIFO pop with configurable batch size

2. **TMImprovementWorker** (`src/workers/tm_improvement_worker.py`)
   - Main worker implementation
   - Scheduling via WindowScheduler
   - LLM-based improvement with validation
   - VRAM enforcement with GPUManager

3. **TranslationMemory Integration**
   - Hook in `TranslationMemory.store()` to append candidates
   - Configurable via `tm_improvement.queue.enabled`

### Data Flow

```
Normal Translation Run
  └─> TranslationMemory.store()
      └─> ImprovementQueue.append_candidate() [if enabled]
          └─> data/tm/improvement_queue.jsonl

TM Improvement Worker (scheduled)
  └─> ImprovementQueue.pop_candidates(limit=50)
  └─> For each candidate:
      ├─> LLMClient.adapt_translation()
      ├─> Validate improved translation
      └─> TranslationMemory.store(force_update=True)
```

## Configuration

### Global Config (`config/global.yaml`)

```yaml
tm_improvement:
  # Master toggle
  enabled: true

  # Scheduling (4-5 runs/day during off-peak)
  schedule:
    runs_per_day: 5
    window_start: "10:00"
    window_end: "22:00"
    timezone: "America/Los_Angeles"
    jitter_minutes: 10

  # Batch configuration
  batch:
    candidates_per_run: 50
    max_llm_calls_per_run: 200
    max_seconds_per_run: 900  # 15 minutes

  # LLM configuration
  llm:
    provider: "ollama"
    model: "llama2"
    base_url: "http://localhost:11434"
    api_key: null
    timeout_seconds: 30
    temperature: 0.3

  # Queue configuration
  queue:
    enabled: true
    path: "data/tm/improvement_queue.jsonl"
    append_on_store: true
    quality_threshold: 0.80  # Only queue entries below this similarity

  # VRAM management
  resources:
    max_gpu_memory_percent: 60
    preflight_check: true
    abort_on_high_usage: true
```

## Usage

### Oneshot Mode (Run Once)

```bash
# Process queued candidates once
python -m src.workers.tm_improvement_worker --mode oneshot

# With custom config
python -m src.workers.tm_improvement_worker \
  --mode oneshot \
  --candidates-per-run 100 \
  --llm-provider ollama \
  --llm-model llama2
```

### Daemon Mode (Self-Scheduling)

```bash
# Run continuously with scheduling
python -m src.workers.tm_improvement_worker --mode daemon

# With custom schedule
python -m src.workers.tm_improvement_worker \
  --mode daemon \
  --runs-per-day 4 \
  --window-start 09:00 \
  --window-end 21:00 \
  --timezone America/New_York
```

### CLI Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--mode` | str | oneshot | Execution mode: oneshot or daemon |
| `--config-root` | str | config/ | Root directory for configuration |
| `--tm-path` | str | data/tm | Path to TM data directory |
| `--runs-per-day` | int | 5 | Number of runs per day (daemon mode) |
| `--window-start` | str | 10:00 | Start of daily window (HH:MM) |
| `--window-end` | str | 22:00 | End of daily window (HH:MM) |
| `--timezone` | str | America/Los_Angeles | Timezone name |
| `--candidates-per-run` | int | 50 | Max candidates per run |
| `--max-llm-calls-per-run` | int | 200 | Max LLM calls per run |
| `--max-seconds-per-run` | int | 900 | Max runtime per run (seconds) |
| `--llm-provider` | str | ollama | LLM provider |
| `--llm-model` | str | llama2 | LLM model name |
| `--max-gpu-memory-percent` | int | 60 | Max GPU memory usage |
| `--no-preflight-check` | flag | False | Disable GPU preflight check |
| `--no-abort-on-high-usage` | flag | False | Disable abort on high GPU |
| `--log-level` | str | INFO | Logging level |

## VRAM Safety

### Preflight Check
Before starting a run, the worker checks GPU usage:
- If usage >= 60% (configurable), abort run
- Prevents competing with active translation workloads
- Configurable via `--no-preflight-check`

### Post-Call Check
After each LLM call, the worker checks GPU usage:
- If usage >= 60%, pause further work
- Prevents GPU memory accumulation
- Re-queues unprocessed candidates

### Implementation

```python
# Preflight check
if self.config.preflight_check:
    gpu_usage = self._check_gpu_usage()
    if gpu_usage >= 60.0:
        logger.warning("GPU usage high, aborting run")
        return {"status": "aborted"}

# Post-call check (after each improvement)
gpu_usage = self._check_gpu_usage()
if gpu_usage >= 60.0:
    logger.warning("GPU usage exceeded threshold, pausing")
    break
```

## Improvement Process

### 1. Candidate Selection
```python
# Pop candidates from queue
candidates = improvement_queue.pop_candidates(limit=50)
```

### 2. LLM Improvement
```python
improved_translation = llm_client.adapt_translation(
    source_text=candidate.text,
    fuzzy_translation=candidate.translation,
    source_lang=candidate.src_lang,
    target_lang=candidate.tgt_lang,
    context=candidate.context,
    similarity_score=candidate.metadata.get("similarity_score", 0.0)
)
```

### 3. Validation
The worker validates improved translations for:
- **Not empty:** Improved translation must have content
- **Different from original:** Must show improvement
- **Placeholder balance:** All placeholders (`{name}`, `{0}`) preserved
- **Formatting preservation:** Markdown/HTML formatting maintained

```python
def _validate_improved_translation(self, original: str, improved: str) -> bool:
    # Check not empty
    if not improved.strip():
        return False

    # Check different
    if improved.strip() == original.strip():
        return False

    # Check placeholders
    original_placeholders = set(re.findall(r"\{[\w\d_]*\}", original))
    improved_placeholders = set(re.findall(r"\{[\w\d_]*\}", improved))
    if original_placeholders != improved_placeholders:
        return False

    # Check markdown
    markdown_indicators = ["**", "*", "`", "#", "[", "]"]
    original_has_markdown = any(i in original for i in markdown_indicators)
    improved_has_markdown = any(i in improved for i in markdown_indicators)
    if original_has_markdown and not improved_has_markdown:
        return False

    return True
```

### 4. Store Improvement
```python
# Store with force_update=True to overwrite existing entry
metadata = {
    "improved_by": "tm_improvement_worker",
    "improved_at": datetime.utcnow().isoformat(),
    "previous_hash": hashlib.sha256(original.encode()).hexdigest()[:16],
    "previous_translation": original,
    "llm_provider": "ollama",
    "llm_model": "llama2"
}

tm.store(
    site_id=candidate.site_id,
    src_lang=candidate.src_lang,
    tgt_lang=candidate.tgt_lang,
    text=candidate.text,
    translation=improved_translation,
    metadata=metadata,
    force_update=True
)
```

## Telemetry

### Metrics (Future)
- `job_type`: "tm_improvement"
- `trigger_type`: "scheduled"
- `candidates_pulled`: Number of candidates popped from queue
- `improved_count`: Number successfully improved
- `skipped_count`: Number skipped (validation failed, no improvement)
- `failed_count`: Number failed (errors)
- `llm_calls`: Total LLM API calls made
- `elapsed_seconds`: Runtime duration

## Safety and Limits

### Rate Limits
1. **Candidates per run:** Max 50 (configurable)
2. **LLM calls per run:** Max 200 (configurable)
3. **Time per run:** Max 15 minutes (configurable)

### VRAM Limits
1. **Preflight check:** Abort if GPU >= 60% before starting
2. **Post-call check:** Pause if GPU >= 60% after each LLM call
3. **Enforcement:** VRAMEnforcer applies budget at startup

### Error Handling
- **LLM unavailable:** Worker logs error and exits
- **Queue empty:** Worker completes successfully (no work)
- **Validation failure:** Skip candidate, continue to next
- **Store failure:** Mark as failed, continue to next

## Testing

### Unit Tests

**Queue Tests** (`tests/unit/tm/test_improvement_queue.py`)
- Append with deduplication
- Pop with limit
- FIFO ordering
- Persistence across instances
- Malformed line handling
- Unicode support

**Worker Tests** (`tests/unit/workers/test_tm_improvement_worker.py`)
- Validation logic (placeholders, markdown, empty)
- Improvement flow with mocked LLM
- VRAM guard logic with mocked GPU readings
- Call limits and time limits
- Preflight check abort

### Integration Tests

**Test oneshot mode:**
```bash
# Add test candidates to queue
python -c "
from pathlib import Path
from src.tm.improvement_queue import ImprovementQueue

queue = ImprovementQueue(Path('data/tm'))
queue.append_candidate(
    site_id='test',
    src_lang='en',
    tgt_lang='de',
    text='Hello world',
    translation='Hallo Welt'
)
"

# Run worker
python -m src.workers.tm_improvement_worker --mode oneshot --log-level DEBUG
```

**Test VRAM guard:**
```bash
# Simulate high GPU usage (requires GPU available)
python -c "
import torch
# Allocate large tensor to increase GPU usage
x = torch.randn(10000, 10000).cuda()
"

# Run worker (should abort on preflight check)
python -m src.workers.tm_improvement_worker --mode oneshot --log-level DEBUG
```

## Deployment

### Systemd Service (Linux)

```ini
[Unit]
Description=TM Improvement Worker (Daemon)
After=network.target

[Service]
Type=simple
User=translator
WorkingDirectory=/home/translator/hugo-translator
Environment="PYTHONPATH=/home/translator/hugo-translator"
ExecStart=/home/translator/.venv/bin/python -m src.workers.tm_improvement_worker \
  --mode daemon \
  --runs-per-day 5 \
  --log-level INFO
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

### Windows Task Scheduler

```powershell
# Create scheduled task to run 5 times/day
$action = New-ScheduledTaskAction -Execute "python" -Argument "-m src.workers.tm_improvement_worker --mode oneshot"
$trigger1 = New-ScheduledTaskTrigger -Daily -At "10:00AM"
$trigger2 = New-ScheduledTaskTrigger -Daily -At "12:30PM"
$trigger3 = New-ScheduledTaskTrigger -Daily -At "15:00PM"
$trigger4 = New-ScheduledTaskTrigger -Daily -At "17:30PM"
$trigger5 = New-ScheduledTaskTrigger -Daily -At "20:00PM"

Register-ScheduledTask -TaskName "TMImprovementWorker" -Action $action -Trigger $trigger1,$trigger2,$trigger3,$trigger4,$trigger5
```

### Docker Compose

```yaml
services:
  tm-improvement-worker:
    image: hugo-translator:latest
    command: python -m src.workers.tm_improvement_worker --mode daemon --runs-per-day 5
    volumes:
      - ./data/tm:/app/data/tm
      - ./config:/app/config
    environment:
      - EXECUTION_MODE=docker_cpu
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G
```

## Monitoring

### Logs

```bash
# Watch worker logs
tail -f data/logs/hugo-translator.ndjson | grep tm_improvement_worker

# Check run status
grep "Improvement run completed" data/logs/hugo-translator.ndjson | tail -5
```

### Metrics (Future)

When telemetry is integrated:
- Monitor improvement success rate
- Track LLM latency
- Alert on high failure rate
- Dashboard for queue size over time

## FAQ

### Q: How often should the worker run?

**A:** Default is 5 times/day (every ~2.4 hours during 10:00-22:00 PT). Adjust based on:
- Translation volume (more translations → more frequent)
- LLM capacity (Ollama throughput)
- GPU availability (avoid peak translation hours)

### Q: What happens if Ollama is down?

**A:** Worker will fail during setup and exit. Restart when Ollama is available. Queue persists across runs.

### Q: Can I use a cloud LLM (OpenAI, Anthropic)?

**A:** Yes! Configure via `--llm-provider openai` and provide `--llm-api-key`. VRAM checks will be skipped for cloud providers.

### Q: How do I check queue size?

```python
from pathlib import Path
from src.tm.improvement_queue import ImprovementQueue

queue = ImprovementQueue(Path("data/tm"))
print(queue.stats())
```

### Q: How do I clear the queue?

```python
from pathlib import Path
from src.tm.improvement_queue import ImprovementQueue

queue = ImprovementQueue(Path("data/tm"))
queue.clear()
```

### Q: What if I want to disable queueing?

Set `tm_improvement.queue.enabled: false` in `config/global.yaml`.

## Future Enhancements

1. **Telemetry Integration:** Add proper telemetry with job_type="tm_improvement"
2. **Quality Scoring:** Only queue candidates below quality threshold
3. **Feedback Loop:** Track improvement acceptance rate and adjust
4. **Multi-model Support:** A/B test different LLMs for improvements
5. **Contextual Prompts:** Use site-specific terminology in prompts
6. **Batch Processing:** Process multiple candidates in one LLM call

## References

- [Autonomous Workers Implementation Plan](./IMPLEMENTATION_PLAN.md)
- [Window Scheduler](../../src/workers/window_scheduler.py)
- [VRAM Enforcer](../../src/hardware/vram_enforcer.py)
- [LLM Client](../../src/intelligence/llm_client.py)
- [Translation Memory](../../src/tm/translation_memory.py)
