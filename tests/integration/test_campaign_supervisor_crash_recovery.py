"""OP-01: prove CampaignSupervisor recovers cleanly from a REAL process interruption
at each of the three boundaries between "receipted", "adopted", and "committed".

Each scenario launches a genuine child ``python.exe`` process (via ``subprocess.run``,
not an in-process fake) that constructs a real ``CampaignSupervisor`` around a real
``CampaignRunner`` pointed at a disposable git repository, then calls ``os._exit(1)``
partway through -- a hard process kill with no unwinding, no ``finally`` blocks, no
atexit handlers, exactly the same end state on disk as an external SIGKILL/TerminateProcess
would leave (Windows releases the child's msvcrt byte-range lock the moment its process
handle closes, killed or not, which is exactly what lets the recovering process re-acquire
CampaignSupervisor's own lock file immediately -- see src/workers/campaign_supervisor.py).

The three interruption points, and how each is forced:

* ``before_adoption``  -- monkeypatched in the child so ``CampaignSupervisor._await_adoption``
  hard-exits at entry: the shard's receipt is already fsynced to disk (job execution
  finished for real), but nothing about adoption or commit has started yet.
* ``before_commit``    -- monkeypatched so ``CampaignSupervisor._commit_shard`` hard-exits at
  entry: the (fake) adoption check already returned, but ``git add`` has not run.
* ``before_commit_finalize`` -- the real ``subprocess.run`` is wrapped so the specific
  ``git commit`` invocation inside ``CampaignRunner._commit_verified_outputs`` hard-exits
  right before it would run; the preceding real ``git add``/``git diff --cached`` calls in
  that same method are left untouched, so the child leaves a genuinely staged-but-uncommitted
  git index behind.

After each interruption, a fresh ``CampaignSupervisor`` (real, in this test's own process,
no crash injected) is invoked and must converge to: every campaign output committed exactly
once, a clean working tree, and a ledger that ``CampaignRunner._validated_resume_receipts()``
accepts without complaint (proves no corrupted/duplicated receipt survived the crash).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from src.workers.campaign_manifest import CampaignManifest, git_dirty_paths, sha256_file
from src.workers.campaign_runner import CampaignRunner
from src.workers.campaign_supervisor import CampaignSupervisor

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "pilot"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "campaign@example.invalid"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Campaign Test"], cwd=path, check=True, capture_output=True
    )


def _build_campaign(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Two-shard (es, fr) disposable campaign. Returns (manifest_path, ledger_root,
    translator_repo); the content repo is embedded in the manifest."""
    content_repo = tmp_path / "content"
    _init_repo(content_repo)
    source = content_repo / "content/docs.aspose.org/en/words/net/page.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("source content", encoding="utf-8")
    marker = content_repo / "baseline.txt"
    marker.write_text("baseline", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=content_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"], cwd=content_repo, check=True, capture_output=True
    )

    payload = {
        "schema_version": 1,
        "campaign_id": "pilot",
        "validation_policy": "zero-defect",
        "content_repo": str(content_repo),
        "content_repo_sha": "a" * 40,
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64,
        "knowledge_fingerprints": {},
        "target_locales": ["es", "fr"],
        "expected_source_count": 1,
        "expected_output_count": 2,
        "retry_policy": {
            "primary_model": "m2m100_418m",
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "professionalize_llm",
        },
        "commit_policy": {"branch": "pilot", "max_outputs_per_commit": 250, "push": False},
        "sources": [
            {
                "site_id": "docs.aspose.org",
                "family": "words",
                "platform": "net",
                "source_path": "content/docs.aspose.org/en/words/net/page.md",
                "source_sha256": sha256_file(source),
                "wave": 2,
                "outputs": {
                    "es": "content/docs.aspose.org/es/words/net/page.md",
                    "fr": "content/docs.aspose.org/fr/words/net/page.md",
                },
            }
        ],
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return manifest_path, tmp_path / "ledger", tmp_path / "translator"


def _load_runner(manifest_path: Path, ledger_root: Path, translator_repo: Path) -> CampaignRunner:
    return CampaignRunner(
        manifest=CampaignManifest.load(manifest_path),
        translation_engine=object(),
        translator_repo=translator_repo,
        ledger_root=ledger_root,
    )


_CHILD_SCRIPT_TEMPLATE = dedent(
    """
    import json
    import os
    import sys

    sys.path.insert(0, {project_root!r})

    from pathlib import Path

    from src.workers.campaign_manifest import CampaignManifest, sha256_file
    from src.workers.campaign_runner import CampaignRunner
    from src.workers.campaign_supervisor import CampaignSupervisor

    manifest = CampaignManifest.load(Path({manifest_path!r}))
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=object(),
        translator_repo=Path({translator_repo!r}),
        ledger_root=Path({ledger_root!r}),
    )


    def _fake_run_shard_jobs(shard_id):
        shards = {{
            str(shard["shard_id"]): shard
            for shard in runner.manifest.shards(
                resume_receipts=set(runner._validated_resume_receipts()), max_outputs=1
            )
        }}
        shard = shards[shard_id]
        source = runner.manifest.sources[0]
        for _source, locale, expected_output in shard["jobs"]:
            output = runner.content_repo / expected_output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("accepted " + locale + " content", encoding="utf-8")
            runner.ledger.append_receipt(
                {{
                    "campaign_id": runner.manifest.campaign_id,
                    "source_path": source.source_path,
                    "output_path": expected_output,
                    "source_sha256": source.source_sha256,
                    "output_sha256": sha256_file(output),
                    "target_lang": locale,
                    "validation_policy": "zero-defect",
                    "config_fingerprint": runner.manifest.config_fingerprint,
                    "model_fingerprint": "fixture",
                    "gate_results": {{str(i): {{"passed": True}} for i in range(1, 45)}},
                }}
            )


    def _fake_adoption_check(shard_id):
        marker = Path({adoption_marker!r})
        calls = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else []
        calls.append(shard_id)
        marker.write_text(json.dumps(calls), encoding="utf-8")
        return {{"adopted": [shard_id]}}


    supervisor = CampaignSupervisor(
        runner=runner,
        heartbeat_path=Path({heartbeat_path!r}),
        state_path=Path({state_path!r}),
        adoption_check=_fake_adoption_check,
        run_shard_jobs=_fake_run_shard_jobs,
    )

    crash_at = {crash_at!r}
    if crash_at == "before_adoption":
        def _crash(shard_id):
            sys.stdout.flush()
            os._exit(1)
        supervisor._await_adoption = _crash
    elif crash_at == "before_commit":
        def _crash(shard_id):
            sys.stdout.flush()
            os._exit(1)
        supervisor._commit_shard = _crash
    elif crash_at == "before_commit_finalize":
        import subprocess as _sp
        _orig_run = _sp.run

        def _patched_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "commit":
                sys.stdout.flush()
                os._exit(1)
            return _orig_run(cmd, *args, **kwargs)

        _sp.run = _patched_run
    else:
        raise SystemExit("unknown crash_at: " + crash_at)

    supervisor.run(max_iterations=4)
    print("UNEXPECTED_CLEAN_COMPLETION")
    """
)


def _run_child_and_crash(
    *,
    crash_at: str,
    manifest_path: Path,
    ledger_root: Path,
    translator_repo: Path,
    heartbeat_path: Path,
    state_path: Path,
    adoption_marker: Path,
    tmp_path: Path,
) -> subprocess.CompletedProcess:
    script_path = tmp_path / f"child_{crash_at}.py"
    script_path.write_text(
        _CHILD_SCRIPT_TEMPLATE.format(
            project_root=str(PROJECT_ROOT),
            manifest_path=str(manifest_path),
            ledger_root=str(ledger_root),
            translator_repo=str(translator_repo),
            heartbeat_path=str(heartbeat_path),
            state_path=str(state_path),
            adoption_marker=str(adoption_marker),
            crash_at=crash_at,
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "UNEXPECTED_CLEAN_COMPLETION" not in result.stdout, (
        f"child did not hit the crash_at={crash_at!r} injection point; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # os._exit(1) is a hard kill with no traceback -- the child must not have gone
    # through any other, unrelated failure path first. (Benign import-time
    # DeprecationWarnings from transitive C-extension imports are tolerated; only an
    # actual Python exception/traceback indicates the child failed for the wrong reason.)
    assert "Traceback (most recent call last)" not in result.stderr, (
        f"child raised before reaching crash_at={crash_at!r}: {result.stderr}"
    )
    assert result.returncode == 1, (
        f"expected the child's self-inflicted os._exit(1) for crash_at={crash_at!r}, "
        f"got returncode={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    return result


def _assert_clean_final_state(runner: CampaignRunner, *, expected_commits: int) -> None:
    """Shared post-recovery assertions: exactly one commit per output, nothing
    duplicated, nothing corrupted, working tree clean."""
    receipts = runner._validated_resume_receipts()  # raises on any corruption/mismatch
    assert set(receipts) == {
        "content/docs.aspose.org/es/words/net/page.md",
        "content/docs.aspose.org/fr/words/net/page.md",
    }
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=runner.content_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == "", f"working tree not clean after recovery: {status!r}"

    log = subprocess.run(
        ["git", "log", "--pretty=%s"],
        cwd=runner.content_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert len(log) == expected_commits, f"unexpected commit count: {log}"
    # No path was ever committed twice across the whole history.
    changed_paths: list[str] = []
    all_shas = subprocess.run(
        ["git", "log", "--pretty=%H"],
        cwd=runner.content_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for sha in all_shas:
        files = subprocess.run(
            ["git", "show", "--pretty=", "--name-only", sha],
            cwd=runner.content_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        changed_paths.extend(f for f in files if f)
    assert len(changed_paths) == len(set(changed_paths)), (
        f"a path was committed more than once across the campaign's history: {changed_paths}"
    )
    for relative in receipts:
        assert relative in changed_paths, f"receipted output never landed in any commit: {relative}"


@pytest.mark.parametrize(
    "crash_at",
    ["before_adoption", "before_commit", "before_commit_finalize"],
    ids=[
        "after-receipt-before-adoption",
        "after-adoption-before-commit-staging",
        "after-commit-staging-before-commit-finalize",
    ],
)
def test_supervisor_recovers_from_real_process_kill(tmp_path, crash_at):
    manifest_path, ledger_root, translator_repo = _build_campaign(tmp_path)
    heartbeat_path = tmp_path / "logs" / "supervisor.heartbeat"
    state_path = tmp_path / "logs" / "supervisor.state.json"
    adoption_marker = tmp_path / "adoption_calls.json"

    # --- Phase 1: a real child process is interrupted at the target boundary ----
    _run_child_and_crash(
        crash_at=crash_at,
        manifest_path=manifest_path,
        ledger_root=ledger_root,
        translator_repo=translator_repo,
        heartbeat_path=heartbeat_path,
        state_path=state_path,
        adoption_marker=adoption_marker,
        tmp_path=tmp_path,
    )

    interrupted_runner = _load_runner(manifest_path, ledger_root, translator_repo)
    # Exactly the first shard's (es) receipt survived -- durably fsynced before the
    # crash point in every scenario -- and nothing has been committed yet.
    receipts_after_crash = interrupted_runner._validated_resume_receipts()
    assert set(receipts_after_crash) == {"content/docs.aspose.org/es/words/net/page.md"}
    log_after_crash = subprocess.run(
        ["git", "log", "--pretty=%s"],
        cwd=interrupted_runner.content_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert log_after_crash == ["baseline"], "no commit must exist before recovery runs"
    # Use the same dirty-path helper CampaignSupervisor/_commit_verified_outputs use
    # (git status --porcelain=v1 -z --untracked-files=all): a plain `git status
    # --porcelain` collapses a brand-new untracked directory into just its directory
    # entry, which would make this assertion pass or fail for the wrong reason.
    dirty_after_crash = set(git_dirty_paths(interrupted_runner.content_repo))
    assert "content/docs.aspose.org/es/words/net/page.md" in dirty_after_crash

    if crash_at == "before_commit_finalize":
        # The distinguishing evidence for this specific boundary: git itself shows
        # the file as staged (index differs from HEAD for it), proving `git add`
        # really ran in the crashed child before it died.
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=interrupted_runner.content_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        assert staged == ["content/docs.aspose.org/es/words/net/page.md"]

    # --- Phase 2: a fresh, real, non-crashing CampaignSupervisor recovers --------
    def _fake_run_shard_jobs(shard_id: str) -> None:
        shards = {
            str(shard["shard_id"]): shard
            for shard in interrupted_runner.manifest.shards(
                resume_receipts=set(interrupted_runner._validated_resume_receipts()),
                max_outputs=1,
            )
        }
        shard = shards[shard_id]
        source = interrupted_runner.manifest.sources[0]
        for _source, locale, expected_output in shard["jobs"]:
            output = interrupted_runner.content_repo / expected_output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"accepted {locale} content", encoding="utf-8")
            interrupted_runner.ledger.append_receipt(
                {
                    "campaign_id": interrupted_runner.manifest.campaign_id,
                    "source_path": source.source_path,
                    "output_path": expected_output,
                    "source_sha256": source.source_sha256,
                    "output_sha256": sha256_file(output),
                    "target_lang": locale,
                    "validation_policy": "zero-defect",
                    "config_fingerprint": interrupted_runner.manifest.config_fingerprint,
                    "model_fingerprint": "fixture",
                    "gate_results": {str(i): {"passed": True} for i in range(1, 45)},
                }
            )

    recovery_adopted: list[str] = []

    def _recovery_adoption_check(shard_id: str):
        recovery_adopted.append(shard_id)
        return {"adopted": [shard_id]}

    recovery_supervisor = CampaignSupervisor(
        runner=interrupted_runner,
        heartbeat_path=heartbeat_path,
        state_path=state_path,
        adoption_check=_recovery_adoption_check,
        run_shard_jobs=_fake_run_shard_jobs,
    )
    result = recovery_supervisor.run()

    assert result["accepted"] == 2
    assert result["lifecycle"] == "DONE"
    # The interrupted shard (es) is committed by recovery, and the untouched
    # second shard (fr) still runs normally afterward -- real multi-shard
    # progression survives an interruption of the first shard.
    assert "es" in " ".join(recovery_adopted) or any(
        "es" in shard_id for shard_id in recovery_adopted
    )
    _assert_clean_final_state(interrupted_runner, expected_commits=3)

    # --- Phase 3: idempotency -- invoking the supervisor again is a clean no-op ---
    idle_runner = _load_runner(manifest_path, ledger_root, translator_repo)
    idle_supervisor = CampaignSupervisor(
        runner=idle_runner,
        heartbeat_path=heartbeat_path,
        state_path=state_path,
        adoption_check=lambda shard_id: None,
        run_shard_jobs=lambda shard_id: pytest.fail("no shard work should remain"),
    )
    idle_result = idle_supervisor.run()
    assert idle_result == {
        "campaign_id": "pilot",
        "accepted": 2,
        "last_commit_sha": None,
        "lifecycle": "DONE",
    }
    _assert_clean_final_state(idle_runner, expected_commits=3)
