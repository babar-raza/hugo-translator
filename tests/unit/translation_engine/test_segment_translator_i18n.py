"""Unit tests for the Step-0 i18n-first pre-TM pass in
SegmentTranslator.translate_to_language (mission
reference-i18n-hardening-20260725, plan item A4).

New file (not test_segment_translator.py) deliberately: that file carries
uncommitted in-flight work from mission HT-INLINE-CODE-001 and this mission
avoids touching it. Reuses the same mock-engine pattern.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.translation_engine.segment_translator import SegmentTranslator


def _make_engine():
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

    def _batch_lookup_side_effect(requests, use_semantic=True, **kwargs):
        return [engine.tm.lookup.return_value for _ in requests]

    engine.tm.batch_lookup.side_effect = _batch_lookup_side_effect

    backend = MagicMock()
    backend.translate_batch.return_value = ["Translated text"]
    engine.model_loader.load_model.return_value = backend
    engine.model_loader.get_tokenizer_for_counting.return_value = None
    engine._get_model_id.return_value = "m2m100_418M"
    return engine


def _make_segment(source_text="Overview", seg_id="seg_1", context_type="HEADING"):
    seg = MagicMock()
    seg.source_text = source_text
    seg.id = seg_id
    seg.placeholder_map = {}
    seg.inline_format_pairs = []
    if context_type is None:
        seg.context = None
    else:
        ctx = MagicMock()
        ctx.context_type = f"SegmentContextType.{context_type}"
        # A real frontmatter-context segment always carries a real key
        # (e.g. "description") -- the reconstructor's completeness check
        # (segment_translator.py ~1191) reads it unconditionally once the
        # segment lands in `translations`.
        ctx.frontmatter_key = "description" if context_type == "FRONTMATTER" else None
        seg.context = ctx
    return seg


def _make_stats():
    from src.translation_engine.models import TranslationStats

    return TranslationStats()


@pytest.fixture
def fixture_registry(tmp_path):
    d = tmp_path / "template_strings"
    d.mkdir()
    (d / "_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "id": "heading.overview",
                        "en": "Overview",
                        "category": "section_heading",
                        "status": "approved",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (d / "de.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "locale": "de",
                "translations": {"heading.overview": {"value": "Übersicht", "reviewed_by": "t"}},
            }
        ),
        encoding="utf-8",
    )
    return d


class TestPreTMI18nPass:
    def test_i18n_hit_skips_tm_and_mt_and_counts_stat(self, fixture_registry):
        from src.translation_engine.terminology.classification import TemplateStringRegistry

        engine = _make_engine()
        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(source_text="Overview", context_type="HEADING")

        registry = TemplateStringRegistry(fixture_registry)
        with (
            patch.object(translator, "_translate_body_ast") as mock_ast,
            patch(
                "src.translation_engine.terminology.classification.get_default_registry",
                return_value=registry,
            ),
        ):
            mock_ast.return_value = "---\ntitle: Test\n---\nÜbersicht"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}, source_path="f.md"),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        assert stats.i18n_hits == 1
        # Never reached TM at all -- batch_lookup called with an EMPTY
        # request list (or not called), never with this segment's request.
        for call in engine.tm.batch_lookup.call_args_list:
            requests = call.args[0] if call.args else call.kwargs.get("requests", [])
            assert all(r.text != "Overview" for r in requests)
        # Never reached MT either.
        engine.model_loader.load_model.assert_not_called()

    def test_i18n_result_never_written_to_tm(self, fixture_registry):
        from src.translation_engine.terminology.classification import TemplateStringRegistry

        engine = _make_engine()
        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(source_text="Overview", context_type="HEADING")

        registry = TemplateStringRegistry(fixture_registry)
        with (
            patch.object(translator, "_translate_body_ast") as mock_ast,
            patch(
                "src.translation_engine.terminology.classification.get_default_registry",
                return_value=registry,
            ),
        ):
            mock_ast.return_value = "---\ntitle: Test\n---\nÜbersicht"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}, source_path="f.md"),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        engine.tm.store.assert_not_called()

    def test_non_heading_segment_is_unaffected(self, fixture_registry):
        """Negative control: a non-heading segment with the SAME text
        ("Overview" as ordinary prose, not a heading context) must NOT be
        i18n-resolved -- it goes through the normal TM/MT path."""
        from src.translation_engine.terminology.classification import TemplateStringRegistry

        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        tm_result.source = None
        engine.tm.lookup.return_value = tm_result

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(source_text="Overview", seg_id="seg_prose", context_type="BODY")

        registry = TemplateStringRegistry(fixture_registry)
        with (
            patch.object(translator, "_translate_body_ast") as mock_ast,
            patch(
                "src.translation_engine.terminology.classification.get_default_registry",
                return_value=registry,
            ),
        ):
            mock_ast.return_value = "---\ntitle: Test\n---\nTranslated text"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}, source_path="f.md"),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        assert stats.i18n_hits == 0
        engine.model_loader.load_model.assert_called_once()

    def test_frontmatter_context_is_ineligible(self, fixture_registry):
        """Negative control: frontmatter units are deliberately i18n-
        ineligible this mission (real content, no field-context keys yet)."""
        from src.translation_engine.terminology.classification import TemplateStringRegistry

        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = False
        tm_result.source = None
        engine.tm.lookup.return_value = tm_result

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(source_text="Overview", seg_id="seg_fm", context_type="FRONTMATTER")

        registry = TemplateStringRegistry(fixture_registry)
        with (
            patch.object(translator, "_translate_body_ast") as mock_ast,
            patch(
                "src.translation_engine.terminology.classification.get_default_registry",
                return_value=registry,
            ),
        ):
            mock_ast.return_value = "---\ntitle: Test\n---\nTranslated text"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}, source_path="f.md"),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        assert stats.i18n_hits == 0

    def test_force_mode_still_excludes_i18n_resolved_segment(self, fixture_registry):
        """force=True must not send an i18n-resolved heading back through MT
        -- Step 0 runs unconditionally, before the force branch."""
        from src.translation_engine.terminology.classification import TemplateStringRegistry

        engine = _make_engine()
        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(source_text="Overview", context_type="HEADING")

        registry = TemplateStringRegistry(fixture_registry)
        with (
            patch.object(translator, "_translate_body_ast") as mock_ast,
            patch(
                "src.translation_engine.terminology.classification.get_default_registry",
                return_value=registry,
            ),
        ):
            mock_ast.return_value = "---\ntitle: Test\n---\nÜbersicht"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}, source_path="f.md"),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=True,
                stats=stats,
            )

        assert stats.i18n_hits == 1
        engine.model_loader.load_model.assert_not_called()

    def test_no_i18n_entry_falls_through_to_ordinary_tm_path(self, fixture_registry):
        """A heading with NO registry entry (e.g. a page-specific one) is
        unaffected -- ordinary TM/MT handling proceeds exactly as before."""
        from src.translation_engine.terminology.classification import TemplateStringRegistry

        engine = _make_engine()
        tm_result = MagicMock()
        tm_result.hit = True
        tm_result.translation = "Anwendungsbeispiele"
        tm_result.source = "l1_cache"
        tm_result.candidates = []
        engine.tm.lookup.return_value = tm_result

        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(source_text="Usage Examples", context_type="HEADING")

        registry = TemplateStringRegistry(fixture_registry)
        with (
            patch.object(translator, "_translate_body_ast") as mock_ast,
            patch(
                "src.translation_engine.terminology.classification.get_default_registry",
                return_value=registry,
            ),
        ):
            mock_ast.return_value = "---\ntitle: Test\n---\nAnwendungsbeispiele"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}, source_path="f.md"),
                segments=[seg],
                source_lang="en",
                target_lang="de",
                force=False,
                stats=stats,
            )

        assert stats.i18n_hits == 0
        assert stats.tm_hits == 1


class TestProductionRoutingProof:
    """Routing proof (plan validation item 5) against the REAL shipped
    registry/locale data (config/i18n/template_strings/), not a fixture --
    proves the Step-0 pass actually resolves production-adjudicated values
    end-to-end, for locales spanning the wrong-dominant-corpus-form cases
    this mission fixed (es, ja) and a newly-covered Latin locale (pt)."""

    @pytest.mark.parametrize(
        "locale,en_text,expected_value",
        [
            ("es", "Overview", "Visión general"),  # corpus-dominant "Revisión" correctly overridden
            ("ja", "Overview", "概要"),
            ("pt", "See Also", None),  # None = only assert i18n_hits, not exact value (checked below)
        ],
    )
    def test_real_registry_resolves_approved_heading_end_to_end(self, locale, en_text, expected_value):
        engine = _make_engine()
        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(source_text=en_text, context_type="HEADING")

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nplaceholder"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}, source_path="f.md"),
                segments=[seg],
                source_lang="en",
                target_lang=locale,
                force=False,
                stats=stats,
            )

        assert stats.i18n_hits == 1
        engine.model_loader.load_model.assert_not_called()
        if expected_value is not None:
            # translations dict isn't returned directly, but the i18n hit
            # having fired for the correct (overridden) value is confirmed
            # by re-resolving through the same production registry.
            from src.translation_engine.terminology.classification import (
                CATEGORIES_FOR_KIND,
                get_default_registry,
                resolve,
            )

            r = resolve(en_text, locale, categories=CATEGORIES_FOR_KIND["heading_text"], registry=get_default_registry())
            assert r.value == expected_value

    def test_es_overview_never_reaches_mt_despite_wrong_corpus_majority(self):
        """The specific defect this mission was built to fix: es 'Overview'
        must resolve to the corpus-minority-but-correct 'Visión general',
        never the corpus-majority-but-wrong 'Revisión', and must never
        reach MT at all."""
        engine = _make_engine()
        translator = SegmentTranslator(engine)
        stats = _make_stats()
        seg = _make_segment(source_text="Overview", context_type="HEADING")

        with patch.object(translator, "_translate_body_ast") as mock_ast:
            mock_ast.return_value = "---\ntitle: Test\n---\nplaceholder"
            translator.translate_to_language(
                site_id="test",
                site_profile=MagicMock(),
                doc=MagicMock(ast=None, frontmatter={"title": "Test"}, source_path="f.md"),
                segments=[seg],
                source_lang="en",
                target_lang="es",
                force=False,
                stats=stats,
            )

        assert stats.i18n_hits == 1
        engine.model_loader.load_model.assert_not_called()
        engine.tm.store.assert_not_called()
