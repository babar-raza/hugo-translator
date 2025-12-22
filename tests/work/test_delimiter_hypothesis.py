#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick test to verify delimiter hypothesis for FIX-BT-01.

Tests:
1. PUA characters (current) are corrupted by M2M100
2. Box-drawing characters (proposed) are preserved by M2M100
"""

import sys
import io
from pathlib import Path

# Force UTF-8 output for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add user site-packages
import site
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

sys.path.insert(0, str(Path(__file__).parent))

from transformers import M2M100Tokenizer

print("Loading M2M100 tokenizer...")
tokenizer = M2M100Tokenizer.from_pretrained("facebook/m2m100_1.2B")

print("\n" + "=" * 70)
print("TEST 1: PUA Characters (Current Implementation)")
print("=" * 70)

pua_batch = "\uE000\uE000\uE000"
pua_protected = "\uE001\uE001\uE001"
pua_text = f"Hello{pua_batch}World{pua_protected}Test"

encoded = tokenizer.encode(pua_text)
decoded = tokenizer.decode(encoded, skip_special_tokens=False)

print(f"Original:  {pua_text!r}")
print(f"Decoded:   {decoded!r}")
print(f"Batch delimiter preserved:     {pua_batch in decoded} [{'PASS' if pua_batch in decoded else 'FAIL'}]")
print(f"Protected delimiter preserved: {pua_protected in decoded} [{'PASS' if pua_protected in decoded else 'FAIL'}]")

print("\n" + "=" * 70)
print("TEST 2: Box-Drawing Characters (Proposed Fix)")
print("=" * 70)

box_batch = "═══"  # U+2550 triple
box_protected = "▬▬▬"  # U+25AC triple
box_text = f"Hello{box_batch}World{box_protected}Test"

encoded = tokenizer.encode(box_text)
decoded = tokenizer.decode(encoded, skip_special_tokens=False)

print(f"Original:  {box_text!r}")
print(f"Decoded:   {decoded!r}")
print(f"Batch delimiter preserved:     {box_batch in decoded} [{'PASS' if box_batch in decoded else 'FAIL'}]")
print(f"Protected delimiter preserved: {box_protected in decoded} [{'PASS' if box_protected in decoded else 'FAIL'}]")

print("\n" + "=" * 70)
print("CONCLUSION")
print("=" * 70)

if pua_batch not in decoded and box_batch in decoded:
    print("[SUCCESS] HYPOTHESIS CONFIRMED:")
    print("   - PUA characters are corrupted by M2M100 (explains 100% batch failure)")
    print("   - Box-drawing characters are preserved by M2M100 (will fix batch translation)")
    print("\nRecommendation: Proceed with FIX-BT-01 implementation")
else:
    print("[FAILED] HYPOTHESIS REJECTED: Need different delimiter strategy")

print("=" * 70)
