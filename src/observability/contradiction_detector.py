"""TC-AGT-08: Professionalize-powered contradiction detector.

Compares configuration claims against observed runtime behavior to detect
contradictions — e.g., a feature marked ``enabled: true`` that never fires,
or a threshold value that doesn't match what the code actually uses.

Operates in dry-run mode by default. In dry-run mode, builds the prompt
and writes it to a file without calling the LLM.

Config section in global.yaml:
    contradiction_detector:
      enabled: false
      dry_run: true
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path("data/contradictions")

_CONTRADICTION_PROMPT = """\
You are a configuration auditor. Compare the following configuration snippets \
against the observed runtime behavior and identify contradictions.

A contradiction is when:
1. A feature is enabled in config but never invoked at runtime
2. A threshold value in config doesn't match the value actually used
3. A feature is disabled but still running
4. Config references a file/path/endpoint that doesn't exist
5. Documentation claims don't match config or code behavior

## Configuration Snippets:
{config_json}

## Observed Runtime Behavior:
{behavior_json}

## Instructions:
- List each contradiction as a JSON object with: id, severity (HIGH/MEDIUM/LOW), \
config_key, expected, observed, recommendation
- If no contradictions found, return an empty array
- Be precise and factual

## Contradictions (JSON array):
"""


def build_contradiction_prompt(
    config_snippets: dict[str, Any],
    observed_behavior: dict[str, Any],
) -> str:
    """Build the LLM prompt from config and behavior data."""
    config_json = json.dumps(config_snippets, indent=2, default=str)
    behavior_json = json.dumps(observed_behavior, indent=2, default=str)
    return _CONTRADICTION_PROMPT.format(
        config_json=config_json,
        behavior_json=behavior_json,
    )


def _call_llm(prompt: str, config: dict[str, Any]) -> str | None:
    """Call the professionalize LLM endpoint for contradiction analysis.

    Uses the same OpenAI-compatible endpoint as the correction pass.
    Returns the response text or None on failure.
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests not available; cannot call LLM endpoint")
        return None

    base_url = config.get("base_url", "https://llm.professionalize.com/v1")
    model = config.get("model", "professionalize_llm")
    api_key_env = config.get("api_key_env", "litellm_key")
    api_key = os.environ.get(api_key_env, "")
    timeout = config.get("timeout_seconds", 90)

    if not api_key:
        logger.warning("LLM API key not set (env: %s); skipping contradiction check", api_key_env)
        return None

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 1024,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
        return None
    except Exception as e:
        logger.warning("Contradiction detector LLM call failed: %s", e)
        return None


def _parse_contradictions(llm_response: str) -> list[dict[str, Any]]:
    """Extract contradiction entries from LLM response."""
    text = llm_response.strip()
    # Try to find a JSON array in the response
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    # Fallback: return the raw text as a single entry
    if text:
        return [{"id": "RAW", "severity": "LOW", "raw_response": text}]
    return []


