"""Analyze model coverage gaps and recommend downloads."""
from dataclasses import dataclass
from typing import List, Dict, Set
import logging

logger = logging.getLogger(__name__)


@dataclass
class ModelRecommendation:
    model_id: str
    hf_model_id: str
    size_mb: int
    languages_covered: List[str]
    license: str
    priority: int
    backend: str
    optimal_device: str


def analyze_gaps(
    current_coverage: Dict[str, List[str]],
    target_languages: Set[str]
) -> List[ModelRecommendation]:
    """Find optimal models to fill coverage gaps.

    Args:
        current_coverage: Map of language -> list of models covering it
        target_languages: Set of all target languages

    Returns:
        List of recommended models to download, sorted by priority
    """
    missing = {lang for lang, models in current_coverage.items() if not models}

    if not missing:
        return []

    recommendations = []

    # Strategy 1: Use NLLB-200 if many languages missing (>10)
    # NLLB-200 supports 200 languages including all our 36 targets
    if len(missing) > 10:
        recommendations.append(ModelRecommendation(
            model_id="nllb_200_1.3b",
            hf_model_id="facebook/nllb-200-1.3B",
            size_mb=5200,
            languages_covered=sorted(missing),
            license="CC-BY-NC-4.0",
            priority=1,
            backend="huggingface",
            optimal_device="cuda"
        ))
        return recommendations  # NLLB covers everything

    # Strategy 2: Use M2M100 if 5-10 languages missing
    # M2M100 supports 100 languages
    elif len(missing) > 5:
        # Check which missing languages M2M100 supports
        m2m100_langs = {
            'ar', 'zh', 'nl', 'en', 'fr', 'de', 'hi', 'id', 'it', 'ja',
            'ko', 'pl', 'pt', 'ru', 'es', 'th', 'tr', 'vi', 'cs', 'uk',
            'fi', 'ro', 'da', 'hu', 'ta', 'he', 'lt', 'ca', 'bg', 'sk',
            'no', 'fa', 'lv', 'el', 'ms', 'sr'
        }
        m2m_covered = missing & m2m100_langs

        if m2m_covered:
            recommendations.append(ModelRecommendation(
                model_id="m2m100_1.2b",
                hf_model_id="facebook/m2m100_1.2B",
                size_mb=4800,
                languages_covered=sorted(m2m_covered),
                license="MIT",
                priority=1,
                backend="huggingface",
                optimal_device="cuda"
            ))
            missing = missing - m2m_covered

    # Strategy 3: Use Helsinki-NLP opus-mt for remaining languages
    # These are smaller specialized models (~300MB each)
    priority = 2
    for lang in sorted(missing):
        # Helsinki-NLP has opus-mt-en-XX models for many languages
        recommendations.append(ModelRecommendation(
            model_id=f"opus_en_{lang}",
            hf_model_id=f"Helsinki-NLP/opus-mt-en-{lang}",
            size_mb=300,
            languages_covered=[lang],
            license="CC-BY-4.0",
            priority=priority,
            backend="huggingface",
            optimal_device="cpu"
        ))
        priority += 1

    # Strategy 4: Add CPU-optimized versions for production
    # CTranslate2 INT8 versions are 50% smaller and 2-4x faster on CPU
    if recommendations:
        # Add INT8 version of the primary multilingual model
        primary = recommendations[0]
        if primary.model_id.startswith('nllb') or primary.model_id.startswith('m2m100'):
            recommendations.append(ModelRecommendation(
                model_id=f"{primary.model_id}_ct2_int8",
                hf_model_id=f"{primary.hf_model_id}-ct2-int8",
                size_mb=int(primary.size_mb * 0.5),
                languages_covered=primary.languages_covered,
                license=primary.license,
                priority=10,  # Lower priority (download after main models)
                backend="ctranslate2",
                optimal_device="cpu"
            ))

    return sorted(recommendations, key=lambda x: x.priority)
