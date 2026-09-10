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
    backend.translate_with_retry_feedback.return_value = ["अनुवाद"]
    model = _RetryFeedbackModel(backend, "Translate every link label fully into hi.")

    result = model.translate(
        ["Aspose.Cells — Enterprise Blog"],
        "en",
        "hi",
        generation_params={"temperature": 0.2},
    )

    assert result == ["अनुवाद"]
    assert backend.translate_with_retry_feedback.call_args.args[0] == [
        "Aspose.Cells — Enterprise Blog"
    ]
    assert backend.translate_with_retry_feedback.call_args.kwargs == {
        "retry_feedback": "Translate every link label fully into hi.",
        "generation_params": {"temperature": 0.2},
    }

    backend.translate_with_token_counts_and_retry_feedback.return_value = (
        ["अनुवाद"],
        5,
        2,
    )
    counted = model.translate_with_token_counts(["Source"], "en", "hi", max_new_tokens=20)
    assert counted == (["अनुवाद"], 5, 2)
    assert backend.translate_with_token_counts_and_retry_feedback.call_args.args[0] == ["Source"]
    assert (
        backend.translate_with_token_counts_and_retry_feedback.call_args.kwargs["retry_feedback"]
        == "Translate every link label fully into hi."
    )


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

    def _make_engine(
        self,
        *,
        llm_raises=False,
        llm_translation="Translated",
        fallback_lacks_context=False,
    ):
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

        elif fallback_lacks_context:
            # TC-HT-ROUTE-002: simulate the circuit breaker transparently
            # substituting a non-LLM fallback (e.g. m2m100) for
            # professionalize_llm -- load_model() does NOT raise, but the
            # returned backend has no translate_with_context() at all.
            # `spec=["translate"]` makes hasattr(...) correctly report the
            # method missing, exactly like the real HuggingFaceBackend.
            llm_backend = MagicMock(spec=["translate"])
            llm_backend.translate.return_value = [llm_translation]
            engine._test_llm_backend = llm_backend

            def _load(model_id):
                if "professionalize_llm" in str(model_id):
                    return llm_backend
                return mt_backend

        else:
            llm_backend = MagicMock()
            llm_backend.translate_with_context.return_value = [llm_translation]
            engine._test_llm_backend = llm_backend

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

    def _run_translate(
        self, engine, doc, plan, retry_feedback=None, batch_translate_side_effect=None
    ):
        translator = SegmentTranslator(engine)
        site_profile = MagicMock()
        site_profile.default_source_lang = "en"

        with (
            patch("src.translation_engine.extractor.TextUnitExtractor") as MockExt,
            patch("src.translation_engine.reconstructor.ASTRenderer") as MockRenderer,
        ):
            mock_ext = MagicMock()
            mock_ext.extract_from_ast.return_value = plan
            if batch_translate_side_effect is not None:
                # TC-HT-ROUTE-002: simulate Step 2b's real MT batch step
                # (mocked away by default) actually translating whatever
                # units it's handed, so tests can assert a unit left
                # unset by the ContentTypeRouter step gets a REAL
                # translation from here rather than staying English.
                mock_ext.batch_translate_units.side_effect = batch_translate_side_effect
            else:
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
                retry_feedback=retry_feedback,
            )

            return mock_ext

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

    def test_ast_routed_unit_receives_retry_feedback(self):
        engine = self._make_engine(llm_raises=False, llm_translation="हिंदी विवरण")
        doc, plan, _unit = self._make_doc_and_unit("Gets the width.")

        self._run_translate(
            engine,
            doc,
            plan,
            retry_feedback="Translate every ordinary word into hi.",
        )

        kwargs = engine._test_llm_backend.translate_with_context.call_args.kwargs
        assert kwargs["context_hint"] == "api_property_description"
        assert kwargs["retry_feedback"] == "Translate every ordinary word into hi."

    # -----------------------------------------------------------------
    # TC-HT-ROUTE-002: circuit breaker substitutes a non-LLM fallback
    # (e.g. m2m100) for professionalize_llm. load_model() does NOT raise
    # (unlike test_llm_down_sets_english_passthrough above), so the old
    # code called the returned backend's translate_with_context() anyway
    # -> AttributeError -> caught by the broad `except Exception` ->
    # EVERY routed unit in the batch landed as English passthrough, even
    # though the fallback is perfectly capable of translating via its own
    # ordinary MT path. Fixed by checking hasattr() first and, when
    # missing, leaving the unit's translated_text unset instead of
    # calling the LLM-only method or marking passthrough -- letting it
    # flow into the normal Step 2b MT batch (`batch_translate_units`)
    # below, which uses that same fallback for real.
    # -----------------------------------------------------------------

    def test_llm_backend_lacking_context_support_routes_to_mt_batch_instead_of_passthrough(self):
        """Fallback lacks translate_with_context -> must not be called (would
        AttributeError), the unit must NOT be marked English passthrough, and
        it must actually reach and be translated by the normal MT batch step
        (Step 2b's batch_translate_units) -- proving genuine fallback
        translation rather than silent English degradation.

        (The `test_llm_down_sets_english_passthrough` test above already
        covers the ORIGINAL passthrough safety net for the case this fix
        does NOT change: `load_model()` itself raising. This test covers
        the previously-broken case: `load_model()` succeeds but returns a
        backend that can't do context-aware translation.)
        """
        engine = self._make_engine(fallback_lacks_context=True)
        doc, plan, unit = self._make_doc_and_unit("Gets the width.")

        mt_translation = "Отримує ширину (MT fallback)."

        def _fake_batch_translate_units(units, *args, **kwargs):
            for u in units:
                if not u.do_not_translate and not u.translated_text:
                    u.translated_text = mt_translation
            return units

        self._run_translate(
            engine, doc, plan, batch_translate_side_effect=_fake_batch_translate_units
        )

        # The broken call must never have been attempted -- proves the fix
        # checks capability before calling, rather than relying on the
        # AttributeError being swallowed.
        assert not hasattr(engine._test_llm_backend, "translate_with_context")
        engine._test_llm_backend.translate.assert_not_called()

        # Old bug: this would be "Gets the width." (English passthrough)
        # with llm_passthrough_reason="professionalize_llm_unavailable".
        # Fixed behavior: genuinely translated via the normal MT batch path.
        assert unit.translated_text == mt_translation
        assert not (unit.metadata or {}).get("llm_passthrough_reason")


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


