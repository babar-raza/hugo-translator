"""
Integration tests for comprehensive language coverage.

Validates that all 36 target languages work correctly with Agent-B's fallback
implementation (PROD-001). Tests verify:
1. No ValueError crashes for any language
2. Correct model selection (Opus vs multilingual fallback)
3. Appropriate logging for fallback events
4. 100% language coverage (36/36 languages)

Task: PROD-002 (Agent-C: Language Coverage Testing)
Priority: P0 - CRITICAL
"""
import logging
import pytest
import yaml
from pathlib import Path

from src.model_runtime.registry import ModelRegistry, ModelInfo
from src.model_runtime.hardware import HardwareInfo


# Load all 36 target languages from config
def load_target_languages():
    """Load target languages from production config."""
    config_path = Path("config/target_languages.yaml")
    if not config_path.exists():
        pytest.skip(f"Target languages config not found: {config_path}")

    with open(config_path, encoding='utf-8') as f:
        data = yaml.safe_load(f)

    return [lang["iso_code"] for lang in data["languages"]]


# Language categorization based on production registry
# config/model_registry.yaml has specialized models for 6 languages:
# - opus_en_de (de only)
# - opus_en_fr, opus_en_es (fr, es)
# - marian_en_romance (fr, es, it, pt, ro - covers Romance languages)
SPECIALIZED_LANGUAGES = ["de", "es", "fr", "it", "pt", "ro"]
ALL_TARGET_LANGUAGES = load_target_languages()
MULTILINGUAL_LANGUAGES = [lang for lang in ALL_TARGET_LANGUAGES if lang not in SPECIALIZED_LANGUAGES]


@pytest.fixture
def mock_hardware():
    """Mock hardware with standard CPU capabilities."""
    return HardwareInfo(
        cpu_count=4,
        total_ram_gb=8.0,
        has_cuda=False,
        cuda_devices=[],
        has_mps=False,
        recommended_device="cpu",
    )


@pytest.fixture
def production_registry():
    """Load production model registry."""
    registry_path = Path("config/model_registry.yaml")
    if not registry_path.exists():
        pytest.skip(f"Production registry not found: {registry_path}")

    return ModelRegistry(registry_path)


# =============================================================================
# Test Suite 1: Universal Coverage (All 36 Languages)
# =============================================================================

class TestUniversalLanguageCoverage:
    """Test that ALL 36 languages work without ValueError."""

    @pytest.mark.parametrize("target_lang", ALL_TARGET_LANGUAGES)
    def test_all_languages_translate_successfully(
        self, target_lang, production_registry, mock_hardware
    ):
        """
        Verify each language can be translated without ValueError.

        This is the PRIMARY acceptance criteria: no crashes for any language.
        Before Agent-B's fix (PROD-001), 33/36 languages crashed here.
        """
        # This should NOT raise ValueError (thanks to Agent-B's fallback)
        model = production_registry.recommend_model('en', target_lang, mock_hardware)

        # Assertions
        assert model is not None, f"No model returned for en→{target_lang}"
        assert model.model_id is not None, f"Model ID is None for en→{target_lang}"
        assert isinstance(model, ModelInfo), f"Invalid model type for en→{target_lang}"

    @pytest.mark.parametrize("target_lang", ALL_TARGET_LANGUAGES)
    def test_all_languages_return_valid_model_info(
        self, target_lang, production_registry, mock_hardware
    ):
        """Verify each language returns a valid ModelInfo with required fields."""
        model = production_registry.recommend_model('en', target_lang, mock_hardware)

        # Verify ModelInfo structure
        assert hasattr(model, 'model_id'), f"Missing model_id for en→{target_lang}"
        assert hasattr(model, 'backend'), f"Missing backend for en→{target_lang}"
        assert hasattr(model, 'supported_pairs'), f"Missing supported_pairs for en→{target_lang}"

        # Verify values are not None
        assert model.model_id, f"Empty model_id for en→{target_lang}"
        assert model.backend, f"Empty backend for en→{target_lang}"


