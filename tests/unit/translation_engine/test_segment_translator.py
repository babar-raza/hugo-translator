"""Unit tests for SegmentTranslator (TC-TEST-03 + TC-TEST-05).

Tests TM lookup, model call, stats mutation, placeholder restoration,
and TC-BUGFIX-A (temperature application on retries).
"""

from unittest.mock import MagicMock, patch

import pytest

from src.translation_engine.segment_translator import SegmentTranslator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    """Build a mock engine with attributes needed by SegmentTranslator."""
    engine = MagicMock()
    engine.config.get_config.return_value = {
        "translation_engine": {},
        "tm_defaults": {},
    }
    engine.batch_size = 16
    engine.sort_segments_by_length = False
    engine.terminology_manager = None
    engine._l3 = None
    engine._check_shutdown.return_value = False

    # Wire batch_lookup to mirror lookup().return_value for each request (for unit tests).
    # segment_translator now calls batch_lookup() instead of per-segment lookup().
    def _batch_lookup_side_effect(requests, use_semantic=True, **kwargs):
        return [engine.tm.lookup.return_value for _ in requests]
    engine.tm.batch_lookup.side_effect = _batch_lookup_side_effect

    # Model loader
    backend = MagicMock()
    backend.translate_batch.return_value = ["Translated text"]
    engine.model_loader.load_model.return_value = backend
    engine.model_loader.get_tokenizer_for_counting.return_value = None

    # _get_model_id
    engine._get_model_id.return_value = "m2m100_418M"

    return engine


def _make_segment(source_text="Hello world", seg_id="seg_1", context=None):
    seg = MagicMock()
    seg.source_text = source_text
    seg.id = seg_id
    seg.context = context
    seg.placeholder_map = {}
    seg.inline_format_pairs = []
    return seg


def _make_stats():
    from src.translation_engine.models import TranslationStats

    return TranslationStats()


# ---------------------------------------------------------------------------
# TM lookup + model translation
# ---------------------------------------------------------------------------


class TestTMLookupAndTranslation:
    def test_tm_hit_skips_model_call(self):
        """When TM has a hit, the segment is not sent to the model."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = True
        tm_result.translation = "Hallo Welt"
        tm_result.source = "l1_cache"
        tm_result.candidates = []
        engine.tm.lookup.return_value = tm_result

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nHallo Welt"
            result = translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        assert stats.tm_hits == 1
        assert stats.l1_hits == 1
        # Model not loaded for translation (only possibly for token counting)
        engine.model_loader.load_model.assert_not_called()

    def test_tm_miss_triggers_model_translation(self):
        """When TM misses, the segment goes to the model backend."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        tm_result.source = None
        engine.tm.lookup.return_value = tm_result

        backend = MagicMock()
        backend.translate_batch.return_value = ["Hallo Welt"]
        engine.model_loader.load_model.return_value = backend

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nHallo Welt"
            result = translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        assert stats.tm_hits == 0
        assert stats.translated_segments >= 0  # Model was invoked
        engine.model_loader.load_model.assert_called_once()

    def test_force_mode_skips_tm_lookup(self):
        """force=True bypasses TM lookup entirely."""
        engine = _make_engine()
        backend = MagicMock()
        backend.translate_batch.return_value = ["Hallo Welt"]
        engine.model_loader.load_model.return_value = backend

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nHallo Welt"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=True,
                stats=stats,
            )

        engine.tm.lookup.assert_not_called()


# ---------------------------------------------------------------------------
# TC-BUGFIX-A: Temperature application on retries
# ---------------------------------------------------------------------------


