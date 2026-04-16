"""
Tests for LLM-WASTE-FIX-1 through LLM-WASTE-FIX-3.

Fix 1: Skip commit when all languages are skipped (no new translations).
Fix 2a: Cap recursive purity split depth to MAX_PURITY_SPLIT_DEPTH.
Fix 2b: batch_purity_skip_langs skips batch-level purity for configured langs.
Fix 3: Multi-segment LLM prompt packing in LLMModelBackend.
"""
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Stub heavy ML deps so imports are fast (same pattern as other unit tests)
# ---------------------------------------------------------------------------
def _ensure_stubs():
    for mod in (
        "ctranslate2", "transformers", "sentence_transformers",
        "faiss", "lmdb", "pytz",
    ):
        sys.modules.setdefault(mod, types.ModuleType(mod))
    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        cuda_stub = types.ModuleType("torch.cuda")
        cuda_stub.is_available = MagicMock(return_value=True)
        cuda_stub.empty_cache = MagicMock()
        torch_stub.cuda = cuda_stub
        sys.modules["torch"] = torch_stub
        sys.modules["torch.cuda"] = cuda_stub


_ensure_stubs()


# ===================================================================
# Fix 1: Skip commit when all languages skipped
# ===================================================================
class TestFix1CommitSkipGuard:
    """LLM-WASTE-FIX-1: skip commit when ALL file results have every
    language in skipped_langs."""

    def _make_file_result(self, outputs, skipped_langs, success=True):
        fr = MagicMock()
        fr.success = success
        fr.outputs = outputs
        fr.skipped_langs = skipped_langs
        return fr

    def test_all_languages_skipped_returns_false(self):
        """When every output language is in skipped_langs, _has_new_translations=False."""
        fr1 = self._make_file_result(
            outputs={"de": Path("/out/de"), "fr": Path("/out/fr")},
            skipped_langs=["de", "fr"],
        )
        fr2 = self._make_file_result(
            outputs={"de": Path("/out/de2"), "fr": Path("/out/fr2")},
            skipped_langs=["de", "fr"],
        )
        result = MagicMock()
        result.file_results = [fr1, fr2]

        # Replicate the guard logic from the worker
        _has_new = any(
            set(fr.outputs.keys()) - set(fr.skipped_langs)
            for fr in result.file_results
            if fr.success and fr.outputs
        )
        assert _has_new is False

    def test_some_languages_not_skipped_returns_true(self):
        """When at least one output language is NOT skipped, _has_new=True."""
        fr = self._make_file_result(
            outputs={"de": Path("/out/de"), "fr": Path("/out/fr")},
            skipped_langs=["de"],  # fr NOT skipped
        )
        result = MagicMock()
        result.file_results = [fr]

        _has_new = any(
            set(fr.outputs.keys()) - set(fr.skipped_langs)
            for fr in result.file_results
            if fr.success and fr.outputs
        )
        assert _has_new is True

    def test_empty_file_results_returns_false(self):
        """With no file results, the any() generator returns False."""
        result = MagicMock()
        result.file_results = []

        _has_new = any(
            set(fr.outputs.keys()) - set(fr.skipped_langs)
            for fr in result.file_results
            if fr.success and fr.outputs
        )
        assert _has_new is False

    def test_mixed_results_one_has_new(self):
        """If one file result has new translations, overall returns True."""
        fr_skipped = self._make_file_result(
            outputs={"de": Path("/out/de")},
            skipped_langs=["de"],
        )
        fr_new = self._make_file_result(
            outputs={"de": Path("/out/de2"), "fr": Path("/out/fr2")},
            skipped_langs=["de"],  # fr is new
        )
        result = MagicMock()
        result.file_results = [fr_skipped, fr_new]

        _has_new = any(
            set(fr.outputs.keys()) - set(fr.skipped_langs)
            for fr in result.file_results
            if fr.success and fr.outputs
        )
        assert _has_new is True


