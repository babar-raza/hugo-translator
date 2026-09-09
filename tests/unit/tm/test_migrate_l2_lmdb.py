"""Offline, real-LMDB coverage for the legacy L2 consolidation utility."""

from __future__ import annotations

import importlib.util
import os
import sys
import json
import subprocess
from pathlib import Path

import lmdb
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "tm" / "migrate_l2_lmdb.py"
SPEC = importlib.util.spec_from_file_location("migrate_l2_lmdb", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = migration
SPEC.loader.exec_module(migration)


def _environment(path: Path, values: dict[bytes, bytes]) -> None:
    env = lmdb.open(str(path), map_size=4 * 1024 * 1024)
    try:
        with env.begin(write=True) as txn:
            for key, value in values.items():
                txn.put(
                    key,
                    json.dumps(
                        {
                            "source_text": key.decode(),
                            "translation": value.decode(),
                            "site_id": "docs.aspose.org",
                            "src_lang": "en",
                            "tgt_lang": "de",
                            "config_fingerprint": "fixture-fp",
                        }
                    ).encode(),
                )
    finally:
        env.close()


def _read(path: Path, key: bytes) -> bytes | None:
    env = lmdb.open(str(path), readonly=True, lock=False)
    try:
        with env.begin() as txn:
            raw = txn.get(key)
            return json.loads(raw)["translation"].encode() if raw else None
    finally:
        env.close()


def test_dry_run_reports_disjoint_and_collision_keys(tmp_path):
    src, dst = tmp_path / "l2_lmdb", tmp_path / "l2.lmdb"
    _environment(src, {b"legacy": b"legacy", b"shared": b"old"})
    _environment(dst, {b"canonical": b"canonical", b"shared": b"new"})
    report = migration.migrate(src, dst, dry_run=True)
    assert (report.source_only_keys, report.collisions, report.missing_source_keys) == (1, 1, 1)
    assert _read(dst, b"legacy") is None


def test_apply_backs_up_merges_and_is_idempotent(tmp_path):
    src, dst = tmp_path / "l2_lmdb", tmp_path / "l2.lmdb"
    _environment(src, {b"legacy": b"legacy", b"shared": b"old"})
    _environment(dst, {b"canonical": b"canonical", b"shared": b"new"})
    report = migration.migrate(src, dst, worker_pid_files=())
    assert report.missing_source_keys == 0
    assert report.backup_path and Path(report.backup_path).is_dir()
    assert _read(dst, b"legacy") == b"legacy"
    assert _read(dst, b"shared") == b"new"
    assert migration.migrate(src, dst, worker_pid_files=()).missing_source_keys == 0


def test_apply_refuses_live_worker_pid(tmp_path):
    src, dst = tmp_path / "l2_lmdb", tmp_path / "l2.lmdb"
    _environment(src, {b"legacy": b"legacy"})
    _environment(dst, {})
    pid_file = tmp_path / "worker.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing apply"):
        migration.migrate(src, dst, worker_pid_files=(pid_file,))
    assert _read(dst, b"legacy") is None


def test_verify_reports_missing_legacy_key(tmp_path):
    src, dst = tmp_path / "l2_lmdb", tmp_path / "l2.lmdb"
    _environment(src, {b"legacy": b"legacy"})
    _environment(dst, {})
    assert migration.verify(src, dst).missing_source_keys == 1


def test_named_index_is_not_a_translation_and_lineage_is_rebuilt(tmp_path):
    src, dst = tmp_path / "legacy", tmp_path / "canonical"
    _environment(src, {b"legacy": b"alt"})
    _environment(dst, {b"canonical": b"neu"})
    env = lmdb.open(str(src), max_dbs=4)
    env.open_db(migration.LINEAGE_DB_NAME, dupsort=True)
    env.close()
    assert migration.verify(src, dst).source_entries == 1
    report = migration.migrate(src, dst)
    assert report.missing_lineage == 0
    assert report.invalid_entries == 0
    env = lmdb.open(str(dst), readonly=True, max_dbs=4)
    try:
        db = env.open_db(migration.LINEAGE_DB_NAME, create=False)
        with env.begin() as txn:
            assert txn.cursor(db).set_key_dup(b"fixture-fp", b"legacy")
    finally:
        env.close()


def test_failed_transaction_rolls_back_and_retains_backup(tmp_path, monkeypatch):
    src, dst = tmp_path / "legacy", tmp_path / "canonical"
    _environment(src, {b"legacy": b"alt"})
    _environment(dst, {b"canonical": b"neu"})
    real_entry = migration._entry
    calls = 0

    def fail_during_rebuild(raw):
        nonlocal calls
        calls += 1
        if calls > 2:
            raise RuntimeError("injected interruption")
        return real_entry(raw)

    monkeypatch.setattr(migration, "_entry", fail_during_rebuild)
    with pytest.raises(RuntimeError, match="interruption"):
        migration.migrate(src, dst)
    assert _read(dst, b"legacy") is None
    backups = list((tmp_path / "migration-backups").iterdir())
    assert len(backups) == 1
    assert _read(backups[0], b"canonical") == b"neu"
    monkeypatch.setattr(migration, "_entry", real_entry)
    assert migration.migrate(src, dst).missing_source_keys == 0


def test_pid_probe_is_readonly_in_child_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.tm.migrate_l2_lmdb import _pid_is_running; import os; assert _pid_is_running(os.getpid()); print('alive')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "alive"


def test_invalid_entry_refuses_apply_without_backup(tmp_path):
    src, dst = tmp_path / "legacy", tmp_path / "canonical"
    _environment(src, {})
    _environment(dst, {})
    env = lmdb.open(str(src))
    with env.begin(write=True) as txn:
        txn.put(b"bad", b"not-json")
    env.close()
    with pytest.raises(ValueError, match="invalid translation"):
        migration.migrate(src, dst)
    assert not (tmp_path / "migration-backups").exists()


def test_maintenance_excludes_active_and_new_openers(tmp_path):
    from src.tm.environment_lease import EnvironmentBusy, EnvironmentLease, maintenance

    env = tmp_path / "canonical"
    lease = EnvironmentLease(env)
    try:
        with pytest.raises(EnvironmentBusy):
            with maintenance([env]):
                pytest.fail("maintenance acquired an active store")
    finally:
        lease.close()
    with maintenance([env]):
        with pytest.raises(EnvironmentBusy):
            EnvironmentLease(env)
    EnvironmentLease(env).close()
