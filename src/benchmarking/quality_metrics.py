"""
Quality metrics for translation evaluation.

Provides BLEU and COMET score calculation for benchmarking translation quality
against reference translations.
"""

import logging
from dataclasses import dataclass

import sacrebleu

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """
    Quality metrics for a translation.

    Attributes:
        bleu_score: BLEU score (0-100)
        comet_score: COMET score (-inf to 1.0, typically 0.0-1.0)
        reference_text: Reference translation used for scoring
        hypothesis_text: Generated translation being evaluated
    """

    bleu_score: float
    comet_score: float | None = None
    reference_text: str = ""
    hypothesis_text: str = ""


class QualityMetrics:
    """
    Calculate translation quality metrics.

    Supports BLEU (via sacrebleu) and COMET (via unbabel-comet) scoring.
    """

    def __init__(self, use_comet: bool = False):
        """
        Initialize quality metrics calculator.

        Args:
            use_comet: Whether to load COMET model (requires GPU, slower)
        """
        self.use_comet = use_comet
        self.comet_model = None

        if use_comet:
            try:
                from comet import download_model, load_from_checkpoint

                # Download and load COMET model (Unbabel's wmt20-comet-da)
                model_path = download_model("Unbabel/wmt20-comet-da")
                self.comet_model = load_from_checkpoint(model_path)
                logger.info("COMET model loaded successfully")
            except ImportError:
                logger.warning(
                    "COMET package not installed. Install with: pip install unbabel-comet"
                )
                self.use_comet = False
            except Exception as e:
                logger.error(f"Failed to load COMET model: {e}")
                self.use_comet = False

    def calculate_bleu(
        self, hypothesis: str, reference: str, tokenize: str = "13a"
    ) -> float:
        """
        Calculate BLEU score for a single translation.

        Args:
            hypothesis: Generated translation
            reference: Reference translation
            tokenize: Tokenization method ('13a', 'intl', 'zh', 'ja-mecab')

        Returns:
            BLEU score (0-100)
        """
        try:
            # sacrebleu expects lists
            bleu = sacrebleu.sentence_bleu(
                hypothesis, [reference], tokenize=tokenize
            )
            return bleu.score
        except Exception as e:
            logger.error(f"BLEU calculation failed: {e}")
            return 0.0

    def calculate_corpus_bleu(
        self,
        hypotheses: list[str],
        references: list[str],
        tokenize: str = "13a",
    ) -> float:
        """
        Calculate corpus-level BLEU score.

        Args:
            hypotheses: List of generated translations
            references: List of reference translations
            tokenize: Tokenization method

        Returns:
            Corpus BLEU score (0-100)
        """
        try:
            # sacrebleu corpus_bleu expects references as list of lists
            bleu = sacrebleu.corpus_bleu(
                hypotheses, [references], tokenize=tokenize
            )
            return bleu.score
        except Exception as e:
            logger.error(f"Corpus BLEU calculation failed: {e}")
            return 0.0

    def calculate_comet(
        self, hypothesis: str, reference: str, source: str
    ) -> float | None:
        """
        Calculate COMET score for a single translation.

        COMET requires source text in addition to hypothesis and reference.

        Args:
            hypothesis: Generated translation
            reference: Reference translation
            source: Source text

        Returns:
            COMET score (typically 0.0-1.0) or None if COMET not available
        """
        if not self.use_comet or self.comet_model is None:
            return None

        try:
            data = [
                {
                    "src": source,
                    "mt": hypothesis,
                    "ref": reference,
                }
            ]
            output = self.comet_model.predict(data, batch_size=1, gpus=0)
            return output["scores"][0]
        except Exception as e:
            logger.error(f"COMET calculation failed: {e}")
            return None

    def calculate_corpus_comet(
        self,
        hypotheses: list[str],
        references: list[str],
        sources: list[str],
        batch_size: int = 8,
    ) -> float | None:
        """
        Calculate corpus-level COMET score.

        Args:
            hypotheses: List of generated translations
            references: List of reference translations
            sources: List of source texts
            batch_size: Batch size for COMET inference

        Returns:
            Mean COMET score or None if COMET not available
        """
        if not self.use_comet or self.comet_model is None:
            return None

        try:
            data = [
                {"src": src, "mt": hyp, "ref": ref}
                for src, hyp, ref in zip(sources, hypotheses, references, strict=False)
            ]
            output = self.comet_model.predict(
                data, batch_size=batch_size, gpus=0
            )
            # Return system-level score (mean of all samples)
            return output["system_score"]
        except Exception as e:
            logger.error(f"Corpus COMET calculation failed: {e}")
            return None

    def evaluate_translation(
        self,
        hypothesis: str,
        reference: str,
        source: str | None = None,
        tokenize: str = "13a",
    ) -> QualityScore:
        """
        Evaluate a translation with all available metrics.

        Args:
            hypothesis: Generated translation
            reference: Reference translation
            source: Source text (required for COMET)
            tokenize: Tokenization method for BLEU

        Returns:
            QualityScore with BLEU and optionally COMET
        """
        bleu_score = self.calculate_bleu(hypothesis, reference, tokenize)

        comet_score = None
        if source is not None:
            comet_score = self.calculate_comet(hypothesis, reference, source)

        return QualityScore(
            bleu_score=bleu_score,
            comet_score=comet_score,
            reference_text=reference,
            hypothesis_text=hypothesis,
        )

    def evaluate_corpus(
        self,
        hypotheses: list[str],
        references: list[str],
        sources: list[str] | None = None,
        tokenize: str = "13a",
        batch_size: int = 8,
    ) -> QualityScore:
        """
        Evaluate a corpus of translations.

        Args:
            hypotheses: List of generated translations
            references: List of reference translations
            sources: List of source texts (required for COMET)
            tokenize: Tokenization method for BLEU
            batch_size: Batch size for COMET

        Returns:
            QualityScore with corpus-level metrics
        """
        bleu_score = self.calculate_corpus_bleu(
            hypotheses, references, tokenize
        )

        comet_score = None
        if sources is not None:
            comet_score = self.calculate_corpus_comet(
                hypotheses, references, sources, batch_size
            )

        return QualityScore(
            bleu_score=bleu_score,
            comet_score=comet_score,
            reference_text="",  # Not applicable for corpus
            hypothesis_text="",
        )