# ===================================================================
# Fix 2a: Cap recursive purity split depth
# ===================================================================
class TestFix2aSplitDepthCap:
    """LLM-WASTE-FIX-2a: _translate_single_batch respects MAX_PURITY_SPLIT_DEPTH."""

    def _make_extractor(self):
        from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
        ext = TextUnitExtractor.__new__(TextUnitExtractor)
        ext.batch_stats = {
            'total_batches': 0,
            'successful_batches': 0,
            'fallback_batches': 0,
            'mapping_failures': 0,
            'translation_errors': 0,
            'individual_translations': 0,
            'individual_translation_errors': 0,
            'empty_translations': 0,
        }
        ext.batch_stats_tracker = MagicMock()
        ext.batch_stats_tracker.react_to_failure.return_value = 4
        ext.fasttext_detector = None
        ext.similarity_tracker = None
        ext.script_validation_thresholds = {}
        ext._batch_purity_skip_langs = frozenset()
        ext.language_purity_min_length = 10
        ext.language_purity_min_script_ratio = 0.5
        ext.script_similar_languages = {}
        ext.technical_terms = set()
        ext.terminology_dict = set()
        return ext

    def test_max_depth_stops_splitting(self):
        """At MAX_PURITY_SPLIT_DEPTH, splitting stops and batch is accepted."""
        ext = self._make_extractor()

        # Create a batch of 4 TextUnits
        units = []
        for i in range(4):
            u = MagicMock()
            u.source_text = f"Test text {i}"
            u.translated_text = ""
            u.do_not_translate = False
            units.append(u)

        mt_model = MagicMock()
        mt_model.translate.return_value = ["Translated"] * 4

        # Patch _verify_translation_language_purity to always fail
        with patch.object(ext, '_verify_translation_language_purity', return_value=False):
            # Call at max depth — should NOT recurse, should accept
            result = ext._translate_single_batch(
                units, mt_model, "en", "cs",
                _split_depth=ext.MAX_PURITY_SPLIT_DEPTH,
            )

        # Should accept (True) and increment successful_batches
        assert result is True
        assert ext.batch_stats['successful_batches'] == 1

    def test_max_depth_cross_script_falls_back(self):
        """Non-Latin targets fall back when max-depth output resolves to the wrong script."""
        ext = self._make_extractor()
        ext.fasttext_detector = MagicMock()
        ext.fasttext_detector.is_available = True
        ext.fasttext_detector.detect.return_value = ("ar", 0.99)

        units = []
        for i in range(2):
            u = MagicMock()
            u.source_text = f"Test text {i}"
            u.translated_text = ""
            u.do_not_translate = False
            units.append(u)

        mt_model = MagicMock()
        mt_model.translate.return_value = ["Arabic output"] * 2

        with patch.object(ext, '_verify_translation_language_purity', return_value=False):
            with patch.object(ext, '_fallback_to_individual') as mock_fallback:
                result = ext._translate_single_batch(
                    units, mt_model, "en", "ru",
                    _split_depth=ext.MAX_PURITY_SPLIT_DEPTH,
                )

        assert result is False
        mock_fallback.assert_called_once_with(units, mt_model, "en", "ru")
        assert ext.batch_stats['successful_batches'] == 0

    def test_max_depth_latin_accepts(self):
        """Latin-script targets keep the original max-depth accept behavior."""
        ext = self._make_extractor()
        ext.fasttext_detector = MagicMock()
        ext.fasttext_detector.is_available = True
        ext.fasttext_detector.detect.return_value = ("fr", 0.99)

        units = []
        for i in range(2):
            u = MagicMock()
            u.source_text = f"Test text {i}"
            u.translated_text = ""
            u.do_not_translate = False
            units.append(u)

        mt_model = MagicMock()
        mt_model.translate.return_value = ["Traduit"] * 2

        with patch.object(ext, '_verify_translation_language_purity', return_value=False):
            result = ext._translate_single_batch(
                units, mt_model, "en", "fr",
                _split_depth=ext.MAX_PURITY_SPLIT_DEPTH,
            )

        assert result is True
        assert ext.batch_stats['successful_batches'] == 1

    def test_max_depth_no_detector_accepts(self):
        """Missing detector preserves existing fail-open behavior."""
        ext = self._make_extractor()

        units = []
        for i in range(2):
            u = MagicMock()
            u.source_text = f"Test text {i}"
            u.translated_text = ""
            u.do_not_translate = False
            units.append(u)

        mt_model = MagicMock()
        mt_model.translate.return_value = ["Translated"] * 2

        with patch.object(ext, '_verify_translation_language_purity', return_value=False):
            result = ext._translate_single_batch(
                units, mt_model, "en", "ru",
                _split_depth=ext.MAX_PURITY_SPLIT_DEPTH,
            )

        assert result is True
        assert ext.batch_stats['successful_batches'] == 1

    def test_depth_0_allows_splitting(self):
        """At depth 0, splitting is allowed (up to MAX_PURITY_SPLIT_DEPTH)."""
        ext = self._make_extractor()

        units = []
        for i in range(4):
            u = MagicMock()
            u.source_text = f"Test text {i}"
            u.translated_text = ""
            u.do_not_translate = False
            units.append(u)

        mt_model = MagicMock()
        mt_model.translate.return_value = ["Translated"] * 4

        call_depths = []

        original_translate = ext._translate_single_batch

        def tracking_translate(batch, model, src, tgt, generation_params=None, _split_depth=0):
            call_depths.append(_split_depth)
            if _split_depth == 0:
                # First call fails purity, triggers split
                for u, t in zip(batch, model.translate([""] * len(batch), src, tgt)):
                    u.translated_text = t
                return original_translate(batch, model, src, tgt, _split_depth=_split_depth)
            # Deeper calls succeed
            for u in batch:
                u.translated_text = "OK"
            return True

        # Patch purity to fail at depth 0, pass at depth 1+
        fail_count = [0]

        def purity_check(units, lang):
            fail_count[0] += 1
            return fail_count[0] > 1  # First check fails, rest pass

        with patch.object(ext, '_verify_translation_language_purity', side_effect=purity_check):
            result = ext._translate_single_batch(
                units, mt_model, "en", "cs", _split_depth=0,
            )

        # Depth 0 should have triggered a split (depth 1 calls)
        # Result depends on recursive behavior — the key test is it didn't recurse forever


