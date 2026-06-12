# ARCHIVED: 2026-06-11. Has hardcoded personal paths (anaconda3/envs/hugo-translator). No canonical replacement.
"""Direct runner for GPU test."""

import subprocess
import sys

python_exe = r"C:\Users\prora\anaconda3\envs\hugo-translator\python.exe"
test_script = r"tests\live_translation_gpu.py"

print("=" * 80)
print("Starting GPU Translation Test")
print("=" * 80)
print(f"Python: {python_exe}")
print(f"Script: {test_script}")
print("=" * 80)
print()

result = subprocess.run(
    [python_exe, test_script], cwd=r"c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator"
)

sys.exit(result.returncode)
