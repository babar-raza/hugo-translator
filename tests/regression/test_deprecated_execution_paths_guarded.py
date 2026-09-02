"""TC-APT-022 / TC-APT-030 regression: deprecated translation execution paths are structurally guarded.

Mission aspose-org-full-portfolio-translation-20260901 (plan §1 hard limits, §5 G-06/G-19).
``campaign_runner.py`` under ``validation_policy: zero-defect`` must be the ONLY reachable
way to run translation work.  These tests prove the guard primitive itself, prove the
gitignored ``.local`` shard scripts carry it (when present on this host), and prove that
invoking the deprecated shard script actually refuses to run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.utils import deprecated_execution_guard as guard

REPO_ROOT = Path(__file__).resolve().parents[2]

LOCAL_SCRIPTS = {
    ".local/unified_translate.py": "unified_translate",
    ".local/fast_translate_kb_direct.py": "fast_translate_kb_direct",
    ".local/fast_translate_kb_shard.py": "fast_translate_kb_shard",
    ".local/heal_missing_indexes_s3.py": "heal_missing_indexes_s3",
}


class TestGuardPrimitive:
    def test_refuses_without_override(self):
        with pytest.raises(guard.DeprecatedExecutionPathError) as exc:
            guard.check_deprecated_entrypoint("unified_translate", environ={})
        assert "REFUSED" in str(exc.value)
        assert "campaign_runner.py" in str(exc.value)

    def test_bare_one_is_not_an_override(self):
        with pytest.raises(guard.DeprecatedExecutionPathError):
            guard.check_deprecated_entrypoint(
                "unified_translate", environ={guard.OVERRIDE_ENV: "1"}
            )

    def test_override_for_one_path_does_not_unlock_another(self):
        env = {guard.OVERRIDE_ENV: "unified_translate"}
        guard.check_deprecated_entrypoint("unified_translate", environ=env)
        with pytest.raises(guard.DeprecatedExecutionPathError):
            guard.check_deprecated_entrypoint("sweep_scheduler", environ=env)

    def test_unregistered_name_is_a_programming_error(self):
        with pytest.raises(ValueError):
            guard.check_deprecated_entrypoint("not_a_registered_path", environ={})

    def test_script_mode_exits_with_refusal_code(self, capsys):
        with pytest.raises(SystemExit) as exc:
            guard.refuse_deprecated_entrypoint("unified_translate", environ={})
        assert exc.value.code == guard.REFUSAL_EXIT_CODE
        assert "REFUSED" in capsys.readouterr().err

    def test_script_mode_passes_with_exact_override(self, capsys):
        guard.refuse_deprecated_entrypoint(
            "unified_translate", environ={guard.OVERRIDE_ENV: "unified_translate"}
        )
        assert "forensic reproduction only" in capsys.readouterr().err

    def test_every_local_script_name_is_registered(self):
        assert set(LOCAL_SCRIPTS.values()) <= guard.DEPRECATED_PATHS
        assert "sweep_scheduler" in guard.DEPRECATED_PATHS


class TestLocalScriptsCarryGuard:
    """``.local/`` is gitignored; these run only where the scripts exist (the production host)."""

    @pytest.mark.parametrize("rel,name", sorted(LOCAL_SCRIPTS.items()))
    def test_guard_is_first_thing_after_sys_path(self, rel: str, name: str):
        path = REPO_ROOT / rel
        if not path.is_file():
            pytest.skip(f"{rel} not present on this host")
        head = path.read_text(encoding="utf-8").splitlines()[:60]
        joined = "\n".join(head)
        assert f"refuse_deprecated_entrypoint({name!r})" in joined, rel
        # The guard must precede every engine/model import so a refusal costs nothing.
        guard_idx = next(
            i
            for i, line in enumerate(head)
            if "refuse_deprecated_entrypoint(" in line and "import" not in line
        )
        heavy = [
            i
            for i, line in enumerate(head)
            if line.startswith("from src.") and "deprecated_execution_guard" not in line
        ]
        assert all(i > guard_idx for i in heavy), f"{rel}: engine import precedes guard"


@pytest.mark.skipif(
    not (REPO_ROOT / ".local/unified_translate.py").is_file(),
    reason=".local/unified_translate.py not present on this host",
)
def test_unified_translate_refuses_to_run_without_override():
    """Acceptance for TC-APT-022: the deprecated path, when attempted, refuses to run."""
    env = {k: v for k, v in os.environ.items() if k != guard.OVERRIDE_ENV}
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / ".local/unified_translate.py"), "--dry-run"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == guard.REFUSAL_EXIT_CODE, proc.stderr[-2000:]
    assert "REFUSED" in proc.stderr
    # Nothing downstream of the guard may have run (no model/TM banner lines).
    assert "[tm]" not in proc.stdout and "Loading" not in proc.stdout
