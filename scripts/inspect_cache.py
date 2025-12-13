#!/usr/bin/env python
"""Quick script to inspect legacy cache directory"""
import os
import glob
import json
import sys

cache_dir = r"D:\onedrive\Documents\GitHub\translationcache"

if not os.path.exists(cache_dir):
    print(f"ERROR: Directory not found: {cache_dir}")
    sys.exit(1)

# Find all JSON files
files = glob.glob(os.path.join(cache_dir, "*.json"))

print("=" * 60)
print(f"Legacy Cache Directory: {cache_dir}")
print("=" * 60)
print(f"\nFound {len(files)} JSON files:\n")

total_size = 0
total_entries = 0

for f in sorted(files):
    size = os.path.getsize(f)
    total_size += size

    # Try to count entries
    try:
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            entries = len(data) if isinstance(data, dict) else 0
            total_entries += entries

        print(f"  {os.path.basename(f):<30} {size:>12,} bytes  {entries:>8,} entries")
    except Exception as e:
        print(f"  {os.path.basename(f):<30} {size:>12,} bytes  (error: {e})")

print("\n" + "=" * 60)
print(f"TOTAL: {len(files)} files, {total_size:,} bytes, {total_entries:,} entries")
print("=" * 60)

# Sample a few entries from first file
if files:
    print(f"\nSample entries from {os.path.basename(files[0])}:")
    try:
        with open(files[0], 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            if isinstance(data, dict):
                for i, (key, value) in enumerate(list(data.items())[:3]):
                    print(f"  {i+1}. '{key[:50]}...' -> '{value[:50]}...'")
    except Exception as e:
        print(f"  Error reading sample: {e}")
