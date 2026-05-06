# Local Model Discovery System

**Status:** IMPLEMENTED
**Date:** 2026-05-06
**Sprint:** Local Model Discovery and Registry System

---

## Overview

The Local Model Discovery system scans configured directories across multiple drives to find usable translation and LLM models. Discovered models are registered with absolute paths and used in-place -- never copied, moved, renamed, or deleted.

## What It Does

- Scans HuggingFace cache, Ollama directories, and custom folders
- Detects Transformers, M2M100, NLLB, OPUS-MT/MarianMT, CTranslate2, GGUF, Ollama, and SentencePiece models
- Generates `config/model_registry.discovered.yaml` with absolute paths
- Merges discovered models into the existing registry (curated entries take priority)
- Produces run reports in `data/discovery/`

## What It Does NOT Do

- Copy or move model files
- Modify model files or directories
- Scan full drives by default
- Follow symlinks by default
- Override curated `config/model_registry.yaml` entries
- Require internet access

## CLI Commands

```bash
# Discover models from default scan roots (HF cache, Ollama)
python -m src.model_runtime.model_cli discover

# Dry run (no files written)
python -m src.model_runtime.model_cli discover --dry-run

# Add custom directories
python -m src.model_runtime.model_cli discover --custom-dirs "D:/models;E:/ai/models"

# Scan specific drives (bounded by max-depth and skip patterns)
python -m src.model_runtime.model_cli discover --include-drives "D:,E:" --max-depth 3

# Exclude HF cache or Ollama
python -m src.model_runtime.model_cli discover --no-hf-cache
python -m src.model_runtime.model_cli discover --no-ollama

# View discovery reports
python -m src.model_runtime.model_cli discover-report --latest
python -m src.model_runtime.model_cli discover-report --list

# Show model details
python -m src.model_runtime.model_cli show <model_id>

# Select best model for a language pair
python -m src.model_runtime.model_cli select --source en --target fr

# Check registry health
python -m src.model_runtime.model_cli doctor
```

## Configuration

In `config/global.yaml`:

```yaml
local_discovery:
  enabled: true
  scan_roots:
    - path: "~/.cache/huggingface/hub"
      label: "hf_cache"
      enabled: true
      max_depth: 4
    - path: "~/.ollama/models"
      label: "ollama"
      enabled: true
      max_depth: 4
    # Add custom roots:
    # - path: "D:/models"
    #   label: "custom"
    #   max_depth: 4
  skip_patterns:
    - "$RECYCLE.BIN"
    - "System Volume Information"
    - "Windows"
    - "Program Files"
    - ".git"
    - "node_modules"
```

## Environment Variables

- `HUGO_TRANSLATOR_MODEL_SEARCH_ROOTS` -- Semicolon-separated additional scan roots
- `HUGO_TRANSLATOR_MODEL_REGISTRY_PATH` -- Override discovered registry output path
- `HUGO_TRANSLATOR_MODEL_DISCOVERY_REPORT_DIR` -- Override report directory
- `HUGO_TRANSLATOR_ENABLE_FULL_DRIVE_SCAN` -- Enable full drive scanning ("true"/"false")

## How Selection Works

1. Discovered models become regular `ModelInfo` entries in the registry
2. `LanguageAwareModelSelector` selects from combined curated + discovered models
3. Curated entries always win on model_id conflicts
4. Selection priority: Opus-specific > Multilingual > Global fallback

## Troubleshooting

**Model not found?**
- Run `python -m src.model_runtime.model_cli discover --dry-run` to see what's detected
- Check scan roots include the directory containing your model
- Increase `--max-depth` if models are deeply nested
- Check skip patterns aren't excluding the directory

**Permission errors?**
- Discovery continues past permission errors (logged in report)
- Run `discover-report --latest` to see which paths were skipped

**Force a specific model?**
- Use `--model MODEL_ID` on the main translate CLI
- Or set `default_model` in site profile config

## Architecture

```
src/model_runtime/
  local_discovery.py     -- Scanning engine + model detectors
  discovery_report.py    -- Run reports + YAML export
  registry.py            -- Extended with load_discovered_models(), merge_discovered()
  model_cli.py           -- Extended with discover, show, select, doctor commands

config/
  model_registry.yaml              -- Curated (never modified by discovery)
  model_registry.discovered.yaml   -- Auto-generated (safe to delete & regenerate)

data/discovery/
  run_{id}.json                    -- Discovery run reports
```