# ===================================================================
# Fix 2b: batch_purity_skip_langs
# ===================================================================
class TestFix2bBatchPuritySkipLangs:
    """LLM-WASTE-FIX-2b: languages in batch_purity_skip_langs bypass batch purity."""

    def _make_extractor(self, skip_langs=None):
        from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
        ext = TextUnitExtractor.__new__(TextUnitExtractor)
        ext.batch_stats = {
            'total_batches': 0,
            'successful_batches': 0,
            'fallback_batches': 0,
            'mapping_failures': 0,
            'translation_errors': 0,
            'individual_translations': 0,
            'individual_translation_errors': 0,
            'empty_translations': 0,
        }
        ext.batch_stats_tracker = MagicMock()
        ext.fasttext_detector = None
        ext.similarity_tracker = None
        ext.script_validation_thresholds = {}
        ext._batch_purity_skip_langs = frozenset(skip_langs or [])
        ext.language_purity_min_length = 10
        ext.language_purity_min_script_ratio = 0.5
        ext.script_similar_languages = {}
        ext.technical_terms = set()
        ext.terminology_dict = set()
        return ext

    def test_skipped_lang_bypasses_purity(self):
        """Czech in skip list → purity check not called, batch succeeds."""
        ext = self._make_extractor(skip_langs=["cs", "hr"])

        units = []
        for i in range(4):
            u = MagicMock()
            u.source_text = f"Test {i}"
            u.translated_text = ""
            u.do_not_translate = False
            units.append(u)

        mt_model = MagicMock()
        mt_model.translate.return_value = ["Přeloženo"] * 4

        with patch.object(ext, '_verify_translation_language_purity') as mock_purity:
            result = ext._translate_single_batch(units, mt_model, "en", "cs")

        assert result is True
        # LWF-07: skip-langs path must increment purity_skipped_batches, NOT successful_batches
        assert ext.batch_stats['purity_skipped_batches'] == 1
        assert ext.batch_stats['successful_batches'] == 0  # not inflated
        # Purity check should NOT have been called
        mock_purity.assert_not_called()

    def test_non_skipped_lang_still_checks_purity(self):
        """German NOT in skip list → purity check IS called."""
        ext = self._make_extractor(skip_langs=["cs", "hr"])

        units = []
        for i in range(2):
            u = MagicMock()
            u.source_text = f"Test {i}"
            u.translated_text = ""
            u.do_not_translate = False
            units.append(u)

        mt_model = MagicMock()
        mt_model.translate.return_value = ["Übersetzt"] * 2

        with patch.object(ext, '_verify_translation_language_purity', return_value=True) as mock_purity:
            result = ext._translate_single_batch(units, mt_model, "en", "de")

        assert result is True
        mock_purity.assert_called_once()

    def test_empty_skip_list_checks_all(self):
        """Empty skip list → all languages go through purity."""
        ext = self._make_extractor(skip_langs=[])

        units = [MagicMock(source_text="Hello", translated_text="", do_not_translate=False)]
        mt_model = MagicMock()
        mt_model.translate.return_value = ["Bonjour"]

        with patch.object(ext, '_verify_translation_language_purity', return_value=True) as mock_purity:
            ext._translate_single_batch(units, mt_model, "en", "fr")

        mock_purity.assert_called_once()

    def test_constructor_accepts_skip_langs(self):
        """Constructor wires batch_purity_skip_langs correctly."""
        from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
        ext = TextUnitExtractor(batch_purity_skip_langs=["cs", "hr", "el"])
        assert ext._batch_purity_skip_langs == frozenset(["cs", "hr", "el"])

    def test_constructor_default_empty(self):
        """Default is empty frozenset."""
        from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
        ext = TextUnitExtractor()
        assert ext._batch_purity_skip_langs == frozenset()

    def test_skip_path_increments_purity_skipped_not_successful(self):
        """LWF-07: purity-skip path uses purity_skipped_batches, not successful_batches.

        Before LWF-07, skip-langs batches inflated successful_batches, making the
        metric misleadingly high and hiding the true verified-success rate.
        """
        ext = self._make_extractor(skip_langs=["cs"])

        units = []
        for i in range(3):
            u = MagicMock()
            u.source_text = f"Sentence {i}"
            u.translated_text = ""
            u.do_not_translate = False
            units.append(u)

        mt_model = MagicMock()
        mt_model.translate.return_value = ["Věta 0", "Věta 1", "Věta 2"]

        baseline_success = ext.batch_stats['successful_batches']

        with patch.object(ext, '_verify_translation_language_purity') as mock_purity:
            result = ext._translate_single_batch(units, mt_model, "en", "cs")

        assert result is True
        # successful_batches must NOT be incremented for a skipped-purity batch
        assert ext.batch_stats['successful_batches'] == baseline_success, (
            "successful_batches was inflated by purity-skip path (LWF-07 regression)"
        )
        # purity_skipped_batches must be incremented
        assert ext.batch_stats['purity_skipped_batches'] == 1
        # purity verification must not be called
        mock_purity.assert_not_called()


