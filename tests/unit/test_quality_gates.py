"""
Unit tests for quality gates.

Tests each gate individually to ensure correct pass/warn/fail behavior.
"""
import sys
import os
from pathlib import Path

# Add src to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

import pytest
from src.translation_engine.quality.quality_gates import (
    GateStatus,
    LineCountGate,
    ListStructureGate,
    MarkdownSyntaxGate,
    GateRunner,
    get_default_gates,
)


class TestLineCountGate:
    """Test line count gate."""

    def test_pass_identical_line_count(self):
        """Test that identical line counts pass."""
        gate = LineCountGate()
        source = "line1\nline2\nline3"
        target = "ligne1\nligne2\nligne3"

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert result.details["source_lines"] == 3
        assert result.details["target_lines"] == 3
        assert result.details["change_pct"] == 0.0

    def test_pass_minor_difference(self):
        """Test that minor line differences (<20%) pass."""
        gate = LineCountGate(warn_threshold=0.2)
        source = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"  # 10 lines
        target = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9"  # 9 lines (10% loss)

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert result.details["source_lines"] == 10
        assert result.details["target_lines"] == 9
        assert result.details["change_pct"] == 10.0

    def test_warn_moderate_difference(self):
        """Test that moderate line differences (20-40%) warn."""
        gate = LineCountGate(warn_threshold=0.2, fail_threshold=0.4)
        source = "line1\nline2\nline3\nline4\nline5"  # 5 lines
        target = "line1\nline2\nline3\nline4"  # 4 lines (20% loss)

        result = gate.check(source, target)

        assert result.status == GateStatus.WARN
        assert result.details["source_lines"] == 5
        assert result.details["target_lines"] == 4
        assert result.details["change_pct"] == 20.0

    def test_fail_excessive_difference(self):
        """Test that excessive line differences (>40%) fail."""
        gate = LineCountGate(warn_threshold=0.2, fail_threshold=0.4)
        source = "line1\nline2\nline3\nline4\nline5"  # 5 lines
        target = "line1\nline2"  # 2 lines (60% loss)

        result = gate.check(source, target)

        assert result.status == GateStatus.FAIL
        assert result.details["source_lines"] == 5
        assert result.details["target_lines"] == 2
        assert result.details["change_pct"] == 60.0
        assert "concatenation or corruption" in result.message.lower()

    def test_empty_source(self):
        """Test that empty source passes (no validation needed)."""
        gate = LineCountGate()
        source = ""
        target = "some content"

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert "empty" in result.message.lower()


