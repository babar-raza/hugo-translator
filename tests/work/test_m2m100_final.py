#!/usr/bin/env python
"""Test M2M100 and write output to file for proper inspection"""

import sys
sys.path.insert(0, r'C:\Users\prora\AppData\Roaming\Python\Python313\site-packages')

from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

# Load model
print("Loading M2M100 model...")
model_name = "facebook/m2m100_418M"
tokenizer = M2M100Tokenizer.from_pretrained(model_name)
model = M2M100ForConditionalGeneration.from_pretrained(model_name)
print("Model loaded!\n")

# Test text
test_text = """The Aspose.Slides Plugins for .NET provide a robust set of tools designed to simplify PowerPoint presentation processing within .NET applications.
Whether you are converting presentations between formats, merging multiple decks together, extracting text for indexing, or exporting slides to PDF, images, or web formats, these plugins offer the flexibility and power you need.
The guides provided here will help you integrate these plugins efficiently, ensuring streamlined workflows and optimized presentation processing in your projects."""

print("Translating to German...")
tokenizer.src_lang = "en"
encoded = tokenizer(test_text, return_tensors="pt", max_length=512, truncation=True)
generated = model.generate(**encoded, forced_bos_token_id=tokenizer.get_lang_id("de"), max_length=512)
translation = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]

# Write to file
output_file = "m2m100_test_output.txt"
with open(output_file, "w", encoding="utf-8") as f:
    f.write("English Source:\n")
    f.write("=" * 80 + "\n")
    f.write(test_text + "\n\n")
    f.write("German Translation:\n")
    f.write("=" * 80 + "\n")
    f.write(translation + "\n\n")

print(f"Output written to {output_file}")
print("\nGerman translation:")
print(translation)

# Test language detection
print("\nLanguage detection test:")
import langdetect
from langdetect import DetectorFactory
DetectorFactory.seed = 0

try:
    detected = langdetect.detect(translation)
    print(f"Overall detected language: {detected}")
except Exception as e:
    print(f"Overall detection failed: {e}")

# Sentence by sentence
import re
sentences = [s.strip() for s in re.split(r'[.!?]+', translation) if len(s.strip()) > 15]

print(f"\nSentence-by-sentence detection ({len(sentences)} sentences):")
german_count = 0
other_count = 0

for i, sent in enumerate(sentences, 1):
    try:
        detected = langdetect.detect(sent)
        if detected == "de":
            german_count += 1
            print(f"  {i}. [de] OK")
        else:
            other_count += 1
            print(f"  {i}. [{detected}] MIXED - {sent[:60]}")
    except Exception as e:
        print(f"  {i}. Failed: {e}")

print(f"\nRESULT: {german_count} German / {other_count} Mixed")

if other_count == 0:
    print("\nCONCLUSION: M2M100 generates PURE German in isolation.")
    print("The mixed-language problem is caused by the AST/batch translation system.")
else:
    print("\nCONCLUSION: M2M100 itself generates mixed-language output.")
    print("The model has fundamental issues with language consistency.")