# =============================================================================
# Test Suite 2: Specialized Language Verification (6 Languages)
# =============================================================================

class TestSpecializedLanguages:
    """Test that specialized languages use Opus/Marian models (NO fallback to multilingual)."""

    @pytest.mark.parametrize("target_lang", SPECIALIZED_LANGUAGES)
    def test_specialized_languages_use_specialized_models(
        self, target_lang, production_registry, mock_hardware
    ):
        """
        Verify specialized languages use Opus or Marian models (NOT multilingual).

        Languages: de, es, fr, it, pt, ro
        Expected: opus_en_X or marian_en_romance (NOT m2m100/nllb)
        """
        model = production_registry.recommend_model('en', target_lang, mock_hardware)

        # Verify specialized model selected (not multilingual)
        is_specialized = ('opus' in model.model_id.lower() or 'marian' in model.model_id.lower())
        is_multilingual = ('m2m100' in model.model_id or 'nllb' in model.model_id)

        assert is_specialized, \
            f"Expected specialized model for en→{target_lang}, got {model.model_id}"
        assert not is_multilingual, \
            f"Expected specialized model (not multilingual) for en→{target_lang}, got {model.model_id}"

    @pytest.mark.parametrize("target_lang", SPECIALIZED_LANGUAGES)
    def test_specialized_languages_no_fallback_log(
        self, target_lang, production_registry, mock_hardware, caplog
    ):
        """
        Verify NO fallback log emitted for specialized languages.

        When specialized model exists, system should use it without logging fallback.
        """
        with caplog.at_level(logging.INFO):
            model = production_registry.recommend_model('en', target_lang, mock_hardware)

            # Verify no INFO log about fallback
            fallback_logs = [
                record for record in caplog.records
                if record.levelname == 'INFO' and 'fallback' in record.message.lower()
            ]
            assert len(fallback_logs) == 0, \
                f"Unexpected fallback log for specialized language en→{target_lang}: {fallback_logs}"

    def test_specialized_models_present_in_registry(self, production_registry):
        """Verify specialized models are present in production registry."""
        models = production_registry.list_models()
        model_ids = [m.model_id for m in models]

        # Check for Opus models (de, fr, es)
        assert 'opus_en_de' in model_ids, "Missing opus_en_de"
        assert 'opus_en_fr' in model_ids, "Missing opus_en_fr"
        assert 'opus_en_es' in model_ids, "Missing opus_en_es"

        # Check for Marian Romance model (covers fr, es, it, pt, ro)
        assert 'marian_en_romance' in model_ids, "Missing marian_en_romance"


# =============================================================================
# Test Suite 3: Multilingual Fallback Verification (30 Languages)
# =============================================================================