class TestListStructureGate:
    """Test list structure gate."""

    def test_pass_identical_lists(self):
        """Test that identical list structures pass."""
        gate = ListStructureGate()
        source = """
- Item 1
- Item 2
- Item 3
"""
        target = """
- Article 1
- Article 2
- Article 3
"""

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert result.details["source_items"] == 3
        assert result.details["target_items"] == 3
        assert result.details["source_containers"] == 1
        assert result.details["target_containers"] == 1

    def test_pass_nested_lists_preserved(self):
        """Test that preserved nested structures pass."""
        gate = ListStructureGate()
        source = """
- Parent 1
  - Child 1
  - Child 2
- Parent 2
  - Child 3
"""
        target = """
- Parent 1
  - Enfant 1
  - Enfant 2
- Parent 2
  - Enfant 3
"""

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert result.details["source_has_nesting"] is True
        assert result.details["target_has_nesting"] is True

    def test_warn_moderate_item_loss(self):
        """Test that 10-20% item loss warns."""
        gate = ListStructureGate(item_warn_threshold=0.1, item_fail_threshold=0.2)
        source = """
- Item 1
- Item 2
- Item 3
- Item 4
- Item 5
- Item 6
- Item 7
- Item 8
- Item 9
- Item 10
"""  # 10 items
        target = """
- Item 1
- Item 2
- Item 3
- Item 4
- Item 5
- Item 6
- Item 7
- Item 8
- Item 9
"""  # 9 items (10% loss)

        result = gate.check(source, target)

        assert result.status == GateStatus.WARN
        assert result.details["source_items"] == 10
        assert result.details["target_items"] == 9
        assert result.details["item_loss_pct"] == 10.0

    def test_fail_excessive_item_loss(self):
        """Test that >20% item loss fails."""
        gate = ListStructureGate(item_fail_threshold=0.2)
        source = """
- Item 1
- Item 2
- Item 3
- Item 4
- Item 5
"""  # 5 items
        target = """
- Item 1
- Item 2
- Item 3
"""  # 3 items (40% loss)

        result = gate.check(source, target)

        assert result.status == GateStatus.FAIL
        assert result.details["source_items"] == 5
        assert result.details["target_items"] == 3
        assert result.details["item_loss_pct"] == 40.0
        assert "concatenated or corrupted" in result.message.lower()

    def test_fail_nesting_lost(self):
        """Test that loss of nesting fails."""
        gate = ListStructureGate()
        source = """
- Parent 1
  - Child 1
  - Child 2
- Parent 2
"""
        target = """
- Parent 1 Child 1 Child 2
- Parent 2
"""  # Nested structure flattened

        result = gate.check(source, target)

        assert result.status == GateStatus.FAIL
        assert result.details["source_has_nesting"] is True
        assert result.details["target_has_nesting"] is False
        assert "nested list structure lost" in result.message.lower()

    def test_pass_no_lists_in_source(self):
        """Test that documents without lists pass (skip validation)."""
        gate = ListStructureGate()
        source = "Just a paragraph.\n\nNo lists here."
        target = "Juste un paragraphe.\n\nPas de listes ici."

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert "no lists" in result.message.lower()

    def test_ordered_lists(self):
        """Test that ordered lists are counted correctly."""
        gate = ListStructureGate()
        source = """
1. First item
2. Second item
3. Third item
"""
        target = """
1. Premier article
2. Deuxième article
3. Troisième article
"""

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert result.details["source_items"] == 3
        assert result.details["target_items"] == 3

    def test_multiple_list_containers(self):
        """Test counting multiple separate list containers."""
        gate = ListStructureGate()
        source = """
First list:
- Item 1
- Item 2

Second list:
- Item 3
- Item 4

Third list:
- Item 5
"""
        target = """
First list:
- Article 1
- Article 2

Second list:
- Article 3
- Article 4

Third list:
- Article 5
"""

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert result.details["source_items"] == 5
        assert result.details["target_items"] == 5
        assert result.details["source_containers"] == 3
        assert result.details["target_containers"] == 3


class TestMarkdownSyntaxGate:
    """Test markdown syntax gate."""

    def test_pass_valid_markdown(self):
        """Test that valid markdown passes."""
        gate = MarkdownSyntaxGate()
        source = "# Heading\n\nParagraph.\n\n- List item"
        target = "# Titre\n\nParagraphe.\n\n- Article de liste"

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS
        assert "valid" in result.message.lower()

    def test_pass_valid_frontmatter(self):
        """Test that valid frontmatter passes."""
        gate = MarkdownSyntaxGate()
        source = """---
title: Test
date: 2026-01-27
---

Content here.
"""
        target = """---
title: Test
date: 2026-01-27
---

Contenu ici.
"""

        result = gate.check(source, target)

        assert result.status == GateStatus.PASS

    def test_fail_unclosed_code_fence(self):
        """Test that unclosed code fence fails."""
        gate = MarkdownSyntaxGate()
        source = "# Heading\n\n```python\ncode\n```"
        target = "# Titre\n\n```python\ncode"  # Missing closing fence

        result = gate.check(source, target)

        assert result.status == GateStatus.FAIL
        assert "unclosed code fence" in result.message.lower()

    def test_fail_invalid_frontmatter(self):
        """Test that invalid frontmatter YAML fails."""
        gate = MarkdownSyntaxGate()
        source = """---
title: Valid
---

Content.
"""
        target = """---
title: Invalid: [unclosed bracket
---

Content.
"""  # Invalid YAML

        result = gate.check(source, target)

        assert result.status == GateStatus.FAIL
        assert "frontmatter yaml" in result.message.lower()


