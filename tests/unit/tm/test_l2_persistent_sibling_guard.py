"""TM-01: five scripts hardcoded `data/tm/l2_lmdb` (the pre-migration,
underscore-style name) instead of resolving the canonical L2 LMDB path the
way `scripts/campaign/run_gate5_batch.py` already does correctly
(`tm_data_dir / L2_DB_NAME` from config) -- silently opening a second, split
LMDB store invisible to real campaigns every time one of them ran.

This file covers both TM-01 acceptance checks:
1. Each of the five fixed scripts' path-resolution logic now matches the
   canonical pattern (imported and asserted directly, not by executing the
   whole script).
2. `_warn_on_sibling_l2_dirs(strict=True)` raises where the existing
   default-`False` behavior only warns.
"""

import importlib
import os
from pathlib import Path

import pytest

from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM
from src.utils.config_loader import get_global_config


def _canonical_l2_lmdb_path() -> Path:
    tm_data_dir = Path(get_global_config().get("paths", {}).get("tm_data_dir", "data/tm"))
    return tm_data_dir / L2_DB_NAME


def _import_without_cwd_side_effect(module_name: str):
    """Import `module_name` and restore CWD immediately afterward.

    Each of these five scripts does a module-level `os.chdir(REPO_ROOT)`
    (pre-existing, out of TM-01's scope) intended for when the script is
    *run* directly -- under that invocation `REPO_ROOT` lands on the real
    repo root. Under a plain `import`, though, `__file__` resolves fully
    absolute, so the same `Path(__file__).parent.parent`/`.parent` arithmetic
    lands one directory too shallow and chdir's the whole test process
    there. Discovered live: importing these for the parity checks below
    silently broke an unrelated later test in this suite
    (test_migrate_l2_lmdb.py's subprocess check) by leaving CWD wrong for
    the rest of the pytest session. Restoring CWD right after each import
    fully neutralizes it, since Python only executes a module's top-level
    code once (cached in sys.modules) -- no repeat side effect on re-import.
    """
    cwd = os.getcwd()
    try:
        return importlib.import_module(module_name)
    finally:
        os.chdir(cwd)


class TestScriptPathResolutionParity:
    """Each script must resolve the same canonical path run_gate5_batch.py
    does, instead of its own hardcoded `data/tm/l2_lmdb` literal."""

    def test_e2e_dry_run_matches_canonical_path(self):
        e2e_dry_run = _import_without_cwd_side_effect("scripts.e2e.e2e_dry_run")

        assert e2e_dry_run._resolve_l2_lmdb_path() == _canonical_l2_lmdb_path()

    def test_e2e_full_run_matches_canonical_path(self):
        e2e_full_run = _import_without_cwd_side_effect("scripts.e2e.e2e_full_run")

        assert e2e_full_run._resolve_l2_lmdb_path() == _canonical_l2_lmdb_path()

    def test_e2e_slides_with_telemetry_matches_canonical_path(self):
        e2e_slides_with_telemetry = _import_without_cwd_side_effect(
            "scripts.e2e.e2e_slides_with_telemetry"
        )

        assert e2e_slides_with_telemetry._resolve_l2_lmdb_path() == _canonical_l2_lmdb_path()

    def test_translate_bg_test_matches_canonical_path(self):
        translate_bg_test = _import_without_cwd_side_effect("scripts.content.translate_bg_test")

        assert translate_bg_test._resolve_l2_lmdb_path() == _canonical_l2_lmdb_path()

    def test_verify_telemetry_matches_canonical_path(self):
        verify_telemetry = _import_without_cwd_side_effect("scripts.diag.verify_telemetry")

        assert verify_telemetry._resolve_l2_lmdb_path() == _canonical_l2_lmdb_path()

    def test_canonical_path_uses_the_dot_style_name_not_the_underscore_variant(self):
        """The bug this taskcard closes: the five scripts hardcoded the
        underscore-style `l2_lmdb` name, a stale pre-migration artifact --
        the canonical name is dot-style `l2.lmdb` (L2_DB_NAME)."""
        assert L2_DB_NAME == "l2.lmdb"
        assert _canonical_l2_lmdb_path().name == "l2.lmdb"


class TestSiblingGuardStrictMode:
    """`_warn_on_sibling_l2_dirs` gains an opt-in `strict` mode (default off,
    so existing callers keep only warning) for a pre-flight/CI check that
    wants to hard-fail on a split-store condition instead of letting it
    linger, as happened live."""

    def _make_tm(self, tmp_path: Path) -> L2PersistentTM:
        # No sibling directory exists yet at construction time, so __init__'s
        # own (default, non-strict) call to _warn_on_sibling_l2_dirs() is a
        # no-op here -- the sibling is created afterward, for each test to
        # exercise _warn_on_sibling_l2_dirs() directly and deterministically.
        return L2PersistentTM(db_path=tmp_path / L2_DB_NAME)

    def test_default_strict_false_only_warns(self, tmp_path):
        tm = self._make_tm(tmp_path)
        (tmp_path / "l2_lmdb").mkdir()

        with pytest.warns(UserWarning, match="sibling LMDB"):
            tm._warn_on_sibling_l2_dirs()

    def test_strict_true_raises_instead_of_warning(self, tmp_path):
        tm = self._make_tm(tmp_path)
        (tmp_path / "l2_lmdb").mkdir()

        with pytest.raises(RuntimeError, match="sibling LMDB"):
            tm._warn_on_sibling_l2_dirs(strict=True)

    def test_strict_true_with_no_sibling_does_not_raise(self, tmp_path):
        tm = self._make_tm(tmp_path)
        # No sibling created -- must be silent under strict mode too.
        tm._warn_on_sibling_l2_dirs(strict=True)