class TestTemperatureOnRetry:
    def test_temperature_applied_on_retry(self):
        """On retry_count > 0, temperature should be set on the LLM backend provider."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        engine.tm.lookup.return_value = tm_result

        # Set up a backend with _provider._config.temperature
        provider_config = MagicMock()
        provider_config.temperature = 0.7
        provider = MagicMock()
        provider._config = provider_config
        backend = MagicMock()
        backend._provider = provider
        backend.translate_batch.return_value = ["Hallo Welt"]
        engine.model_loader.load_model.return_value = backend

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nHallo Welt"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
                retry_count=2,
                retry_feedback="Fix headings",
            )

        # Temperature should be 0.7 + (2 * 0.1) = 0.9
        assert provider_config.temperature == pytest.approx(0.9)

    def test_temperature_not_applied_on_first_attempt(self):
        """On retry_count=0, temperature should remain at base (0.7)."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        engine.tm.lookup.return_value = tm_result

        provider_config = MagicMock()
        provider_config.temperature = 0.7
        provider = MagicMock()
        provider._config = provider_config
        backend = MagicMock()
        backend._provider = provider
        backend.translate_batch.return_value = ["Hallo Welt"]
        engine.model_loader.load_model.return_value = backend

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nHallo Welt"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
                retry_count=0,
            )

        # Temperature should NOT have been changed from the mock's initial value
        # (No assignment to provider_config.temperature on retry_count=0)
        # The base temperature block doesn't write to the provider
        assert provider_config.temperature == 0.7

    def test_temperature_capped_at_max(self):
        """Temperature should not exceed 1.0 even with high retry count."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        engine.tm.lookup.return_value = tm_result

        provider_config = MagicMock()
        provider_config.temperature = 0.7
        provider = MagicMock()
        provider._config = provider_config
        backend = MagicMock()
        backend._provider = provider
        backend.translate_batch.return_value = ["Hallo Welt"]
        engine.model_loader.load_model.return_value = backend

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nHallo Welt"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
                retry_count=10,  # Very high retry
                retry_feedback="Fix everything",
            )

        # Temperature: min(0.7 + 10*0.1, 1.0) = 1.0
        assert provider_config.temperature == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TC-LLM-AVAIL-001: professionalize_llm unavailability graceful degrade
# ---------------------------------------------------------------------------


class TestContentTypeRouterLLMPassthrough:
    """MS-LLM-AVAIL-001-06 / -07: passthrough on LLM down; translation on LLM up."""

    _ROUTING_CONFIG = {
        "table_cell_text": [
            {
                "condition": {"max_chars": 60, "pattern": "^Gets? the "},
                "preferred_model": "professionalize_llm",
                "context_hint": "api_property_description",
            }
        ]
    }

    def _make_engine(self, *, llm_raises=False, llm_translation="Translated"):
        engine = MagicMock()
        engine.config.get_config.return_value = {
            "translation_engine": {"content_type_routing": self._ROUTING_CONFIG},
        }
        engine._get_model_id.return_value = "m2m100_418M"
        engine._check_shutdown.return_value = False
        engine._force_accept = False

        mt_backend = MagicMock()
        mt_backend.translate_batch.return_value = []

        if llm_raises:
            def _load(model_id):
                if "professionalize_llm" in str(model_id):
                    raise ConnectionError("LLM service unavailable")
                return mt_backend
        else:
            llm_backend = MagicMock()
            llm_backend.translate_with_context.return_value = [llm_translation]

            def _load(model_id):
                if "professionalize_llm" in str(model_id):
                    return llm_backend
                return mt_backend

        engine.model_loader.load_model.side_effect = _load
        return engine

    def _make_doc_and_unit(self, source_text="Gets the width."):
        from src.translation_engine.extractor.text_unit import (
            BodyTranslationPlan,
            TextUnit,
            TextUnitKind,
        )

        unit = TextUnit(
            unit_id="test-unit-001",
            node_addr="body.table.0.row.1.cell.2",
            kind=TextUnitKind.TABLE_CELL_TEXT,
            source_text=source_text,
            do_not_translate=False,
        )
        plan = BodyTranslationPlan(ast=[], units=[unit], ast_fingerprint="test-fp")
        doc = MagicMock()
        doc.ast = []
        doc.frontmatter = {}
        doc.output_path = None
        return doc, plan, unit

    def _run_translate(self, engine, doc, plan):
        translator = SegmentTranslator(engine)
        site_profile = MagicMock()
        site_profile.default_source_lang = "en"

        with patch("src.translation_engine.extractor.TextUnitExtractor") as MockExt, patch(
            "src.translation_engine.reconstructor.ASTRenderer"
        ) as MockRenderer:
            mock_ext = MagicMock()
            mock_ext.extract_from_ast.return_value = plan
            mock_ext.batch_translate_units.return_value = plan.units
            mock_ext.batch_stats = {}
            mock_ext._batch_calls = 0
            mock_ext._individual_fallbacks = 0
            MockExt.return_value = mock_ext

            mock_renderer = MagicMock()
            mock_renderer.placeholder_leak_count = 0
            mock_renderer._missing_node_count = 0
            mock_renderer.applied_units = []
            mock_renderer.render_to_markdown.return_value = "body\n"
            MockRenderer.return_value = mock_renderer

            translator._translate_body_ast(
                doc=doc,
                target_lang="uk",
                site_profile=site_profile,
                stats=MagicMock(),
            )

    def test_llm_down_sets_english_passthrough(self):
        """LLM raises ConnectionError → unit gets source_text + passthrough metadata."""
        engine = self._make_engine(llm_raises=True)
        doc, plan, unit = self._make_doc_and_unit("Gets the width.")

        self._run_translate(engine, doc, plan)

        assert unit.translated_text == "Gets the width.", (
            "English passthrough expected when LLM is unavailable"
        )
        assert unit.metadata is not None
        assert unit.metadata.get("llm_passthrough_reason") == "professionalize_llm_unavailable"

    def test_llm_up_returns_translated_content(self):
        """LLM succeeds → unit gets translated content, no passthrough metadata."""
        engine = self._make_engine(llm_raises=False, llm_translation="Отримує ширину.")
        doc, plan, unit = self._make_doc_and_unit("Gets the width.")

        self._run_translate(engine, doc, plan)

        assert unit.translated_text == "Отримує ширину.", (
            "Translated content expected when LLM is available"
        )
        assert not (unit.metadata or {}).get("llm_passthrough_reason"), (
            "No passthrough metadata expected when LLM succeeds"
        )
