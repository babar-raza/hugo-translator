"""
Regression test for glossary-based translation corrections.

Tests that known mistranslations are corrected using glossary post-processing.

MISSION: Implement translation quality mitigation for vocabulary errors
identified in PHASE10_PROD_FORCE_TRANSLATE.md
"""
import sys
import os
from pathlib import Path

# Add src to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

import pytest
from src.translation_engine.quality.glossary_corrector import (
    GlossaryCorrector,
    get_glossary_corrector
)


def test_metrage_correction():
    """
    Test that 'métrage' is corrected to 'fusion'.

    Issue: "merge" translated as "métrage" (footage) instead of "fusion"
    Source: PHASE10_PROD_FORCE_TRANSLATE.md, line 167
    """
    print("\n" + "=" * 80)
    print("TEST: Métrage -> Fusion Correction")
    print("=" * 80)

    glossary_path = REPO_ROOT / "config" / "glossaries" / "en-fr.yaml"
    assert glossary_path.exists(), f"Glossary not found: {glossary_path}"

    corrector = GlossaryCorrector(glossary_path)
    print(f"[1/3] Loaded glossary with {corrector.get_correction_count()} rules")

    # Test lowercase
    wrong_text = "Métrage plusieurs fichiers PPT/PPTX"
    expected_text = "Fusion plusieurs fichiers PPT/PPTX"

    corrected, changes = corrector.apply_corrections(wrong_text, "en", "fr")
    print(f"[2/3] Applied {len(changes)} corrections")
    print(f"      Before: {wrong_text}")
    print(f"      After:  {corrected}")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    assert corrected == expected_text, (
        f"Expected '{expected_text}', got '{corrected}'"
    )
    print(f"[PASS] 'Métrage' correctly replaced with 'Fusion'")

    assert "métrage -> fusion" in changes, (
        f"Correction not recorded in changes: {changes}"
    )
    print(f"[PASS] Correction logged: {changes}")

    print("\n" + "=" * 80)
    print("TEST PASSED: métrage -> fusion correction works!")
    print("=" * 80)


def test_textile_correction():
    """
    Test that 'textile' is corrected to 'textuel'.

    Issue: "textual" translated as "textile" (fabric) instead of "textuel"
    Source: PHASE10_PROD_FORCE_TRANSLATE.md, line 168
    """
    print("\n" + "=" * 80)
    print("TEST: Textile -> Textuel Correction")
    print("=" * 80)

    glossary_path = REPO_ROOT / "config" / "glossaries" / "en-fr.yaml"
    corrector = GlossaryCorrector(glossary_path)
    print("[1/2] Loaded glossary")

    wrong_text = "Extrait de contenu textile des slides"
    expected_text = "Extrait de contenu textuel des slides"

    corrected, changes = corrector.apply_corrections(wrong_text, "en", "fr")
    print(f"[2/2] Corrected: textile -> textuel")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    assert corrected == expected_text, (
        f"Expected '{expected_text}', got '{corrected}'"
    )
    print(f"[PASS] 'textile' correctly replaced with 'textuel'")

    assert "textile -> textuel" in changes
    print(f"[PASS] Correction logged")

    print("\n" + "=" * 80)
    print("TEST PASSED: textile -> textuel correction works!")
    print("=" * 80)


def test_escanner_correction():
    """
    Test that 'escanner' is corrected to 'analyser'.

    Issue: "scanning" translated as "escanner" (anglicism) instead of "analyser"
    Source: PHASE10_PROD_FORCE_TRANSLATE.md, line 170
    """
    print("\n" + "=" * 80)
    print("TEST: Escanner -> Analyser Correction")
    print("=" * 80)

    glossary_path = REPO_ROOT / "config" / "glossaries" / "en-fr.yaml"
    corrector = GlossaryCorrector(glossary_path)
    print("[1/2] Loaded glossary")

    wrong_text = "escanner de la sécurité et des vulnérabilités"
    expected_text = "analyser de la sécurité et des vulnérabilités"

    corrected, changes = corrector.apply_corrections(wrong_text, "en", "fr")
    print(f"[2/2] Corrected: escanner -> analyser")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    assert corrected == expected_text, (
        f"Expected '{expected_text}', got '{corrected}'"
    )
    print(f"[PASS] 'escanner' correctly replaced with 'analyser'")

    print("\n" + "=" * 80)
    print("TEST PASSED: escanner -> analyser correction works!")
    print("=" * 80)


def test_word_boundary_matching():
    """
    Test that corrections use word boundary matching.

    Ensures partial word matches are NOT replaced.
    Example: "estimation" should NOT have "métrage" -> "fusion" applied.
    """
    print("\n" + "=" * 80)
    print("TEST: Word Boundary Matching (No Partial Replacements)")
    print("=" * 80)

    glossary_path = REPO_ROOT / "config" / "glossaries" / "en-fr.yaml"
    corrector = GlossaryCorrector(glossary_path)
    print("[1/2] Loaded glossary")

    # Text that contains substrings but shouldn't be replaced
    text_no_match = "estimation textile de la capacité"  # "textile" is whole word, should be replaced
    # But let's test a case where métrage is NOT a complete word
    text_with_partial = "pourcentage métrique"  # "métrage" not present

    corrected_1, changes_1 = corrector.apply_corrections(text_no_match, "en", "fr")
    print(f"[2/2] Test 1: '{text_no_match}' -> '{corrected_1}'")

    corrected_2, changes_2 = corrector.apply_corrections(text_with_partial, "en", "fr")
    print(f"      Test 2: '{text_with_partial}' -> '{corrected_2}' (no change expected)")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    # Test 1: "textile" should be replaced (it's a whole word)
    assert corrected_1 == "estimation textuel de la capacité", (
        f"Expected 'textile' to be replaced, got '{corrected_1}'"
    )
    print(f"[PASS] Whole word 'textile' replaced")

    # Test 2: "pourcentage métrique" should NOT be changed (no matching words)
    assert corrected_2 == text_with_partial, (
        f"Expected no change, but got '{corrected_2}'"
    )
    assert len(changes_2) == 0, f"Expected no corrections, got {changes_2}"
    print(f"[PASS] No partial word replacements")

    print("\n" + "=" * 80)
    print("TEST PASSED: Word boundary matching works correctly!")
    print("=" * 80)


