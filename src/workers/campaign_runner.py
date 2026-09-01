"""Resumable, manifest-scoped zero-defect campaign execution."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.atomic_write import atomic_write
from src.utils.file_lock import FileLock

from .campaign_manifest import (
    CampaignManifest,
    CampaignManifestError,
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
        return {
            row["output_path"]: row
            for row in self._read_jsonl(self.receipts_path)
        }

    def append_receipt(self, receipt: dict[str, Any]) -> None:
        if "content" in receipt or "translated_content" in receipt:
            raise ValueError("campaign receipts must never contain candidate text")
        row = {
            **receipt,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }
        row["receipt_sha256"] = receipt_fingerprint(row)
        self._append(self.receipts_path, row)

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
                "job_id": job_id
                or f"{source_path}::{target_lang}::{output_path}",
                "gate": gate,
                "reason": error[:1000],
                "attempt": attempt,
                "source_sha256": source_sha256,
                "candidate_sha256": candidate_sha256,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _append(self, path: Path, row: dict[str, Any]) -> None:
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
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
        allowed_outputs = {
            output
            for source in self.manifest.sources
            for output in source.outputs.values()
        }
        for output, receipt in receipts.items():
            if output not in allowed_outputs:
                raise CampaignManifestError(f"receipt outside campaign scope: {output}")
            output_path = self.content_repo / output
            if not output_path.is_file():
                raise CampaignManifestError(f"receipt output missing: {output}")
            if sha256_file(output_path) != receipt.get("output_sha256"):
                raise CampaignManifestError(f"receipt/output hash mismatch: {output}")
            gates = receipt.get("gate_results") or {}
            if len(gates) != 44 or any(
                not item.get("passed", False) for item in gates.values()
            ):
                raise CampaignManifestError(f"receipt is not all-pass: {output}")
            valid[output] = receipt
        return valid

    def _append_campaign_receipt(self, receipt: dict[str, Any]) -> None:
        normalized = dict(receipt)
        for field_name in ("source_path", "output_path"):
            absolute = Path(normalized[field_name]).resolve()
            try:
                normalized[field_name] = absolute.relative_to(
                    self.content_repo
                ).as_posix()
            except ValueError as exc:
                raise CampaignManifestError(
                    f"receipt {field_name} is outside content repo: {absolute}"
                ) from exc
        self.ledger.append_receipt(normalized)

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
        max_outputs = int(
            self.manifest.commit_policy.get("max_outputs_per_commit", 250)
        )
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

                result = self.engine.translate_file(
                    source_path,
                    site_id=source.site_id,
                    target_langs=[locale],
                    validate=True,
                    force=False,
                    force_overwrite=False,
                    trigger_type="campaign",
                )
                receipt = result.acceptance_receipts.get(locale)
                if not result.success or receipt is None:
                    failed += 1
                    shard_failed += 1
                    self.ledger.append_failure(
                        source_path=source.source_path,
                        output_path=expected_output,
                        target_lang=locale,
                        error=(
                            "; ".join(result.errors)
                            or result.decision_reason
                            or "translation rejected"
                        ),
                        attempt=result.retry_attempts,
                        job_id=(
                            f"{shard['shard_id']}::{source.source_path}::{locale}"
                        ),
                        source_sha256=source.source_sha256,
                    )
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
