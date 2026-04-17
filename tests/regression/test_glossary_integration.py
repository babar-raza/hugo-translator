"""
Integration test for glossary corrections in translation pipeline.

Tests that glossary corrections are applied during document reconstruction.

MISSION: Verify glossary corrections work end-to-end in the translation pipeline
"""
import os
import sys
from pathlib import Path

# Add src to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.utils.models import BodyRules, SiteProfile


class FakeMTModelWithErrors:
    """
    Fake MT model that intentionally produces known mistranslations.

    This simulates the errors we've seen from real M2M100 model:
    - "merge" -> "métrage" (WRONG, should be "fusion")
    - "textual" -> "textile" (WRONG, should be "textuel")
    - "scanning" -> "escanner" (WRONG, should be "analyser")
    """

    def translate_batch(self, texts, src_lang, tgt_lang):
        """Translate with intentional errors for testing glossary correction."""
        translations = []
        for text in texts:
            # Simulate known mistranslations
            translated = text
            translated = translated.replace("merge", "métrage")
            translated = translated.replace("Merge", "Métrage")
            translated = translated.replace("textual", "textile")
            translated = translated.replace("Textual", "Textile")
            translated = translated.replace("scanning", "escanner")
            translated = translated.replace("Scanning", "Escanner")

            # Add "TR()" wrapper to make translations visible
            translated = f"TR({translated})"
            translations.append(translated)

        return translations


def test_glossary_corrections_applied_in_pipeline():
    """
    Test that glossary corrections are applied during reconstruction.

    This is an end-to-end integration test that:
    1. Parses a document with known problematic terms
    2. "Translates" using fake backend that produces errors
    3. Reconstructs the document
    4. Verifies glossary corrections were applied
    """
    print("\n" + "=" * 80)
    print("TEST: Glossary Corrections Applied in Translation Pipeline")
    print("=" * 80)

    # Create test document with known problematic terms
    test_markdown = """---
title: Test Document
---

## Features

Merge multiple files to create textual content.
Use security scanning to detect issues.

### Benefits

- Merge files easily
- Textual analysis
- Scanning capabilities
"""

    print("[1/5] Created test document with problematic terms")
    print(f"      Content: {len(test_markdown)} characters")

    # Parse
    parser = HugoParser()
    source_doc = parser.parse_string(test_markdown)
    print("[2/5] Parsed document into AST")

    # Create site profile
    site_profile = SiteProfile(
        site_id="test.site",
        content_roots=["/test"],
        default_source_lang="en",
        target_langs=["fr"],
        body=BodyRules(translate_markdown=True),
        frontmatter={}
    )

    # Extract segments (production path: SegmentExtractor, not TextUnitExtractor)
    # MarkdownReconstructor._find_body_translation looks up by node_id via segment_map,
    # so we must use the same extractor+segment_map pattern as the production engine.
    extractor = SegmentExtractor(site_profile)
    segments = extractor.extract_all(source_doc)

    print(f"[3/5] Extracted {len(segments)} segments")

    # "Translate" with fake backend that produces errors
    fake_backend = FakeMTModelWithErrors()
    translations = {}

    for segment in segments:
        source_text = segment.source_text
        translated_text = fake_backend.translate_batch([source_text], "en", "fr")[0]
        translations[segment.id] = translated_text
        print(f"      Segment '{source_text[:40]}...' -> '{translated_text[:40]}...'")

    print("[4/5] Simulated translation with intentional errors")

    # Build segment_map (node_id -> segment_id), exactly like engine.py does
    segment_map = {}
    for segment in segments:
        if segment.context and segment.context.node_id:
            segment_map[segment.context.node_id] = segment.id

    # Reconstruct with glossary corrections
    reconstructor = MarkdownReconstructor(site_profile)
    reconstructed_body = reconstructor.reconstruct_document(
        source_doc, translations, "fr", segment_map=segment_map
    )

    print(f"[5/5] Reconstructed document: {len(reconstructed_body)} characters")

    # ASSERTIONS
    print("\n" + "=" * 80)
    print("ASSERTIONS:")
    print("=" * 80)

    # Check that mistranslations were corrected
    # Note: The fake backend wraps with "TR()" so we check for those patterns

    # Verify "métrage" was corrected to "fusion"
    assert "métrage" not in reconstructed_body.lower(), (
        f"Found 'métrage' in output - glossary correction not applied!\n"
        f"Output: {reconstructed_body}"
    )
    assert "fusion" in reconstructed_body.lower(), (
        f"Did not find 'fusion' in output - correction failed!\n"
        f"Output: {reconstructed_body}"
    )
    print("[PASS] 'métrage' correctly replaced with 'fusion'")

    # Verify "textile" was corrected to "textuel"
    assert "textile" not in reconstructed_body.lower(), (
        f"Found 'textile' in output - glossary correction not applied!\n"
        f"Output: {reconstructed_body}"
    )
    assert "textuel" in reconstructed_body.lower(), (
        f"Did not find 'textuel' in output - correction failed!\n"
        f"Output: {reconstructed_body}"
    )
    print("[PASS] 'textile' correctly replaced with 'textuel'")

    # Verify "escanner" was corrected to "analyser"
    assert "escanner" not in reconstructed_body.lower(), (
        f"Found 'escanner' in output - glossary correction not applied!\n"
        f"Output: {reconstructed_body}"
    )
    assert "analyser" in reconstructed_body.lower(), (
        f"Did not find 'analyser' in output - correction failed!\n"
        f"Output: {reconstructed_body}"
    )
    print("[PASS] 'escanner' correctly replaced with 'analyser'")

    # Verify TR() wrapper is still present (confirms we're using fake translations)
    assert "TR(" in reconstructed_body, (
        "TR() wrapper missing - test setup may be broken"
    )
    print("[PASS] Fake translation wrapper detected (test setup valid)")

    print("\n" + "=" * 80)
    print("TEST PASSED: Glossary corrections applied in pipeline!")
    print("=" * 80)
    print("\nSample output:")
    print(reconstructed_body[:500])
    print("...")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("REGRESSION TEST: Glossary Integration")
    print("=" * 80)

    try:
        test_glossary_corrections_applied_in_pipeline()
        print("\n[OK] Integration test passed\n")
    except (AssertionError, Exception) as e:
        print(f"\n[FAIL] Integration test FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        raise

    print("\n" + "=" * 80)
    print("INTEGRATION TEST PASSED!")
    print("=" * 80)
