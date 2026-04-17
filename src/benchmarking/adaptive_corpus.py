"""Adaptive corpus management for intelligent benchmark sampling.

Provides tiered corpus sampling strategies to enable quick calibration
on fresh setups while supporting comprehensive analysis when needed.
"""

import hashlib
import logging
import random
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class CorpusSample:
    """Single sample from the corpus."""

    sample_id: str
    category: str
    content: str
    metadata: dict[str, str]


@dataclass
class CorpusTier:
    """Configuration for a corpus tier."""

    name: str  # "calibration", "standard", "comprehensive"
    target_samples: int
    target_duration_seconds: int
    min_samples_per_category: int


@dataclass
class SamplingResult:
    """Result of corpus sampling operation."""

    samples: list[CorpusSample]
    tier: str
    coverage_score: float  # 0-1, how representative the sample is
    categories_covered: list[str]
    estimated_duration_seconds: float
    corpus_version: str  # Hash of corpus for tracking


class AdaptiveCorpusManager:
    """Manages adaptive corpus sampling for benchmarks.

    Provides tiered sampling strategies:
    - Calibration: Fast initial benchmark (< 5 min)
    - Standard: Regular benchmarking (~30 min)
    - Comprehensive: Thorough analysis (~2 hours)
    """

    def __init__(self, corpus_manager: object | None = None, config_path: Path | None = None):
        """Initialize adaptive corpus manager.

        Args:
            corpus_manager: Optional existing CorpusManager instance
            config_path: Optional path to corpus config YAML
        """
        self.corpus_manager = corpus_manager
        self.config = self._load_config(config_path)

        # Mock corpus samples for now (would use real corpus_manager if available)
        self._samples = self._generate_mock_samples()

    def _load_config(self, config_path: Path | None) -> dict:
        """Load corpus configuration."""
        default_config = {
            "tiers": {
                "calibration": {"target_samples": 10, "target_duration_seconds": 300, "min_samples_per_category": 1},
                "standard": {"target_samples": 50, "target_duration_seconds": 1800, "min_samples_per_category": 3},
                "comprehensive": {"target_samples": 200, "target_duration_seconds": 7200, "min_samples_per_category": 10},
            },
            "categories": ["technical_docs", "marketing", "legal", "general"],
            "expansion": {
                "confidence_threshold": 0.8,
                "expansion_factor": 1.5,
            },
        }

        if config_path and config_path.exists():
            try:
                with open(config_path) as f:
                    loaded = yaml.safe_load(f)
                    if loaded:
                        # Merge loaded config with defaults
                        default_config.update(loaded)
                        logger.info(f"Loaded corpus config from {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load corpus config: {e}, using defaults")

        return default_config

    def _generate_mock_samples(self) -> list[CorpusSample]:
        """Generate mock corpus samples for testing."""
        categories = self.config["categories"]
        samples = []

        for cat in categories:
            for i in range(50):  # 50 samples per category
                sample_id = f"{cat}_{i:03d}"
                samples.append(
                    CorpusSample(
                        sample_id=sample_id,
                        category=cat,
                        content=f"Sample content for {cat} #{i}",
                        metadata={
                            "source": "mock",
                            "length": str(random.randint(100, 1000)),
                        },
                    )
                )

        return samples

    def get_calibration_corpus(self) -> SamplingResult:
        """Get minimal corpus for fresh setup calibration.

        Returns:
            SamplingResult with ~10 samples across categories (< 5 min)
        """
        tier_config = self.config["tiers"]["calibration"]
        tier = CorpusTier(
            name="calibration",
            target_samples=tier_config["target_samples"],
            target_duration_seconds=tier_config["target_duration_seconds"],
            min_samples_per_category=tier_config["min_samples_per_category"],
        )

        return self.stratified_sample(tier.target_samples)

    def get_standard_corpus(self) -> SamplingResult:
        """Get standard corpus for regular benchmarking.

        Returns:
            SamplingResult with ~50 samples (~30 min)
        """
        tier_config = self.config["tiers"]["standard"]
        tier = CorpusTier(
            name="standard",
            target_samples=tier_config["target_samples"],
            target_duration_seconds=tier_config["target_duration_seconds"],
            min_samples_per_category=tier_config["min_samples_per_category"],
        )

        return self.stratified_sample(tier.target_samples)

    def get_comprehensive_corpus(self) -> SamplingResult:
        """Get comprehensive corpus for thorough analysis.

        Returns:
            SamplingResult with ~200 samples (~2 hours)
        """
        tier_config = self.config["tiers"]["comprehensive"]
        tier = CorpusTier(
            name="comprehensive",
            target_samples=tier_config["target_samples"],
            target_duration_seconds=tier_config["target_duration_seconds"],
            min_samples_per_category=tier_config["min_samples_per_category"],
        )

        return self.stratified_sample(tier.target_samples)

    def expand_corpus(
        self, current: SamplingResult, target_confidence: float
    ) -> SamplingResult:
        """Expand corpus to improve confidence.

        Args:
            current: Current sampling result
            target_confidence: Target confidence level (0-1)

        Returns:
            Expanded SamplingResult
        """
        expansion_factor = self.config["expansion"]["expansion_factor"]

        # Calculate new target based on current confidence gap
        confidence_gap = target_confidence - current.coverage_score
        if confidence_gap <= 0:
            logger.info("Target confidence already achieved")
            return current

        # Increase samples by expansion factor
        new_target = int(len(current.samples) * expansion_factor)
        logger.info(
            f"Expanding corpus from {len(current.samples)} to {new_target} samples "
            f"(current confidence: {current.coverage_score:.2f})"
        )

        return self.stratified_sample(new_target)

    def stratified_sample(
        self, n: int, categories: list[str] | None = None
    ) -> SamplingResult:
        """Sample proportionally from each category.

        Args:
            n: Target number of samples
            categories: Optional list of categories to sample from (default: all)

        Returns:
            SamplingResult with stratified samples
        """
        if categories is None:
            categories = self.config["categories"]

        # Group samples by category
        by_category = {}
        for sample in self._samples:
            if sample.category in categories:
                if sample.category not in by_category:
                    by_category[sample.category] = []
                by_category[sample.category].append(sample)

        # Calculate samples per category (proportional)
        total_available = sum(len(samples) for samples in by_category.values())
        samples_per_category = {}

        for cat in categories:
            if cat in by_category:
                proportion = len(by_category[cat]) / total_available
                samples_per_category[cat] = max(1, int(n * proportion))

        # Sample from each category
        selected = []
        random.seed(42)  # Deterministic sampling

        for cat, target_count in samples_per_category.items():
            if cat in by_category:
                available = by_category[cat]
                count = min(target_count, len(available))
                selected.extend(random.sample(available, count))

        # Calculate coverage score
        coverage = self.validate_representativeness(selected)

        # Estimate duration (rough heuristic: 6 seconds per sample)
        estimated_duration = len(selected) * 6.0

        # Determine tier based on sample count
        tier = "calibration"
        if len(selected) >= 150:
            tier = "comprehensive"
        elif len(selected) >= 40:
            tier = "standard"

        # Get corpus version
        corpus_version = self.get_corpus_version()

        return SamplingResult(
            samples=selected,
            tier=tier,
            coverage_score=coverage,
            categories_covered=list(samples_per_category.keys()),
            estimated_duration_seconds=estimated_duration,
            corpus_version=corpus_version,
        )

    def get_corpus_version(self) -> str:
        """Get corpus version hash for tracking.

        Returns:
            Hash string identifying current corpus content
        """
        # Hash sample IDs for deterministic versioning
        sample_ids = sorted([s.sample_id for s in self._samples])
        content = ",".join(sample_ids)
        hash_obj = hashlib.sha256(content.encode())
        return hash_obj.hexdigest()[:12]

    def validate_representativeness(self, samples: list[CorpusSample]) -> float:
        """Score how representative a sample set is.

        Args:
            samples: List of selected samples

        Returns:
            Score 0-1 (1 = perfectly representative)
        """
        if not samples:
            return 0.0

        categories = self.config["categories"]

        # Count samples per category
        category_counts = {}
        for sample in samples:
            cat = sample.category
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Check if all categories are represented
        categories_covered = len(category_counts)
        category_coverage = categories_covered / len(categories)

        # Check if distribution is balanced (use coefficient of variation)
        if len(category_counts) > 0:
            counts = list(category_counts.values())
            mean = sum(counts) / len(counts)
            if mean > 0:
                variance = sum((x - mean) ** 2 for x in counts) / len(counts)
                std = variance ** 0.5
                cv = std / mean  # Coefficient of variation
                balance_score = max(0.0, 1.0 - cv)  # Lower CV = better balance
            else:
                balance_score = 0.0
        else:
            balance_score = 0.0

        # Combined score (weighted average)
        coverage_score = (category_coverage * 0.6) + (balance_score * 0.4)
        return min(1.0, coverage_score)
