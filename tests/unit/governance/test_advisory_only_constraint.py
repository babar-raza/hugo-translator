"""TC-PHASE4-04: Enforce advisory-only language constraint in sprint governance artifacts.

The post-sprint loop uses an advisory-only (directive-driven) model.  The term "autonomous"
is prohibited in prompt assets and sprint scripts because it misrepresents what the system
does.  This test detects any prohibited usage that slips into the scanned files.

Allowed exceptions (these are prohibition declarations, not prohibited uses):
  - A bare list item ``- autonomous`` or ``* autonomous`` listing the word for prohibition.
  - Lines that explicitly negate the term (``NOT autonomous``, ``non-autonomous``).
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Scanned paths (relative to repository root)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]

_SCAN_DIRS_AND_GLOBS: list[tuple[Path, str]] = [
    (_REPO_ROOT / "docs" / "governance" / "prompts", "*.md"),
    (_REPO_ROOT / "scripts" / "ops", "sprint_*.py"),
]

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
_PROHIBITED = re.compile(r"\bautonomous\b", re.IGNORECASE)

# A bare prohibition-list item: `- autonomous` or `* autonomous` (only that word on the line).
_BARE_LIST_ITEM = re.compile(r"^\s*[-*]\s+autonomous\s*$", re.IGNORECASE)

# Explicit negation phrases.
_NEGATION = re.compile(r"\b(not\s+autonomous|non-autonomous)\b", re.IGNORECASE)


def _is_exempt(line: str) -> bool:
    """Return True if the line is an allowed exception to the prohibition."""
    return bool(_BARE_LIST_ITEM.match(line) or _NEGATION.search(line))


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_no_autonomous_language_in_prompt_assets_and_sprint_scripts() -> None:
    """Prohibited term 'autonomous' must not appear outside approved exemptions.

    Exemptions:
      - Bare list items that declare the word as prohibited (``- autonomous``).
      - Lines that explicitly negate the term (``NOT autonomous``, ``non-autonomous``).

    If this test fails, find the offending line and either:
      a. Remove the term (replace with advisory, directive-driven, machine-emitted, etc.), or
      b. Wrap it in a negation (e.g. "NOT autonomous") if the intent is to prohibit it.
    """
    violations: list[str] = []
    for scan_dir, glob_pattern in _SCAN_DIRS_AND_GLOBS:
        if not scan_dir.exists():
            continue
        for path in sorted(scan_dir.glob(glob_pattern)):
            for lineno, raw_line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if _PROHIBITED.search(raw_line) and not _is_exempt(raw_line):
                    violations.append(
                        f"{path.relative_to(_REPO_ROOT)}:{lineno}: {raw_line.strip()}"
                    )

    assert not violations, (
        "Prohibited term 'autonomous' found in governance artifacts.\n"
        "Replace with advisory / directive-driven / machine-emitted terminology,\n"
        "or wrap in a negation if the intent is to list it as prohibited.\n\n"
        "Violations:\n" + "\n".join(f"  {v}" for v in violations)
    )
