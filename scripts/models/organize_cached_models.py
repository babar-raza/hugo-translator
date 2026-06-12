#!/usr/bin/env python3
"""
Organize cached HuggingFace models into repository structure.

This script:
1. Scans HuggingFace cache directory
2. Categorizes models by vendor and purpose
3. Copies them to organized models/ directory
4. Generates metadata for model registry update
"""

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class ModelMetadata:
    """Metadata for a discovered model."""

    model_id: str
    vendor: str
    category: str
    source_path: Path
    target_path: Path
    model_type: str  # 'opus', 'm2m100', 'nllb', 't5', etc.
    supported_pairs: list | None = None
    notes: str = ""


class ModelOrganizer:
    """Organize HuggingFace cached models into repository structure."""

    def __init__(self, cache_dir: Path, models_dir: Path, dry_run: bool = False):
        self.cache_dir = cache_dir
        self.models_dir = models_dir
        self.dry_run = dry_run
        self.discovered_models: list[ModelMetadata] = []

    def scan_cache(self) -> list[ModelMetadata]:
        """Scan HuggingFace cache and categorize models."""
        logger.info(f"Scanning cache directory: {self.cache_dir}")

        if not self.cache_dir.exists():
            logger.error(f"Cache directory not found: {self.cache_dir}")
            return []

        cache_items = list(self.cache_dir.iterdir())
        logger.info(f"Found {len(cache_items)} items in cache")

        for item in cache_items:
            if not item.is_dir() or not item.name.startswith("models--"):
                continue

            # Parse model name from cache directory format
            # models--Helsinki-NLP--opus-mt-en-ar -> Helsinki-NLP/opus-mt-en-ar
            model_parts = item.name.replace("models--", "").split("--")
            if len(model_parts) < 2:
                logger.warning(f"Unexpected format: {item.name}")
                continue

            vendor = model_parts[0]
            model_name = "--".join(model_parts[1:])
            model_id = f"{vendor}/{model_name}"

            metadata = self._categorize_model(vendor, model_name, model_id, item)
            if metadata:
                self.discovered_models.append(metadata)

        logger.info(f"Categorized {len(self.discovered_models)} models")
        return self.discovered_models

    def _categorize_model(
        self, vendor: str, model_name: str, model_id: str, source_path: Path
    ) -> ModelMetadata | None:
        """Categorize a model and determine its target location."""

        # Categorize by vendor and type
        if vendor == "Helsinki-NLP":
            return self._categorize_opus_model(vendor, model_name, model_id, source_path)
        elif vendor == "facebook":
            return self._categorize_facebook_model(vendor, model_name, model_id, source_path)
        elif vendor in ("google", "google-t5"):
            return self._categorize_google_model(vendor, model_name, model_id, source_path)
        else:
            # Other models - categorize as misc
            target_path = self.models_dir / "misc" / model_name
            return ModelMetadata(
                model_id=model_id,
                vendor=vendor,
                category="misc",
                source_path=source_path,
                target_path=target_path,
                model_type="other",
                notes=f"Vendor: {vendor}",
            )

    def _categorize_opus_model(
        self, vendor: str, model_name: str, model_id: str, source_path: Path
    ) -> ModelMetadata:
        """Categorize Helsinki-NLP OPUS models."""
        # Extract language pair from model name
        # opus-mt-en-ar -> en->ar
        # opus-mt-tc-big-en-fr -> en->fr (big variant)

        lang_pair = None
        if match := re.match(r"opus-mt-(?:tc-big-)?([a-z]+)-([a-z]+)", model_name):
            src_lang = match.group(1)
            tgt_lang = match.group(2)
            lang_pair = [src_lang, tgt_lang]
        elif "ROMANCE" in model_name:
            lang_pair = "multilingual"

        target_path = self.models_dir / "opus" / model_name

        return ModelMetadata(
            model_id=model_id,
            vendor=vendor,
            category="opus",
            source_path=source_path,
            target_path=target_path,
            model_type="opus-mt",
            supported_pairs=[lang_pair] if lang_pair else None,
            notes=f"Specialized translation model: {lang_pair if lang_pair else 'multilingual'}",
        )

    def _categorize_facebook_model(
        self, vendor: str, model_name: str, model_id: str, source_path: Path
    ) -> ModelMetadata:
        """Categorize Facebook models (M2M100, NLLB)."""
        if "m2m100" in model_name.lower():
            model_type = "m2m100"
            category = "multilingual"
            notes = "100-language multilingual translation"
        elif "nllb" in model_name.lower():
            model_type = "nllb"
            category = "multilingual"
            notes = "200-language No Language Left Behind"
        elif "bart" in model_name.lower():
            model_type = "bart"
            category = "misc"
            notes = "BART sequence-to-sequence model"
        else:
            model_type = "facebook-other"
            category = "misc"
            notes = f"Facebook model: {model_name}"

        target_path = self.models_dir / category / model_name

        return ModelMetadata(
            model_id=model_id,
            vendor=vendor,
            category=category,
            source_path=source_path,
            target_path=target_path,
            model_type=model_type,
            supported_pairs=["all"] if category == "multilingual" else None,
            notes=notes,
        )

    def _categorize_google_model(
        self, vendor: str, model_name: str, model_id: str, source_path: Path
    ) -> ModelMetadata:
        """Categorize Google models (T5, Flan-T5, Gemma)."""
        if "t5" in model_name.lower():
            model_type = "t5"
            category = "t5"
            notes = "T5 text-to-text transfer transformer"
        elif "gemma" in model_name.lower():
            model_type = "gemma"
            category = "llm"
            notes = "Gemma language model"
        else:
            model_type = "google-other"
            category = "misc"
            notes = f"Google model: {model_name}"

        target_path = self.models_dir / category / model_name

        return ModelMetadata(
            model_id=model_id,
            vendor=vendor,
            category=category,
            source_path=source_path,
            target_path=target_path,
            model_type=model_type,
            notes=notes,
        )

    def copy_models(self) -> dict[str, int]:
        """Copy models from cache to organized structure."""
        stats = {"copied": 0, "skipped": 0, "failed": 0}

        for model in self.discovered_models:
            try:
                # Find snapshots directory in cache
                snapshots_dir = model.source_path / "snapshots"
                if not snapshots_dir.exists():
                    logger.warning(f"No snapshots found for {model.model_id}")
                    stats["skipped"] += 1
                    continue

                # Get latest snapshot
                snapshots = sorted(snapshots_dir.iterdir(), key=lambda p: p.stat().st_mtime)
                if not snapshots:
                    logger.warning(f"Empty snapshots for {model.model_id}")
                    stats["skipped"] += 1
                    continue

                latest_snapshot = snapshots[-1]

                if self.dry_run:
                    logger.info(f"[DRY RUN] Would copy: {model.model_id}")
                    logger.info(f"  From: {latest_snapshot}")
                    logger.info(f"  To: {model.target_path}")
                    stats["copied"] += 1
                else:
                    # Create target directory
                    model.target_path.parent.mkdir(parents=True, exist_ok=True)

                    # Copy model files
                    if model.target_path.exists():
                        logger.info(f"Model already exists: {model.model_id}")
                        stats["skipped"] += 1
                    else:
                        logger.info(f"Copying {model.model_id}...")
                        shutil.copytree(latest_snapshot, model.target_path)
                        logger.info(f"  -> {model.target_path}")
                        stats["copied"] += 1

            except Exception as e:
                logger.error(f"Failed to copy {model.model_id}: {e}")
                stats["failed"] += 1

        return stats

    def generate_registry_entries(self, output_file: Path):
        """Generate YAML entries for model registry."""
        # Group models by category
        by_category = {}
        for model in self.discovered_models:
            if model.category not in by_category:
                by_category[model.category] = []
            by_category[model.category].append(model)

        # Generate YAML-like output
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("# Model Registry Entries\n")
            f.write("# Generated from HuggingFace cache scan\n\n")

            for category in sorted(by_category.keys()):
                f.write(f"\n# ========== {category.upper()} MODELS ==========\n\n")

                for model in sorted(by_category[category], key=lambda m: m.model_id):
                    f.write(f"  - model_id: {model.model_id}\n")
                    f.write("    backend: transformers\n")
                    f.write(f"    model_type: {model.model_type}\n")
                    f.write(
                        f"    model_path: {model.target_path.relative_to(self.models_dir.parent)}\n"
                    )

                    if model.supported_pairs:
                        if model.supported_pairs == ["all"]:
                            f.write("    supported_pairs: all\n")
                        else:
                            f.write("    supported_pairs:\n")
                            for pair in model.supported_pairs:
                                if isinstance(pair, list):
                                    f.write(f"      - [{pair[0]}, {pair[1]}]\n")

                    f.write(f"    notes: {model.notes}\n")
                    f.write("\n")

        logger.info(f"Registry entries written to: {output_file}")

    def generate_summary_report(self) -> str:
        """Generate summary report of discovered models."""
        by_category = {}
        for model in self.discovered_models:
            if model.category not in by_category:
                by_category[model.category] = []
            by_category[model.category].append(model)

        report = []
        report.append("\n" + "=" * 80)
        report.append("MODEL ORGANIZATION SUMMARY")
        report.append("=" * 80 + "\n")

        report.append(f"Total models discovered: {len(self.discovered_models)}\n")

        for category in sorted(by_category.keys()):
            models = by_category[category]
            report.append(f"\n{category.upper()}: {len(models)} models")
            report.append("-" * 40)

            for model in sorted(models, key=lambda m: m.model_id)[:10]:  # Show first 10
                report.append(f"  - {model.model_id}")

            if len(models) > 10:
                report.append(f"  ... and {len(models) - 10} more")

        report.append("\n" + "=" * 80 + "\n")
        return "\n".join(report)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Organize HuggingFace cached models")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "huggingface" / "hub",
        help="HuggingFace cache directory",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path(__file__).parent.parent / "models",
        help="Target models directory",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done without copying"
    )
    parser.add_argument(
        "--registry-output",
        type=Path,
        default=Path(__file__).parent.parent / "config" / "model_registry_additions.yaml",
        help="Output file for registry entries",
    )

    args = parser.parse_args()

    organizer = ModelOrganizer(
        cache_dir=args.cache_dir, models_dir=args.models_dir, dry_run=args.dry_run
    )

    # Scan cache
    models = organizer.scan_cache()

    if not models:
        logger.error("No models found in cache")
        return 1

    # Print summary
    print(organizer.generate_summary_report())

    # Copy models
    if args.dry_run:
        logger.info("\n*** DRY RUN MODE - No files will be copied ***\n")

    stats = organizer.copy_models()

    logger.info("\n" + "=" * 80)
    logger.info("COPY STATISTICS")
    logger.info("=" * 80)
    logger.info(f"Copied: {stats['copied']}")
    logger.info(f"Skipped: {stats['skipped']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info("=" * 80 + "\n")

    # Generate registry entries
    organizer.generate_registry_entries(args.registry_output)

    return 0


if __name__ == "__main__":
    exit(main())
