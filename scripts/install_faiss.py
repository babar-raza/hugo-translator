"""Install faiss-cpu via conda (faster)."""
import subprocess
import sys

print("Installing faiss-cpu via conda...")
print("=" * 80)

result = subprocess.run(
    [
        r"C:\Users\prora\anaconda3\Scripts\conda.exe",
        "install",
        "-n", "hugo-translator",
        "-c", "conda-forge",
        "faiss-cpu",
        "pydantic",
        "-y"
    ]
)

if result.returncode == 0:
    print("\n" + "=" * 80)
    print("Successfully installed packages!")
    print("=" * 80)
else:
    print("\n" + "=" * 80)
    print(f"Installation failed with exit code: {result.returncode}")
    print("=" * 80)
    sys.exit(1)
