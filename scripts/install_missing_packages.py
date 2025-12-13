"""Install missing packages in hugo-translator environment."""
import subprocess
import sys

packages = [
    "lmdb",
    "faiss-gpu",  # GPU version for CUDA
    "sentence-transformers",
    "structlog"  # for logging
]

print("Installing missing packages in hugo-translator environment...")
print("=" * 80)
print(f"Packages to install: {', '.join(packages)}")
print()

for package in packages:
    print(f"Installing {package}...")
    result = subprocess.run(
        [
            r"C:\Users\prora\anaconda3\envs\hugo-translator\Scripts\pip.exe",
            "install",
            package
        ],
        capture_output=False,
        text=True
    )

    if result.returncode == 0:
        print(f"  OK - {package} installed successfully\n")
    else:
        print(f"  FAILED - {package} installation failed\n")

print("=" * 80)
print("Package installation complete")
