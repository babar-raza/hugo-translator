"""
Unit tests for batch creation logic.

Tests the batch boundary calculation and deduplication guards
to prevent the bug found in Phase 6 where 248 files became 410 records.
"""

from collections import Counter

import pytest


def create_batches(inventory: list, batch_size: int) -> list:
    """
    Create batches from inventory, grouped by site.

    Args:
        inventory: List of dicts with 'subdomain' and other fields
        batch_size: Number of items per batch

    Returns:
        List of batches (each batch is a list of inventory rows)
    """
    # Group by site
    sites = {}
    for row in inventory:
        subdomain = row["subdomain"]
        if subdomain not in sites:
            sites[subdomain] = []
        sites[subdomain].append(row)

    # Create batches
    all_batches = []
    for site_id, rows in sites.items():
        # Split into batches of batch_size
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            all_batches.append(batch)

    return all_batches


def validate_batches(batches: list, expected_total: int):
    """
    Validate batch creation results.

    Raises:
        AssertionError: If validation fails
    """
    # Count total items
    total_items = sum(len(batch) for batch in batches)
    assert total_items == expected_total, (
        f"Total items in batches ({total_items}) != expected ({expected_total})"
    )

    # Check for duplicates by collecting all items
    all_items = []
    for batch in batches:
        all_items.extend(batch)

    # Use a unique identifier (assume 'source_path' exists)
    identifiers = [item.get("source_path", id(item)) for item in all_items]
    duplicate_count = len(identifiers) - len(set(identifiers))

    if duplicate_count > 0:
        # Find which items are duplicated
        counts = Counter(identifiers)
        duplicates = {k: v for k, v in counts.items() if v > 1}
        raise AssertionError(
            f"Found {duplicate_count} duplicate items in batches. "
            f"Duplicated identifiers: {list(duplicates.keys())[:5]}..."
        )


class TestBatchCreation:
    """Test batch creation logic."""

    def test_single_site_exact_batch_size(self):
        """Test single site with exact batch size."""
        inventory = [
            {"subdomain": "docs.example.com", "source_path": f"file{i}.md"} for i in range(23)
        ]
        batches = create_batches(inventory, batch_size=23)

        assert len(batches) == 1
        assert len(batches[0]) == 23
        validate_batches(batches, expected_total=23)

    def test_single_site_multiple_batches(self):
        """Test single site requiring multiple batches."""
        inventory = [
            {"subdomain": "docs.example.com", "source_path": f"file{i}.md"} for i in range(50)
        ]
        batches = create_batches(inventory, batch_size=23)

        assert len(batches) == 3  # 23 + 23 + 4
        assert len(batches[0]) == 23
        assert len(batches[1]) == 23
        assert len(batches[2]) == 4
        validate_batches(batches, expected_total=50)

    def test_multiple_sites(self):
        """Test multiple sites with different file counts."""
        inventory = []
        # Site 1: 50 files
        for i in range(50):
            inventory.append({"subdomain": "docs.site1.com", "source_path": f"site1_file{i}.md"})
        # Site 2: 30 files
        for i in range(30):
            inventory.append({"subdomain": "docs.site2.com", "source_path": f"site2_file{i}.md"})
        # Site 3: 10 files
        for i in range(10):
            inventory.append({"subdomain": "docs.site3.com", "source_path": f"site3_file{i}.md"})

        batches = create_batches(inventory, batch_size=23)

        # Site 1: 3 batches (23+23+4)
        # Site 2: 2 batches (23+7)
        # Site 3: 1 batch (10)
        # Total: 6 batches
        assert len(batches) == 6
        validate_batches(batches, expected_total=90)

    def test_phase6_scenario(self):
        """Test the actual Phase 6 scenario: 248 files across 5 sites."""
        # Simulate Phase 6 distribution
        inventory = []

        # Approximate distribution from Phase 6
        site_files = {
            "docs.aspose.net": 130,
            "kb.aspose.net": 80,
            "reference.aspose.net": 20,
            "about.aspose.net": 10,
            "releases.aspose.net": 8,
        }

        for site, count in site_files.items():
            for i in range(count):
                inventory.append({"subdomain": site, "source_path": f"{site}/file{i}.md"})

        batches = create_batches(inventory, batch_size=23)

        # Validate no duplicates
        validate_batches(batches, expected_total=248)

        # Check batch count
        # docs.aspose.net: 130 files → 6 batches (23*5 + 15)
        # kb.aspose.net: 80 files → 4 batches (23*3 + 11)
        # reference.aspose.net: 20 files → 1 batch
        # about.aspose.net: 10 files → 1 batch
        # releases.aspose.net: 8 files → 1 batch
        # Total: 13 batches
        assert len(batches) == 13

    def test_no_duplicates_guard(self):
        """Test that duplicate detection works."""
        inventory = [
            {"subdomain": "docs.example.com", "source_path": "file1.md"},
            {"subdomain": "docs.example.com", "source_path": "file2.md"},
            {"subdomain": "docs.example.com", "source_path": "file1.md"},  # Duplicate!
        ]

        batches = create_batches(inventory, batch_size=23)

        # Should raise AssertionError due to duplicate
        with pytest.raises(AssertionError, match="duplicate items"):
            validate_batches(batches, expected_total=3)

    def test_empty_inventory(self):
        """Test empty inventory."""
        batches = create_batches([], batch_size=23)
        assert len(batches) == 0
        validate_batches(batches, expected_total=0)

    def test_batch_size_one(self):
        """Test batch size of 1."""
        inventory = [
            {"subdomain": "docs.example.com", "source_path": f"file{i}.md"} for i in range(5)
        ]
        batches = create_batches(inventory, batch_size=1)

        assert len(batches) == 5
        for batch in batches:
            assert len(batch) == 1
        validate_batches(batches, expected_total=5)


class TestBatchValidation:
    """Test batch validation logic."""

    def test_validates_total_count(self):
        """Test that validation checks total count."""
        batches = [[{"id": 1}, {"id": 2}], [{"id": 3}]]

        # Should pass
        validate_batches(batches, expected_total=3)

        # Should fail
        with pytest.raises(AssertionError, match="Total items"):
            validate_batches(batches, expected_total=5)

    def test_detects_duplicates(self):
        """Test that validation detects duplicates."""
        item1 = {"source_path": "file1.md"}
        item2 = {"source_path": "file2.md"}

        # No duplicates - should pass
        batches = [[item1], [item2]]
        validate_batches(batches, expected_total=2)

        # With duplicates - should fail
        batches = [[item1, item2], [item1]]  # item1 appears twice
        with pytest.raises(AssertionError, match="duplicate items"):
            validate_batches(batches, expected_total=3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
