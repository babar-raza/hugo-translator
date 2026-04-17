"""
Regression test: Shortcode Token Leakage Prevention

CRITICAL INVARIANT:
The translation pipeline must NEVER leak internal tokens into output markdown.

Blocked tokens (case-insensitive):
- xifp (internal marker)
- ⟦ or ⟧ (bracket placeholders)
- {PLACEHOLDER_ (template tokens)

Test strategy:
- Simulate translation pipeline with mock text processing
- Use FakeMTModel that detects token leakage
- Verify shortcodes are preserved
- Verify internal tokens never appear in output

This is a MINIMAL regression test that does NOT require full parser/engine setup.
"""

import re


class FakeMTModel:
    """
    Fake translation model for testing token leakage detection.

    Invariants enforced:
    1. Input text must NOT contain blocked tokens (xifp, ⟦, ⟧, {PLACEHOLDER_)
    2. Output is deterministic: "TR(" + input + ")"
    """

    BLOCKED_TOKENS = [
        "xifp",           # Internal marker (case-insensitive)
        "⟦",              # Left bracket placeholder
        "⟧",              # Right bracket placeholder
        "{PLACEHOLDER_",  # Template token prefix
    ]

    def translate(self, text: str, source_lang: str = "en", target_lang: str = "de") -> str:
        """
        Translate text with token leakage detection.

        Raises AssertionError if input contains blocked tokens.
        """
        # Check for case-insensitive xifp
        if "xifp" in text.lower():
            raise AssertionError(
                f"TOKEN LEAKAGE DETECTED: Input contains 'xifp' token (case-insensitive):\n{text}"
            )

        # Check for other blocked tokens
        for token in self.BLOCKED_TOKENS[1:]:  # Skip xifp (already checked)
            if token in text:
                raise AssertionError(
                    f"TOKEN LEAKAGE DETECTED: Input contains '{token}' token:\n{text}"
                )

        # Return deterministic output
        return f"TR({text})"


def simulate_translation_pipeline(markdown: str, model: FakeMTModel) -> str:
    """
    Simplified translation pipeline simulation.

    Steps:
    1. Extract shortcodes (protected from translation)
    2. Extract translatable text segments
    3. Translate segments using model (which checks for token leakage)
    4. Reassemble markdown with translations and preserved shortcodes
    """
    # Pattern to match Hugo shortcodes
    shortcode_pattern = r'\{\{<\s*\w+\s*>\}\}'

    # Extract shortcodes and their positions
    shortcodes = []
    for match in re.finditer(shortcode_pattern, markdown):
        shortcodes.append((match.start(), match.end(), match.group()))

    # Split markdown into segments (protected vs translatable)
    segments = []
    last_pos = 0

    for start, end, shortcode_text in shortcodes:
        # Add translatable text before shortcode
        if start > last_pos:
            text_segment = markdown[last_pos:start]
            if text_segment.strip():
                segments.append(("text", text_segment))

        # Add protected shortcode
        segments.append(("shortcode", shortcode_text))
        last_pos = end

    # Add remaining text after last shortcode
    if last_pos < len(markdown):
        text_segment = markdown[last_pos:]
        if text_segment.strip():
            segments.append(("text", text_segment))

    # Translate text segments (shortcodes are protected)
    translated_segments = []
    for seg_type, content in segments:
        if seg_type == "shortcode":
            # Preserve shortcode byte-for-byte
            translated_segments.append(content)
        else:
            # Translate text using model (which checks for token leakage)
            # Only translate non-empty text
            if content.strip():
                translated = model.translate(content.strip(), "en", "de")
                translated_segments.append(translated)
            else:
                translated_segments.append(content)

    # Reassemble markdown
    return " ".join(translated_segments)


def test_shortcode_preservation_with_translation():
    """
    Test that shortcodes are preserved byte-for-byte during translation.

    Test sample includes:
    - Shortcode: {{< sections >}}
    - Regular text
    """
    print("\n" + "=" * 80)
    print("TEST: Shortcode Preservation with Translation")
    print("=" * 80)

    # Minimal markdown sample
    markdown_sample = "Intro text {{< sections >}} outro text"

    print("\n[1/3] Input markdown:")
    print(f"   {repr(markdown_sample)}")

    print("\n[2/3] Translate using FakeMTModel (with token leakage detection)...")
    model = FakeMTModel()

    try:
        output_markdown = simulate_translation_pipeline(markdown_sample, model)
        print("   OK: Translation completed without token leakage")
    except AssertionError as e:
        print(f"   ✗ FAIL: {e}")
        raise

    print("\n[3/3] Output markdown:")
    print(f"   {repr(output_markdown)}")

    # VERIFICATION
    print("\n" + "=" * 80)
    print("VERIFICATION")
    print("=" * 80)

    # Check 1: Shortcode preserved byte-for-byte
    shortcode_pattern = r'\{\{<\s*sections\s*>\}\}'
    shortcode_match = re.search(shortcode_pattern, output_markdown)

    print("\n[Check 1] Shortcode preservation:")
    if shortcode_match:
        print(f"   ✓ PASS: Found shortcode: {shortcode_match.group()}")
    else:
        print("   ✗ FAIL: Shortcode '{{< sections >}}' not found in output")
        print(f"   Output: {repr(output_markdown)}")
        raise AssertionError("Shortcode not preserved in output")

    # Check 2: No token leakage
    print("\n[Check 2] Token leakage detection:")

    leaked_tokens = []

    # Check xifp (case-insensitive)
    if "xifp" in output_markdown.lower():
        leaked_tokens.append("xifp (case-insensitive)")

    # Check other tokens
    for token in FakeMTModel.BLOCKED_TOKENS[1:]:
        if token in output_markdown:
            leaked_tokens.append(token)

    if leaked_tokens:
        print(f"   ✗ FAIL: Found leaked tokens: {leaked_tokens}")
        print(f"   Output: {repr(output_markdown)}")
        raise AssertionError(f"Token leakage detected in output: {leaked_tokens}")
    else:
        print("   ✓ PASS: No leaked tokens found (xifp/⟦/⟧/{PLACEHOLDER_)")

    # Check 3: Translations were applied
    print("\n[Check 3] Translations applied:")
    if "TR(" in output_markdown:
        print("   ✓ PASS: Found translated text with TR() wrapper")
    else:
        print("   ✗ FAIL: Translations not applied to output")
        raise AssertionError("Translations not applied")

    print("\n" + "=" * 80)
    print("✓ ALL CHECKS PASSED")
    print("=" * 80)


