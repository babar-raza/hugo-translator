"""Check packages in hugo-translator environment."""
import subprocess
import sys

print("Checking packages in hugo-translator environment...")
print("=" * 80)

result = subprocess.run(
    [
        r"C:\Users\prora\anaconda3\Scripts\conda.exe",
        "list",
        "-n", "hugo-translator"
    ],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    lines = result.stdout.strip().split('\n')
    print(f"Total packages: {len([l for l in lines if l and not l.startswith('#')])}\n")

    # Look for key packages
    key_packages = ['torch', 'transformers', 'sentencepiece', 'cuda', 'faiss', 'sentence-transformers', 'lmdb', 'pyyaml']
    print("Key packages:")
    for line in lines:
        if any(pkg in line.lower() for pkg in key_packages):
            print(f"  {line}")

    print("\nFull package list:")
    for line in lines:
        if line and not line.startswith('#'):
            print(f"  {line}")
else:
    print(f"Error: {result.stderr}")
    sys.exit(1)
