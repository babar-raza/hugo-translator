"""
Contract Test Fixtures and Configuration

Provides shared fixtures for contract tests. These fixtures are designed to
be minimal, deterministic, and focused on user-visible behavior testing.
"""

import logging
import tempfile
from pathlib import Path
from typing import Dict, Any

import pytest
import yaml


logger = logging.getLogger(__name__)


# ==============================================================================
# Directory and File Fixtures
# ==============================================================================


@pytest.fixture
def temp_contract_dir(tmp_path):
    """
    Temporary directory for contract test artifacts.

    Returns clean temporary directory that is automatically cleaned up after test.
    """
    return tmp_path


@pytest.fixture
def golden_files_dir():
    """
    Path to golden files directory for deterministic testing.

    Golden files are checked into git and provide stable test inputs/outputs.
    """
    return Path(__file__).parent / "golden"


# ==============================================================================
# Configuration Fixtures
# ==============================================================================


@pytest.fixture
def minimal_site_profile(temp_contract_dir) -> Dict[str, Any]:
    """
    Minimal valid site profile for contract testing.

    Returns dictionary with bare minimum required fields for a valid site profile.
    """
    return {
        "site_id": "contract_test_site",
        "content_roots": [str(temp_contract_dir / "content")],
        "default_source_lang": "en",
        "target_langs": ["fr", "de", "es"],
        "frontmatter": {
            "title": {"mode": "translate"},
            "date": {"mode": "passthrough"},
        },
        "body": {
            "translate_markdown": True,
            "preserve_blocks": ["block_code", "codespan"],
        },
        "output_layout": {
            "per_language_folders": True,
            "pattern": "{lang}/{path}",
        },
    }


@pytest.fixture
def site_profile_file(temp_contract_dir, minimal_site_profile) -> Path:
    """
    Creates actual site profile YAML file on disk.

    Returns Path to the created profile file.
    """
    profile_dir = temp_contract_dir / "config" / "site_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)

    profile_path = profile_dir / "contract_test_site.yaml"
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.dump(minimal_site_profile, f)

    return profile_path


@pytest.fixture
def validation_config_strict() -> Dict[str, Any]:
    """
    Strict validation configuration for testing critical validators.

    Returns config dict with strict=1 error, 1 retry, no warnings.
    """
    return {
        "decision_rules": {
            "reject_on_error_count": 1,
            "max_retry_attempts": 1,
            "accept_warnings": False,
            "accept_after_max_retries": False,
        }
    }


@pytest.fixture
def validation_config_normal() -> Dict[str, Any]:
    """
    Normal validation configuration for testing standard behavior.

    Returns config dict with normal=3 errors, 2 retries, accept warnings.
    """
    return {
        "decision_rules": {
            "reject_on_error_count": 3,
            "max_retry_attempts": 2,
            "accept_warnings": True,
            "accept_after_max_retries": True,
        }
    }


@pytest.fixture
def validation_config_lenient() -> Dict[str, Any]:
    """
    Lenient validation configuration for testing tolerant behavior.

    Returns config dict with lenient=5 errors, 2 retries, accept warnings.
    """
    return {
        "decision_rules": {
            "reject_on_error_count": 5,
            "max_retry_attempts": 2,
            "accept_warnings": True,
            "accept_after_max_retries": True,
        }
    }


# ==============================================================================
# Test Content Fixtures
# ==============================================================================


@pytest.fixture
def test_markdown_simple(temp_contract_dir) -> Path:
    """
    Simple test markdown file with frontmatter.

    Returns Path to markdown file with minimal frontmatter and body.
    """
    content_dir = temp_contract_dir / "content"
    content_dir.mkdir(parents=True, exist_ok=True)

    md_path = content_dir / "test.md"
    md_content = """---
title: Test Article
date: 2025-01-01
---

# Hello World

This is a test paragraph.
"""
    md_path.write_text(md_content, encoding="utf-8")
    return md_path


