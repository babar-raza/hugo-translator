"""Wrapper to run live translation test with explicit output."""
import subprocess
import sys

# Run the test with explicit environment
cmd = [
    r"C:\Users\prora\anaconda3\envs\llm\python.exe",
    r"tests\live_translation_simple.py"
]

print("Starting live translation test...")
print(f"Command: {' '.join(cmd)}")
print("=" * 80)
sys.stdout.flush()

result = subprocess.run(
    cmd,
    cwd=r"c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator",
    capture_output=False,  # Let output go directly to console
    text=True
)

print("=" * 80)
print(f"Process exited with code: {result.returncode}")
sys.exit(result.returncode)