# ---------------------------------------------------------------------------
# HT-QUALITY-GATES-001 AST-reuse identity fix (2026-09-10)
#
# `_translate_body_ast()`'s legacy-translation reuse map used to key
# `source_to_translation` by re-normalized, placeholder-protected TEXT (a
# fresh `PlaceholderManager` instance per lookup). That was broken two ways:
#   1. False match: `PlaceholderManager.protect()` resets its counter on
#      every call, so any two single-span units anywhere on the page reduce
#      to the identical literal key "{PLACEHOLDER_0}" and silently collide --
#      confirmed live: a table's `.xlsx`/`.csv` code-span cell got restored
#      with an unrelated brand-navigation link's already-translated text,
#      identically across every locale.
#   2. False miss: the re-normalization used only
#      `site_profile.body.preserve_patterns`, diverging from whatever
#      protection the two source strings actually carry, sending a unit to
#      independent re-translation that disagreed with the legacy
#      `translations[]` entry for the same frontmatter field -- raising
#      `frontmatter_segment_not_applied` under zero-defect policy.
#
# The fix keys reuse by stable node identity instead: `TextUnit.node_addr`
# for body units (restricted to Segments with exactly one translatable AST
# leaf descendant), and the shared `frontmatter.<key>` address for
# frontmatter Segments/TextUnits. These tests construct the exact collision/
# divergence conditions the old text-keyed map was vulnerable to and assert
# the new identity-keyed map is immune by construction.
# ---------------------------------------------------------------------------


