#!/usr/bin/env python3
"""Bootstrap script for first-time developer setup.

Run this after cloning the repository:
    python scripts/setup_dev_env.py

It will:
1. Check Python version (>= 3.10 required)
2. Create a virtual environment (.venv)
3. Install base + dev dependencies
4. Copy .env.example to .env if missing
5. Install pre-commit hooks
6. Create required data directories
7. Print next steps
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = REPO_ROOT / ".venv"
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

REQUIRED_DIRS = [
    "data/tm",
    "data/logs",
    "data/models",
    "data/benchmarks",
    "output",
    "backups",
]

MIN_PYTHON = (3, 10)


def check_python_version():
    if sys.version_info[:2] < MIN_PYTHON:
        print(
            f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
            f"found {sys.version_info[0]}.{sys.version_info[1]}"
        )
        sys.exit(1)
    print(f"Python {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]} OK")


def create_venv():
    if VENV_DIR.exists():
        print(f".venv already exists at {VENV_DIR}")
        return
    print("Creating virtual environment...")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    print(f"Created .venv at {VENV_DIR}")


def get_pip():
    """Return the pip executable inside the venv."""
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "pip.exe")
    return str(VENV_DIR / "bin" / "pip")


def get_python():
    """Return the python executable inside the venv."""
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def install_dependencies():
    pip = get_pip()
    print("Installing base dependencies...")
    subprocess.check_call([pip, "install", "-r", str(REPO_ROOT / "requirements" / "base.txt")])
    print("Installing dev dependencies...")
    subprocess.check_call([pip, "install", "-r", str(REPO_ROOT / "requirements" / "dev.txt")])
    print("Installing package in editable mode...")
    subprocess.check_call([pip, "install", "-e", str(REPO_ROOT)])
    print("Dependencies installed.")


def setup_env_file():
    if ENV_FILE.exists():
        print(f".env already exists at {ENV_FILE}")
        return
    if not ENV_EXAMPLE.exists():
        print("WARNING: .env.example not found, skipping .env creation")
        return
    shutil.copy2(ENV_EXAMPLE, ENV_FILE)
    print("Copied .env.example -> .env")
    print("  >> Edit .env to set ASPOSE_NET_CONTENT and ASPOSE_ORG_CONTENT paths")


def install_precommit():
    python = get_python()
    try:
        subprocess.check_call([python, "-m", "pre_commit", "install"], cwd=str(REPO_ROOT))
        print("Pre-commit hooks installed.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("WARNING: pre-commit install failed (will work after manual install)")


def create_directories():
    for d in REQUIRED_DIRS:
        path = REPO_ROOT / d
        path.mkdir(parents=True, exist_ok=True)
    print(f"Created {len(REQUIRED_DIRS)} data directories.")


def print_next_steps():
    activate = (
        ".venv\\Scripts\\activate"
        if platform.system() == "Windows"
        else "source .venv/bin/activate"
    )
    print(f"""
========================================
  Setup complete!
========================================

Next steps:

1. Activate the virtual environment:
   {activate}

2. Edit .env and set your content repository paths:
   ASPOSE_NET_CONTENT=/path/to/aspose.net/content
   ASPOSE_ORG_CONTENT=/path/to/aspose.org/content

3. (Optional) For GPU acceleration, install CUDA dependencies:
   pip install -r requirements/gpu.txt

4. Run the test suite to verify:
   python -m pytest tests/unit -x -q

5. Try a dry-run translation:
   translate-hugo --site products.aspose.net --max-files 5 --dry-run

Models download automatically from HuggingFace on first use.
""")


def main():
    os.chdir(str(REPO_ROOT))
    print(f"Setting up hugo-translator in {REPO_ROOT}\n")

    check_python_version()
    create_venv()
    install_dependencies()
    setup_env_file()
    install_precommit()
    create_directories()
    print_next_steps()


if __name__ == "__main__":
    main()
