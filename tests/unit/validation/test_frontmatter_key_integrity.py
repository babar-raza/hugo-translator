"""
Regression tests: Frontmatter key integrity (RC-3 prevention).

TC-FKI-01: Translation with translated keys (e.g. 'autor' instead of 'author') → ERROR
TC-FKI-02: Translation with correct keys → PASS
TC-FKI-03: Translation has extra hallucinated keys → ERROR
TC-FKI-04: Translation has missing required keys → ERROR
TC-FKI-05: Passthrough field changed (date, draft) → ERROR
TC-FKI-06: Booleans must remain booleans (not "true" string) → ERROR
TC-FKI-07: Czech RC-3 pattern — multiple keys on single line → YAML parse failure
"""

from __future__ import annotations

import pytest

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from scripts.repair_translated_content import (
        check_passthrough_fields,
        check_translated_keys,
        check_type_drift,
        check_yaml_parseable,
    )

    HAS_SCAN = True
except ImportError:
    HAS_SCAN = False


@pytest.mark.skipif(not HAS_SCAN or not HAS_YAML, reason="scan tools not available")
class TestTranslatedKeyDetection:
    """Verify scan tool detects translated YAML key names."""

    SOURCE_FM = """
author: "Test Author"
title: "Test Title"
date: 2024-01-01
draft: false
categories:
- Category A
"""

    def test_tc_fki_01_translated_keys_detected(self):
        """Translation with 'autor' instead of 'author' → translated_yaml_key issue."""
        translated_fm = """
autor: "Translated Author"
title: "Translated Title"
date: 2024-01-01
draft: false
categories:
- Category A
"""
        issues = check_translated_keys(translated_fm, "test/path.md", self.SOURCE_FM)
        translated_key_issues = [i for i in issues if i.kind == "translated_yaml_key"]
        assert len(translated_key_issues) > 0, (
            "Expected 'translated_yaml_key' issue for 'autor' key"
        )

    def test_tc_fki_02_correct_keys_pass(self):
        """Translation with correct English keys → no translated_yaml_key issues."""
        translated_fm = """
author: "Translated Author"
title: "Translated Title"
date: 2024-01-01
draft: false
categories:
- Category A
"""
        issues = check_translated_keys(translated_fm, "test/path.md", self.SOURCE_FM)
        translated_key_issues = [i for i in issues if i.kind == "translated_yaml_key"]
        assert len(translated_key_issues) == 0, (
            "Expected no 'translated_yaml_key' issues for correct keys"
        )

    def test_tc_fki_03_extra_hallucinated_keys_detected(self):
        """Translation with extra keys not in source → translated_yaml_key issue."""
        translated_fm = """
author: "Author"
title: "Title"
date: 2024-01-01
draft: false
categories:
- Category A
step3: "Hallucinated step"
step4: "Another hallucinated step"
"""
        issues = check_translated_keys(translated_fm, "test/path.md", self.SOURCE_FM)
        extra_key_issues = [i for i in issues if i.kind == "translated_yaml_key"]
        assert len(extra_key_issues) > 0, "Expected issue for extra hallucinated keys step3/step4"


@pytest.mark.skipif(not HAS_SCAN or not HAS_YAML, reason="scan tools not available")
class TestTypeDrift:
    """Verify type_drift detection for passthrough fields."""

    def test_tc_fki_06_boolean_must_not_become_string(self):
        """Boolean 'draft: false' must not become 'draft: \"false\"' string."""
        source_fm = "draft: false\nauthor: Test\n"
        # Boolean became string
        translated_fm = 'draft: "false"\nauthor: Translated\n'
        issues = check_type_drift(translated_fm, "test/path.md", source_fm)
        type_issues = [i for i in issues if i.kind == "type_drift"]
        assert len(type_issues) > 0, "Expected type_drift issue for boolean→string conversion"

    def test_correct_boolean_passes(self):
        """Boolean 'draft: false' stays false → no type drift."""
        source_fm = "draft: false\nauthor: Test\n"
        translated_fm = "draft: false\nauthor: Translated\n"
        issues = check_type_drift(translated_fm, "test/path.md", source_fm)
        type_issues = [i for i in issues if i.kind == "type_drift"]
        assert len(type_issues) == 0


@pytest.mark.skipif(not HAS_SCAN or not HAS_YAML, reason="scan tools not available")
class TestPassthroughFields:
    """Verify passthrough field change detection."""

    def test_tc_fki_05_changed_date_detected(self):
        """Passthrough field 'date' changed → passthrough_field_changed issue."""
        source_fm = "date: 2024-01-01\ntitle: English Title\n"
        translated_fm = "date: 2025-06-15\ntitle: Translated Title\n"
        issues = check_passthrough_fields(translated_fm, "test/path.md", source_fm)
        pt_issues = [i for i in issues if i.kind == "passthrough_field_changed"]
        assert len(pt_issues) > 0, "Expected passthrough_field_changed for date"

    def test_unchanged_passthrough_passes(self):
        """Passthrough field unchanged → no passthrough_field_changed issue."""
        source_fm = "draft: false\ntitle: Test\n"
        translated_fm = "draft: false\ntitle: Translated\n"
        issues = check_passthrough_fields(translated_fm, "test/path.md", source_fm)
        pt_issues = [i for i in issues if i.kind == "passthrough_field_changed"]
        assert len(pt_issues) == 0


@pytest.mark.skipif(not HAS_SCAN or not HAS_YAML, reason="scan tools not available")
class TestYAMLParseFailure:
    """Verify YAML parse failure detection."""

    def test_tc_fki_07_czech_rc3_collapsed_yaml(self):
        """Czech RC-3 pattern: multiple key:value pairs on one line → yaml_parse_failure."""
        # Simulates the Czech blog file defect (keys translated, all on one line)
        collapsed_fm = "\nAutor: Test Kategorie: \n- Category A Datum: 2024-01-01 Nazev: Test\n"
        issues = check_yaml_parseable(collapsed_fm, "test/path.md")
        parse_issues = [i for i in issues if i.kind == "yaml_parse_failure"]
        assert len(parse_issues) > 0, "Expected yaml_parse_failure for collapsed YAML blob"

    def test_valid_yaml_no_parse_failure(self):
        """Valid YAML frontmatter → no yaml_parse_failure."""
        valid_fm = "\nauthor: Test\ntitle: Valid Title\ndate: 2024-01-01\ndraft: false\n"
        issues = check_yaml_parseable(valid_fm, "test/path.md")
        parse_issues = [i for i in issues if i.kind == "yaml_parse_failure"]
        assert len(parse_issues) == 0