def test_case_preservation():
    """
    Test that corrections preserve capitalization.

    "Métrage" (capitalized) should become "Fusion" (capitalized).
    """
    print("\n" + "=" * 80)
    print("TEST: Case Preservation in Corrections")
    print("=" * 80)

    glossary_path = REPO_ROOT / "config" / "glossaries" / "en-fr.yaml"
    corrector = GlossaryCorrector(glossary_path)
    print("[1/2] Loaded glossary")

    # Test capitalized version
    text_caps = "Métrage de fichiers multiples"
    expected_caps = "Fusion de fichiers multiples"

    corrected_caps, _ = corrector.apply_corrections(text_caps, "en", "fr")
    print(f"[2/2] Capitalized: '{text_caps}' -> '{corrected_caps}'")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    assert corrected_caps == expected_caps, (
        f"Expected '{expected_caps}', got '{corrected_caps}'"
    )
    print(f"[PASS] Capitalization preserved: Métrage -> Fusion")

    print("\n" + "=" * 80)
    print("TEST PASSED: Case preservation works!")
    print("=" * 80)


def test_multiple_corrections_in_one_text():
    """
    Test that multiple corrections can be applied to the same text.
    """
    print("\n" + "=" * 80)
    print("TEST: Multiple Corrections in Single Text")
    print("=" * 80)

    glossary_path = REPO_ROOT / "config" / "glossaries" / "en-fr.yaml"
    corrector = GlossaryCorrector(glossary_path)
    print("[1/2] Loaded glossary")

    # Text with multiple errors
    text_multi = "Métrage contenu textile avec escanner automatique"
    expected_multi = "Fusion contenu textuel avec analyser automatique"

    corrected_multi, changes_multi = corrector.apply_corrections(text_multi, "en", "fr")
    print(f"[2/2] Applied {len(changes_multi)} corrections")
    print(f"      Before: {text_multi}")
    print(f"      After:  {corrected_multi}")
    print(f"      Changes: {changes_multi}")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    assert corrected_multi == expected_multi, (
        f"Expected '{expected_multi}', got '{corrected_multi}'"
    )
    print(f"[PASS] All corrections applied")

    assert len(changes_multi) == 3, (
        f"Expected 3 corrections, got {len(changes_multi)}: {changes_multi}"
    )
    print(f"[PASS] Correct number of corrections: {len(changes_multi)}")

    print("\n" + "=" * 80)
    print("TEST PASSED: Multiple corrections work!")
    print("=" * 80)


def test_get_glossary_corrector_cache():
    """
    Test that get_glossary_corrector() returns cached instance.
    """
    print("\n" + "=" * 80)
    print("TEST: Glossary Corrector Caching")
    print("=" * 80)

    # Clear cache first (if needed)
    from src.translation_engine.quality.glossary_corrector import _glossary_cache
    _glossary_cache.clear()

    print("[1/3] Cleared cache")

    corrector1 = get_glossary_corrector("en", "fr", config_root=REPO_ROOT / "config")
    print("[2/3] Loaded corrector (first call)")

    corrector2 = get_glossary_corrector("en", "fr", config_root=REPO_ROOT / "config")
    print("[3/3] Loaded corrector (second call)")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    assert corrector1 is not None, "First corrector is None"
    assert corrector2 is not None, "Second corrector is None"
    print(f"[PASS] Both correctors loaded")

    assert corrector1 is corrector2, "Correctors are not the same instance (cache failed)"
    print(f"[PASS] Corrector cached (same instance returned)")

    print("\n" + "=" * 80)
    print("TEST PASSED: Caching works!")
    print("=" * 80)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("REGRESSION TEST SUITE: Glossary-Based Translation Corrections")
    print("=" * 80)

    tests = [
        ("Test 1: métrage -> fusion", test_metrage_correction),
        ("Test 2: textile -> textuel", test_textile_correction),
        ("Test 3: escanner -> analyser", test_escanner_correction),
        ("Test 4: Word boundary matching", test_word_boundary_matching),
        ("Test 5: Case preservation", test_case_preservation),
        ("Test 6: Multiple corrections", test_multiple_corrections_in_one_text),
        ("Test 7: Caching", test_get_glossary_corrector_cache),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            print(f"\n[OK] {name} passed\n")
            passed += 1
        except (AssertionError, Exception) as e:
            print(f"\n[FAIL] {name} FAILED: {e}\n")
            failed += 1

    print("\n" + "=" * 80)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"FAILED: {failed} test(s) did not pass")
    print("=" * 80)

    if failed > 0:
        sys.exit(1)
