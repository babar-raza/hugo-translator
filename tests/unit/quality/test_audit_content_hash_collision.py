"""HT-QUALITY-GATES-001 Phase 8 (Tier B #13): tests for
audit_cross_locale_duplication.py's cross-entity content_hash collision
detection -- the Phase 7 reconnaissance's own "unconfirmed root-cause
candidate": two DIFFERENT EN source files sharing the same
provenance.content_hash value. Distinct from write_gate.py Gate 32, which
only compares a single file's own EN-vs-translation hash (same-file
staleness, not cross-file collision).
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_QUALITY_DIR = _PROJECT_ROOT / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

import audit_cross_locale_duplication as acld  # noqa: E402


class TestGetNestedField:
    def test_extracts_nested_provenance_content_hash(self):
        content = (
            "---\ntitle: Test\nprovenance:\n  content_hash: abc123\n---\nBody.\n"
        )
        assert acld.get_nested_field(content, "provenance", "content_hash") == "abc123"

    def test_missing_field_returns_none(self):
        content = "---\ntitle: Test\n---\nBody.\n"
        assert acld.get_nested_field(content, "provenance", "content_hash") is None

    def test_missing_frontmatter_returns_none(self):
        assert acld.get_nested_field("no frontmatter", "provenance", "content_hash") is None

    def test_non_dict_intermediate_node_returns_none(self):
        content = "---\ntitle: Test\nprovenance: just_a_string\n---\nBody.\n"
        assert acld.get_nested_field(content, "provenance", "content_hash") is None


class TestFindContentHashCollisions:
    def test_two_different_en_files_sharing_a_hash_is_flagged(self):
        en_hash_map = {"pdf/Foo.md": "hash1", "pdf/Bar.md": "hash1"}
        collisions = acld.find_content_hash_collisions(en_hash_map)
        assert collisions == {"hash1": ["pdf/Bar.md", "pdf/Foo.md"]}

    def test_unique_hashes_produce_no_findings(self):
        en_hash_map = {"pdf/Foo.md": "hash1", "pdf/Bar.md": "hash2"}
        assert acld.find_content_hash_collisions(en_hash_map) == {}

    def test_three_way_collision_reports_all_three(self):
        en_hash_map = {"a.md": "h", "b.md": "h", "c.md": "h"}
        collisions = acld.find_content_hash_collisions(en_hash_map)
        assert collisions == {"h": ["a.md", "b.md", "c.md"]}

    def test_empty_map_produces_no_findings(self):
        assert acld.find_content_hash_collisions({}) == {}
