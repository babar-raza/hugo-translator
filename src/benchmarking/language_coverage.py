"""Language coverage validation for model registry."""
from dataclasses import dataclass
from typing import Dict, List, Set
import yaml


@dataclass
class CoverageReport:
    total_languages: int
    covered_languages: Set[str]
    missing_languages: Set[str]
    coverage_percentage: float
    models_per_language: Dict[str, List[str]]

    def is_complete(self) -> bool:
        return len(self.missing_languages) == 0

    def to_dict(self) -> dict:
        return {
            "total": self.total_languages,
            "covered": sorted(self.covered_languages),
            "missing": sorted(self.missing_languages),
            "coverage_pct": self.coverage_percentage,
            "models_per_language": {k: v for k, v in sorted(self.models_per_language.items())}
        }


def check_language_coverage(
    registry_path: str,
    languages_path: str
) -> CoverageReport:
    """Check which languages have model support."""
    # Load configs
    with open(registry_path) as f:
        registry = yaml.safe_load(f)
    with open(languages_path) as f:
        lang_config = yaml.safe_load(f)

    target_languages = {lang['iso_code'] for lang in lang_config['languages']}
    models_per_language = {lang: [] for lang in target_languages}

    # Check each model
    for model in registry['models']:
        model_id = model['model_id']
        pairs = model.get('supported_pairs', [])

        if pairs == 'all':
            # Multilingual model covers all languages
            for lang in target_languages:
                models_per_language[lang].append(model_id)
        else:
            # Check explicit pairs
            for pair in pairs:
                if isinstance(pair, list) and len(pair) == 2:
                    src, tgt = pair
                    if src == 'en' and tgt in target_languages:
                        models_per_language[tgt].append(model_id)

    covered = {lang for lang, models in models_per_language.items() if models}
    missing = target_languages - covered

    return CoverageReport(
        total_languages=len(target_languages),
        covered_languages=covered,
        missing_languages=missing,
        coverage_percentage=100 * len(covered) / len(target_languages) if target_languages else 0,
        models_per_language=models_per_language
    )
