"""Unit tests for SegmentTranslator (TC-TEST-03 + TC-TEST-05).

Tests TM lookup, model call, stats mutation, placeholder restoration,
and TC-BUGFIX-A (temperature application on retries).
"""

from unittest.mock import MagicMock, patch

import pytest

from src.translation_engine.segment_translator import (
    SegmentTranslator,
    _RetryFeedbackModel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_retry_feedback_model_instructs_every_ast_translation_call():
    backend = MagicMock()
    backend.translate.return_value = ["अनुवाद"]
    model = _RetryFeedbackModel(backend, "Translate every link label fully into hi.")

    result = model.translate(
        ["Aspose.Cells — Enterprise Blog"],
        "en",
        "hi",
        generation_params={"temperature": 0.2},
    )

    assert result == ["अनुवाद"]
    assert backend.translate.call_args.args[0] == [
        "Translate every link label fully into hi.\n\n"
        "SOURCE TEXT:\nAspose.Cells — Enterprise Blog"
    ]
    assert backend.translate.call_args.kwargs == {"generation_params": {"temperature": 0.2}}


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
    def test_model_override_is_forwarded_to_authoritative_ast_pass(self):
        """An escalation backend must translate the body that is finally rendered."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        tm_result.source = None
        engine.tm.lookup.return_value = tm_result

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "Translated body"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
                model_id_override="professionalize_llm",
            )

        assert mock_ast.call_args.kwargs["model_id_override"] == "professionalize_llm"

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
# TC-HT-004: legacy reconstruction path retired
# ---------------------------------------------------------------------------


def _make_legacy_site_profile(*, allow_legacy_reconstruction=False):
    """Real BodyRules (not MagicMock) so use_ast_body_reconstruction/
    allow_legacy_reconstruction booleans behave normally -- MagicMock
    auto-vivifies any attribute access as a truthy Mock, which would
    silently defeat the `not use_ast` / `not allow_legacy` guard. Uses the
    real pydantic model so all other attributes SegmentExtractor needs
    (preserve_patterns, preserve_blocks, ...) have correct defaults.
    """
    from src.utils.models import BodyRules

    body = BodyRules(
        translate_markdown=True,
        use_ast_body_reconstruction=False,
        allow_legacy_reconstruction=allow_legacy_reconstruction,
    )
    site_profile = MagicMock()
    site_profile.site_id = "test-site"
    site_profile.body = body
    return site_profile


class TestLegacyReconstructionRetired:
    def test_profile_false_without_escape_hatch_raises(self):
        from src.translation_engine.exceptions import SiteProfileConfigError

        engine = _make_engine()
        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()
        tm_result = MagicMock()
        tm_result.hit = False
        tm_result.source = None
        engine.tm.lookup.return_value = tm_result

        site_profile = _make_legacy_site_profile(allow_legacy_reconstruction=False)

        with pytest.raises(SiteProfileConfigError, match="allow_legacy_reconstruction"):
            translator.translate_to_language(
                site_id="test",
                site_profile=site_profile,
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

    def test_profile_false_with_escape_hatch_proceeds(self):
        """allow_legacy_reconstruction=true permits the legacy path (no raise)."""
        from src.translation_engine.exceptions import SiteProfileConfigError

        engine = _make_engine()
        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()
        tm_result = MagicMock()
        tm_result.hit = False
        tm_result.source = None
        engine.tm.lookup.return_value = tm_result

        site_profile = _make_legacy_site_profile(allow_legacy_reconstruction=True)

        # Should not raise our config error -- proceeds into the legacy
        # MarkdownReconstructor path (may hit unrelated mock-shape errors
        # deeper in that path given the minimal engine mock; only our
        # config error is this test's concern).
        try:
            translator.translate_to_language(
                site_id="test",
                site_profile=site_profile,
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )
        except SiteProfileConfigError:
            pytest.fail("allow_legacy_reconstruction=True must not raise SiteProfileConfigError")
        except Exception:
            pass  # unrelated downstream mock-shape errors are not this test's concern


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

    def test_temperature_set_to_base_on_first_attempt(self):
        """On retry_count=0, temperature should be (re-)written to base (0.7)."""
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

        assert provider_config.temperature == 0.7

    def test_non_retry_call_resets_temperature_left_elevated_by_prior_retry(self):
        """HT-QUALITY-GATES-001 Part 22 (root cause B, retry-temperature
        leak): the confirmed real bug. `_provider._config.temperature` is
        shared, mutable state on a cross-thread singleton backend instance
        (one ModelLoader-cached backend reused by every concurrent worker).
        Before the fix, temperature was only ever written inside the
        `retry_count > 0` branch -- so once ANY file anywhere retried and
        raised it, it stayed elevated forever afterward, including for
        unrelated non-retry calls on the same shared backend. This test
        starts the shared provider_config already elevated (as if a
        DIFFERENT file's retry left it at 0.9) and confirms a fresh,
        non-retry call on the SAME backend instance correctly resets it to
        base, rather than silently inheriting the stale elevated value."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        engine.tm.lookup.return_value = tm_result

        provider_config = MagicMock()
        # Simulates state left behind by an earlier, unrelated retry on this
        # same shared backend instance -- the exact confirmed defect shape.
        provider_config.temperature = 0.9
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
                retry_count=0,  # this call itself never retried
            )

        assert provider_config.temperature == pytest.approx(0.7), (
            "A non-retry call must reset temperature to base, not inherit a "
            "stale elevated value left by a prior, unrelated retry on the "
            "same shared backend instance."
        )

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

        with (
            patch("src.translation_engine.extractor.TextUnitExtractor") as MockExt,
            patch("src.translation_engine.reconstructor.ASTRenderer") as MockRenderer,
        ):
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

        assert (
            unit.translated_text == "Gets the width."
        ), "English passthrough expected when LLM is unavailable"
        assert unit.metadata is not None
        assert unit.metadata.get("llm_passthrough_reason") == "professionalize_llm_unavailable"

    def test_llm_up_returns_translated_content(self):
        """LLM succeeds → unit gets translated content, no passthrough metadata."""
        engine = self._make_engine(llm_raises=False, llm_translation="Отримує ширину.")
        doc, plan, unit = self._make_doc_and_unit("Gets the width.")

        self._run_translate(engine, doc, plan)

        assert (
            unit.translated_text == "Отримує ширину."
        ), "Translated content expected when LLM is available"
        assert not (unit.metadata or {}).get(
            "llm_passthrough_reason"
        ), "No passthrough metadata expected when LLM succeeds"


# ---------------------------------------------------------------------------
# HT-QUALITY-GATES-001 Part 22 (plan 5.1 item 5): min_similarity_score wiring
# ---------------------------------------------------------------------------


class TestMinSimilarityScoreWiring:
    def test_site_profile_min_similarity_score_reaches_batch_lookup(self):
        """Site profiles declare tm_prefs.min_similarity_score, but the
        actual L3 semantic-search call site (batch_lookup's semantic_threshold
        kwarg, default 0.80) never read it -- every site silently got the
        same hardcoded default regardless of its own declared config. This
        test uses a distinctive, non-default value (0.93) so a regression
        back to the hardcoded default would fail loudly rather than
        coincidentally matching."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        engine.tm.lookup.return_value = tm_result

        site_profile = MagicMock()
        site_profile.tm_prefs.min_similarity_score = 0.93

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()  # context=None -> body segment, not frontmatter

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nHallo Welt"
            translator.translate_to_language(
                site_id="test",
                site_profile=site_profile,
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        body_calls = [
            call
            for call in engine.tm.batch_lookup.call_args_list
            if call.kwargs.get("use_semantic") is True
        ]
        assert body_calls, "Expected at least one use_semantic=True batch_lookup call"
        for call in body_calls:
            assert call.kwargs.get("semantic_threshold") == 0.93, (
                f"Expected site profile's min_similarity_score (0.93) to reach "
                f"batch_lookup, got {call.kwargs.get('semantic_threshold')!r}"
            )

    def test_missing_tm_prefs_falls_back_to_default(self):
        """A site_profile with no tm_prefs at all must not crash -- falls
        back to the same 0.80 default batch_lookup already had."""
        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        engine.tm.lookup.return_value = tm_result

        site_profile = MagicMock()
        site_profile.tm_prefs = None

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment()

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nHallo Welt"
            translator.translate_to_language(
                site_id="test",
                site_profile=site_profile,
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        body_calls = [
            call
            for call in engine.tm.batch_lookup.call_args_list
            if call.kwargs.get("use_semantic") is True
        ]
        assert body_calls
        for call in body_calls:
            assert call.kwargs.get("semantic_threshold") == 0.80


class TestAstModelOverride:
    """The authoritative AST batch must load the governed attempt backend."""

    def test_ast_batch_loads_override_instead_of_profile_default(self):
        from src.translation_engine.extractor.text_unit import BodyTranslationPlan

        engine = _make_engine()
        translator = SegmentTranslator(engine)
        doc = MagicMock(ast=[], frontmatter={})
        plan = BodyTranslationPlan(ast=[], units=[], ast_fingerprint="test-fp")
        profile = MagicMock()
        profile.default_source_lang = "en"
        profile.body.ast_segmentation_strategy = "full_sentence"
        profile.body.ast_batch_size = 16
        profile.body.preserve_patterns = []

        with (
            patch("src.translation_engine.extractor.TextUnitExtractor") as mock_cls,
            patch("src.translation_engine.reconstructor.ASTRenderer") as mock_renderer_cls,
        ):
            extractor = mock_cls.return_value
            extractor.extract_from_ast.return_value = plan
            extractor.batch_translate_units.return_value = []
            extractor.batch_stats = {}
            extractor._batch_calls = 0
            extractor._individual_fallbacks = 0

            renderer = mock_renderer_cls.return_value
            renderer.placeholder_leak_count = 0
            renderer._missing_node_count = 0
            renderer.applied_units = []
            renderer.render_to_markdown.return_value = "body\n"

            translator._translate_body_ast(
                doc=doc,
                target_lang="ar",
                site_profile=profile,
                stats=_make_stats(),
                model_id_override="professionalize_llm",
            )

        engine.model_loader.load_model.assert_called_once_with("professionalize_llm")