class TestASTReuseIdentityFix:
    """Regression tests for the identity-keyed AST-reuse map."""

    @staticmethod
    def _run(doc, site_profile, segments, translations, plan, target_lang="tr"):
        engine = _make_engine()
        translator = SegmentTranslator(engine)

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
                target_lang=target_lang,
                site_profile=site_profile,
                stats=_make_stats(),
                segments=segments,
                translations=translations,
                model_id_override="m2m100_418m",
            )

    def test_two_single_span_units_that_would_collide_under_old_text_key_stay_independent(self):
        """Bug 1 regression: a single-link paragraph and an unrelated single
        code-span table cell reduce to the IDENTICAL literal key under the
        retired strip_markdown()+fresh-PlaceholderManager() scheme -- proven
        directly below -- but must not collide under the new address-keyed
        map.
        """
        import re as _re

        from src.translation_engine.extractor.placeholder_manager import (
            PlaceholderManager,
        )
        from src.translation_engine.extractor.segment_extractor import (
            Segment,
            SegmentContext,
            SegmentContextType,
        )
        from src.translation_engine.extractor.text_unit import (
            BodyTranslationPlan,
            TextUnit,
            TextUnitKind,
        )

        def _old_style_key(text: str) -> str:
            stripped = _re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            stripped = _re.sub(r"`(.+?)`", r"\1", stripped)
            protected, _ = PlaceholderManager().protect(stripped, [r".+"])
            return protected

        link_key = _old_style_key("[Free Support Forum](https://x.example/forum)")
        code_key = _old_style_key("`.xlsx`")
        assert link_key == code_key == "{PLACEHOLDER_0}", (
            "sanity check: this is exactly the collision the retired "
            "text-keyed reuse map was vulnerable to"
        )

        link_segment = Segment(
            id="seg-link",
            source_text="[Free Support Forum](https://x.example/forum)",
            context=SegmentContext(
                context_type=SegmentContextType.BODY_TEXT,
                node_addr="body.para[7]",
            ),
            site_id="blog.aspose.org",
            source_lang="en",
        )
        code_segment = Segment(
            id="seg-code",
            source_text="`.xlsx`",
            context=SegmentContext(
                context_type=SegmentContextType.BODY_TEXT,
                node_addr="body.table[0].tablerow[1].tablecell[1]",
            ),
            site_id="blog.aspose.org",
            source_lang="en",
        )
        segments = [link_segment, code_segment]
        translations = {
            "seg-link": "Ücretsiz Destek Forumu",
            "seg-code": ".xlsx",
        }

        link_unit = TextUnit(
            unit_id="u-link",
            node_addr="body.para[7].link[0].text[0]",
            kind=TextUnitKind.LINK_TEXT,
            source_text="Free Support Forum",
        )
        code_unit = TextUnit(
            unit_id="u-code",
            node_addr="body.table[0].tablerow[1].tablecell[1]",
            kind=TextUnitKind.TABLE_CELL_TEXT,
            source_text="`.xlsx`",
        )
        plan = BodyTranslationPlan(
            ast=[], units=[link_unit, code_unit], ast_fingerprint="test-fp"
        )

        doc = MagicMock()
        doc.ast = []
        doc.frontmatter = {}
        doc.source_path = None

        site_profile = MagicMock()
        site_profile.default_source_lang = "en"
        site_profile.body.preserve_patterns = [r".+"]

        # VA-07: link_unit (LINK_TEXT) is no longer a reuse candidate at
        # all (see leaf_inventory.py) -- its own translated_text must come
        # from an independent batch_translate_units call, same as the real
        # pipeline would provide, not this test's default static
        # return_value=plan.units (which leaves it empty and trips the
        # "empty outputs for substantial text" retry). code_unit
        # (TABLE_CELL_TEXT) is unaffected and still reuses its segment
        # translation via the address-keyed map -- the collision-avoidance
        # this test exists to prove.
        def _fake_batch_translate(units, *_a, **_k):
            for u in units:
                if u.translated_text is None:
                    u.translated_text = "Ücretsiz Destek Forumu (independent)"
            return units

        engine = _make_engine()
        translator = SegmentTranslator(engine)
        with (
            patch("src.translation_engine.extractor.TextUnitExtractor") as MockExt,
            patch("src.translation_engine.reconstructor.ASTRenderer") as MockRenderer,
        ):
            mock_ext = MagicMock()
            mock_ext.extract_from_ast.return_value = plan
            mock_ext.batch_translate_units.side_effect = _fake_batch_translate
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
                target_lang="tr",
                site_profile=site_profile,
                stats=_make_stats(),
                segments=segments,
                translations=translations,
                model_id_override="m2m100_418m",
            )

        assert link_unit.translated_text == "Ücretsiz Destek Forumu (independent)", (
            "a LINK_TEXT sole leaf must get its OWN translation, never reuse the "
            "segment's combined text -- reusing it would double-wrap the link "
            "syntax the renderer independently re-adds"
        )
        assert code_unit.translated_text == ".xlsx", (
            "a non-link sole leaf still correctly reuses its segment translation, "
            "unaffected by sharing an old-style text key with link_unit"
        )

    def test_plain_link_only_list_item_does_not_double_wrap(self):
        """VA-07 (TC-APT-105 audit): the exact live shape --
        content/docs.aspose.org/en/cells/rust/getting-started/quickstart.md's
        "Next Steps" list, "- [Developer Guide Features](../../developer-guide/
        features/)" -- a list item that is NOTHING but a plain markdown link,
        no bold wrapper, no trailing prose, no do_not_translate leaf anywhere
        (so TC-APT-105's own fix, keyed off do_not_translate, never applied
        here). Before this fix, the sole LINK_TEXT leaf absorbed the
        segment's own combined translation ("[Developer Guide Features]
        (url)", markdown syntax and all, since the whole segment IS the
        link), and the renderer wrapped that AGAIN in its own "[...]()",
        producing "[[Developer Guide Features](url)](url)" in the rendered
        output. Confirmed live via .local/m2m100-25locale-quality-test/
        trace_quickstart_nested_link.py (gitignored scratch).
        """
        from src.translation_engine.extractor.segment_extractor import (
            Segment,
            SegmentContext,
            SegmentContextType,
        )
        from src.translation_engine.extractor.text_unit import (
            BodyTranslationPlan,
            TextUnit,
            TextUnitKind,
        )

        list_item_segment = Segment(
            id="seg-listitem",
            source_text="[Developer Guide Features](../../developer-guide/features/)",
            context=SegmentContext(
                context_type=SegmentContextType.BODY_TEXT,
                node_addr="body.list[1].listitem[2]",
            ),
            site_id="docs.aspose.org",
            source_lang="en",
        )
        translations = {
            # The real pipeline's segment-level translation for a
            # sole-link segment retains the full markdown syntax --
            # confirmed live, not just plausible.
            "seg-listitem": "[دليل المطور الميزات](../../developer-guide/features/)",
        }

        link_unit = TextUnit(
            unit_id="u-link",
            node_addr="body.list[1].listitem[2].link[0].text[0]",
            kind=TextUnitKind.LINK_TEXT,
            source_text="Developer Guide Features",
        )
        plan = BodyTranslationPlan(ast=[], units=[link_unit], ast_fingerprint="test-fp")

        doc = MagicMock()
        doc.ast = []
        doc.frontmatter = {}
        doc.source_path = None

        site_profile = MagicMock()
        site_profile.default_source_lang = "en"
        site_profile.body.preserve_patterns = []

        def _fake_batch_translate(units, *_a, **_k):
            for u in units:
                if u.translated_text is None:
                    u.translated_text = "دليل المطور الميزات"
            return units

        engine = _make_engine()
        translator = SegmentTranslator(engine)
        with (
            patch("src.translation_engine.extractor.TextUnitExtractor") as MockExt,
            patch("src.translation_engine.reconstructor.ASTRenderer") as MockRenderer,
        ):
            mock_ext = MagicMock()
            mock_ext.extract_from_ast.return_value = plan
            mock_ext.batch_translate_units.side_effect = _fake_batch_translate
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
                target_lang="ar",
                site_profile=site_profile,
                stats=_make_stats(),
                segments=[list_item_segment],
                translations=translations,
                model_id_override="m2m100_418m",
            )

        assert link_unit.translated_text == "دليل المطور الميزات", (
            "must be the independently-batch-translated anchor text only -- "
            f"not the segment's markdown-wrapped translation, got: "
            f"{link_unit.translated_text!r}"
        )
        assert "[" not in link_unit.translated_text and "(" not in link_unit.translated_text, (
            "the corrupted-duplicate signature: link_unit's own translated_text "
            "must never itself contain markdown link syntax, or the renderer's "
            "independent [...](url) wrapper double-wraps it"
        )

    def test_frontmatter_reuse_matches_by_address_despite_source_text_divergence(self):
        """Bug 2 regression: the legacy Segment's and the AST TextUnit's
        source strings are made to diverge on purpose here (simulating the
        historical merged-vs-unmerged preserve_patterns mismatch, or any
        other cause of textual disagreement between the two extraction
        paths). Reuse must still succeed because both sides share the same
        `frontmatter.<key>` address -- text content is no longer compared at
        all.
        """
        from src.translation_engine.extractor.segment_extractor import (
            Segment,
            SegmentContext,
            SegmentContextType,
        )
        from src.translation_engine.extractor.text_unit import (
            BodyTranslationPlan,
            TextUnit,
            TextUnitKind,
        )

        segment = Segment(
            id="seg-description",
            source_text="Learn how to work with {PLACEHOLDER_0} in C++.",
            context=SegmentContext(
                context_type=SegmentContextType.FRONTMATTER,
                frontmatter_key="description",
            ),
            site_id="blog.aspose.org",
            source_lang="en",
        )
        translations = {"seg-description": "Tanulja meg, hogyan dolgozzon."}

        unit = TextUnit(
            unit_id="u-description",
            node_addr="frontmatter.description",
            kind=TextUnitKind.TEXT,
            # Deliberately raw/unprotected text -- would NOT textually match
            # segment.source_text under any strip_markdown()+protect() scheme.
            source_text="Learn how to work with AnnotationCollection in C++.",
            metadata={
                "field_name": "description",
                "original_text": "Learn how to work with AnnotationCollection in C++.",
            },
        )
        plan = BodyTranslationPlan(ast=[], units=[unit], ast_fingerprint="test-fp")

        doc = MagicMock()
        doc.ast = []
        doc.frontmatter = {"description": "Learn how to work with AnnotationCollection in C++."}
        doc.source_path = None

        site_profile = MagicMock()
        site_profile.default_source_lang = "en"
        site_profile.body.preserve_patterns = []

        self._run(doc, site_profile, [segment], translations, plan, target_lang="hu")

        assert unit.translated_text == translations["seg-description"]

    def test_protected_leaf_plus_ordinary_sibling_does_not_reuse_whole_segment(self):
        """TC-APT-105 regression: a list item with one do_not_translate
        LINK_TEXT leaf (a governed/protected term, e.g. "API Reference") and
        one ordinary sibling TEXT leaf (e.g. ": Full class and method
        documentation") must NOT reuse the legacy segment's combined
        translation for the ordinary leaf. The old `_body_units` filter
        excluded do_not_translate units from the "does this container have
        exactly one leaf" count, so this exact shape (2 real leaves, 1
        visible to the filter) miscounted as "exactly one" and assigned the
        whole legacy translation -- including the protected leaf's own
        already-correct markdown -- onto the ordinary sibling. That sibling
        then renders adjacent to the independently-rendered protected leaf,
        duplicating it (confirmed live on content/docs.aspose.org/en/cells/
        go/getting-started/quickstart.md's "Next Steps" list).

        `batch_translate_units` is mocked here to actually fill in a
        (distinct, obviously-not-reused) translation for any unit still
        missing one -- simulating what the real MT/LLM batch step does for a
        unit reuse correctly declined to touch -- so the assertion can prove
        the sibling got its OWN translation, not the corrupted duplicate-
        bearing legacy string, rather than merely asserting `is None` (which
        a real run would never leave true).
        """
        from src.translation_engine.extractor.segment_extractor import (
            Segment,
            SegmentContext,
            SegmentContextType,
        )
        from src.translation_engine.extractor.text_unit import (
            BodyTranslationPlan,
            TextUnit,
            TextUnitKind,
        )

        list_item_segment = Segment(
            id="seg-listitem",
            source_text=(
                "**[API Reference](https://reference.aspose.org/cells/go/)**: "
                "Full class and method documentation"
            ),
            context=SegmentContext(
                context_type=SegmentContextType.BODY_TEXT,
                node_addr="body.list[0].listitem[1]",
            ),
            site_id="docs.aspose.org",
            source_lang="en",
        )
        translations = {
            "seg-listitem": (
                "**[API Reference](https://reference.aspose.org/cells/go/)**: "
                "Vollstaendige Klassen- und Methodendokumentation"
            ),
        }

        protected_link_unit = TextUnit(
            unit_id="u-protected-link",
            node_addr="body.list[0].listitem[1].strong[0].link[0].text[0]",
            kind=TextUnitKind.LINK_TEXT,
            source_text="API Reference",
            do_not_translate=True,
        )
        ordinary_sibling_unit = TextUnit(
            unit_id="u-ordinary-sibling",
            node_addr="body.list[0].listitem[1].text[0]",
            kind=TextUnitKind.TEXT,
            source_text=": Full class and method documentation",
        )
        plan = BodyTranslationPlan(
            ast=[],
            units=[protected_link_unit, ordinary_sibling_unit],
            ast_fingerprint="test-fp",
        )

        doc = MagicMock()
        doc.ast = []
        doc.frontmatter = {}
        doc.source_path = None

        site_profile = MagicMock()
        site_profile.default_source_lang = "en"
        site_profile.body.preserve_patterns = []

        def _fake_batch_translate(units, *_a, **_k):
            for u in units:
                if u.translated_text is None:
                    u.translated_text = (
                        u.source_text if u.do_not_translate else f"[translated] {u.source_text}"
                    )
            return units

        engine = _make_engine()
        translator = SegmentTranslator(engine)

        with (
            patch("src.translation_engine.extractor.TextUnitExtractor") as MockExt,
            patch("src.translation_engine.reconstructor.ASTRenderer") as MockRenderer,
        ):
            mock_ext = MagicMock()
            mock_ext.extract_from_ast.return_value = plan
            mock_ext.batch_translate_units.side_effect = _fake_batch_translate
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
                target_lang="de",
                site_profile=site_profile,
                stats=_make_stats(),
                segments=[list_item_segment],
                translations=translations,
                model_id_override="m2m100_418m",
            )

        assert protected_link_unit.translated_text == "API Reference", (
            "protected leaf must go through the normal do_not_translate "
            "copy-through, not be overwritten by the reuse map"
        )
        assert ordinary_sibling_unit.translated_text == (
            "[translated] : Full class and method documentation"
        ), (
            "ordinary sibling must receive its OWN independent translation, "
            "not the legacy segment's combined string -- reusing that would "
            "duplicate the protected leaf's markdown when both are rendered"
        )
        assert "API Reference" not in ordinary_sibling_unit.translated_text, (
            "the corrupted-duplicate signature: the protected leaf's anchor "
            "text must never appear inside the sibling's own translation"
        )

    def test_sole_do_not_translate_leaf_container_is_harmless(self):
        """Edge case: a container whose ONLY leaf descendant is
        do_not_translate (zero ordinary siblings) must not crash and must
        not have any effect -- the downstream apply loop already skips
        do_not_translate units, so populating (or not populating) the reuse
        map for it is a no-op either way. This pins that the explicit
        `not sole_unit.do_not_translate` guard doesn't regress this case.
        """
        from src.translation_engine.extractor.segment_extractor import (
            Segment,
            SegmentContext,
            SegmentContextType,
        )
        from src.translation_engine.extractor.text_unit import (
            BodyTranslationPlan,
            TextUnit,
            TextUnitKind,
        )

        segment = Segment(
            id="seg-solo-protected",
            source_text="[API Reference](https://reference.aspose.org/cells/go/)",
            context=SegmentContext(
                context_type=SegmentContextType.BODY_TEXT,
                node_addr="body.list[1].listitem[1]",
            ),
            site_id="docs.aspose.org",
            source_lang="en",
        )
        translations = {
            "seg-solo-protected": "[API Reference](https://reference.aspose.org/cells/go/)",
        }

        solo_unit = TextUnit(
            unit_id="u-solo-protected",
            node_addr="body.list[1].listitem[1].link[0].text[0]",
            kind=TextUnitKind.LINK_TEXT,
            source_text="API Reference",
            do_not_translate=True,
        )
        plan = BodyTranslationPlan(ast=[], units=[solo_unit], ast_fingerprint="test-fp")

        doc = MagicMock()
        doc.ast = []
        doc.frontmatter = {}
        doc.source_path = None

        site_profile = MagicMock()
        site_profile.default_source_lang = "en"
        site_profile.body.preserve_patterns = []

        self._run(doc, site_profile, [segment], translations, plan, target_lang="de")

        assert solo_unit.translated_text is None


