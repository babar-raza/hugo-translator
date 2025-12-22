#!/usr/bin/env python
"""Test AST-FIX-01: Verify new delimiter format has no English text."""

import sys
sys.path.insert(0, r'C:\Users\prora\AppData\Roaming\Python\Python313\site-packages')

from src.translation_engine.extractor.text_unit_extractor import _create_batch_delimiter

print("Testing AST-FIX-01: Delimiter Design Fix")
print("=" * 60)

# Create delimiter
test_uuid = "test1234"
delimiter = _create_batch_delimiter(test_uuid)

print(f"\nDelimiter created: {repr(delimiter)}")
print(f"Delimiter length: {len(delimiter)}")

# Verify no English words
english_words = ["UNTRANSLATABLE", "BOUNDARY", "BATCH", "COUNT", "HEADER"]
has_english = False

for word in english_words:
    if word in delimiter:
        print(f"❌ ERROR: Delimiter contains English word: '{word}'")
        has_english = True

if not has_english:
    print("[OK] No English words in delimiter")

# Verify PUA characters present
if "\uE000" in delimiter:
    print(f"[OK] Contains PUA start token (\\uE000)")
else:
    print(f"[ERROR] Missing PUA start token")

if "\uE001" in delimiter:
    print(f"[OK] Contains PUA end token (\\uE001)")
else:
    print(f"[ERROR] Missing PUA end token")

# Verify triple repetition
start_count = delimiter.count("\uE000")
end_count = delimiter.count("\uE001")

print(f"\nPUA token counts:")
print(f"  Start tokens (\\uE000): {start_count}")
print(f"  End tokens (\\uE001): {end_count}")

if start_count == 3:
    print("  [OK] Start token has triple repetition")
else:
    print(f"  [ERROR] Start token count should be 3, got {start_count}")

if end_count == 3:
    print("  [OK] End token has triple repetition")
else:
    print(f"  [ERROR] End token count should be 3, got {end_count}")

# Verify UUID is present
if test_uuid in delimiter:
    print(f"[OK] UUID '{test_uuid}' present in delimiter")
else:
    print(f"[ERROR] UUID '{test_uuid}' missing from delimiter")

# Expected format check
expected_format = f"\uE000\uE000\uE000{test_uuid}\uE001\uE001\uE001"
if delimiter == expected_format:
    print(f"\n[OK] Delimiter matches expected format exactly")
else:
    print(f"\n[ERROR] Delimiter format mismatch")
    print(f"  Expected: {repr(expected_format)}")
    print(f"  Got:      {repr(delimiter)}")

# Final verdict
print("\n" + "=" * 60)
if (not has_english and start_count == 3 and end_count == 3
    and delimiter == expected_format):
    print("[PASS] AST-FIX-01 PASSED: Delimiter design is correct")
    print("\nKey improvements:")
    print("  - No English text (prevents translation corruption)")
    print("  - Triple PUA markers (easy corruption detection)")
    print("  - UUID-only identifier (language-neutral)")
else:
    print("[FAIL] AST-FIX-01 FAILED: Issues found above")
    sys.exit(1)
