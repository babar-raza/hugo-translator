"""TC-AGT-12: Professionalize-powered blocker classifier.

Classifies stuck/blocked items by root cause using the professionalize LLM.
Root cause categories:
- CONFIG_ERROR: misconfigured settings
- DATA_QUALITY: malformed source content
- MODEL_LIMITATION: translation model can't handle this content
- EXTERNAL_DEPENDENCY: external service unavailable
- RESOURCE_EXHAUSTION: OOM, disk full, timeout
- UNKNOWN: can't determine root cause

Operates in dry-run mode by default. In dry-run mode, builds the prompt
and writes it to a file without calling the LLM.

Config section in global.yaml:
    blocker_classifier:
      enabled: false
      dry_run: true
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path("data/blocker_classifications")


class BlockerCategory(str, Enum):
    CONFIG_ERROR = "CONFIG_ERROR"
    DATA_QUALITY = "DATA_QUALITY"
    MODEL_LIMITATION = "MODEL_LIMITATION"
    EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    UNKNOWN = "UNKNOWN"


_CLASSIFIER_PROMPT = """\
You are a root cause analyst for a content translation system. Classify each \
blocked item by its root cause.

Categories:
- CONFIG_ERROR: Misconfigured settings, wrong paths, invalid YAML
- DATA_QUALITY: Malformed source content, broken frontmatter, encoding issues
- MODEL_LIMITATION: Translation model can't handle this content type/language
- EXTERNAL_DEPENDENCY: External API/service unavailable or erroring
- RESOURCE_EXHAUSTION: OOM, disk full, timeout, process killed
- UNKNOWN: Can't determine root cause from available information

## Blocked Items:
{blockers_json}

## Context:
{context_json}

## Instructions:
- For each blocker, return a JSON object with: blocker_id, category, confidence \
(0.0-1.0), reasoning (1 sentence), recommendation (1 sentence)
- Be precise and factual
- Return a JSON array

## Classifications (JSON array):
"""


def build_classifier_prompt(
    blockers: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> str:
    """Build the LLM prompt from blocker data."""
    blockers_json = json.dumps(blockers, indent=2, default=str)
    context_json = json.dumps(context or {}, indent=2, default=str)
    return _CLASSIFIER_PROMPT.format(
        blockers_json=blockers_json,
        context_json=context_json,
    )


def _call_llm(prompt: str, config: dict[str, Any]) -> str | None:
    """Call the professionalize LLM endpoint for blocker classification."""
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
        logger.warning("LLM API key not set (env: %s); skipping classification", api_key_env)
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
        logger.warning("Blocker classifier LLM call failed: %s", e)
        return None


def _parse_classifications(llm_response: str) -> list[dict[str, Any]]:
    """Parse LLM response into classification entries."""
    text = llm_response.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            entries = json.loads(text[start : end + 1])
            # Validate categories
            valid_categories = {c.value for c in BlockerCategory}
            for entry in entries:
                cat = entry.get("category", "")
                if cat not in valid_categories:
                    entry["category"] = BlockerCategory.UNKNOWN.value
            return entries
        except json.JSONDecodeError:
            pass
    if text:
        return [
            {"blocker_id": "RAW", "category": BlockerCategory.UNKNOWN.value, "raw_response": text}
        ]
    return []


def collect_blockers(
    *,
    continuation_state_file: Path | None = None,
    quarantine_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Collect blocked/stuck items from various sources.

    Sources:
    - continuation_state.json blockers
    - quarantine.jsonl (permanently stuck files)
    """
    blockers: list[dict[str, Any]] = []

    # Continuation state blockers
    from src.workers.continuation_state import load_state

    state = load_state(state_file=continuation_state_file)
    for blocker in state.get("blockers", []):
        blockers.append(
            {
                "source": "continuation_state",
                "blocker_id": blocker.get("blocker_id", "unknown"),
                "type": blocker.get("type", "unknown"),
                "description": blocker.get("description", ""),
                "added_at": blocker.get("added_at", ""),
            }
        )

    # Quarantine entries
    q_file = quarantine_file or Path("data/quarantine.jsonl")
    if q_file.exists():
        try:
            for line in q_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    blockers.append(
                        {
                            "source": "quarantine",
                            "blocker_id": Path(entry.get("output_path", "")).name,
                            "type": "quarantined_file",
                            "description": f"File {entry.get('output_path', '')} quarantined after {entry.get('retry_count', '?')} retries",
                            "tgt_lang": entry.get("tgt_lang", ""),
                            "quarantined_at": entry.get("quarantined_at", ""),
                        }
                    )
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.warning("blocker_classifier: failed to read quarantine: %s", e)

    return blockers


def classify_blockers(
    blockers: list[dict[str, Any]],
    *,
    classifier_config: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Classify blockers by root cause.

    Args:
        blockers: List of blocker dicts to classify.
        classifier_config: Classifier settings (enabled, dry_run, etc.).
        context: Optional context (site_id, recent history, etc.).
        output_dir: Directory for output files.

    Returns:
        Dict with keys: prompt, classifications, dry_run, llm_called, output_path.
    """
    cfg = classifier_config or {}
    enabled = cfg.get("enabled", False)
    dry_run = cfg.get("dry_run", True)
    out_dir = output_dir or _OUTPUT_DIR

    result: dict[str, Any] = {
        "prompt": "",
        "classifications": [],
        "dry_run": dry_run,
        "llm_called": False,
        "output_path": "",
    }

    if not enabled:
        logger.debug("Blocker classifier disabled; skipping")
        return result

    if not blockers:
        logger.info("No blockers to classify")
        return result

    prompt = build_classifier_prompt(blockers, context)
    result["prompt"] = prompt

    classifications: list[dict[str, Any]] = []
    if not dry_run:
        llm_config = {
            "base_url": cfg.get("base_url", "https://llm.professionalize.com/v1"),
            "model": cfg.get("model", "professionalize_llm"),
            "api_key_env": cfg.get("api_key_env", "litellm_key"),
            "timeout_seconds": cfg.get("timeout_seconds", 90),
        }
        llm_response = _call_llm(prompt, llm_config)
        if llm_response:
            classifications = _parse_classifications(llm_response)
            result["llm_called"] = True
        else:
            classifications = [
                {
                    "blocker_id": "LLM_UNAVAILABLE",
                    "category": BlockerCategory.UNKNOWN.value,
                    "reasoning": "LLM call failed — manual classification needed",
                }
            ]
    else:
        classifications = [
            {
                "blocker_id": "DRY_RUN",
                "category": "INFO",
                "reasoning": "(dry-run mode — LLM not called)",
            }
        ]

    result["classifications"] = classifications

    # Write output
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"classifications-{ts}.json"
    out_path = out_dir / filename

    output_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "llm_called": result["llm_called"],
        "blockers_count": len(blockers),
        "classifications_count": len(classifications),
        "classifications": classifications,
        "blockers": blockers,
    }
    out_path.write_text(
        json.dumps(output_data, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    result["output_path"] = str(out_path)
    logger.info(
        "Blocker classifications written: %s (dry_run=%s, blockers=%d)",
        out_path,
        dry_run,
        len(blockers),
    )

    return result