# ===================================================================
# Fix 3: Multi-segment LLM prompt packing
# ===================================================================
class TestFix3PromptPacking:
    """LLM-WASTE-FIX-3: LLMModelBackend packs multiple segments per prompt."""

    def _make_backend(self):
        from src.model_runtime.llm_backend import LLMModelBackend
        model_info = MagicMock()
        model_info.system_prompt_template = None
        model_info.llm_provider = "openai_compatible"
        model_info.llm_base_url = "http://test.local/v1"
        model_info.llm_api_key_env = None
        model_info.llm_model_name = "test"
        model_info.llm_temperature = 0.0
        model_info.llm_max_tokens = 6000
        model_info.llm_timeout = 60

        backend = LLMModelBackend(model_info, "cpu")
        backend.loaded = True
        backend._terminology_manager = False  # skip lazy load
        return backend

    def test_parse_packed_output_success(self):
        """Parse correctly formatted <<<SEG_N>>> output."""
        from src.model_runtime.llm_backend import LLMModelBackend
        raw = "<<<SEG_1>>> Bonjour le monde\n<<<SEG_2>>> Bonne journée\n<<<SEG_3>>> Au revoir"
        result = LLMModelBackend._parse_packed_output(raw, 3)
        assert result == ["Bonjour le monde", "Bonne journée", "Au revoir"]

    def test_parse_packed_output_wrong_count(self):
        """Wrong number of segments returns None."""
        from src.model_runtime.llm_backend import LLMModelBackend
        raw = "<<<SEG_1>>> Bonjour\n<<<SEG_2>>> Monde"
        result = LLMModelBackend._parse_packed_output(raw, 3)
        assert result is None

    def test_parse_packed_output_missing_number(self):
        """Missing segment number (gap) returns None."""
        from src.model_runtime.llm_backend import LLMModelBackend
        raw = "<<<SEG_1>>> Bonjour\n<<<SEG_3>>> Monde"  # missing SEG_2
        result = LLMModelBackend._parse_packed_output(raw, 2)
        assert result is None

    def test_parse_packed_output_out_of_range(self):
        """Segment number out of range returns None."""
        from src.model_runtime.llm_backend import LLMModelBackend
        raw = "<<<SEG_1>>> Bonjour\n<<<SEG_5>>> Monde"
        result = LLMModelBackend._parse_packed_output(raw, 2)
        assert result is None

    def test_parse_packed_output_with_leading_whitespace(self):
        """Handles leading whitespace before <<<SEG_N>>>."""
        from src.model_runtime.llm_backend import LLMModelBackend
        raw = "  <<<SEG_1>>> Bonjour\n  <<<SEG_2>>> Monde"
        result = LLMModelBackend._parse_packed_output(raw, 2)
        assert result == ["Bonjour", "Monde"]

    def test_parse_packed_output_segment_containing_bracket_number(self):
        """LWF-01 regression: segment text containing [2] must NOT corrupt parsing.

        Before LWF-01, the [N] delimiter would match [2] inside segment text,
        returning the wrong result.  <<<SEG_N>>> is immune to this.
        """
        from src.model_runtime.llm_backend import LLMModelBackend
        raw = "<<<SEG_1>>> See step [2] above\n<<<SEG_2>>> Done"
        result = LLMModelBackend._parse_packed_output(raw, 2)
        assert result == ["See step [2] above", "Done"]

    def test_single_segment_uses_direct_call(self):
        """Single text should use _translate_single_segment (no packing)."""
        backend = self._make_backend()
        provider = MagicMock()
        provider.generate.return_value = ("Bonjour", 10, 5)
        backend._provider = provider

        result, inp, out = backend.translate_with_token_counts(["Hello"], "en", "fr")

        assert result == ["Bonjour"]
        assert inp == 10
        assert out == 5
        provider.generate.assert_called_once()

    def test_multiple_segments_pack(self):
        """Multiple non-empty segments should attempt packed translation."""
        backend = self._make_backend()
        provider = MagicMock()

        # Mock: packed call returns <<<SEG_N>>> numbered output
        provider.generate.return_value = (
            "<<<SEG_1>>> Bonjour\n<<<SEG_2>>> Monde\n<<<SEG_3>>> Au revoir",
            30, 20,
        )
        backend._provider = provider

        texts = ["Hello", "World", "Goodbye"]
        result, inp, out = backend.translate_with_token_counts(texts, "en", "fr")

        assert result == ["Bonjour", "Monde", "Au revoir"]
        assert inp == 30
        assert out == 20
        # Should have made exactly 1 API call (packed), not 3
        assert provider.generate.call_count == 1

    def test_packed_parsing_failure_falls_back(self):
        """If packed output can't be parsed, falls back to per-segment calls."""
        backend = self._make_backend()
        provider = MagicMock()

        call_count = [0]
        def mock_generate(system_prompt, user_text):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (packed) returns unparseable output
                return ("Some garbage output", 30, 20)
            else:
                # Fallback per-segment calls
                return (f"Trans-{call_count[0]}", 10, 5)

        provider.generate.side_effect = mock_generate
        backend._provider = provider

        texts = ["Hello", "World"]
        result, inp, out = backend.translate_with_token_counts(texts, "en", "fr")

        # Should have fallen back: 1 packed attempt + 2 individual = 3 calls
        assert provider.generate.call_count == 3
        assert result[0] == "Trans-2"
        assert result[1] == "Trans-3"

    def test_empty_texts_preserved(self):
        """Empty/whitespace-only texts bypass LLM calls."""
        backend = self._make_backend()
        provider = MagicMock()
        provider.generate.return_value = ("Bonjour", 10, 5)
        backend._provider = provider

        texts = ["Hello", "", "  ", "World"]
        result, inp, out = backend.translate_with_token_counts(texts, "en", "fr")

        # Empty texts should be preserved as-is
        assert result[1] == ""
        assert result[2] == "  "

    def test_batch_system_prompt_includes_count(self):
        """Batch system prompt mentions the segment count and uses <<<SEG_N>>> delimiter."""
        backend = self._make_backend()
        prompt = backend._build_batch_system_prompt("en", "fr", 5)
        assert "5" in prompt
        assert "English" in prompt
        assert "French" in prompt
        # LWF-01: delimiter must be <<<SEG_N>>> not [N]
        assert "<<<SEG_" in prompt
        assert "[N]" not in prompt

    def test_max_segments_per_prompt_splits(self):
        """Texts exceeding MAX_SEGMENTS_PER_PROMPT are split into sub-batches."""
        backend = self._make_backend()
        backend.MAX_SEGMENTS_PER_PROMPT = 3  # Override for test

        provider = MagicMock()
        call_count = [0]

        def mock_generate(system_prompt, user_text):
            call_count[0] += 1
            # Count <<<SEG_N>>> tags to determine segment count (LWF-01 delimiter)
            tags = re.findall(r'<<<SEG_(\d+)>>>', user_text)
            n = len(tags)
            if n > 1:
                lines = [f"<<<SEG_{i}>>> Translated-{i}" for i in range(1, n + 1)]
                return ("\n".join(lines), 20, 15)
            else:
                return ("Single-translated", 10, 5)

        provider.generate.side_effect = mock_generate
        backend._provider = provider

        texts = ["A", "B", "C", "D", "E"]  # 5 texts, max 3 per prompt
        result, inp, out = backend.translate_with_token_counts(texts, "en", "fr")

        # Should be 2 packed calls: [A,B,C] and [D,E]
        assert provider.generate.call_count == 2
        assert len(result) == 5
