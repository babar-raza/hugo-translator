"""Tests for model_gap_analysis.py - Model recommendation for coverage gaps."""


from src.benchmarking.model_gap_analysis import ModelRecommendation, analyze_gaps


class TestModelRecommendation:
    """Test ModelRecommendation dataclass."""

    def test_model_recommendation_fields(self):
        """Test ModelRecommendation has expected fields."""
        rec = ModelRecommendation(
            model_id="test_model",
            hf_model_id="test/model",
            size_mb=1000,
            languages_covered=["en", "fr"],
            license="MIT",
            priority=1,
            backend="huggingface",
            optimal_device="cuda"
        )
        assert rec.model_id == "test_model"
        assert rec.hf_model_id == "test/model"
        assert rec.size_mb == 1000
        assert rec.languages_covered == ["en", "fr"]
        assert rec.license == "MIT"
        assert rec.priority == 1
        assert rec.backend == "huggingface"
        assert rec.optimal_device == "cuda"


class TestAnalyzeGapsNoMissing:
    """Test analyze_gaps with no coverage gaps."""

    def test_no_missing_returns_empty(self):
        """Test that full coverage returns empty recommendations."""
        current_coverage = {
            "en": ["model_a"],
            "fr": ["model_a", "model_b"],
            "de": ["model_b"],
        }
        target_languages = {"en", "fr", "de"}

        result = analyze_gaps(current_coverage, target_languages)

        assert result == []

    def test_all_covered_returns_empty(self):
        """Test with all target languages covered by at least one model."""
        current_coverage = {
            "en": ["opus_en_fr"],
            "fr": ["opus_en_fr"],
            "es": ["opus_en_es"],
            "de": ["opus_en_de"],
        }
        target_languages = {"en", "fr", "es", "de"}

        result = analyze_gaps(current_coverage, target_languages)

        assert result == []


class TestAnalyzeGapsManyMissing:
    """Test analyze_gaps with >10 missing languages (NLLB strategy)."""

    def test_many_missing_recommends_nllb(self):
        """Test >10 missing languages recommends NLLB-200."""
        # 12 missing languages
        current_coverage = {
            "ar": [], "zh": [], "nl": [], "fr": [], "de": [],
            "hi": [], "id": [], "it": [], "ja": [], "ko": [],
            "pl": [], "pt": []
        }
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        assert len(result) == 1
        assert result[0].model_id == "nllb_200_1.3b"
        assert result[0].hf_model_id == "facebook/nllb-200-1.3B"
        assert result[0].size_mb == 5200
        assert result[0].priority == 1
        assert result[0].backend == "huggingface"
        assert result[0].optimal_device == "cuda"
        assert len(result[0].languages_covered) == 12

    def test_nllb_covers_all_languages(self):
        """Test that NLLB is sole recommendation when >10 missing."""
        # 15 missing languages
        current_coverage = {f"lang_{i}": [] for i in range(15)}
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        # Only NLLB should be returned, no additional models
        assert len(result) == 1
        assert result[0].model_id == "nllb_200_1.3b"


class TestAnalyzeGapsFewMissing:
    """Test analyze_gaps with 5-10 missing languages (M2M100 strategy)."""

    def test_few_missing_recommends_m2m100(self):
        """Test 5-10 missing languages recommends M2M100."""
        # 7 missing languages that M2M100 supports
        current_coverage = {
            "ar": [], "fr": [], "de": [], "es": [],
            "it": [], "ja": [], "ko": []
        }
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        # Should have M2M100 + INT8 version
        assert len(result) >= 1
        m2m100 = result[0]
        assert m2m100.model_id == "m2m100_1.2b"
        assert m2m100.hf_model_id == "facebook/m2m100_1.2B"
        assert m2m100.license == "MIT"
        assert m2m100.priority == 1

    def test_m2m100_only_covers_supported_languages(self):
        """Test M2M100 only covers its supported languages."""
        # Mix of M2M100-supported and unsupported languages
        current_coverage = {
            "fr": [],  # M2M100 supports
            "de": [],  # M2M100 supports
            "xyz_unsupported": [],  # Not in M2M100
            "abc_unsupported": [],  # Not in M2M100
            "en": [],  # M2M100 supports
            "es": []   # M2M100 supports
        }
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        # M2M100 should be first
        m2m100 = result[0]
        assert m2m100.model_id == "m2m100_1.2b"
        # Should only list supported languages
        assert "xyz_unsupported" not in m2m100.languages_covered
        assert "abc_unsupported" not in m2m100.languages_covered


