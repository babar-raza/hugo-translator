"""Clone translator-clean conda environment to hugo-translator."""
import subprocess
import sys

print("Cloning translator-clean to hugo-translator...")
print("=" * 80)
print("This may take several minutes...")
print()

# Clone the environment
result = subprocess.run(
    [
        r"C:\Users\prora\anaconda3\Scripts\conda.exe",
        "create",
        "--name", "hugo-translator",
        "--clone", "translator-clean",
        "-y"
    ],
    capture_output=False,
    text=True
)

if result.returncode == 0:
    print()
    print("=" * 80)
    print("✓ Successfully cloned translator-clean to hugo-translator")
    print("=" * 80)
else:
    print()
    print("=" * 80)
    print(f"✗ Failed to clone environment (exit code: {result.returncode})")
    print("=" * 80)
    sys.exit(1)
