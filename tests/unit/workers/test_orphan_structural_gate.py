"""
Unit tests for the orphan recovery structural gate and language filter.

Tests _validate_orphan_structural_integrity (static method on the worker) and
_is_translated_filename. All git subprocess calls are mocked — no real git repo required.

Run: pytest tests/unit/workers/test_orphan_structural_gate.py -v
"""
import subprocess
import sys
import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub heavy ML deps (same pattern as other worker unit tests)
# ---------------------------------------------------------------------------
def _ensure_stubs():
    for mod in ("ctranslate2", "transformers", "sentence_transformers", "faiss", "lmdb", "pytz"):
        sys.modules.setdefault(mod, types.ModuleType(mod))
    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        cuda_stub = types.ModuleType("torch.cuda")
        cuda_stub.is_available = MagicMock(return_value=True)
        cuda_stub.empty_cache = MagicMock()
        torch_stub.cuda = cuda_stub
        sys.modules["torch"] = torch_stub
        sys.modules["torch.cuda"] = cuda_stub


_ensure_stubs()

from src.translation_engine.engine import _is_translated_filename  # noqa: E402
from src.workers.autonomous_content_translation_worker import (  # noqa: E402
    AutonomousContentTranslationWorker as W,
)

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------
SOURCE_3CB = """\
---
title: My Post
---
Intro.

```csharp
var x = 1;
```

Middle.

```python
print("hi")
```

End.

```bash
echo done
```
"""

ORPHAN_3CB = """\
---
title: Mein Post
---
Einleitung.

```csharp
var x = 1;
```

Mitte.

```python
print("hi")
```

Ende.

```bash
echo done
```
"""

ORPHAN_0CB = """\
---
title: Mein Post
---
Einleitung. Code wurde weggelassen. Ende.
"""

ORPHAN_TITLE_PREFIX = """\
---
title: Mein Post
---
TITLE: My Post Title
Inhalt.
"""

SOURCE_5H = """\
---
title: Doc
---
## A
## B
## C
## D
## E
"""

ORPHAN_8H = """\
---
title: Dok
---
## A
## B
## C
## D
## E
## F
## G
## H
"""


