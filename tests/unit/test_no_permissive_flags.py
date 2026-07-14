"""
TC-HT-006: permissive-flag lockdown lint guards.

Ensures --disable-validation/--force-accept never appear together in a
built command without --i-understand-data-loss, and that
BYPASS_PLACEHOLDER_PROTECTION is only ever read at its one legitimate
site plus the new fatal guard in engine.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _py_files(*dirs: str) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        root = REPO_ROOT / d
        if root.exists():
            files.extend(root.rglob("*.py"))
    return files


class TestNoPermissiveFlagCombo:
    # Scoped to the actual production command-building drivers (per
    # TC-HT-006), not scripts/ broadly -- scripts/test_cli_runtime.py is a
    # CLI-parser smoke-test harness that exercises each flag individually
    # as separate isolated test cases, never combined in one built command,
    # which would otherwise false-positive a naive whole-file scan.
    _DRIVER_DIRS = ("scripts/quality", ".local")

    def test_no_disable_validation_and_force_accept_together(self):
        """A command builder must never emit both flags without the
        explicit --i-understand-data-loss escape hatch alongside them."""
        offenders = []
        for dir_name in self._DRIVER_DIRS:
            for py_file in _py_files(dir_name):
                text = py_file.read_text(encoding="utf-8", errors="replace")
                has_disable = '"--disable-validation"' in text or "'--disable-validation'" in text
                has_force = '"--force-accept"' in text or "'--force-accept'" in text
                has_escape = "i-understand-data-loss" in text or "i_understand_data_loss" in text
                if has_disable and has_force and not has_escape:
                    offenders.append(str(py_file.relative_to(REPO_ROOT)))
        assert offenders == [], f"Permissive flag combo without escape hatch: {offenders}"


class TestBypassPlaceholderProtectionLockedDown:
    _ALLOWED_READ_SITES = (
        "src/translation_engine/extractor/segment_extractor.py",
        "src/translation_engine/engine.py",
        "src/cli.py",
        ".local/unified_translate.py",
        "tests/unit/test_no_permissive_flags.py",
    )

    def test_bypass_var_only_read_at_known_sites(self):
        offenders = []
        for py_file in _py_files("scripts", ".local", "src"):
            rel = str(py_file.relative_to(REPO_ROOT)).replace("\\", "/")
            if rel in self._ALLOWED_READ_SITES:
                continue
            text = py_file.read_text(encoding="utf-8", errors="replace")
            if "BYPASS_PLACEHOLDER_PROTECTION" in text:
                offenders.append(rel)
        assert offenders == [], (
            f"BYPASS_PLACEHOLDER_PROTECTION referenced outside known sites: {offenders}"
        )

    def test_engine_init_raises_fatal_on_bypass_var(self, monkeypatch):
        from src.translation_engine.engine import TranslationEngine

        monkeypatch.setenv("BYPASS_PLACEHOLDER_PROTECTION", "1")
        with pytest.raises(RuntimeError, match="FATAL"):
            TranslationEngine(
                config_service=MagicMock(),
                tm=MagicMock(),
                model_loader=MagicMock(),
            )