@pytest.fixture
def test_markdown_with_placeholders(temp_contract_dir) -> Path:
    """
    Test markdown with placeholders for validation testing.

    Returns Path to markdown containing {{CODE_1}}, {{LINK_2}} placeholders.
    """
    content_dir = temp_contract_dir / "content"
    content_dir.mkdir(parents=True, exist_ok=True)

    md_path = content_dir / "test_placeholders.md"
    md_content = """---
title: Placeholder Test
---

# Code Example

Here is a code snippet: {{CODE_1}}

For more information, see {{LINK_2}}.
"""
    md_path.write_text(md_content, encoding="utf-8")
    return md_path


@pytest.fixture
def test_markdown_with_code_blocks(temp_contract_dir) -> Path:
    """
    Test markdown with code blocks for validation testing.

    Returns Path to markdown containing ``` code fences.
    """
    content_dir = temp_contract_dir / "content"
    content_dir.mkdir(parents=True, exist_ok=True)

    md_path = content_dir / "test_code_blocks.md"
    md_content = '''---
title: Code Block Test
---

# Python Example

```python
def hello():
    print("Hello, World!")
```

# JavaScript Example

```javascript
console.log("Hello, World!");
```
'''
    md_path.write_text(md_content, encoding="utf-8")
    return md_path


# ==============================================================================
# Validation Fixtures
# ==============================================================================


@pytest.fixture
def validation_issue_placeholder_error():
    """
    Validation issue representing PlaceholderValidator ERROR.

    Returns ValidationIssue with ERROR severity and PlaceholderValidator.
    """
    from src.translation_engine.validation.base import (
        ValidationIssue,
        ValidationSeverity,
    )

    return ValidationIssue(
        severity=ValidationSeverity.ERROR,
        validator="PlaceholderValidator",
        message="Missing placeholder: {{CODE_1}}",
        location=None,
        details=None,
    )


@pytest.fixture
def validation_issue_code_block_error():
    """
    Validation issue representing CodeBlockValidator ERROR.

    Returns ValidationIssue with ERROR severity and CodeBlockValidator.
    """
    from src.translation_engine.validation.base import (
        ValidationIssue,
        ValidationSeverity,
    )

    return ValidationIssue(
        severity=ValidationSeverity.ERROR,
        validator="CodeBlockValidator",
        message="Code block count mismatch: source has 2, translation has 1",
        location=None,
        details=None,
    )


@pytest.fixture
def validation_issue_link_error():
    """
    Validation issue representing LinkValidator ERROR.

    Returns ValidationIssue with ERROR severity and LinkValidator.
    """
    from src.translation_engine.validation.base import (
        ValidationIssue,
        ValidationSeverity,
    )

    return ValidationIssue(
        severity=ValidationSeverity.ERROR,
        validator="LinkValidator",
        message="Invalid link syntax: unclosed bracket",
        location=None,
        details=None,
    )


@pytest.fixture
def validation_issue_structure_warning():
    """
    Validation issue representing StructureValidator WARNING.

    Returns ValidationIssue with WARNING severity (non-critical).
    """
    from src.translation_engine.validation.base import (
        ValidationIssue,
        ValidationSeverity,
    )

    return ValidationIssue(
        severity=ValidationSeverity.WARNING,
        validator="StructureValidator",
        message="Heading level skip detected (h1 to h3)",
        location="line 5",
        details=None,
    )


# ==============================================================================
# Logging Fixtures
# ==============================================================================


@pytest.fixture(autouse=True)
def contract_test_logging(caplog):
    """
    Configure logging for contract tests (autouse=True, runs for all tests).

    Sets log level to DEBUG and captures logs for assertion.
    """
    caplog.set_level(logging.DEBUG)
    return caplog


# ==============================================================================
# Cleanup Fixtures
# ==============================================================================


@pytest.fixture(autouse=True)
def cleanup_contract_artifacts(temp_contract_dir):
    """
    Cleanup fixture to ensure no test artifacts persist (autouse=True).

    Runs after each test to clean up any leftover files.
    """
    yield  # Test runs here

    # Cleanup after test
    # (tmp_path fixture already handles temp_contract_dir cleanup, this is for safety)
    pass


# ==============================================================================
# Marker Configuration
# ==============================================================================


def pytest_configure(config):
    """
    Register contract marker.

    This ensures pytest recognizes @pytest.mark.contract without warnings.
    """
    config.addinivalue_line(
        "markers", "contract: marks tests as contract tests (deselect with '-m \"not contract\"')"
    )
