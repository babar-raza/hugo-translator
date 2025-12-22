#!/usr/bin/env python
"""Test M2M100 translation behavior to identify root cause of mixed-language output"""

import sys
sys.path.insert(0, r'C:\Users\prora\AppData\Roaming\Python\Python313\site-packages')

from src.model_runtime.loader import ModelLoader
import torch

# Initialize model loader
loader = ModelLoader(device="cpu")

# Load M2M100 model
print("Loading M2M100 model...")
model_wrapper = loader.load_model("m2m100_418m")
model = model_wrapper.model
tokenizer = model_wrapper.tokenizer

print(f"Model loaded: {type(model).__name__}")
print(f"Tokenizer loaded: {type(tokenizer).__name__}\n")

# Test 1: Simple English to German translation
print("=" * 80)
print("TEST 1: Simple English to German translation")
print("=" * 80)

english_text = "The Aspose.Slides Plugins for .NET provide a robust set of tools."

# Set source and target language tokens
tokenizer.src_lang = "en"
target_lang_token = tokenizer.get_lang_id("de")

print(f"Source text: {english_text}")
print(f"Source lang: en")
print(f"Target lang: de (token={target_lang_token})")

# Tokenize
inputs = tokenizer(english_text, return_tensors="pt")

# Force target language token
forced_bos_token_id = tokenizer.get_lang_id("de")

# Translate
with torch.no_grad():
    generated_tokens = model.generate(
        **inputs,
        forced_bos_token_id=forced_bos_token_id,
        max_length=200
    )

# Decode
translation = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]

print(f"Translation: {translation}")
print()

# Test 2: Check if model mixes languages with multiple sentences
print("=" * 80)
print("TEST 2: Multiple sentences (more likely to show mixing)")
print("=" * 80)

english_multi = """The Aspose.Slides Plugins for .NET provide a robust set of tools.
These plugins offer the flexibility and power you need.
Whether you are converting presentations between formats or merging multiple decks together."""

tokenizer.src_lang = "en"
inputs_multi = tokenizer(english_multi, return_tensors="pt")

with torch.no_grad():
    generated_tokens_multi = model.generate(
        **inputs_multi,
        forced_bos_token_id=forced_bos_token_id,
        max_length=500
    )

translation_multi = tokenizer.batch_decode(generated_tokens_multi, skip_special_tokens=True)[0]

print(f"Source text:\n{english_multi}")
print(f"\nTranslation:\n{translation_multi}")
print()

# Test 3: Check language detection of output
print("=" * 80)
print("TEST 3: Language detection of translations")
print("=" * 80)

import langdetect
from langdetect import DetectorFactory
DetectorFactory.seed = 0

try:
    detected_lang1 = langdetect.detect(translation)
    print(f"Translation 1 detected language: {detected_lang1}")
except Exception as e:
    print(f"Detection 1 failed: {e}")

try:
    detected_lang2 = langdetect.detect(translation_multi)
    print(f"Translation 2 detected language: {detected_lang2}")

    # Check sentence-by-sentence
    import re
    sentences = re.split(r'[.!?]+\s+', translation_multi)
    print(f"\nSentence-by-sentence detection:")
    for i, sent in enumerate(sentences):
        if len(sent.strip()) < 15:
            continue
        try:
            detected = langdetect.detect(sent)
            print(f"  Sentence {i+1}: {detected} - {sent[:60]}...")
        except Exception as e:
            print(f"  Sentence {i+1}: Failed - {sent[:60]}...")

except Exception as e:
    print(f"Detection 2 failed: {e}")

print("\n" + "=" * 80)
print("CONCLUSIONS:")
print("=" * 80)
print("If translations show mixed languages, the issue is with M2M100 model behavior.")
print("If translations are pure German, the issue is with the AST/batch translation system.")
