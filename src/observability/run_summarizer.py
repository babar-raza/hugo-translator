"""TC-AGT-04: Professionalize-powered run summarizer.

After a translation run completes, sends run metrics to the professionalize
LLM endpoint for a human-readable summary. Operates in dry-run mode by
default — writes metrics to file without making LLM API calls.

Config section in global.yaml:
    run_summarizer:
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

_SUMMARY_DIR = Path("data/summaries")

_SUMMARY_PROMPT = """\
You are a concise technical reporter. Summarize the following translation run \
metrics in 3-5 sentences. Focus on: files processed vs rejected, validation \
pass rate, LLM usage, and any notable issues. Be factual and precise.

## Run Metrics:
{metrics_json}

## Summary:
"""


def build_summary_prompt(metrics: dict[str, Any]) -> str:
    """Build the LLM prompt from run metrics."""
    metrics_json = json.dumps(metrics, indent=2, default=str)
    return _SUMMARY_PROMPT.format(metrics_json=metrics_json)


def _call_llm(prompt: str, config: dict[str, Any]) -> str | None:
    """Call the professionalize LLM endpoint.

    Uses the same OpenAI-compatible endpoint as the correction pass.
    Returns the summary text or None on failure.
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
    timeout = config.get("timeout_seconds", 60)

    if not api_key:
        logger.warning("LLM API key not set (env: %s); skipping summary", api_key_env)
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
        "max_tokens": 512,
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
        logger.warning("LLM summarizer call failed: %s", e)
        return None


def summarize_run(
    metrics: dict[str, Any],
    config: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate a human-readable summary of a translation run.

    Args:
        metrics: Run metrics dictionary (from worker/engine stats).
        config: Summarizer config from global.yaml (run_summarizer section).
            Keys: enabled, dry_run, base_url, model, api_key_env, timeout_seconds.
        output_dir: Directory for summary files (default: data/summaries/).

    Returns:
        Dict with keys: prompt, summary, dry_run, llm_called, output_path.
    """
    cfg = config or {}
    enabled = cfg.get("enabled", False)
    dry_run = cfg.get("dry_run", True)
    out_dir = output_dir or _SUMMARY_DIR

    result: dict[str, Any] = {
        "prompt": "",
        "summary": "",
        "dry_run": dry_run,
        "llm_called": False,
        "output_path": "",
    }

    if not enabled:
        logger.debug("Run summarizer disabled; skipping")
        return result

    prompt = build_summary_prompt(metrics)
    result["prompt"] = prompt

    summary = ""
    if not dry_run:
        llm_config = {
            "base_url": cfg.get("base_url", "https://llm.professionalize.com/v1"),
            "model": cfg.get("model", "professionalize_llm"),
            "api_key_env": cfg.get("api_key_env", "litellm_key"),
            "timeout_seconds": cfg.get("timeout_seconds", 60),
        }
        llm_summary = _call_llm(prompt, llm_config)
        if llm_summary:
            summary = llm_summary
            result["llm_called"] = True
        else:
            summary = "(LLM call failed — metrics saved for manual review)"
    else:
        summary = "(dry-run mode — LLM not called)"

    result["summary"] = summary

    # Always write the summary file (even in dry-run)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    site_id = metrics.get("site_id", "unknown")
    filename = f"summary-{site_id}-{ts}.json"
    out_path = out_dir / filename

    output_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "site_id": site_id,
        "dry_run": dry_run,
        "llm_called": result["llm_called"],
        "summary": summary,
        "metrics": metrics,
    }
    out_path.write_text(
        json.dumps(output_data, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    result["output_path"] = str(out_path)
    logger.info("Run summary written: %s (dry_run=%s)", out_path, dry_run)

    return result
