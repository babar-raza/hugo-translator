# Hugo Translation System - Setup Guide

## Prerequisites

### Required Software
- Python 3.10 or higher
- Git
- Docker Desktop (for containerized deployment)

### Recommended
- 16GB+ RAM (32GB recommended)
- 50GB+ free disk space
- GPU with CUDA support (optional, for faster translation)

## Installation Steps

### 1. Clone the Repository

```bash
git clone <repository-url>
cd hugo-translator
```

### 2. Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate on Linux/Mac
source venv/bin/activate

# Activate on Windows
venv\Scriptsctivate
```

### 3. Install Dependencies

Choose based on your hardware:

```bash
# For CPU-only systems
pip install -r requirements/cpu.txt

# For systems with GPU
pip install -r requirements/gpu.txt

# For development (includes testing tools)
pip install -r requirements/dev.txt
```

### 4. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
# Use your preferred text editor
```

### 5. Verify Installation

```bash
# Check Python environment
python --version

# Verify imports work
python -c "import pydantic; import yaml; print('OK')"

# Run tests (if dev dependencies installed)
pytest tests/ -v
```

## VSCode Setup

If using VS Code:

1. Open the project folder in VS Code
2. Install recommended extensions when prompted:
   - Python
   - Pylance
   - Ruff
3. The workspace settings will auto-configure formatting and linting

## Next Steps

1. Review the architecture plan: [implementation/living-architecture-plan-v0.2.md](../../implementation/living-architecture-plan-v0.2.md)
2. Check the task list: [implementation/tasks.md](../../implementation/tasks.md)
3. Start with Phase 1: Configuration & Site Profiles

## Troubleshooting

### Issue: Module not found errors
**Solution**: Ensure virtual environment is activated and dependencies are installed

### Issue: VSCode not recognizing Python interpreter  
**Solution**: Press Ctrl+Shift+P, search "Python: Select Interpreter", choose venv

### Issue: Tests failing
**Solution**: Check PYTHONPATH includes src/ directory

---

For more help, see the [main README](../../README.md)
