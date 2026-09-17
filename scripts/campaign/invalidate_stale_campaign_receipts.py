"""Conservatively demote campaign receipts issued under an older config policy.

The original metadata-only receipts are retained in an append-only evidence
file. Their on-disk outputs are declared as exact-hash replacement targets in
the manifest, allowing the normal zero-defect pipeline to regenerate them.
Candidate text is never copied into the ledger and content files are untouched.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.utils.atomic_write import atomic_write
from src.workers.campaign_manifest import receipt_fingerprint, sha256_file


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    manifest_path = args.manifest.resolve()
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a mapping")
    campaign_id = str(raw["campaign_id"])
    current_config = str(raw["config_fingerprint"])
    content_repo = Path(str(raw["content_repo"])).resolve()
    ledger_dir = args.ledger_root.resolve() / campaign_id
    receipts_path = ledger_dir / "acceptance_receipts.jsonl"
    receipts = read_jsonl(receipts_path)

    ownership: dict[str, tuple[dict[str, Any], str]] = {}
    for source in raw.get("sources", []):
        for locale, output in (source.get("outputs") or {}).items():
            output = str(output)
            if output in ownership:
                raise ValueError(f"duplicate manifest output ownership: {output}")
            ownership[output] = (source, str(locale))

    retained: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    for receipt in receipts:
        output = str(receipt.get("output_path") or "")
        if output not in ownership:
            raise ValueError(f"receipt outside manifest: {output}")
        claimed = str(receipt.get("receipt_sha256") or "")
        unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        if not claimed or receipt_fingerprint(unsigned) != claimed:
            raise ValueError(f"receipt fingerprint mismatch: {output}")
        target = content_repo / output
        # This is a real, shared, multi-session content repo -- another
        # session can legitimately remove or modify a file this campaign
        # committed, entirely outside this campaign's own config-policy
        # question. Found live 2026-09-17, twice, in the same session: (1) a
        # peer session's approved Deletion Governance Record removed an
        # entire stale shadow-candidate page this campaign had translated
        # into, including a file a receipt here still pointed at; (2) a
        # separate peer session fixed a deploy-breaking frontmatter field in
        # a file this campaign had also translated, changing its hash. Both
        # are real, legitimate, already-governed changes (auditable in the
        # content repo's own git history) -- not corruption, and not this
        # campaign's call to overwrite by queuing a replace_existing
        # retranslation. Either case must never hard-stop every future
        # unattended startup: drop the stale receipt and move on.
        if not target.is_file() or sha256_file(target) != receipt.get("output_sha256"):
            orphaned.append(receipt)
            continue
        if str(receipt.get("config_fingerprint") or "") == current_config:
            retained.append(receipt)
            continue
        source, locale = ownership[output]
        replacements = source.setdefault("replace_existing", {})
        replacements[locale] = {
            "expected_sha256": sha256_file(target),
            "reason_code": "stale_receipt_policy_retranslation",
        }
        stale.append(receipt)

    result = {
        "campaign": campaign_id,
        "receipts": len(receipts),
        "retained": len(retained),
        "invalidated": len(stale),
        "orphaned": len(orphaned),
        "executed": bool(args.execute),
    }
    if (not stale and not orphaned) or not args.execute:
        print(json.dumps(result, sort_keys=True))
        return 0

    invalidated_at = datetime.now(timezone.utc).isoformat()
    evidence_path = ledger_dir / "invalidated_receipts.jsonl"
    evidence = "".join(
        json.dumps(
            {
                "campaign_id": campaign_id,
                "invalidated_at": invalidated_at,
                "reason": "config_fingerprint_superseded",
                "prior_receipt": receipt,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for receipt in stale
    )
    previous_evidence = evidence_path.read_text(encoding="utf-8") if evidence_path.is_file() else ""
    atomic_write(
        path=evidence_path,
        content=previous_evidence + evidence,
        encoding="utf-8",
        fsync=True,
        create_parents=True,
    )

    if orphaned:
        orphaned_path = ledger_dir / "orphaned_receipts.jsonl"
        orphaned_evidence = "".join(
            json.dumps(
                {
                    "campaign_id": campaign_id,
                    "dropped_at": invalidated_at,
                    "reason": "receipted_output_missing_from_content_repo",
                    "prior_receipt": receipt,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for receipt in orphaned
        )
        previous_orphaned = (
            orphaned_path.read_text(encoding="utf-8") if orphaned_path.is_file() else ""
        )
        atomic_write(
            path=orphaned_path,
            content=previous_orphaned + orphaned_evidence,
            encoding="utf-8",
            fsync=True,
            create_parents=True,
        )
    atomic_write(
        path=receipts_path,
        content="".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in retained
        ),
        encoding="utf-8",
        fsync=True,
        create_parents=True,
    )
    atomic_write(
        path=manifest_path,
        content=yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        fsync=True,
        create_parents=True,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
