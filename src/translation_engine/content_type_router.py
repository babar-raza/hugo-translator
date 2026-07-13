"""
Content-type routing for translation backends.

Routes TextUnits to the appropriate translation backend based on configurable
rules.  No site-specific logic — all routing rules live in config/global.yaml
under ``translation_engine.content_type_routing``.

TC-HDN-005 implementation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.translation_engine.extractor.text_unit import TextUnit


@dataclass
class RoutingDecision:
    """Routing decision for a single TextUnit."""

    model_id: str | None = None
    """Model ID to use. None = use the shard/site default (NLLB or m2m100)."""

    context_hint: str | None = None
    """Hint injected into LLM system prompt when model is an LLM backend."""

    escalation_model: str | None = None
    """Model to escalate to after N gate failures."""

    escalation_threshold: int = 2
    """Number of consecutive gate failures before escalation triggers."""


# Default routing decision — use whatever model the shard is running.
_DEFAULT_DECISION = RoutingDecision()


class ContentTypeRouter:
    """Config-driven router that assigns a RoutingDecision to each TextUnit.

    Rules are evaluated in order; first matching rule wins.  Each rule has:
      - ``condition``: dict with optional keys ``max_chars`` and ``pattern``
      - ``preferred_model``: model ID or null (use default)
      - ``context_hint``: string injected into LLM prompt
      - ``gate_failure_escalation_model``: model ID for CASE-4 escalation
      - ``gate_failure_escalation_threshold``: int (default 2)

    Example config block (config/global.yaml, under ``translation_engine``):

        content_type_routing:
          table_cell_text:
            - condition:
                max_chars: 60
                pattern: '^(?:Gets?|Sets?|Indicates?|Enables?|Disables?|Represents?)\\s'
              preferred_model: professionalize_llm
              context_hint: api_property_description
            - condition: {}
              preferred_model: null
              gate_failure_escalation_model: professionalize_llm
          frontmatter_description:
            - condition: {}
              preferred_model: professionalize_llm
              context_hint: frontmatter_description
          default:
            - condition: {}
              preferred_model: null
              gate_failure_escalation_threshold: 2
              gate_failure_escalation_model: professionalize_llm
    """

    def __init__(self, routing_config: dict[str, Any]) -> None:
        self._config = routing_config or {}
        # Pre-compile condition patterns for speed
        self._compiled: dict[str, list[tuple[dict, re.Pattern | None]]] = {}
        for kind_key, rules in self._config.items():
            compiled_rules: list[tuple[dict, re.Pattern | None]] = []
            for rule in rules:
                cond = rule.get("condition", {})
                pat = re.compile(cond["pattern"]) if "pattern" in cond else None
                compiled_rules.append((cond, pat))
            self._compiled[kind_key] = compiled_rules

    def route(self, unit: TextUnit, field_name: str = "") -> RoutingDecision:
        """Determine routing for a TextUnit.

        Args:
            unit: The TextUnit to route.
            field_name: For frontmatter units, the YAML field name
                        (e.g. "description", "title").  Empty for body units.

        Returns:
            RoutingDecision with the assigned backend and context.
        """
        # TC-OPS-001: Check metadata override first.  text_unit_extractor.py may
        # set metadata['preferred_model'] for units that have a hard-wired backend
        # (e.g. short API descriptions).  This takes precedence over config rules.
        _meta_model = None
        _meta = getattr(unit, "metadata", None) or {}
        if isinstance(_meta, dict):
            _meta_model = _meta.get("preferred_model")
        if _meta_model:
            return RoutingDecision(
                model_id=_meta_model,
                context_hint=_meta.get("context_hint"),
                escalation_model=None,
            )

        # Determine the routing key
        kind_key: str
        if field_name:
            kind_key = f"frontmatter_{field_name}"
        else:
            # Use TextUnitKind value (e.g. "table_cell_text", "heading_text")
            try:
                kind_key = unit.kind.value
            except AttributeError:
                kind_key = str(unit.kind)

        # Look up rules for this kind; fall back to default
        rules_raw = self._config.get(kind_key) or self._config.get("default") or []
        compiled_rules = self._compiled.get(kind_key) or self._compiled.get("default") or []

        # If no pre-compiled rules for this key, build them on-demand
        if not compiled_rules and rules_raw:
            compiled_rules = []
            for rule in rules_raw:
                cond = rule.get("condition", {})
                pat = re.compile(cond["pattern"]) if "pattern" in cond else None
                compiled_rules.append((cond, pat))

        for i, rule in enumerate(rules_raw):
            cond, pat = compiled_rules[i] if i < len(compiled_rules) else ({}, None)
            if not self._matches(unit, cond, pat):
                continue
            return RoutingDecision(
                model_id=rule.get("preferred_model"),
                context_hint=rule.get("context_hint"),
                escalation_model=rule.get("gate_failure_escalation_model"),
                escalation_threshold=rule.get("gate_failure_escalation_threshold", 2),
            )

        return _DEFAULT_DECISION

    def _matches(self, unit: TextUnit, condition: dict, pattern: re.Pattern | None) -> bool:
        """Check whether a unit matches the given condition dict."""
        text = getattr(unit, "source_text", "") or ""
        text_stripped = text.strip()

        if "max_chars" in condition and len(text_stripped) > condition["max_chars"]:
            return False

        if pattern is not None and not pattern.search(text_stripped):
            return False

        return True
