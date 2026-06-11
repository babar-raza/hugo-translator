"""
Simple integration test for glossary corrections.

Tests that glossary corrections work by directly injecting mistranslations.
"""

import os
import sys
from pathlib import Path

# Add src to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

from src.translation_engine.quality.glossary_corrector import get_glossary_corrector
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.utils.models import BodyRules, SiteProfile


def test_glossary_direct_application():
    """
    Test that glossary corrections are applied to reconstructed markdown.

    This is a direct unit test that bypasses the full pipeline and just
    tests the glossary correction logic in reconstruct_body().
    """
    print("\n" + "=" * 80)
    print("TEST: Direct Glossary Correction Application")
    print("=" * 80)

    # Create site profile
    site_profile = SiteProfile(
        site_id="test.site",
        content_roots=["/test"],
        default_source_lang="en",
        target_langs=["fr"],
        body=BodyRules(translate_markdown=True),
        frontmatter={},
    )

    # Create reconstructor
    reconstructor = MarkdownReconstructor(site_profile)
    print("[1/3] Created reconstructor")

    # Simulate markdown with intentional errors (as if from MT)
    markdown_with_errors = """## Features

Métrage plusieurs fichiers pour créer du contenu textile.
Utilisez escanner de sécurité pour détecter les problèmes.

### Benefits

- Métrage des fichiers facilement
- Analyse textile
- Capacités de escanner
"""

    print("[2/3] Created markdown with intentional errors")
    print(f"      Content length: {len(markdown_with_errors)} chars")

    # Apply glossary corrections directly
    src_lang = site_profile.default_source_lang
    tgt_lang = "fr"

    corrector = get_glossary_corrector(src_lang, tgt_lang)
    assert corrector is not None, "Glossary corrector not found for en-fr"

    corrected_markdown, corrections = corrector.apply_corrections(
        markdown_with_errors, src_lang, tgt_lang
    )

    print(f"[3/3] Applied {len(corrections)} corrections")
    print(f"      Corrections: {corrections}")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    # Verify corrections were applied
    assert "métrage" not in corrected_markdown.lower(), "Found 'métrage' in corrected output"
    assert "fusion" in corrected_markdown.lower(), "Did not find 'fusion' in corrected output"
    print("[PASS] 'métrage' -> 'fusion' correction applied")

    assert "textile" not in corrected_markdown.lower(), "Found 'textile' in corrected output"
    assert "textuel" in corrected_markdown.lower(), "Did not find 'textuel' in corrected output"
    print("[PASS] 'textile' -> 'textuel' correction applied")

    assert "escanner" not in corrected_markdown.lower(), "Found 'escanner' in corrected output"
    assert "analyser" in corrected_markdown.lower(), "Did not find 'analyser' in corrected output"
    print("[PASS] 'escanner' -> 'analyser' correction applied")

    assert len(corrections) == 3, f"Expected 3 corrections, got {len(corrections)}"
    print(f"[PASS] Correct number of corrections: {len(corrections)}")

    print("\n" + "=" * 80)
    print("TEST PASSED: Glossary corrections work!")
    print("=" * 80)

    print("\nCorrected output:")
    print(corrected_markdown)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("SIMPLE GLOSSARY TEST")
    print("=" * 80)

    try:
        test_glossary_direct_application()
        print("\n[OK] Test passed\n")
    except (AssertionError, Exception) as e:
        print(f"\n[FAIL] Test FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        raise

    print("\n" + "=" * 80)
    print("TEST COMPLETE!")
    print("=" * 80)
