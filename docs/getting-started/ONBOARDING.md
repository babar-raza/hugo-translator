# Onboarding — Zero to First Translation

This guide gets you from a fresh clone to a working translation in under 30 minutes. It covers the most direct path only. For full detail on any step, follow the links to the deeper guides.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | `python --version` |
| Git | Any | For auto-committing translated files |
| CUDA + GPU | 12.1+ | Optional; CPU fallback is automatic |

No Redis. No Docker. Not required for getting started.

---

## 2. Install

```bash
# Clone (if you haven't)
git clone <repo-url> hugo-translator
cd hugo-translator

# Create virtual environment
python -m venv .venv

# Activate
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install (CPU mode — works on any machine)
pip install -r requirements/cpu.txt
pip install -e .

# For GPU acceleration (optional — requires CUDA 12.1+)
pip install -r requirements/gpu.txt
```

Verify the install:
```bash
translate-hugo --help
```

---

## 3. Configure

```bash
# Copy the environment template
cp .env.example .env
```

Open `.env` and set the paths for your content repositories. At minimum, set one content root:

```bash
# Path to a Hugo content repository you want to translate
ASPOSE_NET_CONTENT=C:\path\to\your\content\repo
```

If you don't have a content repository yet, the test fixture at `tests/fixtures/` works for initial testing.

---

## 4. Verify Setup with a Dry Run

The `products-test` site profile points to a small fixture and is safe to use for testing:

```bash
# Dry run — shows what would be translated without writing any files
translate-hugo --site products-test --languages fr --dry-run
```

Expected output: a list of files that would be translated, with TM hit rates. No files written.

---

## 5. Run Your First Real Translation

```bash
# Translate up to 5 files to French (writes output files + auto-commits)
translate-hugo --site products-test --languages fr --max-files 5
```

Output files appear in the `output/` directory (or next to source files, depending on site profile). A git commit is created in the content repository with translation stats.

---

## 6. Run the Tests

```bash
# Core unit tests (no GPU required, ~2 minutes)
python -m pytest tests/unit/ -m "not gpu" -q

# Contract tests (fast, ~30 seconds)
python -m pytest tests/contract/ -q
```

Expected: no failures. If you see import errors on specific files, check the `tests/_archived/` directory — those are known-archived tests that have been removed from the active suite.

---

## 7. Understand the Config

The two most important config files:

- **`config/global.yaml`** — global settings: models, TM, validation, VRAM limits, per-site overrides
- **`config/site_profiles/<site>.yaml`** — per-site: content root path, target languages, output layout, model choice

To translate your own Hugo site, create a new site profile:
```bash
cp config/site_profiles/products-test.yaml config/site_profiles/mysite.yaml
# Edit mysite.yaml: set content_roots, target_languages, source_lang
```

Then:
```bash
translate-hugo --site mysite --languages fr,de --max-files 10
```

---

## 8. Run the Autonomous Workers (Production Setup)

For scheduled, recurring translation instead of manual CLI runs:

→ See [Windows-Native Deployment](../operations/windows-native-deployment.md)

For a full description of what each worker does:

→ See [AGENTS.md](../../AGENTS.md)

---

## Key Reference Links

| Topic | Link |
|-------|------|
| Full setup (all platforms) | [docs/user-guide/setup.md](../user-guide/setup.md) |
| CLI reference | [docs/reference/cli.md](../reference/cli.md) |
| Configuration reference | [docs/reference/config.md](../reference/config.md) |
| Windows worker deployment | [docs/operations/windows-native-deployment.md](../operations/windows-native-deployment.md) |
| Translation Memory guide | [docs/guides/tm-getting-started.md](../guides/tm-getting-started.md) |
| Troubleshooting | [docs/operations/troubleshooting.md](../operations/troubleshooting.md) |
| Worker monitoring | [AGENTS.md](../../AGENTS.md) |

---

## Common First-Run Issues

**`translate-hugo: command not found`**
Run `pip install -e .` in the repo root with your virtual environment active.

**`No site profile found for 'mysite'`**
Site profile file must exist at `config/site_profiles/mysite.yaml`.

**Model download takes a long time**
Normal — first run downloads the translation model (~1-5 GB from HuggingFace). Cached for all future runs in `~/.cache/huggingface/`.

**`content_roots` path not found**
The content root path in your site profile (or `.env`) must point to an existing directory. Use absolute paths or paths relative to the repo root.

**GPU not detected / CUDA error**
The system falls back to CPU automatically. For GPU, install `requirements/gpu.txt` and ensure CUDA 12.1+ drivers are installed.