def test_token_leakage_detection():
    """
    Test that FakeMTModel correctly detects token leakage attempts.

    This test verifies the test infrastructure itself.
    """
    print("\n" + "=" * 80)
    print("TEST: FakeMTModel Token Leakage Detection")
    print("=" * 80)

    model = FakeMTModel()

    # Test 1: Clean text should pass
    print("\n[Test 1] Clean text (should pass):")
    try:
        result = model.translate("This is clean text")
        print(f"   ✓ PASS: Translation successful: {result}")
    except AssertionError as e:
        print(f"   ✗ FAIL: Unexpected error: {e}")
        raise

    # Test 2: Text with xifp should fail (lowercase)
    print("\n[Test 2] Text with 'xifp' (should fail):")
    try:
        model.translate("This has xifp token")
        print("   ✗ FAIL: Should have raised AssertionError for xifp")
        raise AssertionError("FakeMTModel failed to detect xifp token")
    except AssertionError as e:
        if "TOKEN LEAKAGE DETECTED" in str(e):
            print("   ✓ PASS: Correctly detected xifp token")
        else:
            raise

    # Test 3: Text with XIFP should fail (uppercase - case insensitive)
    print("\n[Test 3] Text with 'XIFP' (should fail - case insensitive):")
    try:
        model.translate("This has XIFP token")
        print("   ✗ FAIL: Should have raised AssertionError for XIFP")
        raise AssertionError("FakeMTModel failed to detect XIFP token (case-insensitive)")
    except AssertionError as e:
        if "TOKEN LEAKAGE DETECTED" in str(e):
            print("   ✓ PASS: Correctly detected XIFP token (case-insensitive)")
        else:
            raise

    # Test 4: Text with ⟦ should fail
    print("\n[Test 4] Text with '⟦' (should fail):")
    try:
        model.translate("This has ⟦bracket token")
        print("   ✗ FAIL: Should have raised AssertionError for ⟦")
        raise AssertionError("FakeMTModel failed to detect ⟦ token")
    except AssertionError as e:
        if "TOKEN LEAKAGE DETECTED" in str(e):
            print("   ✓ PASS: Correctly detected ⟦ token")
        else:
            raise

    # Test 5: Text with placeholder token should fail
    print("\n[Test 5] Text with placeholder token (should fail):")
    try:
        model.translate("This has {PLACEHOLDER_123} token")
        print("   ✗ FAIL: Should have raised AssertionError for placeholder")
        raise AssertionError("FakeMTModel failed to detect {PLACEHOLDER_ token")
    except AssertionError as e:
        if "TOKEN LEAKAGE DETECTED" in str(e):
            print("   ✓ PASS: Correctly detected {PLACEHOLDER_ token")
        else:
            raise

    print("\n" + "=" * 80)
    print("✓ ALL DETECTION TESTS PASSED")
    print("=" * 80)


def test_complex_markdown_with_bold_and_code():
    """
    Test shortcode preservation in markdown with bold and inline code.

    This tests more realistic markdown that includes:
    - Bold text: **Bold**
    - Inline code: `SaveFormat.Pdf`
    - Shortcode: {{< sections >}}
    """
    print("\n" + "=" * 80)
    print("TEST: Complex Markdown with Bold, Code, and Shortcode")
    print("=" * 80)

    markdown = "Intro **bold** text {{< sections >}} `code` and more"

    print("\n[1/2] Input markdown:")
    print(f"   {repr(markdown)}")

    model = FakeMTModel()
    output = simulate_translation_pipeline(markdown, model)

    print("\n[2/2] Output markdown:")
    print(f"   {repr(output)}")

    # Verify shortcode preserved
    assert "{{< sections >}}" in output, "Shortcode not preserved"
    print("\n   ✓ PASS: Shortcode preserved in complex markdown")

    # Verify no token leakage
    assert "xifp" not in output.lower(), "xifp token leaked"
    assert "⟦" not in output, "⟦ token leaked"
    assert "⟧" not in output, "⟧ token leaked"
    assert "{PLACEHOLDER_" not in output, "{PLACEHOLDER_ token leaked"
    print("   ✓ PASS: No token leakage in complex markdown")

    print("\n" + "=" * 80)
    print("✓ COMPLEX MARKDOWN TEST PASSED")
    print("=" * 80)