def _good_git_result(content: str) -> MagicMock:
    """subprocess.run mock returning content with returncode=0."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = content
    return m


def _missing_git_result() -> MagicMock:
    """subprocess.run mock for 'not in git HEAD' (nonzero exit)."""
    m = MagicMock()
    m.returncode = 128
    m.stdout = ""
    return m


def _run_gate(tmp_path, orphan_content, git_result, lang="de", per_language_folders=False):
    """Helper: write orphan file, patch subprocess.run, call gate."""
    orphan = tmp_path / f"index.{lang}.md"
    orphan.write_text(orphan_content, encoding="utf-8")
    with patch("subprocess.run", return_value=git_result):
        return W._validate_orphan_structural_integrity(
            orphan, tmp_path, "en", per_language_folders=per_language_folders
        )


# ===========================================================================
# 1. Fail-safe tests (SR-01 — git error must return False)
# ===========================================================================
class TestFailSafe:
    def test_runtime_error_returns_false(self, tmp_path):
        """git RuntimeError → fail-safe False (not True)."""
        orphan = tmp_path / "index.de.md"
        orphan.write_text(ORPHAN_3CB, encoding="utf-8")
        with patch("subprocess.run", side_effect=RuntimeError("git not found")):
            result = W._validate_orphan_structural_integrity(
                orphan, tmp_path, "en", per_language_folders=False
            )
        assert result is False

    def test_timeout_returns_false(self, tmp_path):
        """subprocess.TimeoutExpired → fail-safe False."""
        orphan = tmp_path / "index.de.md"
        orphan.write_text(ORPHAN_3CB, encoding="utf-8")
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("git", 10)):
            result = W._validate_orphan_structural_integrity(
                orphan, tmp_path, "en", per_language_folders=False
            )
        assert result is False

    def test_os_error_reading_orphan_returns_false(self, tmp_path):
        """OSError reading the orphan file → fail-safe False."""
        orphan = tmp_path / "index.de.md"
        # Do NOT create the file — read_text will raise FileNotFoundError (OSError)
        with patch("subprocess.run", return_value=_good_git_result(SOURCE_3CB)):
            result = W._validate_orphan_structural_integrity(
                orphan, tmp_path, "en", per_language_folders=False
            )
        assert result is False

    def test_git_missing_source_returns_true(self, tmp_path):
        """Nonzero git exit (source not in HEAD) → pass-through True (can't compare)."""
        result = _run_gate(tmp_path, ORPHAN_3CB, _missing_git_result())
        assert result is True


# ===========================================================================
# 2. Code block preservation
# ===========================================================================
class TestCodeBlockPreservation:
    def test_matching_blocks_pass(self, tmp_path):
        """3 source CB, 3 orphan CB → passes."""
        result = _run_gate(tmp_path, ORPHAN_3CB, _good_git_result(SOURCE_3CB))
        assert result is True

    def test_zero_orphan_blocks_rejected(self, tmp_path):
        """3 source CB, 0 orphan CB → rejected."""
        result = _run_gate(tmp_path, ORPHAN_0CB, _good_git_result(SOURCE_3CB))
        assert result is False

    def test_partial_loss_rejected(self, tmp_path):
        """3 source CB, 2 orphan CB → rejected."""
        orphan_2cb = """\
---
title: Mein Post
---
```csharp
var x = 1;
```

```python
print("hi")
```
"""
        result = _run_gate(tmp_path, orphan_2cb, _good_git_result(SOURCE_3CB))
        assert result is False

    def test_source_no_code_blocks_passes(self, tmp_path):
        """Source 0 CB → any orphan CB count passes (no constraint)."""
        source_0cb = "---\ntitle: T\n---\nNo code here.\n"
        orphan_0cb = "---\ntitle: Т\n---\nНет кода.\n"
        result = _run_gate(tmp_path, orphan_0cb, _good_git_result(source_0cb))
        assert result is True

    def test_gate_reads_from_git_not_disk(self, tmp_path):
        """Gate uses git HEAD content even if source file is corrupted on disk."""
        # Corrupt source file on disk (0 CB)
        (tmp_path / "index.md").write_text(
            "---\ntitle: Corrupted\n---\nNo code.", encoding="utf-8"
        )
        # Orphan also has 0 CB — would pass if gate read from disk
        # But git HEAD returns SOURCE_3CB (3 CB) → gate must reject
        result = _run_gate(tmp_path, ORPHAN_0CB, _good_git_result(SOURCE_3CB))
        assert result is False, (
            "Gate must read source from git HEAD, not the corrupted disk copy"
        )


# ===========================================================================
# 3. Hallucination detection
# ===========================================================================
class TestHallucinationDetection:
    def test_title_prefix_rejected(self, tmp_path):
        """Body starting with TITLE: → rejected."""
        result = _run_gate(tmp_path, ORPHAN_TITLE_PREFIX, _good_git_result(SOURCE_5H))
        assert result is False

    def test_heading_surplus_3_rejected(self, tmp_path):
        """Source 5H, orphan 8H (+3) → rejected."""
        result = _run_gate(tmp_path, ORPHAN_8H, _good_git_result(SOURCE_5H))
        assert result is False

    def test_heading_surplus_2_passes(self, tmp_path):
        """Source 5H, orphan 7H (+2) → passes (below threshold of 3)."""
        orphan_7h = SOURCE_5H.replace("title: Doc", "title: Dok") + "## F\n## G\n"
        result = _run_gate(tmp_path, orphan_7h, _good_git_result(SOURCE_5H))
        assert result is True

    def test_title_prefix_with_whitespace_rejected(self, tmp_path):
        """Leading whitespace before TITLE: should still be caught."""
        orphan = "---\ntitle: T\n---\n  TITLE: Something\nContent."
        result = _run_gate(tmp_path, orphan, _good_git_result(SOURCE_5H))
        assert result is False


# ===========================================================================
# 4. Language filter (_is_translated_filename)
# ===========================================================================
TARGET_LANGS = [
    "ar", "bg", "ca", "cs", "da", "de", "el", "es", "fa", "fi",
    "fr", "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "lt",
    "lv", "ms", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl",
    "sv", "th", "tr", "uk", "vi", "zh",
]


class TestLanguageFilter:
    def test_source_file_excluded(self):
        is_trans, lang = _is_translated_filename("index.md", TARGET_LANGS, "en")
        assert is_trans is False
        assert lang is None

    def test_underscore_index_excluded(self):
        is_trans, _ = _is_translated_filename("_index.md", TARGET_LANGS, "en")
        assert is_trans is False

    def test_german_translation_included(self):
        is_trans, lang = _is_translated_filename("index.de.md", TARGET_LANGS, "en")
        assert is_trans is True
        assert lang == "de"

    def test_case_insensitive_match(self):
        is_trans, lang = _is_translated_filename("index.DE.MD", TARGET_LANGS, "en")
        assert is_trans is True
        assert lang == "de"

    def test_source_lang_en_excluded(self):
        is_trans, _ = _is_translated_filename("index.en.md", TARGET_LANGS, "en")
        assert is_trans is False

    def test_unknown_lang_code_excluded(self):
        is_trans, _ = _is_translated_filename("index.xx.md", TARGET_LANGS, "en")
        assert is_trans is False

    def test_markdown_extension_included(self):
        is_trans, lang = _is_translated_filename("post.fr.markdown", TARGET_LANGS, "en")
        assert is_trans is True
        assert lang == "fr"

    def test_no_lang_in_name_excluded(self):
        is_trans, _ = _is_translated_filename("about.md", TARGET_LANGS, "en")
        assert is_trans is False
