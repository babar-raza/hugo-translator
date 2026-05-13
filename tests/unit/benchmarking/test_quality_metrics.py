"""Tests for quality_metrics.py - BLEU and COMET translation metrics."""

from unittest.mock import MagicMock, patch

import pytest

sacrebleu = pytest.importorskip("sacrebleu", reason="sacrebleu not installed")
from src.benchmarking.quality_metrics import QualityMetrics, QualityScore


class TestQualityScore:
    """Test QualityScore dataclass."""

    def test_quality_score_fields(self):
        """Test QualityScore has expected fields."""
        score = QualityScore(
            bleu_score=85.0,
            comet_score=0.92,
            reference_text="Hello world",
            hypothesis_text="Hello world",
        )
        assert score.bleu_score == 85.0
        assert score.comet_score == 0.92
        assert score.reference_text == "Hello world"
        assert score.hypothesis_text == "Hello world"

    def test_quality_score_optional_comet(self):
        """Test QualityScore with optional COMET (None)."""
        score = QualityScore(bleu_score=50.0)
        assert score.bleu_score == 50.0
        assert score.comet_score is None
        assert score.reference_text == ""
        assert score.hypothesis_text == ""


class TestQualityMetricsInit:
    """Test QualityMetrics initialization."""

    def test_init_without_comet(self):
        """Test initialization without COMET."""
        metrics = QualityMetrics(use_comet=False)
        assert metrics.use_comet is False
        assert metrics.comet_model is None

    def test_init_comet_import_error(self):
        """Test graceful handling when COMET package not installed."""
        with patch.dict("sys.modules", {"comet": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'comet'")):
                metrics = QualityMetrics(use_comet=True)
                # Should fallback to False when import fails
                assert metrics.use_comet is False
                assert metrics.comet_model is None

    def test_init_comet_load_error(self):
        """Test graceful handling when COMET model fails to load."""
        mock_comet = MagicMock()
        mock_comet.download_model.side_effect = Exception("Model download failed")

        with patch.dict("sys.modules", {"comet": mock_comet}):
            metrics = QualityMetrics(use_comet=True)
            # Should fallback to False when load fails
            assert metrics.use_comet is False


class TestCalculateBleu:
    """Test BLEU score calculation."""

    @pytest.fixture
    def metrics(self):
        """Create QualityMetrics without COMET."""
        return QualityMetrics(use_comet=False)

    def test_bleu_perfect_match(self, metrics):
        """Test BLEU score for identical strings."""
        score = metrics.calculate_bleu("Hello world", "Hello world")
        # Perfect match should give 100 BLEU (use approx for float comparison)
        assert score == pytest.approx(100.0, rel=1e-6)

    def test_bleu_partial_match(self, metrics):
        """Test BLEU score for partial matches."""
        score = metrics.calculate_bleu(
            "The cat sat on the mat",
            "The cat is sitting on the mat"
        )
        # Should be between 0 and 100
        assert 0 < score < 100

    def test_bleu_no_match(self, metrics):
        """Test BLEU score for completely different strings."""
        score = metrics.calculate_bleu(
            "Hello world",
            "Goodbye universe"
        )
        # Should be low but not necessarily 0
        assert score < 50

    def test_bleu_empty_hypothesis(self, metrics):
        """Test BLEU with empty hypothesis."""
        score = metrics.calculate_bleu("", "Reference text")
        assert score == 0.0

    def test_bleu_error_handling(self, metrics):
        """Test BLEU handles errors gracefully."""
        # Test with None values (should return 0.0 due to error handling)
        with patch("sacrebleu.sentence_bleu", side_effect=Exception("Error")):
            score = metrics.calculate_bleu("test", "test")
            assert score == 0.0


class TestCalculateCorpusBleu:
    """Test corpus-level BLEU calculation."""

    @pytest.fixture
    def metrics(self):
        """Create QualityMetrics without COMET."""
        return QualityMetrics(use_comet=False)

    def test_corpus_bleu_perfect(self, metrics):
        """Test corpus BLEU with perfect matches."""
        # Use longer sentences - short sentences get 0.0 due to n-gram brevity penalty
        hypotheses = ["The quick brown fox jumps over the lazy dog", "This is another test sentence for BLEU"]
        references = ["The quick brown fox jumps over the lazy dog", "This is another test sentence for BLEU"]
        score = metrics.calculate_corpus_bleu(hypotheses, references)
        assert score == pytest.approx(100.0, rel=1e-6)

    def test_corpus_bleu_partial(self, metrics):
        """Test corpus BLEU with partial matches."""
        hypotheses = ["The quick brown fox", "Lazy dog sleeps"]
        references = ["The quick red fox", "Lazy dogs sleep"]
        score = metrics.calculate_corpus_bleu(hypotheses, references)
        assert 0 < score < 100

    def test_corpus_bleu_empty_list(self, metrics):
        """Test corpus BLEU with empty lists."""
        score = metrics.calculate_corpus_bleu([], [])
        # sacrebleu returns 0 for empty corpus
        assert score == 0.0

    def test_corpus_bleu_error_handling(self, metrics):
        """Test corpus BLEU handles errors gracefully."""
        with patch("sacrebleu.corpus_bleu", side_effect=Exception("Error")):
            score = metrics.calculate_corpus_bleu(["test"], ["test"])
            assert score == 0.0


class TestCalculateComet:
    """Test COMET score calculation."""

    def test_comet_disabled_returns_none(self):
        """Test that COMET returns None when disabled."""
        metrics = QualityMetrics(use_comet=False)
        score = metrics.calculate_comet("hyp", "ref", "src")
        assert score is None

    def test_comet_with_mock_model(self):
        """Test COMET calculation with mocked model."""
        metrics = QualityMetrics(use_comet=False)
        # Manually set up a mock COMET model
        metrics.use_comet = True
        metrics.comet_model = MagicMock()
        metrics.comet_model.predict.return_value = {"scores": [0.85]}

        score = metrics.calculate_comet("hypothesis", "reference", "source")
        assert score == 0.85

        # Verify the model was called correctly
        metrics.comet_model.predict.assert_called_once()
        call_args = metrics.comet_model.predict.call_args
        assert call_args[0][0] == [{"src": "source", "mt": "hypothesis", "ref": "reference"}]

    def test_comet_error_handling(self):
        """Test COMET handles errors gracefully."""
        metrics = QualityMetrics(use_comet=False)
        metrics.use_comet = True
        metrics.comet_model = MagicMock()
        metrics.comet_model.predict.side_effect = Exception("Prediction failed")

        score = metrics.calculate_comet("hyp", "ref", "src")
        assert score is None


class TestCalculateCorpusComet:
    """Test corpus-level COMET calculation."""

    def test_corpus_comet_disabled_returns_none(self):
        """Test that corpus COMET returns None when disabled."""
        metrics = QualityMetrics(use_comet=False)
        score = metrics.calculate_corpus_comet(["hyp"], ["ref"], ["src"])
        assert score is None

    def test_corpus_comet_with_mock_model(self):
        """Test corpus COMET calculation with mocked model."""
        metrics = QualityMetrics(use_comet=False)
        metrics.use_comet = True
        metrics.comet_model = MagicMock()
        metrics.comet_model.predict.return_value = {"system_score": 0.88}

        hypotheses = ["hyp1", "hyp2"]
        references = ["ref1", "ref2"]
        sources = ["src1", "src2"]

        score = metrics.calculate_corpus_comet(hypotheses, references, sources, batch_size=4)
        assert score == 0.88

        # Verify batch_size was passed
        call_args = metrics.comet_model.predict.call_args
        assert call_args[1]["batch_size"] == 4

    def test_corpus_comet_error_handling(self):
        """Test corpus COMET handles errors gracefully."""
        metrics = QualityMetrics(use_comet=False)
        metrics.use_comet = True
        metrics.comet_model = MagicMock()
        metrics.comet_model.predict.side_effect = Exception("Error")

        score = metrics.calculate_corpus_comet(["hyp"], ["ref"], ["src"])
        assert score is None


class TestEvaluateTranslation:
    """Test combined translation evaluation."""

    @pytest.fixture
    def metrics(self):
        """Create QualityMetrics without COMET."""
        return QualityMetrics(use_comet=False)

    def test_evaluate_translation_bleu_only(self, metrics):
        """Test evaluation with BLEU only (no source for COMET)."""
        result = metrics.evaluate_translation(
            hypothesis="Hello world",
            reference="Hello world"
        )
        assert isinstance(result, QualityScore)
        assert result.bleu_score == pytest.approx(100.0, rel=1e-6)
        assert result.comet_score is None
        assert result.hypothesis_text == "Hello world"
        assert result.reference_text == "Hello world"

    def test_evaluate_translation_with_source(self, metrics):
        """Test evaluation with source text (would use COMET if available)."""
        result = metrics.evaluate_translation(
            hypothesis="Bonjour monde",
            reference="Bonjour le monde",
            source="Hello world"
        )
        assert isinstance(result, QualityScore)
        assert 0 < result.bleu_score < 100
        # COMET disabled, so should be None
        assert result.comet_score is None

    def test_evaluate_translation_with_comet_mock(self):
        """Test evaluation with mocked COMET model."""
        metrics = QualityMetrics(use_comet=False)
        metrics.use_comet = True
        metrics.comet_model = MagicMock()
        metrics.comet_model.predict.return_value = {"scores": [0.9]}

        result = metrics.evaluate_translation(
            hypothesis="Bonjour",
            reference="Bonjour",
            source="Hello"
        )
        assert result.bleu_score == pytest.approx(100.0, rel=1e-6)
        assert result.comet_score == 0.9


class TestEvaluateCorpus:
    """Test corpus-level evaluation."""

    @pytest.fixture
    def metrics(self):
        """Create QualityMetrics without COMET."""
        return QualityMetrics(use_comet=False)

    def test_evaluate_corpus_bleu_only(self, metrics):
        """Test corpus evaluation with BLEU only."""
        # Use longer sentences - short sentences get 0.0 due to n-gram brevity penalty
        result = metrics.evaluate_corpus(
            hypotheses=["The quick brown fox jumps over the lazy dog", "This is a test sentence"],
            references=["The quick brown fox jumps over the lazy dog", "This is a test sentence"]
        )
        assert isinstance(result, QualityScore)
        assert result.bleu_score == pytest.approx(100.0, rel=1e-6)
        assert result.comet_score is None
        # Corpus doesn't store individual texts
        assert result.reference_text == ""
        assert result.hypothesis_text == ""

    def test_evaluate_corpus_with_sources(self, metrics):
        """Test corpus evaluation with source texts."""
        # Use longer sentences - short sentences get 0.0 due to n-gram brevity penalty
        result = metrics.evaluate_corpus(
            hypotheses=["Bonjour le monde entier", "Au revoir et bonne journee"],
            references=["Bonjour le monde entier", "Au revoir et bonne journee"],
            sources=["Hello entire world", "Goodbye and have a nice day"]
        )
        assert result.bleu_score == pytest.approx(100.0, rel=1e-6)
        # COMET disabled
        assert result.comet_score is None

    def test_evaluate_corpus_custom_batch_size(self):
        """Test corpus evaluation with custom batch size."""
        metrics = QualityMetrics(use_comet=False)
        metrics.use_comet = True
        metrics.comet_model = MagicMock()
        metrics.comet_model.predict.return_value = {"system_score": 0.85}

        result = metrics.evaluate_corpus(
            hypotheses=["hyp1", "hyp2"],
            references=["ref1", "ref2"],
            sources=["src1", "src2"],
            batch_size=16
        )

        # Verify batch_size was passed
        call_args = metrics.comet_model.predict.call_args
        assert call_args[1]["batch_size"] == 16
        assert result.comet_score == 0.85