class TestMultilingualFallback:
    """Test that unsupported languages fall back to multilingual models."""

    @pytest.mark.parametrize("target_lang", MULTILINGUAL_LANGUAGES)
    def test_multilingual_fallback_languages_use_multilingual(
        self, target_lang, production_registry, mock_hardware
    ):
        """
        Verify unsupported languages fall back to multilingual models.

        Languages: All except de, es, fr, it, pt, ro (30 languages)
        Expected: m2m100 or nllb models
        """
        model = production_registry.recommend_model('en', target_lang, mock_hardware)

        # Verify multilingual model selected
        is_multilingual = 'm2m100' in model.model_id or 'nllb' in model.model_id
        assert is_multilingual, \
            f"Expected multilingual model for en→{target_lang}, got {model.model_id}"

    @pytest.mark.parametrize("target_lang", MULTILINGUAL_LANGUAGES)
    def test_multilingual_fallback_emits_info_log(
        self, target_lang, production_registry, mock_hardware, caplog
    ):
        """
        Verify INFO log emitted when falling back to multilingual.

        Expected log: "No Opus model for en→{target_lang}, using multilingual fallback"
        """
        with caplog.at_level(logging.INFO):
            model = production_registry.recommend_model('en', target_lang, mock_hardware)

            # Verify INFO log about fallback
            fallback_logs = [
                record for record in caplog.records
                if record.levelname == 'INFO' and 'fallback' in record.message.lower()
            ]

            assert len(fallback_logs) > 0, \
                f"Missing fallback INFO log for en→{target_lang}"

            # Verify log message content
            log_message = fallback_logs[0].message
            assert target_lang in log_message or f'en→{target_lang}' in log_message, \
                f"Fallback log missing language pair en→{target_lang}: {log_message}"

    def test_multilingual_models_support_all_pairs(self, production_registry):
        """Verify multilingual models have supported_pairs='all'."""
        models = production_registry.list_models()

        # Find multilingual models
        multilingual_models = [
            m for m in models
            if 'm2m100' in m.model_id or 'nllb' in m.model_id
        ]

        assert len(multilingual_models) > 0, \
            "No multilingual models found in production registry"

        # Verify supported_pairs="all"
        for model in multilingual_models:
            assert model.supported_pairs == "all", \
                f"Multilingual model {model.model_id} should have supported_pairs='all', " \
                f"got {model.supported_pairs}"


# =============================================================================
# Test Suite 4: Coverage Summary and Reporting
# =============================================================================

class TestCoverageSummary:
    """Generate coverage summary and verify 100% language support."""

    def test_language_coverage_summary(self, production_registry, mock_hardware):
        """
        Generate and verify language coverage summary.

        Expected: 36/36 languages work (100% coverage)
        Before Agent-B: 3/36 languages worked (8% coverage)
        After Agent-B: 36/36 languages work (100% coverage)
        """
        successful_languages = []
        failed_languages = []

        for lang in ALL_TARGET_LANGUAGES:
            try:
                model = production_registry.recommend_model('en', lang, mock_hardware)
                if model and model.model_id:
                    successful_languages.append(lang)
                else:
                    failed_languages.append((lang, "No model returned"))
            except ValueError as e:
                failed_languages.append((lang, str(e)))
            except Exception as e:
                failed_languages.append((lang, f"Unexpected error: {e}"))

        # Generate coverage report
        total = len(ALL_TARGET_LANGUAGES)
        success_count = len(successful_languages)
        fail_count = len(failed_languages)
        coverage_pct = (success_count / total) * 100 if total > 0 else 0

        report = f"""
Language Coverage Summary:
--------------------------
Total languages: {total}
Successful: {success_count} ({coverage_pct:.1f}%)
Failed: {fail_count}

Specialized languages (6): {', '.join(SPECIALIZED_LANGUAGES)}
Multilingual fallback (30): {len(MULTILINGUAL_LANGUAGES)} languages

"""

        if failed_languages:
            report += "Failed languages:\n"
            for lang, error in failed_languages:
                report += f"  - {lang}: {error}\n"

        # Print report for evidence collection
        print(report)

        # Assertions
        assert success_count == total, \
            f"Expected 100% coverage ({total}/{total}), got {success_count}/{total}. " \
            f"Failed: {failed_languages}"

        assert coverage_pct == 100.0, \
            f"Expected 100% coverage, got {coverage_pct:.1f}%"

    def test_model_selection_distribution(self, production_registry, mock_hardware):
        """
        Verify model selection distribution across language categories.

        Expected:
        - 6 languages use specialized models (de, es, fr, it, pt, ro)
        - 30 languages use multilingual models
        """
        specialized_selected = []
        multilingual_selected = []

        for lang in ALL_TARGET_LANGUAGES:
            model = production_registry.recommend_model('en', lang, mock_hardware)

            # Check if specialized (opus or marian) or multilingual
            is_specialized = ('opus' in model.model_id.lower() or 'marian' in model.model_id.lower())
            is_multilingual = ('m2m100' in model.model_id or 'nllb' in model.model_id)

            if is_specialized:
                specialized_selected.append(lang)
            elif is_multilingual:
                multilingual_selected.append(lang)

        # Verify distribution
        assert len(specialized_selected) + len(multilingual_selected) == 36, \
            f"Expected all 36 languages covered, got {len(specialized_selected)} + {len(multilingual_selected)}"

        assert len(specialized_selected) == 6, \
            f"Expected 6 specialized selections, got {len(specialized_selected)}: {specialized_selected}"

        assert len(multilingual_selected) == 30, \
            f"Expected 30 multilingual selections, got {len(multilingual_selected)}"

        # Verify correct languages in each category
        assert set(specialized_selected) == set(SPECIALIZED_LANGUAGES), \
            f"Specialized languages mismatch. Expected: {SPECIALIZED_LANGUAGES}, got: {specialized_selected}"

        assert set(multilingual_selected) == set(MULTILINGUAL_LANGUAGES), \
            f"Multilingual languages mismatch. Expected {len(MULTILINGUAL_LANGUAGES)} languages, " \
            f"got {len(multilingual_selected)}"


