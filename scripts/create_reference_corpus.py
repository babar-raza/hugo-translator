#!/usr/bin/env python3
"""
Create reference translation corpus from WMT test sets.

Downloads WMT newstest datasets and creates a standardized corpus format
with reference translations for quality benchmarking (BLEU, COMET).

Usage:
    python scripts/create_reference_corpus.py --year 2020 --languages es,fr,de --samples 100
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

import sacrebleu

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


class ReferenceCorpusCreator:
    """
    Create reference translation corpus from WMT datasets.

    Uses sacrebleu to download WMT test sets with official reference translations.
    """

    def __init__(self, output_dir: Path):
        """
        Initialize corpus creator.

        Args:
            output_dir: Directory to save corpus files
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_wmt_testset(
        self,
        testset: str,
        lang_pair: str,
        max_samples: int = None
    ) -> List[Dict]:
        """
        Download WMT test set for a language pair.

        Args:
            testset: WMT test set name (e.g., "wmt20", "wmt21")
            lang_pair: Language pair (e.g., "en-de", "en-cs")
            max_samples: Maximum number of samples to extract

        Returns:
            List of corpus entries with source and reference translations
        """
        source_lang, target_lang = lang_pair.split("-")

        try:
            logger.info(f"Downloading {testset} {lang_pair}...")

            # Check if test set exists
            if testset not in sacrebleu.DATASETS:
                logger.error(f"Test set {testset} not found in sacrebleu")
                return []

            dataset = sacrebleu.DATASETS[testset]

            # Check if language pair is available
            if lang_pair not in dataset.langpairs:
                logger.error(f"Language pair {lang_pair} not available in {testset}")
                logger.info(f"Available pairs: {list(dataset.langpairs.keys())}")
                return []

            # Get source and reference from sacrebleu
            # These return generators, so we convert to lists
            srcs = list(dataset.source(lang_pair))
            refs = list(dataset.references(lang_pair))

            # sacrebleu refs is a list of tuples, each containing reference translations
            corpus = []
            num_samples = len(srcs) if max_samples is None else min(len(srcs), max_samples)

            for i in range(num_samples):
                entry = {
                    "id": f"{testset}_{lang_pair}_{i:04d}",
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "source_text": srcs[i].strip(),
                    "reference_text": refs[i][0].strip(),  # First reference, strip newlines
                    "testset": testset,
                    "dataset": "wmt",
                }
                corpus.append(entry)

            logger.info(f"Extracted {len(corpus)} samples for {lang_pair}")
            return corpus

        except Exception as e:
            logger.error(f"Failed to download {testset} {lang_pair}: {e}")
            return []

    def create_corpus(
        self,
        testsets: List[str],
        lang_pairs: List[str],
        max_samples_per_pair: int = 100
    ) -> Dict[str, List[Dict]]:
        """
        Create reference corpus from multiple test sets and language pairs.

        Args:
            testsets: List of WMT test sets (e.g., ["wmt20", "wmt21"])
            lang_pairs: List of language pairs (e.g., ["en-es", "en-fr"])
            max_samples_per_pair: Maximum samples per language pair

        Returns:
            Dictionary mapping language pairs to corpus entries
        """
        corpus_by_lang = {}

        for lang_pair in lang_pairs:
            corpus_by_lang[lang_pair] = []

            for testset in testsets:
                samples = self.download_wmt_testset(
                    testset,
                    lang_pair,
                    max_samples=max_samples_per_pair
                )
                corpus_by_lang[lang_pair].extend(samples)

        return corpus_by_lang

    def save_corpus(
        self,
        corpus_by_lang: Dict[str, List[Dict]],
        metadata: Dict = None
    ):
        """
        Save corpus to JSON files (one per language pair).

        Args:
            corpus_by_lang: Dictionary mapping language pairs to corpus entries
            metadata: Optional metadata to include in each file
        """
        for lang_pair, corpus in corpus_by_lang.items():
            if not corpus:
                logger.warning(f"No samples for {lang_pair}, skipping")
                continue

            # Create filename
            safe_lang_pair = lang_pair.replace("-", "_")
            output_file = self.output_dir / f"wmt_{safe_lang_pair}.json"

            # Add metadata
            corpus_data = {
                "metadata": metadata or {},
                "language_pair": lang_pair,
                "sample_count": len(corpus),
                "samples": corpus
            }

            # Save to JSON
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(corpus_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved {len(corpus)} samples to {output_file}")

    def create_metadata(
        self,
        testsets: List[str],
        lang_pairs: List[str],
        max_samples: int
    ) -> Dict:
        """
        Create metadata for corpus files.

        Args:
            testsets: List of WMT test sets used
            lang_pairs: List of language pairs
            max_samples: Maximum samples per pair

        Returns:
            Metadata dictionary
        """
        return {
            "source": "WMT test sets via sacrebleu",
            "testsets": testsets,
            "language_pairs": lang_pairs,
            "max_samples_per_pair": max_samples,
            "purpose": "Reference translations for BLEU/COMET quality metrics",
            "citation": "Post, Matt. 2018. A Call for Clarity in Reporting BLEU Scores. "
                       "In Proceedings of the Third Conference on Machine Translation: "
                       "Research Papers, pp. 186–191, Belgium, Brussels. "
                       "Association for Computational Linguistics.",
        }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create reference translation corpus from WMT test sets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create corpus for EN→DE, EN→CS from WMT20/21 (100 samples each)
  python scripts/create_reference_corpus.py --years 2020,2021 --languages de,cs --samples 100

  # Create comprehensive corpus with more samples
  python scripts/create_reference_corpus.py --years 2020,2021 --languages de,cs,ru,zh --samples 200

  # Quick test corpus
  python scripts/create_reference_corpus.py --years 2020 --languages de --samples 10

Note:
  WMT20 and WMT21 support EN→DE, EN→CS, EN→RU, EN→ZH, EN→JA, and others.
  Use --languages to specify target languages (source is always 'en').
        """
    )

    parser.add_argument(
        "--years",
        type=str,
        default="2020",
        help="Comma-separated list of WMT years (e.g., '2020,2021')"
    )

    parser.add_argument(
        "--languages",
        type=str,
        default="de,cs,ru,zh",
        help="Comma-separated list of target languages (source is always 'en'). WMT20/21 support: de,cs,ru,zh,ja"
    )

    parser.add_argument(
        "--samples",
        type=int,
        default=100,
        help="Maximum number of samples per language pair (default: 100)"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/reference_corpus",
        help="Output directory for corpus files (default: data/reference_corpus)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Parse arguments
    years = [y.strip() for y in args.years.split(",")]
    languages = [lang.strip() for lang in args.languages.split(",")]

    # Convert years to test set names
    testsets = [f"wmt{year[2:]}" if len(year) == 4 else f"wmt{year}" for year in years]

    # Create language pairs (always EN→target)
    lang_pairs = [f"en-{lang}" for lang in languages]

    logger.info(f"Creating reference corpus:")
    logger.info(f"  Test sets: {testsets}")
    logger.info(f"  Language pairs: {lang_pairs}")
    logger.info(f"  Max samples per pair: {args.samples}")

    # Create corpus
    output_dir = Path(args.output_dir)
    creator = ReferenceCorpusCreator(output_dir)

    try:
        # Download and create corpus
        corpus_by_lang = creator.create_corpus(
            testsets=testsets,
            lang_pairs=lang_pairs,
            max_samples_per_pair=args.samples
        )

        # Create metadata
        metadata = creator.create_metadata(
            testsets=testsets,
            lang_pairs=lang_pairs,
            max_samples=args.samples
        )

        # Save to files
        creator.save_corpus(corpus_by_lang, metadata)

        # Print summary
        total_samples = sum(len(corpus) for corpus in corpus_by_lang.values())
        logger.info(f"\n{'='*60}")
        logger.info(f"Reference corpus created successfully!")
        logger.info(f"  Total samples: {total_samples}")
        logger.info(f"  Language pairs: {len(corpus_by_lang)}")
        logger.info(f"  Output directory: {output_dir}")
        logger.info(f"{'='*60}")

        return 0

    except Exception as e:
        logger.error(f"Failed to create reference corpus: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
