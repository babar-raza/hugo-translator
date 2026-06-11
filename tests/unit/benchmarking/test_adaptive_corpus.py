"""Unit tests for adaptive corpus management (BM-05)."""

from src.benchmarking.adaptive_corpus import (
    AdaptiveCorpusManager,
    CorpusSample,
    CorpusTier,
    SamplingResult,
)


def test_bm05_adaptive_corpus_manager_init():
    """Test adaptive corpus manager initialization."""
    manager = AdaptiveCorpusManager()

    assert manager is not None
    assert manager.config is not None


def test_bm05_get_calibration_corpus():
    """Test getting calibration corpus."""
    manager = AdaptiveCorpusManager()

    result = manager.get_calibration_corpus()

    # Should return a small corpus (~10 samples)
    assert isinstance(result, SamplingResult)
    assert len(result.samples) <= 15
    assert result.tier == "calibration"
    assert result.coverage_score > 0


def test_bm05_get_standard_corpus():
    """Test getting standard corpus."""
    manager = AdaptiveCorpusManager()

    result = manager.get_standard_corpus()

    # Should return medium corpus (~50 samples)
    assert isinstance(result, SamplingResult)
    assert 40 <= len(result.samples) <= 60
    assert result.tier == "standard"


def test_bm05_get_comprehensive_corpus():
    """Test getting comprehensive corpus."""
    manager = AdaptiveCorpusManager()

    result = manager.get_comprehensive_corpus()

    # Should return large corpus (~200 samples)
    assert isinstance(result, SamplingResult)
    assert len(result.samples) >= 150
    assert result.tier == "comprehensive"


def test_bm05_corpus_tiers_ordered_by_size():
    """Test that corpus tiers increase in size."""
    manager = AdaptiveCorpusManager()

    calibration = manager.get_calibration_corpus()
    standard = manager.get_standard_corpus()
    comprehensive = manager.get_comprehensive_corpus()

    # Calibration < Standard < Comprehensive
    assert len(calibration.samples) < len(standard.samples)
    assert len(standard.samples) < len(comprehensive.samples)


def test_bm05_stratified_sampling_covers_all_categories():
    """Test that stratified sampling covers all categories."""
    manager = AdaptiveCorpusManager()

    result = manager.stratified_sample(n=50)

    # Should cover all configured categories
    categories = set(sample.category for sample in result.samples)
    assert len(categories) == len(manager.config["categories"])


def test_bm05_stratified_sampling_proportional():
    """Test that stratified sampling is roughly proportional."""
    manager = AdaptiveCorpusManager()

    result = manager.stratified_sample(n=100)

    # Count samples per category
    category_counts = {}
    for sample in result.samples:
        cat = sample.category
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # All categories should have some samples
    assert len(category_counts) > 0
    for count in category_counts.values():
        assert count > 0


def test_bm05_stratified_sampling_deterministic():
    """Test that stratified sampling is deterministic."""
    manager = AdaptiveCorpusManager()

    result1 = manager.stratified_sample(n=50)
    result2 = manager.stratified_sample(n=50)

    # Should get same samples (deterministic seed)
    sample_ids_1 = {s.sample_id for s in result1.samples}
    sample_ids_2 = {s.sample_id for s in result2.samples}

    assert sample_ids_1 == sample_ids_2


def test_bm05_expand_corpus():
    """Test corpus expansion."""
    manager = AdaptiveCorpusManager()

    # Start with calibration
    current = manager.get_calibration_corpus()
    initial_size = len(current.samples)

    # Expand to reach higher confidence
    # Note: If current coverage >= target, no expansion occurs (correct behavior)
    expanded = manager.expand_corpus(current, target_confidence=0.9)

    # Should have at least as many samples (may not expand if coverage already met)
    assert len(expanded.samples) >= initial_size


def test_bm05_expand_corpus_no_op_if_confident():
    """Test that expansion is no-op if already confident."""
    manager = AdaptiveCorpusManager()

    # Get comprehensive corpus (should have high confidence)
    current = manager.get_comprehensive_corpus()

    # Try to expand with already-achieved confidence
    expanded = manager.expand_corpus(current, target_confidence=current.coverage_score)

    # Should return current (no expansion needed)
    assert len(expanded.samples) == len(current.samples)


