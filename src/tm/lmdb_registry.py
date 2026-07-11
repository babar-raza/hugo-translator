"""
LMDB path registry and enforcement.

Single source of truth for the canonical L2 LMDB path.  Every call to
L2PersistentTM.__init__ goes through assert_approved_path() so that any
unapproved path raises immediately rather than silently creating an isolated
database.

Usage in application startup (cli.py, unified_translate.py):
    from src.tm import lmdb_registry
    lmdb_registry.set_project_root(Path(__file__).parent.parent)

Usage in L2PersistentTM.__init__:
    from src.tm import lmdb_registry as _reg
    _reg.assert_approved_path(self.db_path)

Usage in scripts and tests:
    from src.tm.lmdb_registry import get_canonical_l2_path
    l2 = L2PersistentTM(db_path=get_canonical_l2_path())
"""
from __future__ import annotations

from pathlib import Path

from src.tm.l2_persistent import L2_DB_NAME

# ---------------------------------------------------------------------------
# Approved paths (relative to project root, forward-slash normalised)
# ---------------------------------------------------------------------------

APPROVED_LMDB_RELATIVE_PATHS: frozenset[str] = frozenset({
    f"data/tm/{L2_DB_NAME}",   # production canonical — the only allowed L2
})

# Paths registered as read-only migration sources during consolidation.
# Populated transiently by the merge script; empty in steady-state.
MIGRATION_SOURCE_PATHS: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_PROJECT_ROOT: Path | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def set_project_root(root: Path) -> None:
    """Called once at application startup to enable path enforcement."""
    global _PROJECT_ROOT
    _PROJECT_ROOT = root.resolve()


def get_canonical_l2_path() -> Path:
    """Return the one authoritative L2 LMDB path.  Raises if root not set."""
    if _PROJECT_ROOT is None:
        raise RuntimeError(
            "lmdb_registry.set_project_root() was not called. "
            "Call it at application startup before creating L2PersistentTM."
        )
    return _PROJECT_ROOT / "data" / "tm" / L2_DB_NAME


def assert_approved_path(db_path: Path) -> None:
    """
    Raise ValueError if db_path is not an approved LMDB path.

    Exemptions (never raise):
    - Project root not set (enforcement not active — allows tests without startup).
    - Path is outside the project root (e.g. pytest tmp_path fixtures).
    - Path is registered in MIGRATION_SOURCE_PATHS.
    """
    if _PROJECT_ROOT is None:
        return  # enforcement not active

    try:
        resolved = Path(db_path).resolve()
        rel = str(resolved.relative_to(_PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return  # outside project root → allow (pytest tmp_path, etc.)

    if rel in MIGRATION_SOURCE_PATHS:
        return  # registered migration source → allow

    if rel not in APPROVED_LMDB_RELATIVE_PATHS:
        raise ValueError(
            f"Unapproved LMDB path: '{rel}'. "
            f"Use get_canonical_l2_path() or register path in "
            f"src/tm/lmdb_registry.APPROVED_LMDB_RELATIVE_PATHS."
        )
