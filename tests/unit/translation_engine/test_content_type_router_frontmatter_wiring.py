"""TC-HT-ROUTE-001: ContentTypeRouter must actually reach frontmatter output.

Root cause (DELIVERABLE 53, Root Cause 2): ContentTypeRouter was wired into
the AST/body path only. Frontmatter fields (description, title, summary, ...)
flow exclusively through the "segments" system in
`SegmentTranslator.translate_to_language()`, which never consulted the
router -- so `content_type_routing.frontmatter_description` was configured
but dead: a TM miss on a short, decontextualized description always went to
raw MT (which can hallucinate) instead of the configured LLM backend.

This is a wiring test, not a test of the router's own matching logic (already
covered by test_content_type_router.py) -- it proves the routed translation
actually reaches the final reconstructed document string, not just that the
router *would* route it.
"""

from unittest.mock import MagicMock, patch

from src.translation_engine.segment_translator import SegmentTranslator


def _make_engine(content_type_routing=None):
    engine = MagicMock()
    engine.config.get_config.return_value = {
        "translation_engine": {
            "content_type_routing": content_type_routing or {},
        },
        "tm_defaults": {},
    }
    engine.batch_size = 16
    engine.sort_segments_by_length = False
    engine.terminology_manager = None
    engine.cache_write_mode = "auto"
    engine._l3 = None
    engine._check_shutdown.return_value = False
    # Force the singleline path in _translate_with_multiline_support -- a
    # bare MagicMock's is_multiline() would otherwise return a truthy Mock
    # for every segment, silently skipping the batch-translate call this
    # test needs to observe.
    engine.multiline_handler.is_multiline.return_value = False

    tm_miss = MagicMock()
    tm_miss.hit = False
    tm_miss.source = None

    def _batch_lookup_side_effect(requests, use_semantic=True, **kwargs):
        return [tm_miss for _ in requests]

    engine.tm.batch_lookup.side_effect = _batch_lookup_side_effect
    engine.tm.store.return_value = True
    engine.model_loader.get_tokenizer_for_counting.return_value = None
    engine._get_model_id.return_value = "m2m100_418M"

    return engine


def _make_mt_backend(translation_text):
    """MT backend mock using the method _translate_with_multiline_support
    actually calls (translate_with_token_counts), not translate_batch."""
    backend = MagicMock()
    backend.translate_with_token_counts.side_effect = lambda texts, src, tgt: (
        [translation_text] * len(texts),
        0,
        0,
    )
    return backend


_SITE_ID = "reference.aspose.org"