# =============================================================================
# Test Suite 4: Regression Tests (Verify No Breakage)
# =============================================================================

class TestNoRegressions:
    """Verify Agent-B's changes didn't break existing functionality."""

    def test_manual_model_selection_still_works(self, production_registry):
        """Verify manual get_model() still works (backward compatibility)."""
        # Test with Opus model
        opus_model = production_registry.get_model('opus_en_fr')
        assert opus_model.model_id == 'opus_en_fr'

        # Test with multilingual model (if exists)
        models = production_registry.list_models()
        multilingual = [m for m in models if 'm2m100' in m.model_id or 'nllb' in m.model_id]

        if multilingual:
            m2m_model = production_registry.get_model(multilingual[0].model_id)
            assert m2m_model.model_id == multilingual[0].model_id

    def test_list_models_still_works(self, production_registry):
        """Verify list_models() still works (backward compatibility)."""
        # List all models
        all_models = production_registry.list_models()
        assert len(all_models) > 0, "Registry appears empty"

        # List models for specific language pair
        fr_models = production_registry.list_models(lang_pair=('en', 'fr'))
        assert len(fr_models) > 0, "No models for en→fr"

        # Verify Opus model in French results
        opus_in_results = any('opus' in m.model_id for m in fr_models)
        assert opus_in_results, "Opus model not found in en→fr results"

    def test_registry_loading(self):
        """Verify production registry loads successfully."""
        registry_path = Path("config/model_registry.yaml")
        assert registry_path.exists(), f"Production registry not found: {registry_path}"

        registry = ModelRegistry(registry_path)
        assert registry is not None

        # Verify registry has models
        models = registry.list_models()
        assert len(models) > 0, "Production registry has no models"


# =============================================================================
# Test Suite 6: Edge Cases and Validation
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_language_handled_gracefully(self, production_registry, mock_hardware):
        """
        Verify invalid/unknown language codes are handled gracefully.

        Note: With multilingual fallback (supported_pairs="all"), even unknown
        language codes may not raise ValueError. This is acceptable behavior.
        """
        # Try an invalid language code - may or may not raise depending on fallback
        try:
            model = production_registry.recommend_model('en', 'invalid_lang_123', mock_hardware)
            # If multilingual fallback accepts it, verify valid model returned
            assert model is not None
            assert model.model_id is not None
        except ValueError as e:
            # If it raises ValueError, verify clear error message
            assert 'invalid' in str(e).lower() or 'not found' in str(e).lower() or 'language' in str(e).lower()

    def test_same_source_and_target_language(self, production_registry, mock_hardware):
        """Verify same source/target language is handled gracefully."""
        # en→en should either work or raise clear error
        # This tests boundary condition handling
        try:
            model = production_registry.recommend_model('en', 'en', mock_hardware)
            # If it succeeds, verify valid model returned
            assert model is not None
            assert model.model_id is not None
        except ValueError as e:
            # If it fails, verify clear error message
            assert 'en' in str(e).lower() or 'language' in str(e).lower()

    def test_bidirectional_support_where_applicable(self, production_registry, mock_hardware):
        """
        Verify bidirectional translation support for languages where applicable.

        Multilingual models should support both en→X and X→en.
        """
        # Test a sample of bidirectional pairs
        test_languages = ['fr', 'de', 'ja', 'ar']  # Mix of Opus and multilingual

        for lang in test_languages:
            # en→lang
            model_forward = production_registry.recommend_model('en', lang, mock_hardware)
            assert model_forward is not None, f"en→{lang} failed"

            # lang→en (may not be supported by all models)
            try:
                model_reverse = production_registry.recommend_model(lang, 'en', mock_hardware)
                # If supported, verify valid model
                assert model_reverse is not None, f"{lang}→en failed"
            except ValueError:
                # Some Opus models may not support reverse direction
                # This is acceptable for Opus, but multilingual should support both
                if 'm2m100' in model_forward.model_id or 'nllb' in model_forward.model_id:
                    pytest.fail(
                        f"Multilingual model {model_forward.model_id} should support "
                        f"bidirectional translation, but {lang}→en failed"
                    )


