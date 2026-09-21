"""Structural guard for deprecated translation execution paths (TC-APT-022 / TC-APT-030).

Plan: ``C:/Users/prora/.claude/plans/hugo-translator-aspose-org-partitioned-kahn.md``
(mission ``aspose-org-full-portfolio-translation-20260901``, §1 hard limits, §5 G-06/G-19,
§5.1 root cause 2).

The only sanctioned way to run translation work against a content repository is
``src/workers/campaign_runner.py`` under ``validation_policy: zero-defect``.  Every
other historical entry point (the gitignored ``.local/unified_translate.py`` shard
script and its siblings, the mtime-only ``SweepScheduler`` sweep path) produced
output under a *different, weaker* acceptance bar, which is a verified root cause
of cross-rerun inconsistency in the corpus.

This module makes that a structural fact instead of a documentation convention:
a deprecated entry point calls :func:`refuse_deprecated_entrypoint` before it does
anything else and exits unless the operator has set an explicit, loud, per-path
override.  The override exists only for forensic reproduction of historical
behaviour -- never for producing content.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

#: Environment variable that carries the override.  Its value must equal the exact
#: deprecated path name being invoked (e.g. ``unified_translate``); a bare ``1`` is
#: deliberately NOT accepted so an override for one path can never unlock another.
OVERRIDE_ENV = "HT_ALLOW_DEPRECATED_EXECUTION_PATH"

#: Exit status used when a deprecated entry point refuses to run.
REFUSAL_EXIT_CODE = 2

SANCTIONED_PATH = "src/workers/campaign_runner.py (validation_policy: zero-defect)"

#: Names of every known deprecated path.  Kept as data so tests and audits can
#: enumerate them; a new deprecated path is registered here, not in prose.
DEPRECATED_PATHS: frozenset[str] = frozenset(
    {
        "unified_translate",  # .local/unified_translate.py  (G-06)
        "fast_translate_kb_direct",  # .local/fast_translate_kb_direct.py
        "fast_translate_kb_shard",  # .local/fast_translate_kb_shard.py
        "heal_missing_indexes_s3",  # .local/heal_missing_indexes_s3.py
        "sweep_scheduler",  # src/orchestrator/scheduler.py::SweepScheduler (G-19)
    }
)


class DeprecatedExecutionPathError(RuntimeError):
    """Raised (in library mode) when a deprecated path is used without override."""


def override_granted(path_name: str, environ: Mapping[str, str] | None = None) -> bool:
    """Return True only if the environment carries an exact override for ``path_name``."""
    env = os.environ if environ is None else environ
    return env.get(OVERRIDE_ENV, "") == path_name


def refusal_message(path_name: str) -> str:
    return (
        f"REFUSED: '{path_name}' is a deprecated, ungoverned translation execution path "
        f"(TC-APT-022/TC-APT-030). The only sanctioned path is {SANCTIONED_PATH}. "
        f"To reproduce historical behaviour for forensics ONLY, set "
        f"{OVERRIDE_ENV}={path_name} explicitly. Never use it to produce content."
    )


def check_deprecated_entrypoint(
    path_name: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Library-mode guard: raise :class:`DeprecatedExecutionPathError` unless overridden.

    ``path_name`` must be one of :data:`DEPRECATED_PATHS`; passing an unregistered
    name is a programming error and raises ``ValueError`` so a typo can never
    silently grant passage.
    """
    if path_name not in DEPRECATED_PATHS:
        raise ValueError(f"unregistered deprecated path name: {path_name!r}")
    if not override_granted(path_name, environ):
        raise DeprecatedExecutionPathError(refusal_message(path_name))


def refuse_deprecated_entrypoint(
    path_name: str,
    *,
    environ: Mapping[str, str] | None = None,
    stream=None,
) -> None:
    """Script-mode guard: print the refusal and ``sys.exit(REFUSAL_EXIT_CODE)`` unless overridden.

    Call this as the *first* statement after ``sys.path`` setup in a deprecated
    script, before any heavy import (models, TM stores) so that a refused run
    costs nothing and touches nothing.
    """
    try:
        check_deprecated_entrypoint(path_name, environ=environ)
    except DeprecatedExecutionPathError as exc:
        print(str(exc), file=stream or sys.stderr, flush=True)
        sys.exit(REFUSAL_EXIT_CODE)
    print(
        f"WARNING: deprecated execution path '{path_name}' running under explicit "
        f"{OVERRIDE_ENV} override -- forensic reproduction only.",
        file=stream or sys.stderr,
        flush=True,
    )
