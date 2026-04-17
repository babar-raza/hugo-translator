#!/usr/bin/env python3
"""
Generate Final Matrix Report from Benchmark Results.

Analyzes benchmark database to produce:
- Top model per language (by speed)
- Coverage gaps (languages missing specialized models)
- Recommended default model policy for production

Output: runs/<timestamp>/FINAL_MATRIX_REPORT.md
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.analytics import AnalyticsQueryAPI
from src.model_runtime.registry import ModelRegistry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_target_languages() -> List[Dict]:
    """Load target languages from config."""
    config_path = Path('config/target_languages.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config.get('languages', [])


def analyze_top_models_per_language(
    db: BenchmarkDatabase,
    languages: List[str],
    device: str = 'cuda',
) -> Dict[str, Dict]:
    """
    Analyze top-performing model for each language.

    Args:
        db: BenchmarkDatabase instance
        languages: List of language codes
        device: Device filter ('cpu', 'cuda')

    Returns:
        Dictionary mapping language -> {model_id, throughput, ...}
    """
    logger.info(f"Analyzing top models per language on {device}")

    top_models = {}

    for lang in languages:
        # Query benchmark results for this language
        query = f"""
            SELECT
                br.model_id,
                AVG(br.throughput_tokens_per_sec) as avg_throughput,
                COUNT(*) as sample_count
            FROM benchmark_results br
            JOIN benchmark_runs r ON br.run_id = r.run_id
            WHERE br.tgt_lang = ? AND br.device = ?
            GROUP BY br.model_id
            ORDER BY avg_throughput DESC
            LIMIT 1
        """

        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (lang, device))
            result = cursor.fetchone()

        if result:
            top_models[lang] = {
                'model_id': result['model_id'],
                'avg_throughput': result['avg_throughput'],
                'sample_count': result['sample_count'],
            }
        else:
            logger.warning(f"No benchmark results found for {lang} on {device}")
            top_models[lang] = {
                'model_id': 'N/A',
                'avg_throughput': 0.0,
                'sample_count': 0,
            }

    return top_models


def analyze_coverage_gaps(
    registry: ModelRegistry,
    languages: List[str],
) -> Dict[str, List[str]]:
    """
    Analyze coverage gaps: languages without specialized models.

    Args:
        registry: ModelRegistry instance
        languages: List of language codes

    Returns:
        Dictionary with:
            - 'specialized': Languages with specialized models
            - 'multilingual_only': Languages with only multilingual models
    """
    logger.info("Analyzing model coverage gaps")

    models = registry.list_models()

    # Categorize languages
    specialized_langs = set()
    all_supported_langs = set(languages)

    for model in models:
        supported_pairs = model.supported_pairs

        if supported_pairs != 'all' and isinstance(supported_pairs, list):
            # This is a specialized model
            for pair in supported_pairs:
                # Pairs are tuples in ModelInfo
                if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] == 'en':
                    tgt_lang = pair[1]
                    if tgt_lang in all_supported_langs:
                        specialized_langs.add(tgt_lang)

    multilingual_only = all_supported_langs - specialized_langs

    return {
        'specialized': sorted(list(specialized_langs)),
        'multilingual_only': sorted(list(multilingual_only)),
    }


def recommend_model_policy(
    top_models: Dict[str, Dict],
    coverage_gaps: Dict[str, List[str]],
) -> Dict:
    """
    Recommend default model policy for production.

    Args:
        top_models: Top models per language from benchmark results
        coverage_gaps: Coverage gap analysis

    Returns:
        Dictionary with recommendation and rationale
    """
    logger.info("Generating model policy recommendation")

    # Count how many languages have specialized models in top performers
    specialized_count = 0
    for lang in top_models:
        model_id = top_models[lang]['model_id']
        if model_id != 'N/A' and 'opus' in model_id.lower():
            specialized_count += 1

    total_langs = len(top_models)
    specialized_ratio = specialized_count / total_langs if total_langs > 0 else 0

    # Recommendation logic
    if specialized_ratio > 0.3:
        # Many languages benefit from specialized models
        policy = 'fallback-chain'
        rationale = (
            f"{specialized_ratio*100:.0f}% of languages perform best with specialized models. "
            f"Recommend fallback-chain policy: use specialized models where available, "
            f"fall back to multilingual for others."
        )
    else:
        # Most languages do well with multilingual
        policy = 'fixed'
        fixed_model = 'm2m100_418m_ct2'  # Fast multilingual model
        rationale = (
            f"Only {specialized_ratio*100:.0f}% of languages benefit from specialized models. "
            f"Recommend fixed policy with {fixed_model} for simplicity and consistent performance."
        )

    return {
        'recommended_policy': policy,
        'rationale': rationale,
        'specialized_ratio': specialized_ratio,
    }


def generate_report(
    db_path: Path,
    output_path: Path,
    languages: Optional[List[str]] = None,
    device: str = 'cuda',
):
    """
    Generate final matrix report.

    Args:
        db_path: Path to benchmark database
        output_path: Path to output markdown report
        languages: List of languages to analyze (None = all)
        device: Device to analyze ('cpu', 'cuda')
    """
    logger.info(f"Generating matrix report from {db_path}")

    # Initialize components
    db = BenchmarkDatabase(db_path)
    registry = ModelRegistry()

    # Load languages
    if languages is None:
        all_langs = load_target_languages()
        languages = [lang['iso_code'] for lang in all_langs]

    # Analyze
    top_models = analyze_top_models_per_language(db, languages, device)
    coverage_gaps = analyze_coverage_gaps(registry, languages)
    recommendation = recommend_model_policy(top_models, coverage_gaps)

    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# Final Benchmark Matrix Report\n\n")
        f.write(f"**Generated:** {datetime.now(UTC).isoformat()}\n")
        f.write(f"**Device:** {device}\n")
        f.write(f"**Languages Analyzed:** {len(languages)}\n")
        f.write(f"**Database:** {db_path}\n\n")

        # Executive Summary
        f.write(f"## Executive Summary\n\n")
        f.write(f"**Recommended Model Policy:** `{recommendation['recommended_policy']}`\n\n")
        f.write(f"**Rationale:** {recommendation['rationale']}\n\n")

        # Coverage Analysis
        f.write(f"## Coverage Analysis\n\n")
        f.write(f"### Languages with Specialized Models ({len(coverage_gaps['specialized'])})\n\n")
        for lang in coverage_gaps['specialized']:
            f.write(f"- {lang}\n")

        f.write(f"\n### Languages with Multilingual Models Only ({len(coverage_gaps['multilingual_only'])})\n\n")
        for lang in coverage_gaps['multilingual_only']:
            f.write(f"- {lang}\n")

        # Top Models Per Language
        f.write(f"\n## Top Models Per Language (by Speed)\n\n")
        f.write(f"| Language | Top Model | Avg Throughput (tokens/sec) | Samples |\n")
        f.write(f"|----------|-----------|------------------------------|----------|\n")

        for lang in sorted(top_models.keys()):
            data = top_models[lang]
            model_id = data['model_id']
            throughput = data['avg_throughput']
            samples = data['sample_count']
            f.write(f"| {lang} | {model_id} | {throughput:.1f} | {samples} |\n")

        # Recommendations
        f.write(f"\n## Production Recommendations\n\n")
        f.write(f"### Model Selection Strategy\n\n")

        if recommendation['recommended_policy'] == 'fallback-chain':
            f.write(f"1. **Primary:** Use specialized models for languages with dedicated support:\n")
            for lang in coverage_gaps['specialized'][:5]:  # Show top 5
                if lang in top_models:
                    f.write(f"   - {lang}: {top_models[lang]['model_id']}\n")
            f.write(f"\n2. **Fallback:** Use `m2m100_418m_ct2` for all other languages\n")

        elif recommendation['recommended_policy'] == 'fixed':
            f.write(f"1. **Use single model for all languages:** `m2m100_418m_ct2`\n")
            f.write(f"2. **Rationale:** Consistent performance, simpler deployment\n")

        f.write(f"\n### Deployment Configuration\n\n")
        f.write(f"```yaml\n")
        f.write(f"model_defaults:\n")
        f.write(f"  fallback_model: \"m2m100_418m_ct2\"\n")
        f.write(f"  device: \"{device}\"\n")
        f.write(f"  batch_size: 8\n")
        f.write(f"  policy: \"{recommendation['recommended_policy']}\"\n")
        f.write(f"```\n\n")

        # Appendix
        f.write(f"## Appendix: Benchmark Methodology\n\n")
        f.write(f"- **Corpus:** Stratified sample across aspose.net subdomains and families\n")
        f.write(f"- **Metrics:** Average throughput (tokens/second)\n")
        f.write(f"- **Device:** {device}\n")
        f.write(f"- **Iterations:** 3 per benchmark\n")

    logger.info(f"Wrote matrix report to {output_path}")
    print(f"\n{'='*60}")
    print(f"FINAL MATRIX REPORT")
    print(f"{'='*60}")
    print(f"Recommended policy: {recommendation['recommended_policy']}")
    print(f"Languages analyzed: {len(languages)}")
    print(f"Languages with specialized models: {len(coverage_gaps['specialized'])}")
    print(f"Report: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Generate final benchmark matrix report')
    parser.add_argument('--db-path', type=Path, default=Path('data/benchmarks/benchmarks.db'),
                       help='Path to benchmark database')
    parser.add_argument('--output', type=Path, required=True, help='Output report path')
    parser.add_argument('--langs', nargs='+', help='Languages to analyze (default: all)')
    parser.add_argument('--device', default='cuda', choices=['cpu', 'cuda'], help='Device to analyze')

    args = parser.parse_args()

    generate_report(
        db_path=args.db_path,
        output_path=args.output,
        languages=args.langs,
        device=args.device,
    )


if __name__ == '__main__':
    main()