# =============================================================================
# Test Configuration and Metadata
# =============================================================================

def test_language_count_matches_config():
    """Verify we're testing exactly 36 languages from config."""
    assert len(ALL_TARGET_LANGUAGES) == 36, \
        f"Expected 36 target languages, found {len(ALL_TARGET_LANGUAGES)}"


def test_categorization_is_complete():
    """Verify language categorization covers all languages."""
    specialized_count = len(SPECIALIZED_LANGUAGES)
    multilingual_count = len(MULTILINGUAL_LANGUAGES)
    total = specialized_count + multilingual_count

    assert specialized_count == 6, f"Expected 6 specialized languages, got {specialized_count}"
    assert multilingual_count == 30, f"Expected 30 multilingual languages, got {multilingual_count}"
    assert total == 36, f"Expected 36 total languages, got {total}"

    # Verify no overlap
    overlap = set(SPECIALIZED_LANGUAGES) & set(MULTILINGUAL_LANGUAGES)
    assert len(overlap) == 0, f"Language categorization has overlap: {overlap}"

    # Verify no languages missed
    all_categorized = set(SPECIALIZED_LANGUAGES) | set(MULTILINGUAL_LANGUAGES)
    assert all_categorized == set(ALL_TARGET_LANGUAGES), \
        f"Not all languages categorized. Missing: {set(ALL_TARGET_LANGUAGES) - all_categorized}"


# =============================================================================
# Performance and Runtime Tests
# =============================================================================

class TestPerformance:
    """Verify tests run within acceptable time limits."""

    def test_model_selection_is_fast(self, production_registry, mock_hardware):
        """
        Verify model selection completes quickly (<1 second per language).

        Target: <5 minutes for all 36 languages = <8.3 seconds per language
        Stretch goal: <1 second per language
        """
        import time

        timings = []

        for lang in ALL_TARGET_LANGUAGES[:5]:  # Test sample of 5 languages
            start = time.time()
            model = production_registry.recommend_model('en', lang, mock_hardware)
            elapsed = time.time() - start
            timings.append((lang, elapsed))

        # Verify all are fast
        for lang, elapsed in timings:
            assert elapsed < 1.0, \
                f"Model selection too slow for en→{lang}: {elapsed:.3f}s (target: <1s)"

        # Calculate average
        avg_time = sum(t for _, t in timings) / len(timings)
        print(f"\nAverage model selection time: {avg_time:.3f}s")

        # Extrapolate to all 36 languages
        estimated_total = avg_time * 36
        print(f"Estimated time for all 36 languages: {estimated_total:.1f}s")

        # Verify total estimated time is reasonable
        assert estimated_total < 300, \
            f"Estimated total time {estimated_total:.1f}s exceeds 5 minute target"