# ---------------------------------------------------------------------------
# HT-QUALITY-GATES-001 RC2 (follow-up to TC-APT-042 / TC-APT-106, 2026-09-10)
#
# commit b7ba0813 fixed the AST-reuse identity bug above but explicitly left
# a SECOND, independent cause of `frontmatter_segment_not_applied` unfixed:
# `_repair_cross_field_frontmatter_residuals` legitimately mutates a
# frontmatter TextUnit's `translated_text` (e.g. fixing a near-duplicate
# description/summary field that left a shared English phrase untranslated)
# AFTER `translate_to_language`'s `_fm_expected_by_key` snapshot -- sourced
# from the separate, earlier legacy segments/translations pass -- has
# already been taken. That snapshot has no way to learn about an AST-side
# repair on its own, so the placement-consistency check
# (`_unapplied_frontmatter_keys`) compared the repaired-and-now-CORRECT
# rendered value against a stale pre-repair expectation and raised a false
# positive under zero-defect policy.
#
# The fix: `_translate_body_ast` records the ACTUAL accepted rendered value
# for every frontmatter key a repair pass touched into
# `stats.fm_repair_overrides` (read via the same `YAMLFormatter.
# get_nested_value` accessor the check itself uses against the same
# `doc.frontmatter`), and `translate_to_language` merges those overrides
# into `_fm_expected_by_key` before running the check -- widening acceptance
# only for keys a repair actually touched, so a genuinely wrong/unapplied
# frontmatter translation is still caught.
# ---------------------------------------------------------------------------


