#!/usr/bin/env python3
"""Test sacrebleu API to understand correct usage."""

import sacrebleu

# Test WMT20 en-de
print("Testing WMT20 en-de...")
dataset = sacrebleu.DATASETS['wmt20']

# Get references and sources
refs_gen = dataset.references('en-de')
srcs_gen = dataset.source('en-de')

refs = list(refs_gen)
srcs = list(srcs_gen)

print(f"Got {len(srcs)} source sentences")
print(f"Got {len(refs)} reference items")
print(f"Type of refs[0]: {type(refs[0])}")
print(f"refs[0]: {refs[0]}")

print(f"\nFirst 3 source sentences:")
for i in range(3):
    print(f"  {i}: {srcs[i][:100]}")

print(f"\nFirst 3 reference items:")
for i in range(3):
    print(f"  {i}: {refs[i][:100] if isinstance(refs[i], str) else refs[i]}")
