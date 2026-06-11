"""Integration test: scope audit gate passes for all production profiles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestScopeAuditGate:
    def test_no_ambiguous_production_profiles(self):
        """No production profile may be classified as 'ambiguous'."""
        audit_path = Path("data/metrics/scope_audit.json")
        if not audit_path.exists():
            pytest.skip("scope_audit.json not generated yet")

        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        ambiguous = [
            e
            for e in audit
            if e.get("classification") == "ambiguous" and not e.get("is_test_profile", False)
        ]
        assert ambiguous == [], (
            f"Ambiguous production profiles found: {[e['profile'] for e in ambiguous]}"
        )

    def test_all_profiles_have_required_fields(self):
        """Every production profile must have non-empty website, product, website_section, platform."""
        audit_path = Path("data/metrics/scope_audit.json")
        if not audit_path.exists():
            pytest.skip("scope_audit.json not generated yet")

        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        for entry in audit:
            if entry.get("is_test_profile", False):
                continue
            resolved = entry.get("resolved", {})
            assert resolved.get("website"), f"Empty website in {entry['profile']}"
            assert resolved.get("product"), f"Empty product in {entry['profile']}"
            assert resolved.get("website_section"), f"Empty website_section in {entry['profile']}"
            assert resolved.get("platform"), f"Empty platform in {entry['profile']}"
            # item_name is built at run time in integration layer, not in scope audit

    def test_test_profiles_excluded(self):
        """Test/fixture profiles must be marked as excluded."""
        audit_path = Path("data/metrics/scope_audit.json")
        if not audit_path.exists():
            pytest.skip("scope_audit.json not generated yet")

        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        test_profiles = [e for e in audit if e.get("is_test_profile", False)]
        for tp in test_profiles:
            assert tp.get("classification") == "fixture_excluded", (
                f"Test profile {tp['profile']} not excluded: {tp.get('classification')}"
            )