def collect_config_snippets(config: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant config sections for contradiction checking.

    Pulls out key config sections that have observable behavioral
    implications (features with enabled flags, thresholds, paths).
    """
    snippets = {}
    # Adaptive thresholds
    if "adaptive_thresholds" in config:
        snippets["adaptive_thresholds"] = config["adaptive_thresholds"]
    # Agent metrics
    if "agent_metrics" in config:
        am = config["agent_metrics"]
        snippets["agent_metrics"] = {
            "enabled": am.get("enabled"),
            "dry_run": am.get("dry_run"),
        }
    # Correction pass
    if "correction_pass" in config:
        cp = config["correction_pass"]
        snippets["correction_pass"] = {
            "enabled": cp.get("enabled"),
            "model": cp.get("model"),
        }
    # Run summarizer
    if "run_summarizer" in config:
        snippets["run_summarizer"] = config["run_summarizer"]
    # Translation settings
    if "translation" in config:
        t = config["translation"]
        snippets["translation"] = {
            "default_model": t.get("default_model"),
            "max_retries": t.get("max_retries"),
        }
    return snippets


def collect_observed_behavior(
    *,
    run_signals_dir: Path | None = None,
    continuation_state_file: Path | None = None,
) -> dict[str, Any]:
    """Collect observed runtime behavior from state files and signals.

    Reads run signals and continuation state to build a picture of
    what actually happened at runtime.
    """
    behavior: dict[str, Any] = {}

    # Read most recent run signal
    signals_dir = run_signals_dir or Path("data/signals")
    if signals_dir.exists():
        signal_files = sorted(signals_dir.glob("run-signal-*.json"))
        if signal_files:
            try:
                latest = json.loads(signal_files[-1].read_text(encoding="utf-8"))
                behavior["latest_signal"] = {
                    "status": latest.get("status"),
                    "verdict": latest.get("verdict"),
                    "files": latest.get("files"),
                    "llm_usage": latest.get("llm_usage"),
                }
            except Exception:
                pass

    # Read continuation state
    state_file = continuation_state_file or Path("data/logs/continuation_state.json")
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            behavior["continuation_state"] = {
                "phase": state.get("phase"),
                "total_runs": state.get("stats", {}).get("total_runs"),
                "consecutive_failures": state.get("stats", {}).get("consecutive_failures"),
                "blockers_count": len(state.get("blockers", [])),
            }
        except Exception:
            pass

    # Read adaptive threshold metrics
    metrics_file = Path("data/logs/validation_metrics.jsonl")
    if metrics_file.exists():
        try:
            lines = metrics_file.read_text(encoding="utf-8").strip().splitlines()
            behavior["validation_metrics_lines"] = len(lines)
        except Exception:
            pass

    return behavior


def detect_contradictions(
    config_snippets: dict[str, Any],
    observed_behavior: dict[str, Any],
    *,
    detector_config: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run contradiction detection.

    Args:
        config_snippets: Config sections to check.
        observed_behavior: Observed runtime data.
        detector_config: Detector settings (enabled, dry_run, base_url, etc.).
        output_dir: Directory for output files.

    Returns:
        Dict with keys: prompt, contradictions, dry_run, llm_called, output_path.
    """
    cfg = detector_config or {}
    enabled = cfg.get("enabled", False)
    dry_run = cfg.get("dry_run", True)
    out_dir = output_dir or _OUTPUT_DIR

    result: dict[str, Any] = {
        "prompt": "",
        "contradictions": [],
        "dry_run": dry_run,
        "llm_called": False,
        "output_path": "",
    }

    if not enabled:
        logger.debug("Contradiction detector disabled; skipping")
        return result

    prompt = build_contradiction_prompt(config_snippets, observed_behavior)
    result["prompt"] = prompt

    contradictions: list[dict[str, Any]] = []
    if not dry_run:
        llm_config = {
            "base_url": cfg.get("base_url", "https://llm.professionalize.com/v1"),
            "model": cfg.get("model", "professionalize_llm"),
            "api_key_env": cfg.get("api_key_env", "litellm_key"),
            "timeout_seconds": cfg.get("timeout_seconds", 90),
        }
        llm_response = _call_llm(prompt, llm_config)
        if llm_response:
            contradictions = _parse_contradictions(llm_response)
            result["llm_called"] = True
        else:
            contradictions = [
                {
                    "id": "LLM_UNAVAILABLE",
                    "severity": "LOW",
                    "description": "LLM call failed — manual review needed",
                }
            ]
    else:
        contradictions = [
            {"id": "DRY_RUN", "severity": "INFO", "description": "(dry-run mode — LLM not called)"}
        ]

    result["contradictions"] = contradictions

    # Write output file
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"contradictions-{ts}.json"
    out_path = out_dir / filename

    output_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "llm_called": result["llm_called"],
        "contradictions_count": len(contradictions),
        "contradictions": contradictions,
        "config_snippets": config_snippets,
        "observed_behavior": observed_behavior,
    }
    out_path.write_text(
        json.dumps(output_data, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    result["output_path"] = str(out_path)
    logger.info(
        "Contradiction check written: %s (dry_run=%s, findings=%d)",
        out_path,
        dry_run,
        len(contradictions),
    )

    return result