def _make_site_profile():
    """MarkdownReconstructor.reconstruct_frontmatter iterates a REAL
    site_profile.frontmatter dict of FrontmatterRule and recomputes the
    segment id via Segment.create_id(original_text, context, site_id) to
    look up translations -- a bare MagicMock().frontmatter.items() silently
    iterates as empty, and a MagicMock site_id breaks id recomputation. Both
    must be real for an end-to-end reconstruction assertion to mean anything."""
    from src.utils.models import FrontmatterMode, FrontmatterRule

    profile = MagicMock()
    profile.site_id = _SITE_ID
    profile.frontmatter = {"description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE)}
    return profile


def _make_segment(source_text, frontmatter_key, tm_key_text=None):
    """Builds a segment whose id matches what MarkdownReconstructor will
    recompute via Segment.create_id(original_text, context, site_id) when
    resolving translations -- using an arbitrary id would silently no-op the
    reconstruction (translation looked up, not found, original EN text kept)."""
    from src.translation_engine.extractor.segment_extractor import (
        Segment,
        SegmentContext,
        SegmentContextType,
    )

    context = SegmentContext(
        context_type=SegmentContextType.FRONTMATTER, frontmatter_key=frontmatter_key
    )
    seg = MagicMock()
    seg.source_text = source_text
    seg.tm_key_text = tm_key_text
    seg.id = Segment.create_id(source_text, context, _SITE_ID)
    seg.context = context
    seg.placeholder_map = {}
    seg.protected_terms = []
    seg.metadata = None
    seg.inline_format_pairs = []
    return seg


def _make_stats():
    from src.translation_engine.models import TranslationStats

    return TranslationStats()


_ROUTING_CONFIG = {
    "frontmatter_description": [
        {
            "condition": {},
            "preferred_model": "professionalize_llm",
            "context_hint": "frontmatter_description",
        }
    ],
}

_ALIGNMENT_DESC = "`Alignment` class with 1 method and 8 properties"


class TestFrontmatterDescriptionReachesLlmBackend:
    def test_routed_description_translation_reaches_final_translations_dict(self):
        """The concrete gap: a marker string returned only by the mocked LLM
        backend must appear in the file that's actually reconstructed."""
        engine = _make_engine(content_type_routing=_ROUTING_CONFIG)

        llm_backend = MagicMock()
        llm_backend.translate_with_context.return_value = ["LLM_MARKER_TRANSLATION"]
        mt_backend = _make_mt_backend("should not be used")

        def _load_model(model_id):
            if model_id == "professionalize_llm":
                return llm_backend
            return mt_backend

        engine.model_loader.load_model.side_effect = _load_model

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(_ALIGNMENT_DESC, "description", tm_key_text=_ALIGNMENT_DESC)
        doc = MagicMock(ast=None, frontmatter={"description": _ALIGNMENT_DESC}, output_path=None)

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = ""
            result = translator.translate_to_language(
                site_id="reference.aspose.org",
                site_profile=_make_site_profile(),
                doc=doc,
                segments=[seg],
                source_lang="en",
                target_lang="uk",
                force=False,
                stats=stats,
            )

        # End-to-end: the marker only the mocked LLM backend can produce must
        # appear in the FINAL reconstructed document string, not merely be
        # something the router "would" have chosen.
        assert "LLM_MARKER_TRANSLATION" in result
        llm_backend.translate_with_context.assert_called_once()
        # MT backend must never see this segment -- routing removes it from
        # the batch entirely rather than escalating only after MT is tried.
        mt_backend.translate_with_token_counts.assert_not_called()
        # And the store call used the un-collided TM key (Option A0), proving
        # both fixes compose correctly for a routed segment.
        engine.tm.store.assert_called_once()
        assert engine.tm.store.call_args.kwargs["text"] == _ALIGNMENT_DESC

    def test_routed_description_receives_governed_retry_feedback(self):
        engine = _make_engine(content_type_routing=_ROUTING_CONFIG)
        llm_backend = MagicMock()
        llm_backend.translate_with_context.return_value = ["हिंदी विवरण"]
        engine.model_loader.load_model.return_value = llm_backend
        translator = SegmentTranslator(engine)
        seg = _make_segment(_ALIGNMENT_DESC, "description")
        doc = MagicMock(
            ast=None,
            frontmatter={"description": _ALIGNMENT_DESC},
            output_path=None,
        )

        with patch.object(translator, "_translate_body_ast", return_value=""):
            translator.translate_to_language(
                site_id="blog.aspose.org",
                site_profile=_make_site_profile(),
                doc=doc,
                segments=[seg],
                source_lang="en",
                target_lang="hi",
                force=False,
                stats=_make_stats(),
                retry_feedback="Translate description fully into hi.",
            )

        hint = llm_backend.translate_with_context.call_args.kwargs["context_hint"]
        assert "frontmatter_description" in hint
        assert "Translate description fully into hi." in hint

    def test_llm_failure_falls_back_to_passthrough_not_mt(self):
        """TC-LLM-AVAIL-001-style graceful degrade: on LLM failure, keep the
        original text rather than sending it to raw MT (which hallucinates
        worse on decontextualized short strings than plain English does)."""
        engine = _make_engine(content_type_routing=_ROUTING_CONFIG)

        llm_backend = MagicMock()
        llm_backend.translate_with_context.side_effect = ConnectionError("LLM down")
        mt_backend = _make_mt_backend("should not be used")

        def _load_model(model_id):
            if model_id == "professionalize_llm":
                return llm_backend
            return mt_backend

        engine.model_loader.load_model.side_effect = _load_model

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(_ALIGNMENT_DESC, "description")
        doc = MagicMock(ast=None, frontmatter={"description": _ALIGNMENT_DESC}, output_path=None)

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = ""
            result = translator.translate_to_language(
                site_id="reference.aspose.org",
                site_profile=_make_site_profile(),
                doc=doc,
                segments=[seg],
                source_lang="en",
                target_lang="uk",
                force=False,
                stats=stats,
            )

        assert _ALIGNMENT_DESC in result
        mt_backend.translate_with_token_counts.assert_not_called()

    def test_no_routing_config_leaves_segments_path_unchanged(self):
        """When content_type_routing is empty (existing production default for
        most sites), the new Step 1b block must be a no-op -- prose/body
        frontmatter segments continue through the pre-existing MT path."""
        engine = _make_engine(content_type_routing={})
        mt_backend = _make_mt_backend("MT translated")
        engine.model_loader.load_model.return_value = mt_backend

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(_ALIGNMENT_DESC, "description")
        doc = MagicMock(ast=None, frontmatter={"description": _ALIGNMENT_DESC}, output_path=None)

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = ""
            translator.translate_to_language(
                site_id="reference.aspose.org",
                site_profile=_make_site_profile(),
                doc=doc,
                segments=[seg],
                source_lang="en",
                target_lang="uk",
                force=False,
                stats=stats,
            )

        mt_backend.translate_with_token_counts.assert_called()
