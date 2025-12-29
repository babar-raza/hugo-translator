# Golden Files for Contract Tests

This directory contains golden files - stable, deterministic test inputs and expected outputs for contract testing.

## Purpose

Golden files serve as:
- **Stable inputs** for deterministic contract tests
- **Expected outputs** for behavior verification
- **Regression prevention** (changes to golden files require explicit review)

## Structure

```
golden/
├── validation/           # Files with known validation issues
│   ├── placeholder_error.md         # Missing {{CODE_1}} placeholder
│   ├── code_block_mismatch.md       # Source has 3 code blocks, translation has 2
│   ├── link_broken.md                # Broken link in translation
│   └── validation_error_2_issues.md # Exactly 2 non-critical errors (for mode testing)
├── translation/          # Multi-language test inputs
│   ├── simple_article.md            # Basic markdown for subprocess tests
│   └── multi_lang_input.md          # Input for multi-language translation
└── config/               # Configuration test files
    ├── site_profile_valid.yaml      # Valid site profile
    └── site_profile_invalid.yaml    # Invalid site profile (missing required fields)
```

## Naming Conventions

- **Pattern:** `{feature}_{variant}.{ext}`
- **Examples:**
  - `placeholder_error.md` - Placeholder validation error
  - `validation_error_2_issues.md` - Validation with exactly 2 issues
- **No timestamps, no random strings** - Golden files must be deterministic

## Usage

Contract tests load golden files to verify behavior:

```python
import pytest
from pathlib import Path

@pytest.fixture
def golden_files_dir():
    return Path(__file__).parent / "golden"

def test_validation_mode(golden_files_dir):
    input_file = golden_files_dir / "validation" / "validation_error_2_issues.md"
    # Test validates behavior with known input
```

## Modification Policy

- Golden files are part of the contract
- Changes to golden files require spec review
- Add new golden files for new contract tests
- Do not modify existing golden files without justification
