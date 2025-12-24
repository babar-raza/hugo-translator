# Setup Guide

This guide covers installation and setup of the Hugo Translation System for first-time users on Windows, Linux, and macOS.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Platform-Specific Setup](#platform-specific-setup)
  - [Windows](#windows)
  - [Linux](#linux)
  - [macOS](#macos)
  - [WSL (Windows Subsystem for Linux)](#wsl-windows-subsystem-for-linux)
- [GPU vs CPU Mode](#gpu-vs-cpu-mode)
- [Verifying Installation](#verifying-installation)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### All Platforms

- **Python 3.10 or higher** - Required
- **Git** - For cloning the repository
- **8GB+ RAM** - Minimum recommended for translation workloads
- **10GB+ free disk space** - For dependencies and models

### Windows-Specific

- **PowerShell 5.1+** (PowerShell 7+ recommended)
- **Windows 10/11** with latest updates
- **CUDA Toolkit 12.1+** (optional, for GPU acceleration)
  - Only if you have an NVIDIA GPU with 8GB+ VRAM
  - Download from: https://developer.nvidia.com/cuda-downloads

### Linux-Specific

- **bash** shell
- **CUDA Toolkit 12.1+** (optional, for GPU acceleration)
  - Only if you have an NVIDIA GPU with 8GB+ VRAM
  - Install via package manager or from: https://developer.nvidia.com/cuda-downloads

### macOS-Specific

- **macOS 10.15+** (Catalina or later)
- **Xcode Command Line Tools**
  ```bash
  xcode-select --install
  ```
- Note: CUDA is not available on macOS; the system will use CPU mode

## Quick Start

### Windows

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/your-org/hugo-translator.git
   cd hugo-translator
   ```

2. **Run the setup script:**
   ```powershell
   .\scripts\setup\setup.ps1
   ```

   The script will:
   - Detect your Python version
   - Detect GPU capabilities (CUDA mode if VRAM ≥ 8GB)
   - Create a virtual environment
   - Install appropriate dependencies
   - Verify the installation

3. **Activate the environment:**
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

4. **Run smoke tests:**
   ```powershell
   .\scripts\smoke\smoke_test.ps1
   ```

### Linux

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/hugo-translator.git
   cd hugo-translator
   ```

2. **Make scripts executable:**
   ```bash
   chmod +x scripts/setup/setup.sh scripts/smoke/smoke_test.sh
   ```

3. **Run the setup script:**
   ```bash
   ./scripts/setup/setup.sh
   ```

4. **Activate the environment:**
   ```bash
   source venv/bin/activate
   ```

5. **Run smoke tests:**
   ```bash
   ./scripts/smoke/smoke_test.sh
   ```

### macOS

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/hugo-translator.git
   cd hugo-translator
   ```

2. **Make scripts executable:**
   ```bash
   chmod +x scripts/setup/setup_macos.sh scripts/smoke/smoke_test.sh
   ```

3. **Run the setup script:**
   ```bash
   ./scripts/setup/setup_macos.sh
   ```

4. **Activate the environment:**
   ```bash
   source venv/bin/activate
   ```

5. **Run smoke tests:**
   ```bash
   ./scripts/smoke/smoke_test.sh
   ```

## Platform-Specific Setup

### Windows

#### PowerShell Execution Policy

If you encounter an execution policy error when running PowerShell scripts, you may need to temporarily allow script execution:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

After running the setup, you can restore the policy:

```powershell
Set-ExecutionPolicy -ExecutionPolicy Restricted -Scope CurrentUser
```

#### Long Path Support

Windows has a 260-character path limit by default. To enable long paths:

1. Run as Administrator:
   ```powershell
   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
   ```

2. Or enable via Group Policy:
   - Run `gpedit.msc`
   - Navigate to: Local Computer Policy → Computer Configuration → Administrative Templates → System → Filesystem
   - Enable "Enable Win32 long paths"

#### Force CPU or CUDA Mode

```powershell
# Force CPU mode (even if GPU is detected)
.\scripts\setup\setup.ps1 -CPU

# Force CUDA mode (requires compatible GPU)
.\scripts\setup\setup.ps1 -CUDA
```

### Linux

#### System Dependencies

Some Linux distributions may require additional system packages:

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
```

**RHEL/CentOS/Fedora:**
```bash
sudo dnf install -y python3 python3-pip python3-venv git
```

#### Force CPU or CUDA Mode

```bash
# Force CPU mode (even if GPU is detected)
./scripts/setup/setup.sh --cpu

# Force CUDA mode (requires compatible GPU)
./scripts/setup/setup.sh --cuda
```

### macOS

#### Python Installation

macOS may ship with an older Python version. Install Python 3.10+ using:

**Homebrew (recommended):**
```bash
brew install python@3.11
```

**Official Installer:**
Download from: https://www.python.org/downloads/

#### Apple Silicon Notes

- The system will automatically use CPU mode (CUDA not available on macOS)
- PyTorch may use Metal Performance Shaders (MPS) for acceleration on M1/M2/M3 chips
- MPS support is automatic and does not require configuration

### WSL (Windows Subsystem for Linux)

WSL2 with Ubuntu is supported and works well for CPU mode. GPU support in WSL2 requires additional setup.

#### Setup WSL2

1. **Enable WSL2:**
   ```powershell
   wsl --install
   ```

2. **Install Ubuntu:**
   ```powershell
   wsl --install -d Ubuntu-22.04
   ```

3. **Launch Ubuntu and run setup:**
   ```bash
   cd /mnt/c/Users/YourUsername/path/to/hugo-translator
   ./scripts/setup/setup.sh
   ```

#### GPU Support in WSL2

To use CUDA in WSL2:

1. **Install NVIDIA drivers on Windows host** (not in WSL)
   - Download from: https://www.nvidia.com/Download/index.aspx
   - Use driver version 450.80.02 or higher

2. **Verify GPU access in WSL:**
   ```bash
   nvidia-smi
   ```

3. **If GPU is detected, setup script will automatically use CUDA mode**

**Important Notes:**
- Do NOT install CUDA toolkit in WSL - it's provided by the Windows driver
- If `nvidia-smi` fails in WSL, the script will fall back to CPU mode
- WSL GPU support requires Windows 10 build 21382+ or Windows 11

## GPU vs CPU Mode

The setup script automatically detects your hardware and selects the appropriate mode:

### CUDA Mode (GPU)

**Requirements:**
- NVIDIA GPU with **8GB+ VRAM**
- CUDA Toolkit 12.1+ installed
- `nvidia-smi` command available

**Benefits:**
- Faster translation (3-10x speedup)
- Better for large batches
- Required for optimal L3 semantic matching

**Detection:**
The script queries GPU VRAM using:
```bash
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits
```

If VRAM ≥ 8192 MiB (8GB), CUDA mode is selected.

### CPU Mode

**When Used:**
- No NVIDIA GPU detected
- GPU has < 8GB VRAM
- macOS (CUDA not supported)
- User forces CPU mode with `--cpu` flag

**Benefits:**
- Works on any system
- Lower memory usage
- No driver dependencies

**Performance:**
- Adequate for small-medium translation jobs
- Still benefits from Translation Memory (TM) caching

### Overriding Auto-Detection

**Force CPU mode:**
```bash
# Linux/macOS
./scripts/setup/setup.sh --cpu

# Windows
.\scripts\setup\setup.ps1 -CPU
```

**Force CUDA mode:**
```bash
# Linux/macOS
./scripts/setup/setup.sh --cuda

# Windows
.\scripts\setup\setup.ps1 -CUDA
```

## Verifying Installation

### Automated Verification

Run the smoke tests to verify your installation:

**Windows:**
```powershell
.\venv\Scripts\Activate.ps1
.\scripts\smoke\smoke_test.ps1
```

**Linux/macOS:**
```bash
source venv/bin/activate
./scripts/smoke/smoke_test.sh
```

The smoke tests verify:
- ✓ CLI help command works
- ✓ Python modules import correctly
- ✓ Package version is accessible
- ✓ Dry-run translation succeeds

### Manual Verification

**Check CLI is available:**
```bash
translate-hugo --help
```

**Check Python imports:**
```python
python -c "
from src.cli import main
from src.translation_engine import TranslationEngine
from src.tm import TranslationMemory
print('All imports successful')
"
```

**Check CUDA status:**
```python
python -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'CUDA version: {torch.version.cuda}')
    print(f'GPU: {torch.cuda.get_device_name(0)}')
"
```

## Troubleshooting

### Common Issues

#### "Python not found" or "python3: command not found"

**Solution:**
- Ensure Python 3.10+ is installed
- On Windows: Add Python to PATH during installation
- On Linux/macOS: Install via package manager

#### "nvidia-smi not found" (when expecting GPU mode)

**Solution:**
- Install NVIDIA drivers: https://www.nvidia.com/Download/index.aspx
- Reboot after installation
- Verify with `nvidia-smi` command

#### "Virtual environment activation failed"

**Windows PowerShell:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Linux/macOS:**
```bash
chmod +x venv/bin/activate
source venv/bin/activate
```

#### "Permission denied" on Linux/macOS

**Solution:**
```bash
chmod +x scripts/setup/setup.sh scripts/smoke/smoke_test.sh
```

#### Pip install fails with SSL/Certificate errors

**Solution:**
- Check network connectivity and proxy settings
- Upgrade pip: `python -m pip install --upgrade pip`
- On corporate networks, configure pip for proxy:
  ```bash
  pip config set global.proxy http://proxy.example.com:8080
  ```

#### "ImportError: No module named 'torch'"

**Solution:**
- Ensure virtual environment is activated
- Re-run setup script
- Check installation logs for errors

#### CUDA installation succeeds but torch.cuda.is_available() returns False

**Possible causes:**
1. CUDA toolkit version mismatch
2. NVIDIA driver too old
3. PyTorch installed for wrong CUDA version

**Solution:**
```bash
# Uninstall current PyTorch
pip uninstall torch

# Reinstall with correct CUDA version
pip install torch --index-url https://download.pytorch.org/whl/cu121

# Verify
python -c "import torch; print(torch.cuda.is_available())"
```

#### WSL: "nvidia-smi: command not found"

**Solution:**
- Install NVIDIA drivers on Windows host (not in WSL)
- Ensure Windows build is 21382+ or Windows 11
- Restart WSL: `wsl --shutdown` then restart

#### macOS: "xcrun: error: invalid active developer path"

**Solution:**
```bash
xcode-select --install
```

#### Smoke tests fail with "Models not found"

**Note:** The first run will download ML models (~1-2GB). This is normal and happens automatically.

If downloads fail:
- Check internet connectivity
- Ensure sufficient disk space
- Check Hugging Face Hub access (some networks block it)

### Getting Help

If you encounter issues not covered here:

1. **Check the logs** - Setup and smoke test scripts provide detailed output
2. **Review existing documentation:**
   - [Troubleshooting Guide](../operations/troubleshooting.md)
   - [CLI Reference](../reference/cli.md)
   - [Configuration Reference](../reference/config.md)
3. **Search existing issues** on GitHub
4. **Open a new issue** with:
   - Platform and version (OS, Python version)
   - Setup script output (full log)
   - Error messages
   - Steps to reproduce

## Next Steps

After successful setup:

1. **Read the User Quickstart**: [docs/getting-started/user-quickstart.md](../getting-started/user-quickstart.md)
2. **Explore configuration**: [docs/reference/config.md](../reference/config.md)
3. **Learn about Translation Memory**: [docs/guides/tm-getting-started.md](../guides/tm-getting-started.md)
4. **Review CLI reference**: [docs/reference/cli.md](../reference/cli.md)

## Frequently Asked Questions

### Do I need a GPU?

No. The system works on CPU-only systems. GPU acceleration is optional and recommended for:
- Large translation jobs (1000+ files)
- Frequent translations
- Optimal L3 semantic matching performance

### How much disk space do I need?

Minimum **10GB** free space:
- Python dependencies: ~2GB
- ML models (downloaded on first run): ~1-2GB
- Translation Memory databases: ~1GB+ (grows with usage)
- Working space for translations: varies by workload

### Can I use conda instead of venv?

Yes, but the automated setup scripts use `venv` by default. If you prefer conda:

```bash
conda create -n hugo-translator python=3.11
conda activate hugo-translator
pip install -r requirements/cpu.txt  # or gpu.txt
pip install -e .
```

### How do I update to a newer version?

```bash
git pull origin main
source venv/bin/activate  # or .\venv\Scripts\Activate.ps1 on Windows
pip install --upgrade -e .
```

### Can I run multiple instances simultaneously?

Yes, but be aware:
- Each instance needs separate virtual environments
- GPU instances share GPU memory
- Translation Memory databases support concurrent access
- Consider resource limits (CPU, RAM, GPU VRAM)

### What Python version should I use?

- **Minimum**: Python 3.10
- **Recommended**: Python 3.11
- **Supported**: Python 3.10, 3.11, 3.12

Newer versions generally offer better performance.

---

**Last Updated:** 2024-12-24
**Applies To:** Hugo Translation System v0.1.0+