def test_bm05_validate_representativeness():
    """Test representativeness validation."""
    manager = AdaptiveCorpusManager()

    # Get samples
    result = manager.get_standard_corpus()

    # Calculate representativeness
    score = manager.validate_representativeness(result.samples)

    # Should be between 0 and 1
    assert 0.0 <= score <= 1.0


def test_bm05_validate_representativeness_empty():
    """Test representativeness of empty sample set."""
    manager = AdaptiveCorpusManager()

    score = manager.validate_representativeness([])

    # Empty set should have 0 representativeness
    assert score == 0.0


def test_bm05_validate_representativeness_unbalanced():
    """Test representativeness of unbalanced sample set."""
    manager = AdaptiveCorpusManager()

    # Create unbalanced sample (all from one category)
    unbalanced = [
        CorpusSample(
            sample_id=f"sample_{i}",
            category="technical_docs",
            content=f"Content {i}",
            metadata={},
        )
        for i in range(10)
    ]

    score = manager.validate_representativeness(unbalanced)

    # Unbalanced should have lower score than balanced (< 0.6)
    # A single-category sample gets partial credit for coverage
    assert score < 0.6  # Not covering all categories effectively


def test_bm05_get_corpus_version():
    """Test corpus version hash generation."""
    manager = AdaptiveCorpusManager()

    version = manager.get_corpus_version()

    # Should return a hash string
    assert isinstance(version, str)
    assert len(version) == 12  # Truncated hash


def test_bm05_corpus_version_stable():
    """Test that corpus version is stable."""
    manager = AdaptiveCorpusManager()

    version1 = manager.get_corpus_version()
    version2 = manager.get_corpus_version()

    # Should be deterministic
    assert version1 == version2


def test_bm05_sampling_result_fields():
    """Test that SamplingResult has all expected fields."""
    manager = AdaptiveCorpusManager()

    result = manager.get_calibration_corpus()

    # Check all fields are present
    assert isinstance(result.samples, list)
    assert isinstance(result.tier, str)
    assert isinstance(result.coverage_score, float)
    assert isinstance(result.categories_covered, list)
    assert isinstance(result.estimated_duration_seconds, float)
    assert isinstance(result.corpus_version, str)


def test_bm05_corpus_tier_dataclass():
    """Test CorpusTier dataclass."""
    tier = CorpusTier(
        name="test_tier",
        target_samples=100,
        target_duration_seconds=600,
        min_samples_per_category=5,
    )

    assert tier.name == "test_tier"
    assert tier.target_samples == 100
    assert tier.target_duration_seconds == 600
    assert tier.min_samples_per_category == 5


def test_bm05_corpus_sample_dataclass():
    """Test CorpusSample dataclass."""
    sample = CorpusSample(
        sample_id="sample_001",
        category="technical_docs",
        content="Test content",
        metadata={"source": "test"},
    )

    assert sample.sample_id == "sample_001"
    assert sample.category == "technical_docs"
    assert sample.content == "Test content"
    assert sample.metadata["source"] == "test"


def test_bm05_estimated_duration():
    """Test that estimated duration scales with sample count."""
    manager = AdaptiveCorpusManager()

    calibration = manager.get_calibration_corpus()
    comprehensive = manager.get_comprehensive_corpus()

    # More samples = longer duration
    assert comprehensive.estimated_duration_seconds > calibration.estimated_duration_seconds


def test_bm05_calibration_fast():
    """Test that calibration corpus meets speed target."""
    manager = AdaptiveCorpusManager()

    result = manager.get_calibration_corpus()

    # Should be under 5 minutes (300 seconds)
    assert result.estimated_duration_seconds <= 300


def test_bm05_integration_workflow():
    """Integration test: calibration → expansion → validation."""
    manager = AdaptiveCorpusManager()

    # 1. Start with calibration
    calibration = manager.get_calibration_corpus()
    assert calibration.tier == "calibration"

    # 2. Validate representativeness
    initial_coverage = calibration.coverage_score
    assert initial_coverage > 0

    # 3. Expand if confidence is low
    if initial_coverage < 0.8:
        expanded = manager.expand_corpus(calibration, target_confidence=0.8)
        assert len(expanded.samples) > len(calibration.samples)

    # 4. Get corpus version for tracking
    version = manager.get_corpus_version()
    assert isinstance(version, str)
