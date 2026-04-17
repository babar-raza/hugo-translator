#!/usr/bin/env python
"""
Smoke test for AST batch translation fixes (VLD-05).

Fast validation that AST-FIX-01 through AST-FIX-06 and SR-01 through SR-07
fixes are working correctly. Suitable for CI pipeline.

Exit codes:
    0 - All tests passed
    1 - One or more tests failed
"""

import subprocess
import sys
from pathlib import Path

# Colors for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'
BOLD = '\033[1m'


def print_header(text: str):
    """Print section header."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}{text}{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}\n")


def print_success(text: str):
    """Print success message."""
    print(f"{GREEN}[PASS]{RESET} {text}")


def print_error(text: str):
    """Print error message."""
    print(f"{RED}[FAIL]{RESET} {text}")


def print_info(text: str):
    """Print info message."""
    print(f"{YELLOW}[INFO]{RESET} {text}")


def check_pytest_available() -> bool:
    """
    Check if pytest is available (PH-04).

    Returns:
        True if pytest is available, False otherwise
    """
    try:
        import pytest
        return True
    except ImportError:
        print_error("pytest is not installed")
        print(f"\n{BOLD}pytest is required to run the smoke tests.{RESET}")
        print("\nInstall it with:")
        print(f"  {YELLOW}pip install pytest{RESET}")
        print("\nOr install all test dependencies:")
        print(f"  {YELLOW}pip install -r requirements-dev.txt{RESET}")
        return False


def test_module_import() -> bool:
    """
    Test 1: Module Import with Constant Validation.

    Verifies:
    - Module imports without errors
    - Constant validation assertions pass (VLD-04)
    """
    print_header("Test 1: Module Import + Constant Validation")

    try:
        # Import the module - this triggers constant validation
        from src.translation_engine.extractor.text_unit_extractor import (
            FALLBACK_RATE_THRESHOLD,
            LANGUAGE_PURITY_MIN_LENGTH,
            TOKEN_PER_WORD_ESTIMATE,
            TextUnitExtractor,
        )

        print_success("Module imports successfully")
        print_info(f"LANGUAGE_PURITY_MIN_LENGTH = {LANGUAGE_PURITY_MIN_LENGTH}")
        print_info(f"FALLBACK_RATE_THRESHOLD = {FALLBACK_RATE_THRESHOLD}")
        print_info(f"TOKEN_PER_WORD_ESTIMATE = {TOKEN_PER_WORD_ESTIMATE}")

        # Verify extractor can be instantiated
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
        print_success("TextUnitExtractor instantiated successfully")

        return True

    except Exception as e:
        print_error(f"Module import failed: {e}")
        return False


def test_delimiter_design() -> bool:
    """
    Test 2: Delimiter Design (AST-FIX-01).

    Runs test_delimiter_fix.py to verify:
    - No English text in delimiters
    - PUA characters used
    - Triple repetition
    """
    print_header("Test 2: Delimiter Design (AST-FIX-01)")

    delimiter_test_path = Path("test_delimiter_fix.py")

    if not delimiter_test_path.exists():
        print_error(f"Delimiter test not found: {delimiter_test_path}")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(delimiter_test_path)],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            print_success("Delimiter design test passed")
            return True
        else:
            print_error("Delimiter design test failed")
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr)
            return False

    except subprocess.TimeoutExpired:
        print_error("Delimiter test timed out")
        return False
    except Exception as e:
        print_error(f"Delimiter test error: {e}")
        return False


def test_batch_translation_unit_tests() -> bool:
    """
    Test 3: Batch Translation Unit Tests.

    Runs subset of unit tests covering:
    - Basic batch translation
    - Delimiter corruption fallback
    - Language purity check
    - Helper methods
    """
    print_header("Test 3: Batch Translation Unit Tests")

    tests = [
        "tests/unit/translation_engine/extractor/test_text_unit_extraction.py::TestBatchTranslation::test_batch_translate_success",
        "tests/unit/translation_engine/extractor/test_text_unit_extraction.py::TestBatchTranslation::test_batch_translate_language_purity_check",
        "tests/unit/translation_engine/extractor/test_text_unit_extraction.py::TestHelperMethods::test_is_tokenizer_available_with_valid_tokenizer",
    ]

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"] + tests + ["-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            print_success("Unit tests passed")
            # Show test count
            if "passed" in result.stdout:
                for line in result.stdout.split('\n'):
                    if "passed" in line:
                        print_info(line.strip())
            return True
        else:
            print_error("Unit tests failed")
            # Show failures
            if result.stdout:
                print(result.stdout)
            return False

    except subprocess.TimeoutExpired:
        print_error("Unit tests timed out")
        return False
    except Exception as e:
        print_error(f"Unit tests error: {e}")
        return False


def test_integration_test() -> bool:
    """
    Test 4: Integration Test (VLD-01).

    Runs E2E pipeline test covering:
    - Parse → Extract → Translate → Apply → Render
    - Delimiter preservation
    - Structure preservation
    """
    print_header("Test 4: Integration Test (VLD-01)")

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "tests/integration/test_ast_batch_translation_e2e.py::TestASTBatchTranslationE2E::test_ast_batch_translation_full_pipeline",
                "-v", "--tb=short"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            print_success("Integration test passed")
            return True
        else:
            print_error("Integration test failed")
            if result.stdout:
                print(result.stdout)
            return False

    except subprocess.TimeoutExpired:
        print_error("Integration test timed out")
        return False
    except Exception as e:
        print_error(f"Integration test error: {e}")
        return False


def test_vld_validation_complete() -> bool:
    """
    Test 5: VLD Validation Taskcards Completed (PH-03).

    Verifies that VLD taskcards were properly completed:
    - VLD-03: Helper method _is_tokenizer_available exists
    - VLD-04: Constant validation uses ValueError (not assert)
    - VLD-07: Rollback documentation exists
    """
    print_header("Test 5: VLD Validation Completion (PH-03)")

    all_passed = True

    # VLD-03: Check helper method exists
    try:
        from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Check method exists
        if not hasattr(extractor, '_is_tokenizer_available'):
            print_error("VLD-03: Helper method _is_tokenizer_available not found")
            all_passed = False
        else:
            # Check it's callable
            if not callable(extractor._is_tokenizer_available):
                print_error("VLD-03: _is_tokenizer_available is not callable")
                all_passed = False
            else:
                print_success("VLD-03: Helper method _is_tokenizer_available exists")

    except Exception as e:
        print_error(f"VLD-03: Failed to verify helper method: {e}")
        all_passed = False

    # VLD-04: Check constant validation uses ValueError (not assert)
    try:
        # Read the source file to verify ValueError is used
        source_file = Path("src/translation_engine/extractor/text_unit_extractor.py")

        if not source_file.exists():
            print_error("VLD-04: Source file not found")
            all_passed = False
        else:
            content = source_file.read_text(encoding='utf-8')

            # Check for ValueError in validation section
            has_valueerror = "raise ValueError" in content and "LANGUAGE_PURITY_MIN_LENGTH" in content

            # Check that assert is NOT used for validation
            # (assert can still exist elsewhere, but not for constant validation)
            lines = content.split('\n')
            validation_section_start = None
            validation_section_end = None

            for i, line in enumerate(lines):
                if "Validate constants at module load time" in line:
                    validation_section_start = i
                if validation_section_start and "def " in line and i > validation_section_start:
                    validation_section_end = i
                    break

            if validation_section_start and validation_section_end:
                validation_lines = lines[validation_section_start:validation_section_end]
                validation_text = '\n'.join(validation_lines)

                has_assert_in_validation = "assert " in validation_text and "LANGUAGE_PURITY_MIN_LENGTH" in validation_text

                if has_valueerror and not has_assert_in_validation:
                    print_success("VLD-04: Constant validation uses ValueError (not assert)")
                else:
                    if not has_valueerror:
                        print_error("VLD-04: ValueError not found in validation")
                    if has_assert_in_validation:
                        print_error("VLD-04: assert still used in validation (should be ValueError)")
                    all_passed = False
            else:
                print_error("VLD-04: Could not locate validation section")
                all_passed = False

    except Exception as e:
        print_error(f"VLD-04: Failed to verify constant validation: {e}")
        all_passed = False

    # VLD-07: Check rollback documentation exists
    try:
        rollback_doc = Path("docs/operations/AST_FIX_ROLLBACK.md")

        if not rollback_doc.exists():
            print_error("VLD-07: Rollback documentation not found")
            all_passed = False
        else:
            content = rollback_doc.read_text(encoding='utf-8')

            # Verify key sections exist
            required_sections = [
                "When to Rollback",
                "Rollback Procedure",
                "use_ast_body_reconstruction",
                "Re-enabling AST Translation"
            ]

            missing_sections = []
            for section in required_sections:
                if section not in content:
                    missing_sections.append(section)

            if missing_sections:
                print_error(f"VLD-07: Rollback doc missing sections: {', '.join(missing_sections)}")
                all_passed = False
            else:
                print_success("VLD-07: Rollback documentation complete")

    except Exception as e:
        print_error(f"VLD-07: Failed to verify rollback documentation: {e}")
        all_passed = False

    return all_passed


def main():
    """Run all smoke tests."""
    print_header("AST Batch Translation Smoke Tests")
    print_info("Testing AST-FIX-01 through AST-FIX-06 + SR-01 through SR-07")
    print_info("This is a fast subset for CI validation")

    # Check pytest availability (PH-04)
    if not check_pytest_available():
        return 1

    results = {
        "Module Import": test_module_import(),
        "Delimiter Design": test_delimiter_design(),
        "Unit Tests": test_batch_translation_unit_tests(),
        "Integration Test": test_integration_test(),
        "VLD Validation": test_vld_validation_complete(),
    }

    # Summary
    print_header("Summary")
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_test in results.items():
        if passed_test:
            print_success(f"{test_name}")
        else:
            print_error(f"{test_name}")

    print(f"\n{BOLD}Result: {passed}/{total} tests passed{RESET}")

    if passed == total:
        print(f"\n{GREEN}{BOLD}ALL SMOKE TESTS PASSED{RESET}")
        print(f"\n{BOLD}Next Steps:{RESET}")
        print("  1. Run full test suite: pytest tests/")
        print("  2. Test with real file from kb.aspose.net")
        print("  3. Measure batch success rate in production")
        return 0
    else:
        print(f"\n{RED}{BOLD}SMOKE TESTS FAILED{RESET}")
        print(f"\n{BOLD}Failed: {total - passed} test(s){RESET}")
        print("Review errors above and fix before deployment")
        return 1


if __name__ == "__main__":
    sys.exit(main())
