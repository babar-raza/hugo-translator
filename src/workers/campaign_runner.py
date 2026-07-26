"""Resumable, manifest-scoped zero-defect campaign execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from src.utils.atomic_write import atomic_write
from src.utils.file_lock import FileLock

from .campaign_manifest import (
    CampaignManifest,
    CampaignManifestError,
    git_dirty_paths,
    legacy_integer_gate_receipt_fingerprint,
    receipt_fingerprint,
    sha256_file,
)


class CampaignLedger:
    """Thread-safe metadata-only acceptance and rejection ledger."""

    def __init__(self, root: Path, campaign_id: str) -> None:
        self.root = root / campaign_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.receipts_path = self.root / "acceptance_receipts.jsonl"
        self.failures_path = self.root / "failure_metadata.jsonl"
        self.summary_path = self.root / "summary.json"
        self._lock = threading.Lock()
        self._receipt_index = self.receipts()

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def receipts(self) -> dict[str, dict[str, Any]]:
        return {row["output_path"]: row for row in self._read_jsonl(self.receipts_path)}

    def append_receipt(self, receipt: dict[str, Any]) -> None:
        if "content" in receipt or "translated_content" in receipt:
            raise ValueError("campaign receipts must never contain candidate text")
        row = {
            **receipt,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }
        row["receipt_sha256"] = receipt_fingerprint(row)
        output = str(row.get("output_path") or "")
        if not output:
            raise ValueError("campaign receipt requires output_path")
        with self._lock:
            previous = self._receipt_index.get(output)
            if previous is not None:
                comparable_previous = {
                    key: value
                    for key, value in previous.items()
                    if key not in {"accepted_at", "receipt_sha256"}
                }
                comparable_row = {
                    key: value
                    for key, value in row.items()
                    if key not in {"accepted_at", "receipt_sha256"}
                }
                if comparable_previous != comparable_row:
                    raise ValueError(f"conflicting acceptance receipt: {output}")
                return
            self._append_unlocked(self.receipts_path, row)
            self._receipt_index[output] = row

    def append_failure(
        self,
        *,
        source_path: str,
        output_path: str,
        target_lang: str,
        error: str,
        attempt: int = 0,
        job_id: str | None = None,
        gate: str = "pipeline",
        source_sha256: str | None = None,
        candidate_sha256: str | None = None,
    ) -> None:
        self._append(
            self.failures_path,
            {
                "source_path": source_path,
                "output_path": output_path,
                "target_lang": target_lang,
                "job_id": job_id or f"{source_path}::{target_lang}::{output_path}",
                "gate": gate,
                "reason": error[:1000],
                "attempt": attempt,
                "source_sha256": source_sha256,
                "candidate_sha256": candidate_sha256,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def latest_failure(self, *, output_path: str, target_lang: str) -> dict[str, Any] | None:
        """Return the latest metadata-only failure for a resumable job."""
        if not self.failures_path.is_file():
            return None
        latest = None
        with self.failures_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("output_path") == output_path and row.get("target_lang") == target_lang:
                    latest = row
        return latest

    def replace_receipts(self, receipts: list[dict[str, Any]]) -> None:
        """Atomically replace metadata-only receipts after verified migration."""
        if any(
            "content" in row or "translated_content" in row
            for row in receipts
        ):
            raise ValueError("campaign receipts must never contain candidate text")
        encoded = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in receipts
        )
        with self._lock:
            atomic_write(
                path=self.receipts_path,
                content=encoded,
                encoding="utf-8",
                fsync=True,
                create_parents=True,
            )
            self._receipt_index = {str(row["output_path"]): row for row in receipts}

    def _append(self, path: Path, row: dict[str, Any]) -> None:
        with self._lock:
            self._append_unlocked(path, row)

    @staticmethod
    def _append_unlocked(path: Path, row: dict[str, Any]) -> None:
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

    def write_summary(self, payload: dict[str, Any]) -> None:
        atomic_write(
            path=self.summary_path,
            content=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
            fsync=True,
            create_parents=True,
        )


class CampaignRunner:
    """Execute only jobs enumerated by a pinned CampaignManifest."""

    _LOCALE_NAMES = {
        "ar": "Arabic",
        "cs": "Czech",
        "de": "German",
        "el": "Greek",
        "es": "Spanish",
        "fa": "Persian",
        "fr": "French",
        "he": "Hebrew",
        "hi": "Hindi",
        "hu": "Hungarian",
        "id": "Indonesian",
        "it": "Italian",
        "ja": "Japanese",
        "ko": "Korean",
        "nl": "Dutch",
        "pl": "Polish",
        "pt": "Portuguese",
        "ro": "Romanian",
        "ru": "Russian",
        "sv": "Swedish",
        "th": "Thai",
        "tr": "Turkish",
        "uk": "Ukrainian",
        "vi": "Vietnamese",
        "zh": "Chinese",
    }
    _LOCALE_SCRIPT_HINTS = {
        "ar": "Arabic script",
        "el": "Greek script",
        "fa": "Persian script",
        "he": "Hebrew script",
        "hi": "Devanagari script",
        "ja": "Japanese script",
        "ko": "Hangul",
        "ru": "Cyrillic script",
        "th": "Thai script",
        "uk": "Cyrillic script",
        "zh": "Chinese Han characters",
    }
    _LOCALE_RETRY_HINTS = {
        "nl": (
            "For a short Dutch technical title, translate the source phrase "
            "'Deep Dive' idiomatically as 'Een grondige analyse van'. "
            "Do not use an English or Afrikaans-like literal calque."
        ),
    }

    def __init__(
        self,
        *,
        manifest: CampaignManifest,
        translation_engine,
        translator_repo: Path,
        ledger_root: Path = Path("data/campaigns"),
    ) -> None:
        self.manifest = manifest
        self.engine = translation_engine
        self.translator_repo = translator_repo.resolve()
        self.content_repo = Path(manifest.content_repo).resolve()
        self.ledger = CampaignLedger(ledger_root, manifest.campaign_id)

    def _validated_resume_receipts(self) -> dict[str, dict[str, Any]]:
        receipts = self.ledger.receipts()
        valid: dict[str, dict[str, Any]] = {}
        receipt_migrations: dict[str, dict[str, Any]] = {}
        expected_outputs = {
            output: (source, locale)
            for source in self.manifest.sources
            for locale, output in source.outputs.items()
        }
        for output, receipt in receipts.items():
            if output not in expected_outputs:
                raise CampaignManifestError(f"receipt outside campaign scope: {output}")
            source, locale = expected_outputs[output]
            claimed_fingerprint = receipt.get("receipt_sha256")
            unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            if not claimed_fingerprint or receipt_fingerprint(unsigned) != claimed_fingerprint:
                if (
                    claimed_fingerprint
                    and legacy_integer_gate_receipt_fingerprint(unsigned) == claimed_fingerprint
                ):
                    migrated = dict(unsigned)
                    migrated["receipt_sha256"] = receipt_fingerprint(unsigned)
                    receipt_migrations[output] = migrated
                else:
                    raise CampaignManifestError(
                        f"acceptance receipt fingerprint mismatch: {output}"
                    )
            expected_context = {
                "campaign_id": self.manifest.campaign_id,
                "source_path": source.source_path,
                "output_path": output,
                "source_sha256": source.source_sha256,
                "target_lang": locale,
                "validation_policy": "zero-defect",
                "config_fingerprint": self.manifest.config_fingerprint,
            }
            for field_name, expected_value in expected_context.items():
                current_receipt = receipt_migrations.get(output, receipt)
                if current_receipt.get(field_name) != expected_value:
                    source_path = self.content_repo / source.source_path
                    legacy_normalized_source_sha = hashlib.sha256(
                        source_path.read_text(encoding="utf-8").encode("utf-8")
                    ).hexdigest()
                    if (
                        field_name == "source_sha256"
                        and current_receipt.get(field_name) == legacy_normalized_source_sha
                    ):
                        migrated = {
                            key: value
                            for key, value in current_receipt.items()
                            if key != "receipt_sha256"
                        }
                        migrated[field_name] = expected_value
                        migrated["receipt_sha256"] = receipt_fingerprint(migrated)
                        receipt_migrations[output] = migrated
                        continue
                    raise CampaignManifestError(f"receipt {field_name} mismatch for {output}")
            output_path = self.content_repo / output
            if not output_path.is_file():
                raise CampaignManifestError(f"receipt output missing: {output}")
            if sha256_file(output_path) != receipt.get("output_sha256"):
                raise CampaignManifestError(f"receipt/output hash mismatch: {output}")
            gates = receipt.get("gate_results") or {}
            if len(gates) != 44 or any(not item.get("passed", False) for item in gates.values()):
                raise CampaignManifestError(f"receipt is not all-pass: {output}")
            valid[output] = receipt_migrations.get(output, receipt)
        if receipt_migrations:
            self.ledger.replace_receipts(
                [receipt_migrations.get(output, receipt) for output, receipt in receipts.items()]
            )
        return valid

    def _append_campaign_receipt(self, receipt: dict[str, Any]) -> None:
        normalized = dict(receipt)
        for field_name in ("source_path", "output_path"):
            absolute = Path(normalized[field_name]).resolve()
            try:
                normalized[field_name] = absolute.relative_to(self.content_repo).as_posix()
            except ValueError as exc:
                raise CampaignManifestError(
                    f"receipt {field_name} is outside content repo: {absolute}"
                ) from exc
        self.ledger.append_receipt(normalized)

    def _receipt_recovery_candidates(
        self,
    ) -> list[tuple[Any, str, str, str]]:
        """Return manifest outputs backed by immutable governed add commits.

        Each candidate must be the sole path added by its latest path commit,
        that commit must be after the pinned content baseline and reachable
        from the current branch, and the current bytes must equal the commit
        blob.  This deliberately excludes arbitrary pre-existing files.
        """
        candidates: list[tuple[Any, str, str, str]] = []
        for source in self.manifest.sources:
            for locale, relative in source.outputs.items():
                output_path = self.content_repo / relative
                if not output_path.exists():
                    continue
                if not output_path.is_file():
                    raise CampaignManifestError(
                        f"receipt recovery output is not a file: {relative}"
                    )
                log = subprocess.run(
                    ["git", "log", "-1", "--format=%H%x00%s", "--", relative],
                    cwd=self.content_repo,
                    check=True,
                    capture_output=True,
                ).stdout.decode("utf-8", errors="strict").strip()
                if "\0" not in log:
                    raise CampaignManifestError(
                        f"receipt recovery path has no commit provenance: {relative}"
                    )
                commit_sha, subject = log.split("\0", 1)
                shard_prefix = (
                    f"w{source.wave}:{source.site_id}:{source.family}:"
                    f"{source.platform}:{locale}:"
                )
                expected_subject = re.compile(
                    rf"^content\(locale\): zero-defect shard "
                    rf"{re.escape(shard_prefix)}[1-9][0-9]*$"
                )
                if not expected_subject.fullmatch(subject):
                    raise CampaignManifestError(
                        f"receipt recovery commit is not governed: {relative}"
                    )
                if not subprocess.run(
                    [
                        "git",
                        "merge-base",
                        "--is-ancestor",
                        self.manifest.content_repo_sha,
                        commit_sha,
                    ],
                    cwd=self.content_repo,
                    capture_output=True,
                ).returncode == 0:
                    raise CampaignManifestError(
                        f"receipt recovery commit predates pinned baseline: {relative}"
                    )
                if not subprocess.run(
                    ["git", "merge-base", "--is-ancestor", commit_sha, "HEAD"],
                    cwd=self.content_repo,
                    capture_output=True,
                ).returncode == 0:
                    raise CampaignManifestError(
                        f"receipt recovery commit is not reachable: {relative}"
                    )
                changed = subprocess.run(
                    [
                        "git",
                        "diff-tree",
                        "--no-commit-id",
                        "--name-status",
                        "-r",
                        commit_sha,
                    ],
                    cwd=self.content_repo,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
                if changed != [f"A\t{relative}"]:
                    raise CampaignManifestError(
                        f"receipt recovery requires a one-file add commit: {relative}"
                    )
                committed_bytes = subprocess.run(
                    ["git", "show", f"{commit_sha}:{relative}"],
                    cwd=self.content_repo,
                    check=True,
                    capture_output=True,
                ).stdout
                if hashlib.sha256(committed_bytes).hexdigest() != sha256_file(output_path):
                    raise CampaignManifestError(
                        f"receipt recovery blob drift: {relative}"
                    )
                candidates.append((source, locale, relative, commit_sha))
        return sorted(candidates, key=lambda item: item[2])

    def recover_committed_receipts(self) -> dict[str, Any]:
        """Recover lost receipts by revalidating governed committed bytes.

        This is not an acceptance shortcut: all candidate bytes are kept in
        memory and independently rerun through validation, verification,
        fidelity, all 44 gates, and placement.  Each all-pass metadata-only
        receipt is fsynced independently so an outage or later bad candidate
        cannot erase completed revalidation work; a resumed recovery validates
        existing receipt hashes before skipping them.
        """
        with FileLock(self.ledger.root / "campaign.lock", timeout=0):
            candidates = self._receipt_recovery_candidates()
            if not candidates:
                raise CampaignManifestError(
                    "receipt recovery found no governed committed outputs"
                )
            existing_expected = {
                output
                for source in self.manifest.sources
                for output in source.outputs.values()
                if (self.content_repo / output).exists()
            }
            recovered_outputs = {item[2] for item in candidates}
            if recovered_outputs != existing_expected:
                raise CampaignManifestError(
                    "receipt recovery provenance does not cover every existing output"
                )
            existing_receipts = self._validated_resume_receipts()
            unexpected_receipts = set(existing_receipts) - recovered_outputs
            if unexpected_receipts:
                raise CampaignManifestError(
                    "receipt recovery ledger contains outputs without current "
                    "governed commit provenance"
                )

            self.manifest.verify_environment(
                translator_repo=self.translator_repo,
                require_clean=True,
                allow_existing_accepted=recovered_outputs,
            )
            self.engine.campaign_context.update(
                {
                    "campaign_id": self.manifest.campaign_id,
                    "config_fingerprint": self.manifest.config_fingerprint,
                }
            )

            for source, locale, relative, commit_sha in candidates:
                if relative in existing_receipts:
                    continue
                source_path = self.content_repo / source.source_path
                output_path = self.content_repo / relative
                try:
                    accepted = self.engine.accept_candidate_bytes(
                        source_bytes=source_path.read_bytes(),
                        candidate_bytes=output_path.read_bytes(),
                        source_path=source_path,
                        output_path=output_path,
                        target_lang=locale,
                        site_id=source.site_id,
                    )
                except Exception as exc:
                    raise CampaignManifestError(
                        f"receipt recovery validation failed for {relative}: {exc}"
                    ) from exc
                receipt = accepted.receipt()
                normalized = dict(receipt)
                for field_name in ("source_path", "output_path"):
                    normalized[field_name] = (
                        Path(normalized[field_name])
                        .resolve()
                        .relative_to(self.content_repo)
                        .as_posix()
                    )
                expected_context = {
                    "campaign_id": self.manifest.campaign_id,
                    "source_path": source.source_path,
                    "output_path": relative,
                    "source_sha256": source.source_sha256,
                    "target_lang": locale,
                    "validation_policy": "zero-defect",
                    "config_fingerprint": self.manifest.config_fingerprint,
                }
                if any(
                    normalized.get(field) != expected
                    for field, expected in expected_context.items()
                ):
                    raise CampaignManifestError(
                        f"revalidated receipt context mismatch: {relative}"
                    )
                normalized["receipt_recovery"] = {
                    "mode": "all-gates-byte-revalidation-v1",
                    "commit_sha": commit_sha,
                }
                self.ledger.append_receipt(normalized)
                existing_receipts[relative] = self.ledger.receipts()[relative]

            verified = self._validated_resume_receipts()
            if set(verified) != recovered_outputs:
                raise CampaignManifestError("recovered receipt reconciliation failed")
            summary = {
                **self.manifest.to_summary(),
                "status": "RECEIPTS_RECOVERED",
                "accepted": len(verified),
                "remaining": self.manifest.expected_output_count - len(verified),
            }
            self.ledger.write_summary(summary)
            return summary

    def _commit_verified_outputs(self, shard_id: str) -> str | None:
        """Commit only checksum-verified, receipted campaign outputs."""
        branch = self.manifest.commit_policy.get("branch")
        if not branch:
            return None
        if self.manifest.commit_policy.get("push", False):
            raise CampaignManifestError("campaign policy prohibits autonomous push")

        current_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if current_branch != branch:
            raise CampaignManifestError(
                f"content branch {current_branch!r} != campaign branch {branch!r}"
            )

        receipts = self.ledger.receipts()
        dirty = {Path(item).as_posix() for item in git_dirty_paths(self.content_repo)}
        allowed = set(receipts)
        unexpected = sorted(dirty - allowed)
        if unexpected:
            raise CampaignManifestError(
                f"dirty path outside accepted receipt scope: {unexpected[:10]}"
            )
        commit_paths = sorted(dirty & allowed)
        if not commit_paths:
            return None
        for relative in commit_paths:
            receipt = receipts[relative]
            output = self.content_repo / relative
            if not output.is_file() or sha256_file(output) != receipt.get("output_sha256"):
                raise CampaignManifestError(
                    f"refusing commit for checksum-invalid output: {relative}"
                )

        subprocess.run(
            ["git", "add", "--", *commit_paths],
            cwd=self.content_repo,
            check=True,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if {Path(item).as_posix() for item in staged} != set(commit_paths):
            raise CampaignManifestError("staged diff differs from accepted output set")
        run_id = self._create_governed_skill_run(shard_id, len(commit_paths))
        message = [f"content(locale): zero-defect shard {shard_id}"]
        if run_id:
            message.extend(
                [
                    "-m",
                    (
                        f"Accepted outputs: {len(commit_paths)}; every file has an "
                        "all-44-gates zero-defect receipt."
                    ),
                    "-m",
                    "Skills invoked: [S-HT-02]",
                    "-m",
                    "Co-authored-by: Codex <noreply@openai.com>",
                ]
            )
        try:
            subprocess.run(
                ["git", "commit", "-m", *message],
                cwd=self.content_repo,
                check=True,
            )
        except Exception:
            self._finalize_governed_skill_run(run_id, "failure")
            raise
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._finalize_governed_skill_run(run_id, "success", commit_sha)
        return commit_sha

    def _governance_command(self) -> list[str] | None:
        script = (
            self.content_repo / "scripts" / "pipeline" / "commands" / "ops" / "skill_run_manager.py"
        )
        if not script.is_file():
            return None
        candidates = [
            self.content_repo / ".venv" / "Scripts" / "python.exe",
            self.content_repo / ".venv" / "bin" / "python",
        ]
        python = next((path for path in candidates if path.is_file()), None)
        return [str(python or Path(sys.executable)), str(script)]

    def _create_governed_skill_run(self, shard_id: str, output_count: int) -> str | None:
        command = self._governance_command()
        if command is None:
            return None
        created = subprocess.run(
            [
                *command,
                "create",
                "--skills",
                "S-HT-02",
                "--plan",
                f"{self.manifest.campaign_id}:{shard_id}",
                "--run-type",
                "targeted",
            ],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        match = re.search(r"Created skill run record:\s*(\S+)", created.stdout)
        if not match:
            raise CampaignManifestError("governance tool did not return a skill run ID")
        run_id = match.group(1)
        subprocess.run(
            [
                *command,
                "record-step",
                "--run-id",
                run_id,
                "--skill",
                "S-HT-02",
                "--type",
                "full",
                "--steps",
                "managed-campaign",
                "--note",
                (f"Zero-defect campaign shard {shard_id}; {output_count} receipted outputs"),
            ],
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return run_id

    def _finalize_governed_skill_run(
        self,
        run_id: str | None,
        outcome: str,
        commit_sha: str | None = None,
    ) -> None:
        command = self._governance_command()
        if not run_id or command is None:
            return
        args = [
            *command,
            "finalize",
            "--run-id",
            run_id,
            "--outcome",
            outcome,
        ]
        if commit_sha:
            args.extend(["--commit-sha", commit_sha])
        subprocess.run(
            args,
            cwd=self.content_repo,
            check=True,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _failure_metadata(result: Any) -> tuple[str, str]:
        """Return rejection metadata without persisting candidate-derived text."""
        error_count = len(getattr(result, "errors", None) or [])
        retry_count = int(getattr(result, "retry_attempts", 0) or 0)
        validation_result = getattr(result, "validation_result", None)
        validators = sorted(
            {
                str(getattr(issue, "validator", "unknown"))
                for issue in getattr(validation_result, "issues", []) or []
                if str(
                    getattr(
                        getattr(issue, "severity", None), "value", getattr(issue, "severity", "")
                    )
                )
                in {"error", "warning"}
            }
        )
        verification_result = getattr(result, "verification_result", None)
        verification_checks = sorted(
            {
                re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    str(getattr(issue, "check_name", "unknown")),
                )
                or "unknown"
                for issue in getattr(verification_result, "issues", []) or []
                if str(getattr(issue, "severity", "")) in {"error", "warning"}
            }
        )
        raw_error = str(getattr(result, "error", "") or "")
        safe_codes = sorted(
            set(
                re.findall(
                    r"\b(?:GATE\d+|TC-[A-Z0-9-]+|" r"[A-Za-z][A-Za-z0-9_]*(?:Validator|Check))\b",
                    raw_error,
                )
            )
        )
        failed_gate_ids = sorted(
            int(gate_id)
            for gate_id, gate_result in (
                getattr(result, "rejection_gate_results", None) or {}
            ).items()
            if not bool(gate_result.get("passed", False))
        )
        safe_codes = sorted({*safe_codes, *(f"GATE{gate_id}" for gate_id in failed_gate_ids)})
        exception_classes = sorted(
            set(
                re.findall(
                    r"\b([A-Za-z][A-Za-z0-9_]*(?:Error|Exception|Incomplete)):",
                    raw_error,
                )
            )
        )
        score_match = re.search(r"\bscore=(\d+(?:\.\d+)?)\b", raw_error)
        verdict_match = re.search(r"\b(fail|warn|pass)\b", raw_error, re.IGNORECASE)
        unit_fingerprints = re.search(
            r"\bunit_fingerprints=([a-z0-9_:,-]+)\b",
            raw_error,
            re.IGNORECASE,
        )
        issue_fingerprints: list[str] = []
        for issue in getattr(validation_result, "issues", []) or []:
            severity = str(
                getattr(
                    getattr(issue, "severity", None),
                    "value",
                    getattr(issue, "severity", ""),
                )
            )
            if severity not in {"error", "warning"}:
                continue
            validator = (
                re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    str(getattr(issue, "validator", "unknown")),
                )
                or "unknown"
            )
            details = getattr(issue, "details", None) or {}
            if "ngram" in details:
                issue_kind = "ngram"
            elif "frequency" in details and "word" in details:
                issue_kind = "word_frequency"
            elif "sentence" in details:
                issue_kind = "sentence_duplication"
            elif "heading" in details:
                issue_kind = "heading_repetition"
            elif validator == "FrontmatterLanguageCheck":
                issue_kind = "frontmatter_language"
            else:
                issue_kind = "generic"
            location_hash = hashlib.sha256(
                str(getattr(issue, "location", "")).encode("utf-8")
            ).hexdigest()[:16]
            numeric_parts: list[str] = []
            for key in (
                "count",
                "threshold",
                "source_ngram_ceiling",
                "frequency",
                "source_word_freq_ceiling",
                "confidence",
                "letter_count",
                "latin_letter_ratio",
                "target_script_ratio",
            ):
                value = details.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                rendered = f"{value:.6g}" if isinstance(value, float) else str(value)
                numeric_parts.append(f"{key}={rendered}")
            categorical_parts: list[str] = []
            field = str(details.get("field", ""))
            if field in {"title", "description", "seoTitle", "summary"}:
                categorical_parts.append(f"field={field}")
            for key in ("detected_lang", "expected_lang"):
                value = str(details.get(key, "")).lower()
                if re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2})?", value):
                    categorical_parts.append(f"{key}={value}")
            payload_value = None
            for key in ("ngram", "word", "sentence", "heading"):
                value = details.get(key)
                if isinstance(value, str) and value:
                    payload_value = value
                    break
            payload_hash = (
                hashlib.sha256(payload_value.encode("utf-8")).hexdigest()[:16]
                if payload_value is not None
                else "none"
            )
            issue_fingerprints.append(
                ":".join(
                    [
                        validator,
                        severity,
                        issue_kind,
                        location_hash,
                        f"payload_sha256={payload_hash}",
                        *categorical_parts,
                        *(numeric_parts or ["numeric=none"]),
                    ]
                )
            )
        verification_fingerprints: list[str] = []
        for issue in getattr(verification_result, "issues", []) or []:
            severity = str(getattr(issue, "severity", ""))
            if severity not in {"error", "warning"}:
                continue
            check_name = (
                re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    str(getattr(issue, "check_name", "unknown")),
                )
                or "unknown"
            )
            location_hash = hashlib.sha256(
                str(getattr(issue, "location", "")).encode("utf-8")
            ).hexdigest()[:16]
            location = str(getattr(issue, "location", ""))
            field_match = re.fullmatch(
                r"frontmatter\.(title|description|seoTitle|summary)", location
            )
            metadata = getattr(issue, "metadata", None) or {}
            numeric_parts: list[str] = []
            for key, value in sorted(metadata.items()):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                safe_key = re.sub(r"[^A-Za-z0-9_-]", "", str(key)) or "metric"
                rendered = f"{value:.6g}" if isinstance(value, float) else str(value)
                numeric_parts.append(f"{safe_key}={rendered}")
            verification_fingerprints.append(
                ":".join(
                    [
                        check_name,
                        severity,
                        location_hash,
                        *([f"field={field_match.group(1)}"] if field_match else []),
                        *(numeric_parts or ["numeric=none"]),
                    ]
                )
            )
        gate = (
            validators[0]
            if validators
            else (
                f"verification:{verification_checks[0]}"
                if verification_checks
                else (safe_codes[0] if safe_codes else "pipeline")
            )
        )
        validator_text = ",".join(validators) if validators else "unknown"
        reason = (
            f"translation_rejected; error_count={error_count}; "
            f"internal_retries={retry_count}; validators={validator_text}; "
            f"codes={','.join(safe_codes) if safe_codes else 'unknown'}; "
            f"exceptions="
            f"{','.join(exception_classes) if exception_classes else 'unknown'}; "
            f"verdict={verdict_match.group(1).lower() if verdict_match else 'unknown'}; "
            f"score={score_match.group(1) if score_match else 'unknown'}; "
            f"unit_fingerprints="
            f"{unit_fingerprints.group(1) if unit_fingerprints else 'none'}; "
            f"issue_fingerprints="
            f"{','.join(sorted(issue_fingerprints)) if issue_fingerprints else 'none'}; "
            f"verification_checks="
            f"{','.join(verification_checks) if verification_checks else 'none'}; "
            f"verification_fingerprints="
            f"{','.join(sorted(verification_fingerprints)) if verification_fingerprints else 'none'}; "
            f"error_sha256={hashlib.sha256(raw_error.encode('utf-8')).hexdigest()}"
        )
        return gate, reason

    @staticmethod
    def _frontmatter_source_guidance(
        source_path: Path | None, fields: list[str], target_lang: str
    ) -> str:
        """Build source-derived, candidate-free lexical retry boundaries."""
        if source_path is None or not source_path.is_file():
            return ""
        try:
            text = source_path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                return ""
            end = text.find("---", 3)
            if end < 0:
                return ""
            frontmatter = yaml.safe_load(text[3:end]) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            return ""
        selected = fields or ["title", "description", "seoTitle", "summary"]
        source_text = " ".join(str(frontmatter.get(field) or "") for field in selected)
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.+#-]*", source_text)
        if not tokens:
            return ""
        known_protected = {
            "FOSS",
            "Rust",
            "Python",
            "Java",
            "Microsoft",
            "Office",
        }
        protected: list[str] = []
        ordinary: list[str] = []
        stopwords = {
            "a",
            "an",
            "and",
            "all",
            "for",
            "in",
            "of",
            "the",
            "to",
            "with",
            "without",
        }
        for token in tokens:
            is_identifier = (
                "." in token
                or token.isupper()
                or bool(re.search(r"[a-z][A-Z]", token))
                or token in known_protected
            )
            target = protected if is_identifier else ordinary
            if token not in target:
                target.append(token)
        substantive = [
            token for token in ordinary if token.casefold() not in stopwords and len(token) >= 4
        ][:40]
        field_text = ", ".join(selected)
        protected_text = ", ".join(protected) if protected else "none"
        substantive_text = ", ".join(substantive) if substantive else "all ordinary words"
        locale_label = CampaignRunner._target_locale_label(target_lang)
        return (
            f"For source field(s) {field_text}, preserve exactly only these source tokens: "
            f"{protected_text}. Translate every other English source token into {locale_label}, "
            f"including these ordinary technical terms: {substantive_text}."
        )

    @classmethod
    def _target_locale_label(cls, target_lang: str) -> str:
        """Return an explicit, governed language/script label for model feedback."""
        locale = target_lang.lower().split("-")[0]
        name = cls._LOCALE_NAMES.get(locale, target_lang)
        script = cls._LOCALE_SCRIPT_HINTS.get(locale)
        return f"{name} ({target_lang})" + (
            f", using {script} for all ordinary prose" if script else ""
        )

    @staticmethod
    def _sas_link_source_guidance(
        source_path: Path | None, raw_error: str, target_lang: str
    ) -> str:
        """Resolve hashed same-as-source link units to source-only lexical guidance."""
        if source_path is None or not source_path.is_file():
            return ""
        fingerprint_match = re.search(r"\bunit_fingerprints=([a-z0-9_:,-]+)\b", raw_error)
        if not fingerprint_match:
            return ""
        requested = {
            (digest, int(length))
            for digest, length in re.findall(
                r"(?:^|,)link_text:([a-f0-9]{16}):(\d+)",
                fingerprint_match.group(1),
            )
        }
        if not requested:
            return ""
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

        labels = re.findall(r"\[([^\]\r\n]+)\]\([^)]+\)", source_text)
        matched = [
            label
            for label in labels
            if (
                hashlib.sha256(label.encode("utf-8")).hexdigest()[:16],
                len(label),
            )
            in requested
        ]
        if not matched:
            return ""

        known_protected = {
            "FOSS",
            "Rust",
            "Python",
            "Java",
            "Microsoft",
            "Office",
        }
        protected: list[str] = []
        ordinary: list[str] = []
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+#-]*", " ".join(matched)):
            is_identifier = (
                "." in token
                or token.isupper()
                or bool(re.search(r"[a-z][A-Z]", token))
                or token in known_protected
            )
            target = protected if is_identifier else ordinary
            if token not in target:
                target.append(token)
        if not ordinary:
            return ""
        locale_label = CampaignRunner._target_locale_label(target_lang)
        return (
            "For the affected source link label(s), preserve exactly only these "
            f"identifier/product tokens: {', '.join(protected) if protected else 'none'}. "
            f"Translate all ordinary label words into {locale_label}, including: "
            f"{', '.join(ordinary)}. Do not preserve the complete English label as a title."
        )

    @staticmethod
    def _retry_feedback(
        result: Any,
        target_lang: str,
        prior_feedback: str | None = None,
        *,
        source_path: Path | None = None,
    ) -> str:
        """Build candidate-free instructions for the next governed attempt."""
        validation_result = getattr(result, "validation_result", None)
        issues = getattr(validation_result, "issues", []) or []
        validators = {str(getattr(issue, "validator", "")) for issue in issues}
        instructions: list[str] = []
        locale_label = CampaignRunner._target_locale_label(target_lang)
        locale_retry_hint = CampaignRunner._LOCALE_RETRY_HINTS.get(
            target_lang.lower().split("-")[0]
        )
        if "FrontmatterLanguageCheck" in validators:
            fields = sorted(
                {
                    str((getattr(issue, "details", None) or {}).get("field", ""))
                    for issue in issues
                    if str(getattr(issue, "validator", "")) == "FrontmatterLanguageCheck"
                    and str((getattr(issue, "details", None) or {}).get("field", ""))
                    in {"title", "description", "seoTitle", "summary"}
                }
            )
            field_text = ", ".join(fields) if fields else "unspecified"
            instructions.append(
                "Translate every translatable frontmatter field (title, description, "
                f"seoTitle, summary) fully into target locale {locale_label}; "
                f"the fields detected as failing were: {field_text}. "
                "preserve only product names, API identifiers, code, and file formats. "
                "Do not leave English prose."
            )
            source_guidance = CampaignRunner._frontmatter_source_guidance(
                source_path, fields, target_lang
            )
            if source_guidance:
                instructions.append(source_guidance)
        if "RepetitionDetectorValidator" in validators:
            instructions.append(
                "Avoid adding repeated phrases or duplicate sentences beyond the source structure."
            )
        raw_error = str(getattr(result, "error", "") or "")
        if "GATE36" in raw_error:
            instructions.append(
                "Preserve every source claim and section with no omission, reversal, or invented fact."
            )
        if "TC-SAS-01" in raw_error:
            instructions.append(
                "Translate every translatable source unit; identical output is allowed only for "
                "product names, API identifiers, and reviewed locale cognates."
            )
            source_guidance = CampaignRunner._sas_link_source_guidance(
                source_path, raw_error, target_lang
            )
            if source_guidance:
                instructions.append(source_guidance)
        verification_result = getattr(result, "verification_result", None)
        failed_checks = sorted(
            {
                str(getattr(issue, "check_name", "unknown"))
                for issue in getattr(verification_result, "issues", []) or []
                if str(getattr(issue, "severity", "")) in {"error", "warning"}
            }
        )
        if failed_checks:
            instructions.append(
                "Correct every post-translation verification issue from these checks: "
                f"{', '.join(failed_checks)}. Preserve source meaning and structure, "
                f"and render all ordinary prose in target locale {locale_label}."
            )
            verification_fields = sorted(
                {
                    match.group(1)
                    for issue in getattr(verification_result, "issues", []) or []
                    if str(getattr(issue, "check_name", "")) == "language_detection"
                    and (
                        match := re.fullmatch(
                            r"frontmatter\.(title|description|seoTitle|summary)",
                            str(getattr(issue, "location", "")),
                        )
                    )
                }
            )
            if verification_fields:
                instructions.append(
                    "Translate every ordinary-language word in the affected "
                    f"frontmatter field(s) {', '.join(verification_fields)} into "
                    f"target locale {locale_label}."
                )
                source_guidance = CampaignRunner._frontmatter_source_guidance(
                    source_path, verification_fields, target_lang
                )
                if source_guidance:
                    instructions.append(source_guidance)
            if locale_retry_hint and "language_detection" in failed_checks:
                instructions.append(locale_retry_hint)
        if not instructions and not prior_feedback:
            instructions.append(
                f"Regenerate the complete translation in target locale {locale_label} and correct "
                "all prior validation failures without changing structure, code, links, or shortcodes."
            )
        additions = " ".join(instructions)
        if not prior_feedback:
            return additions
        if not additions or additions in prior_feedback:
            return prior_feedback
        return f"{prior_feedback} {additions}"

    @classmethod
    def _retry_feedback_from_failure(
        cls,
        failure: dict[str, Any] | None,
        target_lang: str,
        *,
        source_path: Path | None = None,
    ) -> str | None:
        """Rehydrate safe retry guidance from metadata when resuming."""
        if not failure:
            return None
        reason = str(failure.get("reason") or "")
        gate = str(failure.get("gate") or "")
        validators: list[str] = []
        if gate == "FrontmatterLanguageCheck" or "FrontmatterLanguageCheck" in reason:
            validators.append("FrontmatterLanguageCheck")
        if "RepetitionDetectorValidator" in reason:
            validators.append("RepetitionDetectorValidator")
        fields = re.findall(r"\bfield=(title|description|seoTitle|summary)\b", reason)
        issues = [
            SimpleNamespace(
                validator=validator,
                details={"field": fields[0]} if fields else {},
            )
            for validator in validators
        ]
        verification_checks_match = re.search(r"\bverification_checks=([A-Za-z0-9_,-]+)\b", reason)
        verification_issues = [
            SimpleNamespace(
                check_name=check,
                severity="warning",
                location=(
                    f"frontmatter.{fields[0]}"
                    if check == "language_detection" and fields
                    else next(
                        (
                            f"frontmatter.{field}"
                            for field in ("title", "description", "seoTitle", "summary")
                            if re.search(
                                rf"{re.escape(check)}:(?:error|warning):"
                                rf"{hashlib.sha256(f'frontmatter.{field}'.encode()).hexdigest()[:16]}",
                                reason,
                            )
                        ),
                        "",
                    )
                ),
                metadata={},
            )
            for check in (
                verification_checks_match.group(1).split(",")
                if verification_checks_match and verification_checks_match.group(1) != "none"
                else []
            )
        ]
        return cls._retry_feedback(
            SimpleNamespace(
                validation_result=SimpleNamespace(issues=issues),
                verification_result=SimpleNamespace(issues=verification_issues),
                error=reason,
            ),
            target_lang,
            source_path=source_path,
        )

    def verify(self, *, resume: bool = False) -> dict[str, Any]:
        receipts = self._validated_resume_receipts() if resume else {}
        self.manifest.verify_environment(
            translator_repo=self.translator_repo,
            require_clean=True,
            allow_existing_accepted=set(receipts),
        )
        return {
            **self.manifest.to_summary(),
            "accepted": len(receipts),
            "remaining": self.manifest.expected_output_count - len(receipts),
        }

    def run(self, *, resume: bool = False, verify_only: bool = False) -> dict[str, Any]:
        with FileLock(self.ledger.root / "campaign.lock", timeout=0):
            return self._run_locked(resume=resume, verify_only=verify_only)

    def _run_locked(
        self,
        *,
        resume: bool = False,
        verify_only: bool = False,
    ) -> dict[str, Any]:
        summary = self.verify(resume=resume)
        if verify_only:
            self.ledger.write_summary({**summary, "status": "VERIFIED"})
            return summary

        receipts = self._validated_resume_receipts() if resume else {}
        self.engine.campaign_context.update(
            {
                "campaign_id": self.manifest.campaign_id,
                "config_fingerprint": self.manifest.config_fingerprint,
                "receipt_sink": self._append_campaign_receipt,
            }
        )

        accepted = len(receipts)
        failed = 0
        max_outputs = int(self.manifest.commit_policy.get("max_outputs_per_commit", 250))
        for shard in self.manifest.shards(
            resume_receipts=set(receipts),
            max_outputs=max_outputs,
        ):
            shard_accepted = 0
            shard_failed = 0
            for source, locale, expected_output in shard["jobs"]:
                source_path = self.content_repo / source.source_path
                profile = self.engine.config.get_site_profile(source.site_id)
                calculated = self.engine._get_output_path(source_path, locale, profile)
                expected = self.content_repo / expected_output
                if calculated.resolve() != expected.resolve():
                    raise CampaignManifestError(
                        f"output routing mismatch: calculated={calculated}, expected={expected}"
                    )

                primary_attempts = int(self.manifest.retry_policy["primary_attempts"])
                llm_attempts = int(self.manifest.retry_policy["llm_escalation_attempts"])
                receipt = None
                result = None
                llm_paths = getattr(self.engine, "_rtq_llm_output_paths", None)
                if llm_paths is None:
                    llm_paths = set()
                    self.engine._rtq_llm_output_paths = llm_paths
                resolved_output = str(expected.resolve())
                decision_engine = getattr(self.engine, "decision_engine", None)
                original_retry_budget = getattr(decision_engine, "max_retry_attempts", None)
                # The primary invocation owns the initial translation plus two
                # feedback-guided retries. Each LLM invocation is one attempt,
                # for exactly five attempts total.
                phases = [
                    (False, primary_attempts - 1, primary_attempts),
                    *[(True, 0, primary_attempts + index) for index in range(1, llm_attempts + 1)],
                ]
                feedback_by_output = getattr(
                    self.engine, "_campaign_retry_feedback_by_output", None
                )
                if feedback_by_output is None:
                    feedback_by_output = {}
                    self.engine._campaign_retry_feedback_by_output = feedback_by_output
                next_feedback = self._retry_feedback_from_failure(
                    self.ledger.latest_failure(output_path=expected_output, target_lang=locale),
                    locale,
                    source_path=source_path,
                )
                try:
                    for use_llm, retry_budget, attempt_number in phases:
                        if decision_engine is not None:
                            decision_engine.max_retry_attempts = retry_budget
                        if use_llm:
                            llm_paths.add(resolved_output)
                        if next_feedback:
                            feedback_by_output[resolved_output] = next_feedback
                        result = self.engine.translate_file(
                            source.site_id,
                            source_path,
                            target_langs=[locale],
                            validate=True,
                            force=False,
                            force_overwrite=False,
                            trigger_type="campaign",
                        )
                        receipt = result.acceptance_receipts.get(locale)
                        if receipt is None:
                            receipt = self.ledger.receipts().get(expected_output)
                        if receipt is not None and expected.is_file():
                            break
                        if expected.exists():
                            expected.unlink(missing_ok=True)
                            raise CampaignManifestError(
                                "rejected attempt produced an unreceipted "
                                f"output: {expected_output}"
                            )
                        failure_gate, failure_reason = self._failure_metadata(result)
                        next_feedback = self._retry_feedback(
                            result,
                            locale,
                            next_feedback,
                            source_path=source_path,
                        )
                        self.ledger.append_failure(
                            source_path=source.source_path,
                            output_path=expected_output,
                            target_lang=locale,
                            error=failure_reason,
                            attempt=attempt_number,
                            job_id=(f"{shard['shard_id']}::{source.source_path}::{locale}"),
                            source_sha256=source.source_sha256,
                            gate=failure_gate,
                        )
                finally:
                    llm_paths.discard(resolved_output)
                    feedback_by_output.pop(resolved_output, None)
                    if decision_engine is not None:
                        decision_engine.max_retry_attempts = original_retry_budget
                if receipt is None or not expected.is_file():
                    failed += 1
                    shard_failed += 1
                    continue
                if Path(receipt["output_path"]).resolve() != expected.resolve():
                    expected.unlink(missing_ok=True)
                    raise CampaignManifestError(
                        f"accepted receipt path mismatch for {expected_output}"
                    )
                accepted += 1
                shard_accepted += 1
            self.ledger.write_summary(
                {
                    **self.manifest.to_summary(),
                    "status": "SHARD_COMPLETE" if shard_failed == 0 else "SHARD_BLOCKED",
                    "shard_id": shard["shard_id"],
                    "shard_accepted": shard_accepted,
                    "shard_failed": shard_failed,
                    "accepted": accepted,
                    "failed": failed,
                }
            )
            if shard_failed:
                raise CampaignManifestError(
                    f"shard blocked: {shard['shard_id']} failures={shard_failed}"
                )
            commit_sha = self._commit_verified_outputs(shard["shard_id"])
            if commit_sha:
                self.ledger.write_summary(
                    {
                        **self.manifest.to_summary(),
                        "status": "SHARD_COMMITTED",
                        "shard_id": shard["shard_id"],
                        "commit_sha": commit_sha,
                        "accepted": accepted,
                        "failed": failed,
                    }
                )

        final = {
            **self.manifest.to_summary(),
            "accepted": accepted,
            "failed": failed,
            "remaining": self.manifest.expected_output_count - accepted,
            "status": (
                "COMPLETE"
                if accepted == self.manifest.expected_output_count and failed == 0
                else "INCOMPLETE"
            ),
        }
        self.ledger.write_summary(final)
        if final["status"] != "COMPLETE":
            raise CampaignManifestError(
                f"campaign incomplete: accepted={accepted}, failed={failed}, "
                f"remaining={final['remaining']}"
            )
        return final
