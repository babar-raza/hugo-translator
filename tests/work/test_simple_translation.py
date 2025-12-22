#!/usr/bin/env python
"""Simple test to check if M2M100 generates pure or mixed-language output"""

import sys
sys.path.insert(0, r'C:\Users\prora\AppData\Roaming\Python\Python313\site-packages')

from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

# Load model directly
print("Loading M2M100 model...")
model_name = "facebook/m2m100_418M"
tokenizer = M2M100Tokenizer.from_pretrained(model_name)
model = M2M100ForConditionalGeneration.from_pretrained(model_name)

print("Model loaded!\n")

# Test cases
test_texts = [
    "The Aspose.Slides Plugins for .NET provide a robust set of tools.",
    "These plugins offer the flexibility and power you need for presentation processing.",
    "Whether you are converting presentations between formats or merging multiple decks."
]

print("=" * 80)
print("Testing M2M100 English to German translation")
print("=" * 80)

# Translate each sentence
for i, text in enumerate(test_texts, 1):
    print(f"\n[Test {i}]")
    print(f"English: {text}")

    # Set source language
    tokenizer.src_lang = "en"

    # Tokenize
    encoded = tokenizer(text, return_tensors="pt")

    # Generate with explicit German target
    generated_tokens = model.generate(
        **encoded,
        forced_bos_token_id=tokenizer.get_lang_id("de")
    )

    # Decode
    translation = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]
    print(f"German:  {translation}")

    # Detect language
    import langdetect
    from langdetect import DetectorFactory
    DetectorFactory.seed = 0

    try:
        detected_lang = langdetect.detect(translation)
        print(f"Detected language: {detected_lang} {'✓' if detected_lang == 'de' else '✗ WRONG!'}")
    except:
        print("Detection failed")

print("\n" + "=" * 80)
print("Testing batch translation (more complex)")
print("=" * 80)

combined_text = " ".join(test_texts)
print(f"\nCombined text:\n{combined_text}\n")

tokenizer.src_lang = "en"
encoded_combined = tokenizer(combined_text, return_tensors="pt")
generated_combined = model.generate(
    **encoded_combined,
    forced_bos_token_id=tokenizer.get_lang_id("de"),
    max_length=512
)
translation_combined = tokenizer.batch_decode(generated_combined, skip_special_tokens=True)[0]

print(f"Translation:\n{translation_combined}\n")

# Check each sentence
import re
sentences = re.split(r'[.!?]+\s+', translation_combined)

print("Sentence-by-sentence language detection:")
pure_count = 0
mixed_count = 0

for i, sent in enumerate(sentences, 1):
    if len(sent.strip()) < 15:
        continue
    try:
        detected = langdetect.detect(sent)
        status = "✓" if detected == "de" else f"✗ ({detected})"
        print(f"  {i}. [{detected}] {sent[:70]}... {status}")
        if detected == "de":
            pure_count += 1
        else:
            mixed_count += 1
    except:
        print(f"  {i}. [?] {sent[:70]}... (detection failed)")

print("\n" + "=" * 80)
print("RESULT:")
print("=" * 80)
print(f"Pure German sentences: {pure_count}")
print(f"Mixed/wrong language sentences: {mixed_count}")

if mixed_count > 0:
    print("\n⚠️  CONCLUSION: M2M100 model itself is generating mixed-language output!")
    print("   This is a fundamental model behavior issue, not a system integration problem.")
else:
    print("\n✓ M2M100 generates pure German output in isolation.")
    print("  The mixing issue must be caused by the AST/batch translation system.")