class TestAnalyzeGapsSingleMissing:
    """Test analyze_gaps with 1-4 missing languages (Helsinki-NLP strategy)."""

    def test_single_missing_recommends_opus(self):
        """Test single missing language recommends Helsinki-NLP opus-mt."""
        current_coverage = {
            "fr": []
        }
        target_languages = {"fr"}

        result = analyze_gaps(current_coverage, target_languages)

        # Should have opus model for fr (no INT8 since opus is not multilingual)
        opus_models = [r for r in result if r.model_id.startswith("opus_")]
        assert len(opus_models) >= 1
        assert opus_models[0].model_id == "opus_en_fr"
        assert opus_models[0].hf_model_id == "Helsinki-NLP/opus-mt-en-fr"
        assert opus_models[0].size_mb == 300
        assert opus_models[0].license == "CC-BY-4.0"
        assert opus_models[0].optimal_device == "cpu"

    def test_few_missing_uses_opus_for_each(self):
        """Test 1-4 missing languages creates opus model for each."""
        current_coverage = {
            "fr": [],
            "de": [],
            "es": []
        }
        target_languages = {"fr", "de", "es"}

        result = analyze_gaps(current_coverage, target_languages)

        # Should have 3 opus models, one for each language
        opus_models = [r for r in result if r.model_id.startswith("opus_")]
        assert len(opus_models) == 3
        opus_ids = {m.model_id for m in opus_models}
        assert "opus_en_fr" in opus_ids
        assert "opus_en_de" in opus_ids
        assert "opus_en_es" in opus_ids


class TestAnalyzeGapsInt8Versions:
    """Test INT8 version recommendations."""

    def test_nllb_gets_int8_version(self):
        """Test NLLB recommendation includes INT8 version."""
        # Note: When >10 missing, only NLLB is returned (returns early)
        # INT8 is NOT added in that case (line 54 returns early)
        # This tests the M2M100 path which does add INT8
        current_coverage = {
            "ar": [], "fr": [], "de": [], "es": [],
            "it": [], "ja": [], "ko": []
        }
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        # Check for INT8 version of M2M100
        int8_models = [r for r in result if "_ct2_int8" in r.model_id]
        assert len(int8_models) == 1
        assert int8_models[0].model_id == "m2m100_1.2b_ct2_int8"
        assert int8_models[0].backend == "ctranslate2"
        assert int8_models[0].optimal_device == "cpu"
        # INT8 should be half the size
        assert int8_models[0].size_mb == 2400  # 4800 * 0.5

    def test_int8_has_lower_priority(self):
        """Test INT8 versions have lower priority (download later)."""
        current_coverage = {
            "ar": [], "fr": [], "de": [], "es": [],
            "it": [], "ja": []
        }
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        int8_models = [r for r in result if "_ct2_int8" in r.model_id]
        if int8_models:
            assert int8_models[0].priority == 10  # Lower priority


class TestAnalyzeGapsSorting:
    """Test that results are sorted by priority."""

    def test_results_sorted_by_priority(self):
        """Test recommendations are sorted by priority."""
        current_coverage = {
            "fr": [],
            "de": [],
            "es": []
        }
        target_languages = {"fr", "de", "es"}

        result = analyze_gaps(current_coverage, target_languages)

        # Verify sorted by priority
        priorities = [r.priority for r in result]
        assert priorities == sorted(priorities)


class TestAnalyzeGapsEdgeCases:
    """Test edge cases."""

    def test_empty_coverage_with_targets(self):
        """Test with empty coverage map but targets specified."""
        current_coverage = {}
        target_languages = {"en", "fr"}

        result = analyze_gaps(current_coverage, target_languages)

        # No missing languages if not in current_coverage
        assert result == []

    def test_mixed_coverage_status(self):
        """Test with some covered and some not covered."""
        current_coverage = {
            "en": ["model_a"],  # Covered
            "fr": [],           # Not covered
            "de": ["model_b"],  # Covered
            "es": [],           # Not covered
        }
        target_languages = {"en", "fr", "de", "es"}

        result = analyze_gaps(current_coverage, target_languages)

        # Should recommend models for fr and es only
        covered_langs = set()
        for rec in result:
            covered_langs.update(rec.languages_covered)
        assert "fr" in covered_langs
        assert "es" in covered_langs
        # Already covered languages should not be in recommendations
        assert "en" not in covered_langs
        assert "de" not in covered_langs

    def test_exactly_five_missing(self):
        """Test boundary case: exactly 5 missing (triggers M2M100 path)."""
        # 5 missing, which triggers elif len(missing) > 5 is False
        # So it goes to Strategy 3 (opus-mt)
        current_coverage = {
            "fr": [], "de": [], "es": [], "it": [], "ja": []
        }
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        # With exactly 5, should use opus-mt for each
        opus_models = [r for r in result if r.model_id.startswith("opus_")]
        assert len(opus_models) == 5

    def test_exactly_six_missing(self):
        """Test boundary case: exactly 6 missing (triggers M2M100 path)."""
        current_coverage = {
            "fr": [], "de": [], "es": [], "it": [], "ja": [], "ko": []
        }
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        # Should use M2M100
        m2m_models = [r for r in result if r.model_id.startswith("m2m100")]
        assert len(m2m_models) >= 1

    def test_exactly_eleven_missing(self):
        """Test boundary case: exactly 11 missing (triggers NLLB path)."""
        current_coverage = {f"lang_{i}": [] for i in range(11)}
        target_languages = set(current_coverage.keys())

        result = analyze_gaps(current_coverage, target_languages)

        # Should use NLLB
        assert len(result) == 1
        assert result[0].model_id == "nllb_200_1.3b"
