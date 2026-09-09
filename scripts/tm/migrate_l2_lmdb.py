"""Safely consolidate legacy ``l2_lmdb`` into canonical ``l2.lmdb``.

The utility copies individual source-only keys, never copies LMDB files,
never overwrites canonical values, and never deletes the legacy store.
Run ``--dry-run``, stop workers, run ``--apply``, then ``--verify``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.tm.environment_lease import maintenance
from src.tm.l2_persistent import L2_DB_NAME, LINEAGE_DB_NAME, TranslationEntry

try:
    import lmdb
except ImportError:  # pragma: no cover
    print("ERROR: lmdb not installed", file=sys.stderr)
    sys.exit(1)


DEFAULT_WORKER_PID_FILES = (
    Path("data/logs/content_worker_daemon.pid"),
    Path("data/logs/tm_worker_daemon.pid"),
)


@dataclass(frozen=True)
class MigrationReport:
    source_entries: int
    destination_entries_before: int
    destination_entries_after: int
    source_only_keys: int
    collisions: int
    missing_source_keys: int
    backup_path: str | None = None
    invalid_entries: int = 0
    missing_lineage: int = 0


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _pid_is_running(pid: int) -> bool:
    # os.kill(pid, 0) can terminate the target on Windows. psutil is an
    # existing runtime dependency and implements a read-only process probe.
    return pid > 0 and psutil.pid_exists(pid)


def active_workers(pid_files: tuple[Path, ...]) -> list[Path]:
    """Fail closed for malformed PID files; check live PIDs without signals."""
    active: list[Path] = []
    for pid_file in pid_files:
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"unreadable worker PID file: {pid_file}") from exc
        if _pid_is_running(pid):
            active.append(pid_file)
    return active


def _open_readonly(path: Path):
    return lmdb.open(str(path), readonly=True, create=False, max_dbs=4)


def _entry(raw: bytes) -> TranslationEntry:
    entry = TranslationEntry.from_dict(json.loads(raw.decode("utf-8")))
    if not entry.is_valid():
        raise ValueError("invalid translation entry")
    return entry


def _count_merge(src_path: Path, dst_path: Path) -> tuple[int, int, int, int]:
    """Return source entries, destination entries, source-only keys and collisions."""
    src_env = _open_readonly(src_path)
    try:
        dst_env = _open_readonly(dst_path)
        try:
            source_entries = source_only = collisions = 0
            with src_env.begin() as src_txn, dst_env.begin() as dst_txn:
                destination_entries = sum(key != LINEAGE_DB_NAME for key, _ in dst_txn.cursor())
                for key, _ in src_txn.cursor():
                    if key == LINEAGE_DB_NAME:
                        continue
                    source_entries += 1
                    if dst_txn.get(key) is None:
                        source_only += 1
                    else:
                        collisions += 1
            return source_entries, destination_entries, source_only, collisions
        finally:
            dst_env.close()
    finally:
        src_env.close()


def _backup_destination(dst_path: Path, backup_root: Path | None) -> Path:
    root = backup_root or dst_path.parent / "migration-backups"
    if root.resolve().is_relative_to(dst_path.resolve()):
        raise ValueError("backup must be outside the destination environment")
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = root / f"{dst_path.name}.pre-migration-{stamp}"
    number = 1
    while backup.exists():
        number += 1
        backup = root / f"{dst_path.name}.pre-migration-{stamp}-{number}"
    backup.mkdir()
    env = _open_readonly(dst_path)
    try:
        # LMDB's snapshot API includes named databases consistently.
        env.copy(str(backup), compact=True)
    finally:
        env.close()
    return backup


def migrate(
    src_path: Path,
    dst_path: Path,
    dry_run: bool = False,
    *,
    worker_pid_files: tuple[Path, ...] | None = None,
    backup_root: Path | None = None,
) -> MigrationReport:
    """Copy source-only keys and verify every source key is readable afterward."""
    if dry_run:
        return _migrate(src_path, dst_path, dry_run=True)
    with maintenance([src_path, dst_path]):
        return _migrate(
            src_path, dst_path, worker_pid_files=worker_pid_files, backup_root=backup_root
        )


def _migrate(src_path, dst_path, dry_run=False, *, worker_pid_files=None, backup_root=None):
    src_path, dst_path = Path(src_path).resolve(), Path(dst_path).resolve()
    if src_path == dst_path or src_path in dst_path.parents or dst_path in src_path.parents:
        raise ValueError("source and destination must be separate, non-nested environments")
    if not src_path.is_dir():
        raise FileNotFoundError(f"source LMDB does not exist: {src_path}")
    if not dst_path.is_dir():
        raise FileNotFoundError(f"canonical LMDB does not exist: {dst_path}")
    if not dry_run:
        pid_files = tuple(repository_root() / p for p in DEFAULT_WORKER_PID_FILES)
        active = active_workers(pid_files + tuple(worker_pid_files or ()))
        if active:
            raise RuntimeError(
                "refusing apply while worker PID file(s) are live: " + ", ".join(map(str, active))
            )

        # One-shot workers need not have daemon PID files. Refuse recognized
        # writers too; repeat after backup immediately before the transaction.
        _refuse_writer_processes()

    source_entries, destination_before, source_only, collisions = _count_merge(src_path, dst_path)
    invalid, _ = _integrity(src_path)
    dst_invalid, _ = _integrity(dst_path)
    if not dry_run and invalid + dst_invalid:
        raise ValueError("invalid translation entries; apply refused before backup")
    backup: Path | None = None
    if not dry_run:
        backup = _backup_destination(dst_path, backup_root)
        _refuse_writer_processes()
        src_env = _open_readonly(src_path)
        try:
            dst_env = lmdb.open(str(dst_path), map_size=0, max_dbs=4)
            try:
                with src_env.begin() as src_txn, dst_env.begin(write=True) as dst_txn:
                    lineage = dst_env.open_db(LINEAGE_DB_NAME, txn=dst_txn, dupsort=True)
                    for key, value in src_txn.cursor():
                        if key != LINEAGE_DB_NAME and dst_txn.get(key) is None:
                            dst_txn.put(key, value)
                    # Rebuild from authoritative destination values: legacy
                    # collision lineage must never replace canonical lineage.
                    dst_txn.drop(lineage, delete=False)
                    for key, value in dst_txn.cursor():
                        if key == LINEAGE_DB_NAME:
                            continue
                        entry = _entry(value)
                        if entry.config_fingerprint:
                            dst_txn.put(
                                entry.config_fingerprint.encode(), key, db=lineage, dupdata=True
                            )
            finally:
                dst_env.close()
        finally:
            src_env.close()

    source_entries, destination_after, missing, collisions_after = _count_merge(src_path, dst_path)
    dst_invalid, missing_lineage = _integrity(dst_path)
    return MigrationReport(
        source_entries=source_entries,
        destination_entries_before=destination_before,
        destination_entries_after=destination_after,
        source_only_keys=source_only if dry_run else missing,
        collisions=collisions if dry_run else collisions_after,
        missing_source_keys=missing,
        backup_path=str(backup) if backup else None,
        invalid_entries=invalid + dst_invalid,
        missing_lineage=missing_lineage,
    )


def _refuse_writer_processes() -> None:
    tokens = (
        "autonomous_content_translation_worker",
        "tm_improvement_worker",
        "src.cli",
        "l3_rebuild",
    )
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if not (process.info["name"] or "").lower().startswith("python"):
                continue
            command = " ".join(process.info["cmdline"] or [])
            if any(token in command for token in tokens):
                raise RuntimeError(
                    f"active TM writer process {process.pid}; stop workers before apply"
                )
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise RuntimeError("cannot inspect possible writer process") from exc


def _integrity(path: Path) -> tuple[int, int]:
    invalid = missing = 0
    env = _open_readonly(path)
    try:
        try:
            lineage = env.open_db(LINEAGE_DB_NAME, create=False)
        except lmdb.NotFoundError:
            lineage = None
        with env.begin() as txn:
            for key, raw in txn.cursor():
                if key == LINEAGE_DB_NAME:
                    continue
                try:
                    entry = _entry(raw)
                except (ValueError, TypeError, UnicodeError):
                    invalid += 1
                    continue
                if entry.config_fingerprint:
                    if lineage is None or not txn.cursor(lineage).set_key_dup(
                        entry.config_fingerprint.encode(), key
                    ):
                        missing += 1
        return invalid, missing
    finally:
        env.close()


def verify(src_path: Path, dst_path: Path) -> MigrationReport:
    return migrate(src_path, dst_path, dry_run=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--src", default="data/tm/l2_lmdb")
    parser.add_argument("--dst", default=f"data/tm/{L2_DB_NAME}")
    parser.add_argument("--backup-root", default=None)
    parser.add_argument("--worker-pid-file", action="append", default=None)
    args = parser.parse_args(argv)
    root = repository_root()
    src, dst = (root / args.src).resolve(), (root / args.dst).resolve()
    backup_root = (root / args.backup_root).resolve() if args.backup_root else None
    pid_files = (
        tuple((root / value).resolve() for value in args.worker_pid_file)
        if args.worker_pid_file is not None
        else tuple((root / value).resolve() for value in DEFAULT_WORKER_PID_FILES)
    )
    try:
        report = (
            verify(src, dst)
            if args.verify
            else migrate(
                src, dst, dry_run=args.dry_run, worker_pid_files=pid_files, backup_root=backup_root
            )
        )
    except (OSError, ValueError, RuntimeError, lmdb.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), sort_keys=True))
    failed = report.missing_source_keys or report.invalid_entries or report.missing_lineage
    return 1 if (args.verify or args.apply) and failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
