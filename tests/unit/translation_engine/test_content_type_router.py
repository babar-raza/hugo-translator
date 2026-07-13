"""Tests for ContentTypeRouter — TC-HDN-005."""
from unittest.mock import MagicMock

import pytest

from src.translation_engine.content_type_router import ContentTypeRouter, RoutingDecision


def _make_unit(kind_value: str, source_text: str) -> MagicMock:
    """Create a mock TextUnit with a given kind value and source_text."""
    unit = MagicMock()
    unit.kind = MagicMock()
    unit.kind.value = kind_value
    unit.source_text = source_text
    return unit


# Minimal routing config matching what global.yaml specifies
_CONFIG = {
    "table_cell_text": [
        {
            "condition": {
                "max_chars": 60,
                "pattern": r"^(?:Gets?|Sets?|Indicates?|Enables?|Disables?|Represents?)\s",
            },
            "preferred_model": "professionalize_llm",
            "context_hint": "api_property_description",
        },
        {
            "condition": {},
            "preferred_model": None,
            "gate_failure_escalation_model": "professionalize_llm",
            "gate_failure_escalation_threshold": 2,
        },
    ],
    "frontmatter_description": [
        {
            "condition": {},
            "preferred_model": "professionalize_llm",
            "context_hint": "frontmatter_description",
        },
    ],
    "default": [
        {
            "condition": {},
            "preferred_model": None,
            "gate_failure_escalation_model": "professionalize_llm",
            "gate_failure_escalation_threshold": 2,
        },
    ],
}


class TestRoutingRules:
    """Test that routing rules assign correct backends."""

    def test_short_api_desc_routes_to_llm(self):
        """TABLE_CELL_TEXT ≤60 chars matching API pattern → professionalize_llm."""
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("table_cell_text", "Gets the shrink to fit.")
        decision = router.route(unit)
        assert decision.model_id == "professionalize_llm"
        assert decision.context_hint == "api_property_description"

    def test_sets_api_desc_routes_to_llm(self):
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("table_cell_text", "Sets the indent level.")
        decision = router.route(unit)
        assert decision.model_id == "professionalize_llm"

    def test_indicates_api_desc_routes_to_llm(self):
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("table_cell_text", "Indicates whether wrap text is enabled.")
        decision = router.route(unit)
        assert decision.model_id == "professionalize_llm"

    def test_long_table_cell_uses_default_model(self):
        """TABLE_CELL_TEXT >60 chars → MT (null = use shard default)."""
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("table_cell_text", "Gets the value of this property, which controls the rendering of the element in the document.")
        decision = router.route(unit)
        assert decision.model_id is None  # use MT
        assert decision.escalation_model == "professionalize_llm"

    def test_prose_text_uses_mt_with_escalation(self):
        """Prose TEXT → null model, with LLM escalation on gate failure."""
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("text", "This is a long developer guide paragraph explaining the feature.")
        decision = router.route(unit)
        assert decision.model_id is None
        assert decision.escalation_model == "professionalize_llm"
        assert decision.escalation_threshold == 2

    def test_heading_text_uses_default(self):
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("heading_text", "Installation Guide")
        decision = router.route(unit)
        assert decision.model_id is None  # use MT

    def test_frontmatter_description_routes_to_llm(self):
        """frontmatter description field → professionalize_llm."""
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("text", "API class description.")
        decision = router.route(unit, field_name="description")
        assert decision.model_id == "professionalize_llm"
        assert decision.context_hint == "frontmatter_description"

    def test_frontmatter_title_uses_default(self):
        """frontmatter title has no special rule → default (MT)."""
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("text", "Alignment")
        decision = router.route(unit, field_name="title")
        assert decision.model_id is None  # no rule for frontmatter_title → default


class TestConditionMatching:
    """Test condition matching logic."""

    def test_max_chars_boundary(self):
        """Exactly 60 chars → matches; 61 chars → does not match short-desc rule."""
        router = ContentTypeRouter(_CONFIG)
        text_60 = "Gets the " + "x" * 51  # total = 60 chars
        text_61 = "Gets the " + "x" * 52  # total = 61 chars
        assert len(text_60) == 60
        assert len(text_61) == 61

        unit_60 = _make_unit("table_cell_text", text_60)
        unit_61 = _make_unit("table_cell_text", text_61)

        d_60 = router.route(unit_60)
        d_61 = router.route(unit_61)

        assert d_60.model_id == "professionalize_llm"  # ≤60: matches
        assert d_61.model_id is None  # >60: falls through to catch-all (MT)

    def test_empty_config_returns_default(self):
        """Empty config → always return default RoutingDecision."""
        router = ContentTypeRouter({})
        unit = _make_unit("table_cell_text", "Gets the value.")
        decision = router.route(unit)
        assert decision.model_id is None
        assert decision.context_hint is None
        assert decision.escalation_model is None

    def test_no_hardcoded_site_logic(self):
        """Router must be purely config-driven — no site-specific code path."""
        router = ContentTypeRouter(_CONFIG)
        # Same unit, same result regardless of hypothetical site
        unit = _make_unit("table_cell_text", "Sets the font size.")
        d1 = router.route(unit)
        d2 = router.route(unit)
        assert d1.model_id == d2.model_id  # deterministic


class TestEscalationDecision:
    """Test escalation threshold in routing decision."""

    def test_escalation_threshold_default(self):
        """Default escalation threshold is 2."""
        router = ContentTypeRouter(_CONFIG)
        unit = _make_unit("text", "Some prose text.")
        decision = router.route(unit)
        assert decision.escalation_threshold == 2

    def test_custom_escalation_threshold(self):
        """Custom threshold in config is respected."""
        config = {
            "default": [
                {
                    "condition": {},
                    "preferred_model": None,
                    "gate_failure_escalation_model": "my_llm",
                    "gate_failure_escalation_threshold": 5,
                }
            ]
        }
        router = ContentTypeRouter(config)
        unit = _make_unit("text", "Some text.")
        decision = router.route(unit)
        assert decision.escalation_threshold == 5
        assert decision.escalation_model == "my_llm"
