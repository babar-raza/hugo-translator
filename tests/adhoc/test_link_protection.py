"""
Test markdown link protection fix.
"""
import re
from src.translation_engine.extractor.placeholder_manager import PlaceholderManager

def test_link_protection():
    """Test that markdown links are protected correctly."""

    # Test input with markdown link
    text = "Get Aspose.Slides from [NuGet](https://www.nuget.org/packages/Aspose.Slides.NET/)."

    # Pattern from site profile (protect complete link)
    preserve_patterns = [r'\[[^\]]+\]\([^)]+\)']

    # Apply protection
    pm = PlaceholderManager()
    protected_text, placeholder_map = pm.protect(text, preserve_patterns)

    print("Original text:")
    print(f"  {text}")
    print()
    print("Protected text (sent to translator):")
    print(f"  {protected_text}")
    print()
    print("Placeholder map:")
    for placeholder, original in placeholder_map.items():
        print(f"  {placeholder} -> {original}")
    print()

    # Simulate translation (translator sees: "Get Aspose.Slides from {PLACEHOLDER_0}.")
    # Translator translates to German, preserving the placeholder:
    simulated_translation = "Holen Sie Aspose.Slides von {PLACEHOLDER_0}."

    print("Simulated translation (with placeholder):")
    print(f"  {simulated_translation}")
    print()

    # Restore placeholders
    restored = pm.restore(simulated_translation, placeholder_map)

    print("Restored text (final output):")
    print(f"  {restored}")
    print()

    # Verify
    expected = "Holen Sie Aspose.Slides von [NuGet](https://www.nuget.org/packages/Aspose.Slides.NET/)."
    if restored == expected:
        print("[PASS] Link URL and syntax preserved!")
    else:
        print("[FAIL]")
        print(f"  Expected: {expected}")
        print(f"  Got:      {restored}")

if __name__ == "__main__":
    test_link_protection()