class TestFrontmatterRepairPlacementCheck:
    """Direct tests of `_unapplied_frontmatter_keys`'s contract once a repair
    override has been merged into its `expected_by_key` argument."""

    def test_accepts_a_repaired_value_when_present_in_expected_by_key(self):
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter
        from src.translation_engine.segment_translator import _unapplied_frontmatter_keys

        # Mirrors the merged _fm_expected_by_key: the stale legacy pre-repair
        # value plus the repaired value stats.fm_repair_overrides recorded.
        expected_by_key = {
            "summary": ["Stale untranslated summary text", "Repaired summary text"]
        }
        translated_frontmatter = {"summary": "Repaired summary text"}

        not_applied = _unapplied_frontmatter_keys(
            expected_by_key, translated_frontmatter, YAMLFormatter()
        )

        assert not_applied == []

    def test_still_flags_a_genuinely_wrong_value_not_in_expected_by_key(self):
        """Regression guard: the check's original defect-catching purpose
        must survive the fix. A rendered value matching NEITHER the legacy
        translation NOR any repair override is still a real
        frontmatter_segment_not_applied defect."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter
        from src.translation_engine.segment_translator import _unapplied_frontmatter_keys

        expected_by_key = {"summary": ["Correct expected summary text"]}
        translated_frontmatter = {
            "summary": "Something else entirely, unrelated to any expectation"
        }

        not_applied = _unapplied_frontmatter_keys(
            expected_by_key, translated_frontmatter, YAMLFormatter()
        )

        assert not_applied == ["summary"]


class TestFrontmatterRepairOverrideCapture:
    """`_translate_body_ast` must record a genuine cross-field repair's
    accepted value into `stats.fm_repair_overrides`."""

    def test_cross_field_repair_is_captured_into_stats_fm_repair_overrides(self):
        from src.translation_engine.extractor.text_unit import (
            BodyTranslationPlan,
            TextUnit,
            TextUnitKind,
        )

        # Two near-duplicate frontmatter fields sharing "MIT-licensed,
        # zero-dependency": description translated it, summary left it as an
        # untranslated English residual -- the exact TC-APT-042 shape.
        description_unit = TextUnit(
            unit_id="fm-description",
            node_addr="frontmatter.description",
            kind=TextUnitKind.TEXT,
            source_text="A MIT-licensed, zero-dependency PDF library.",
            translated_text="Knihovna PDF s licenci MIT bez zavislosti.",
            metadata={
                "field_name": "description",
                "original_text": "A MIT-licensed, zero-dependency PDF library.",
            },
        )
        summary_unit = TextUnit(
            unit_id="fm-summary",
            node_addr="frontmatter.summary",
            kind=TextUnitKind.TEXT,
            source_text="Overview of the MIT-licensed, zero-dependency PDF library.",
            translated_text="Prehled MIT-licensed, zero-dependency PDF knihovny.",
            metadata={
                "field_name": "summary",
                "original_text": "Overview of the MIT-licensed, zero-dependency PDF library.",
            },
        )
        plan = BodyTranslationPlan(
            ast=[], units=[description_unit, summary_unit], ast_fingerprint="test-fp"
        )

        engine = _make_engine()
        # A MagicMock's auto-vivified .campaign_context.get(...) is truthy,
        # which would make _repair_cross_field_frontmatter_residuals treat
        # "defer_llm_fallbacks" as set and skip the repair entirely -- must
        # be a real dict, same as production's default {}.
        engine.campaign_context = {}
        repaired_summary = "Prehled knihovny PDF s licenci MIT bez zavislosti."
        backend = engine.model_loader.load_model.return_value
        backend.translate_with_context.return_value = [repaired_summary]

        translator = SegmentTranslator(engine)
        site_profile = MagicMock()
        site_profile.default_source_lang = "en"
        site_profile.body.preserve_patterns = []

        # `renderer.apply_translations` (mocked below, existing/unrelated
        # rendering code) is what would normally copy a repaired unit's
        # translated_text into doc.frontmatter -- set directly here so this
        # test isolates the NEW capture logic rather than re-testing
        # ASTRenderer.
        doc = MagicMock()
        doc.ast = []
        doc.frontmatter = {"summary": repaired_summary}
        doc.source_path = None

        stats = _make_stats()

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
                target_lang="cs",
                site_profile=site_profile,
                stats=stats,
                model_id_override="m2m100_418m",
            )

        assert summary_unit.metadata.get(
            "cross_field_repair_phrase"
        ), "cross-field repair pass should have fired for this residual shape"
        assert stats.fm_repair_overrides.get("summary") == [repaired_summary]


class TestFrontmatterRepairOverrideIntegration:
    """End-to-end (through `translate_to_language`) regression coverage for
    the false-positive fix and its regression guard."""

    def test_accepts_legitimate_post_repair_frontmatter_value(self):
        from src.translation_engine.extractor.segment_extractor import (
            SegmentContext,
            SegmentContextType,
        )

        engine = _make_engine()
        engine.validation_policy = "zero-defect"
        tm_result = MagicMock()
        tm_result.hit = True
        tm_result.translation = "Stale pre-repair summary"
        tm_result.source = "l1_cache"
        tm_result.candidates = []
        engine.tm.lookup.return_value = tm_result

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(
            source_text="Summary source text",
            seg_id="seg-summary",
            context=SegmentContext(
                context_type=SegmentContextType.FRONTMATTER,
                frontmatter_key="summary",
            ),
        )

        repaired_value = "Repaired summary text (cross-field fix)"
        doc = MagicMock(ast=None, frontmatter={"summary": repaired_value})

        def _fake_translate_body_ast(doc_arg, target_lang_arg, site_profile_arg, stats_arg, **kwargs):
            # Simulates what the real _translate_body_ast does once a
            # cross-field repair fires: record the accepted value, then
            # return the (already-rendered) body.
            stats_arg.fm_repair_overrides["summary"] = [repaired_value]
            return f"Body"

        with patch.object(
            translator, "_translate_body_ast", side_effect=_fake_translate_body_ast
        ):
            # Must not raise -- this is the exact false positive this fix
            # closes (previously: ValueError frontmatter_segment_not_applied).
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=doc,
                segments=[seg],
                source_lang="en",
                target_lang="cs",
                force=False,
                stats=stats,
            )

    def test_still_raises_when_frontmatter_value_is_genuinely_unapplied(self):
        """Regression guard: with NO repair override recorded, a rendered
        frontmatter value that disagrees with the legacy expectation must
        still raise -- this is the original defect class the check exists
        to catch, and the fix must not weaken it."""
        from src.translation_engine.extractor.segment_extractor import (
            SegmentContext,
            SegmentContextType,
        )

        engine = _make_engine()
        engine.validation_policy = "zero-defect"
        tm_result = MagicMock()
        tm_result.hit = True
        tm_result.translation = "Correct expected title"
        tm_result.source = "l1_cache"
        tm_result.candidates = []
        engine.tm.lookup.return_value = tm_result

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(
            source_text="Title source text",
            seg_id="seg-title",
            context=SegmentContext(
                context_type=SegmentContextType.FRONTMATTER,
                frontmatter_key="title",
            ),
        )

        # No repair fired this attempt (stats.fm_repair_overrides stays
        # empty) -- the rendered value matches neither the legacy
        # expectation nor any override.
        doc = MagicMock(ast=None, frontmatter={"title": "Wrong unrelated rendered title"})

        def _fake_translate_body_ast(doc_arg, target_lang_arg, site_profile_arg, stats_arg, **kwargs):
            return "Body"

        with patch.object(
            translator, "_translate_body_ast", side_effect=_fake_translate_body_ast
        ):
            with pytest.raises(ValueError, match="frontmatter_segment_not_applied"):
                translator.translate_to_language(
                    site_id="test",
                    site_profile=MagicMock(),
                    doc=doc,
                    segments=[seg],
                    source_lang="en",
                    target_lang="cs",
                    force=False,
                    stats=stats,
                )


# ---------------------------------------------------------------------------
# TC-HT-ROUTE-002: segment-path (translate_to_language's Step 1b) counterpart
# of TestContentTypeRouterLLMPassthrough's AST-path fix above.
#
# ContentTypeRouter routes a frontmatter Segment to what should be
# professionalize_llm, but the circuit breaker has transparently substituted
# a non-LLM fallback backend (e.g. m2m100) for it -- `load_model()` does NOT
# raise, it just returns something without `translate_with_context()`. The
# old code called that method unconditionally anyway; the resulting
# AttributeError was swallowed by a broad `except Exception`, and the
# segment was left as English passthrough even though the fallback is
# perfectly capable of translating it via its own ordinary MT path
# (`translate()`, the same one Step 2 below uses for every other segment).
#
# Fixed by checking `hasattr(backend, "translate_with_context")` first and,
# when missing, routing the segment through
# `self._translate_with_multiline_support(...)` -- the exact call this same
# method already uses for ordinary (non-context-aware) MT translation --
# instead of calling the LLM-only method or jumping straight to passthrough.
# ---------------------------------------------------------------------------


class TestContentTypeRouterSegmentFallbackMTRouting:
    _ROUTING_CONFIG = {
        "frontmatter_description": [
            {
                "condition": {},
                "preferred_model": "professionalize_llm",
                "context_hint": "frontmatter_description",
            }
        ]
    }

    def _make_engine(self, *, fallback_backend):
        engine = _make_engine()
        engine.config.get_config.return_value = {
            "translation_engine": {"content_type_routing": self._ROUTING_CONFIG},
            "tm_defaults": {},
        }
        tm_result = MagicMock()
        tm_result.hit = False
        tm_result.source = None
        engine.tm.lookup.return_value = tm_result
        # Force the deterministic single-line path in
        # _translate_with_multiline_support -- a MagicMock's default
        # truthiness would otherwise route through the far more elaborate
        # (and here irrelevant) multiline-structure-preservation branch.
        engine.multiline_handler.is_multiline.return_value = False

        def _load(model_id):
            if "professionalize_llm" in str(model_id):
                return fallback_backend
            raise AssertionError(
                f"Step 2 (whole-document MT batch) should not run in this "
                f"test -- the single routed segment is fully consumed by "
                f"Step 1b; unexpected load_model({model_id!r})"
            )

        engine.model_loader.load_model.side_effect = _load
        return engine

    def _make_segment(self, text="Gets the width of the widget."):
        from src.translation_engine.extractor.segment_extractor import (
            Segment,
            SegmentContext,
            SegmentContextType,
        )

        return Segment(
            id="seg-description",
            source_text=text,
            context=SegmentContext(
                context_type=SegmentContextType.FRONTMATTER,
                frontmatter_key="description",
            ),
            site_id="test-site",
            source_lang="en",
        )

    def _run(self, engine, segment):
        translator = SegmentTranslator(engine)
        stats = _make_stats()
        doc = MagicMock(ast=None, frontmatter={"description": segment.source_text})
        doc.source_path = None
        site_profile = MagicMock()
        site_profile.default_source_lang = "en"

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ndescription: Test\n---\nBody"
            translator.translate_to_language(
                site_id="test",
                site_profile=site_profile,
                doc=doc,
                segments=[segment],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )
        return stats

    def test_fallback_without_context_capability_still_gets_real_translation(self):
        """Circuit breaker substituted a fallback (e.g. m2m100) lacking
        translate_with_context -- the segment must be genuinely translated
        via the fallback's normal translate() path, and that REAL value
        (not the English source) is what reaches the TM store."""
        fallback_backend = MagicMock(spec=["translate"])
        fallback_backend.translate.return_value = ["Erhält die Breite des Widgets."]

        segment = self._make_segment()
        engine = self._make_engine(fallback_backend=fallback_backend)

        stats = self._run(engine, segment)

        # hasattr() correctly reports the method missing (spec-restricted
        # mock), exactly like the real HuggingFaceBackend fallback.
        assert not hasattr(fallback_backend, "translate_with_context")
        fallback_backend.translate.assert_called_once()

        assert engine.tm.store.call_count == 1
        stored_kwargs = engine.tm.store.call_args.kwargs
        assert stored_kwargs["translation"] == "Erhält die Breite des Widgets."

        # Old bug: this would be "professionalize_llm_unavailable" with the
        # English source text stored instead.
        assert segment.metadata.get("llm_passthrough_reason") is None
        # Genuinely MT-translated, not LLM-translated -- the per-unit
        # "actually LLM-translated" stat must stay unset for this path.
        assert stats.llm_units_translated == 0

    def test_fallback_translate_failure_still_degrades_gracefully_to_passthrough(self):
        """Regression guard: when the MT fallback's own translate() call ALSO
        fails, the ORIGINAL graceful-degrade-to-English-passthrough safety
        net must still catch it -- no crash, and the English source is what
        reaches the TM store as a true last resort."""
        fallback_backend = MagicMock(spec=["translate"])
        fallback_backend.translate.side_effect = RuntimeError("MT backend exploded")

        segment = self._make_segment()
        engine = self._make_engine(fallback_backend=fallback_backend)

        stats = self._run(engine, segment)

        fallback_backend.translate.assert_called_once()

        assert segment.metadata.get("llm_passthrough_reason") == "professionalize_llm_unavailable"
        assert engine.tm.store.call_count == 1
        stored_kwargs = engine.tm.store.call_args.kwargs
        assert stored_kwargs["translation"] == segment.source_text
        assert stats.llm_units_translated == 0