class TestGateRunner:
    """Test gate runner."""

    def test_run_all_gates_pass(self):
        """Test runner when all gates pass."""
        runner = GateRunner([
            LineCountGate(),
            ListStructureGate(),
            MarkdownSyntaxGate(),
        ])

        source = """# Heading

- Item 1
- Item 2
- Item 3
"""
        target = """# Titre

- Article 1
- Article 2
- Article 3
"""

        report = runner.run_all(source, target, file_path="test.md", target_lang="fr")

        assert len(report.results) == 3
        assert all(r.status == GateStatus.PASS for r in report.results)
        assert not report.has_failures()
        assert not report.has_warnings()
        assert report.get_overall_status() == GateStatus.PASS

    def test_run_all_gates_warn(self):
        """Test runner when some gates warn."""
        runner = GateRunner([
            LineCountGate(warn_threshold=0.1),
            ListStructureGate(),
        ])

        source = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"  # 10 lines
        target = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9"  # 9 lines (10% loss)

        report = runner.run_all(source, target)

        assert report.has_warnings()
        assert not report.has_failures()
        assert report.get_overall_status() == GateStatus.WARN

    def test_run_all_gates_fail(self):
        """Test runner when some gates fail."""
        runner = GateRunner([
            LineCountGate(fail_threshold=0.3),
            ListStructureGate(),
        ])

        source = "line1\nline2\nline3\nline4\nline5"  # 5 lines
        target = "line1\nline2"  # 2 lines (60% loss)

        report = runner.run_all(source, target)

        assert report.has_failures()
        assert report.get_overall_status() == GateStatus.FAIL

    def test_report_summary(self):
        """Test report summary generation."""
        runner = GateRunner([
            LineCountGate(warn_threshold=0.1),  # Will warn on 10% change
            ListStructureGate(),                # Will pass
            MarkdownSyntaxGate(),               # Will pass
        ])

        source = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"
        target = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9"

        report = runner.run_all(source, target)
        summary = report.get_summary()

        assert summary["pass"] == 2
        assert summary["warn"] == 1
        assert summary["fail"] == 0

    def test_report_console_format(self):
        """Test console report formatting."""
        runner = GateRunner([LineCountGate()])
        source = "line1\nline2\nline3"
        target = "line1\nline2\nline3"

        report = runner.run_all(source, target, file_path="test.md", target_lang="fr")
        console_output = report.format_console()

        assert "QUALITY GATES REPORT" in console_output
        assert "test.md" in console_output
        assert "fr" in console_output
        assert "[PASS]" in console_output
        assert "APPROVED" in console_output

    def test_report_to_dict(self):
        """Test report JSON serialization."""
        runner = GateRunner([LineCountGate()])
        source = "line1\nline2\nline3"
        target = "line1\nline2\nline3"

        report = runner.run_all(source, target, file_path="test.md", target_lang="fr")
        data = report.to_dict()

        assert data["file_path"] == "test.md"
        assert data["target_lang"] == "fr"
        assert len(data["gates"]) == 1
        assert data["gates"][0]["status"] == "pass"
        assert data["summary"]["pass"] == 1
        assert data["overall_status"] == "pass"


class TestDefaultGates:
    """Test default gate configuration."""

    def test_get_default_gates(self):
        """Test that default gates are properly configured."""
        gates = get_default_gates()

        assert len(gates) == 3
        assert any(isinstance(g, LineCountGate) for g in gates)
        assert any(isinstance(g, ListStructureGate) for g in gates)
        assert any(isinstance(g, MarkdownSyntaxGate) for g in gates)

        # Check that all gates are enabled
        assert all(g.enabled for g in gates)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
