"""TC-APT-046 step 2: automated verification of a concurrency canary run.

Plan §11 requires the canary at ``max_parallel_jobs > 1`` to be judged by an automated
diff, *not* a spot-check, on three things: zero cross-language/cross-file content bleed,
zero empty-frontmatter incidents, and a recorded model that matches manifest routing for
every cell. This script is that check, so the canary's verdict never depends on someone
reading a handful of files.

A fourth check is included because it is the sharpest direct evidence of a cross-job
race: every receipted ``output_sha256`` must still match the bytes on disk. A mismatch
means something overwrote an accepted output after its receipt was written — exactly the
failure mode concurrency would introduce, and one no per-file gate can catch.

CAVEAT (found while closing TC-APT-047, 2026-09-06): this fourth check has no sense of
time. If a page is legitimately retriggered by a LATER, SEPARATE campaign (a RECURRENCE
step-3 heal retrigger, for example) after this canary's receipts were written, every one
of that page's cells will show a "receipt_integrity" mismatch forever after — the current
disk bytes reflect the later campaign, not this one, and that is correct, not a race. This
is indistinguishable from a real cross-job race using this check alone. Run this
immediately after the canary campaign finishes, before anything else touches the same
page, for it to mean what it says; a mismatch found long after the fact must first be
traced (which campaign's acceptance receipt DOES match current disk / a chain of
``superseded_sha256`` fields across later campaigns) before it is treated as a concurrency
defect.

Usage:
    python scripts/campaign/verify_concurrency_canary.py \
        --manifest data/campaigns/<id>/manifest.yaml [--json-out report.json]

Exit code is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FRONTMATTER_KEYS = ("title", "description")


def load_receipts(ledger_root: Path, campaign_id: str) -> list[dict[str, Any]]:
    path = ledger_root / campaign_id / "acceptance_receipts.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_text, body). Empty frontmatter yields ('', whole text)."""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    return text[3:end], text[end + 4 :]


def check_model_routing(receipts: list[dict[str, Any]], retry_policy: dict) -> list[str]:
    """Every cell's recorded model must be one the manifest actually routes to."""
    allowed = {
        str(retry_policy.get("primary_model") or ""),
        str(retry_policy.get("llm_model") or ""),
    } - {""}
    return [
        f"{receipt.get('target_lang')} {receipt.get('output_path')}: model "
        f"{receipt.get('model_fingerprint')!r} is not in manifest routing {sorted(allowed)}"
        for receipt in receipts
        if str(receipt.get("model_fingerprint") or "") not in allowed
    ]


def check_frontmatter(receipts: list[dict[str, Any]], content_repo: Path) -> list[str]:
    """No empty-frontmatter incidents: parseable, non-empty, required keys filled."""
    problems: list[str] = []
    for receipt in receipts:
        output = content_repo / str(receipt["output_path"])
        if not output.is_file():
            problems.append(f"{receipt['output_path']}: receipted output is missing on disk")
            continue
        raw, _body = split_frontmatter(output.read_text(encoding="utf-8"))
        if not raw.strip():
            problems.append(f"{receipt['output_path']}: empty or absent frontmatter")
            continue
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            problems.append(f"{receipt['output_path']}: frontmatter does not parse ({exc.__class__.__name__})")
            continue
        if not isinstance(parsed, dict) or not parsed:
            problems.append(f"{receipt['output_path']}: frontmatter is not a non-empty mapping")
            continue
        for key in REQUIRED_FRONTMATTER_KEYS:
            value = parsed.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                problems.append(f"{receipt['output_path']}: frontmatter key {key!r} is empty")
    return problems


def check_content_bleed(receipts: list[dict[str, Any]], content_repo: Path) -> list[str]:
    """Two accepted cells must never share a body.

    Same source, different locale with identical bodies means one job's output landed
    under another's name (or nothing was translated). Same locale, different source is
    the cross-file form of the same defect. Byte identity is used deliberately: it has
    effectively no false-positive rate on real prose, which a similarity threshold
    would not.
    """
    by_body: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for receipt in receipts:
        output = content_repo / str(receipt["output_path"])
        if not output.is_file():
            continue
        _raw, body = split_frontmatter(output.read_text(encoding="utf-8"))
        if not body.strip():
            continue
        digest = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()
        by_body[digest].append(
            (str(receipt["source_path"]), str(receipt["target_lang"]), str(receipt["output_path"]))
        )

    problems: list[str] = []
    for cells in by_body.values():
        if len(cells) < 2:
            continue
        locales = {locale for _source, locale, _output in cells}
        sources = {source for source, _locale, _output in cells}
        kind = "cross-language" if len(locales) > 1 else "cross-file"
        if len(locales) > 1 or len(sources) > 1:
            paths = ", ".join(output for _s, _l, output in sorted(cells, key=lambda c: c[2]))
            problems.append(f"{kind} content bleed: identical bodies in {paths}")
    return problems


def check_receipt_integrity(receipts: list[dict[str, Any]], content_repo: Path) -> list[str]:
    """An accepted output must still be the bytes its receipt attests to."""
    problems: list[str] = []
    for receipt in receipts:
        expected = str(receipt.get("output_sha256") or "")
        output = content_repo / str(receipt["output_path"])
        if not expected or not output.is_file():
            continue
        actual = hashlib.sha256(output.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(
                f"{receipt['output_path']}: on-disk bytes no longer match the accepted "
                f"receipt (expected {expected[:12]}, found {actual[:12]}) -- an accepted "
                f"output was overwritten after acceptance"
            )
    return problems


def verify(manifest_path: Path, ledger_root: Path) -> dict[str, Any]:
    from src.workers.campaign_manifest import CampaignManifest

    manifest = CampaignManifest.load(manifest_path)
    content_repo = Path(manifest.content_repo).resolve()
    receipts = load_receipts(ledger_root, manifest.campaign_id)

    checks = {
        "model_routing": check_model_routing(receipts, manifest.retry_policy),
        "empty_frontmatter": check_frontmatter(receipts, content_repo),
        "content_bleed": check_content_bleed(receipts, content_repo),
        "receipt_integrity": check_receipt_integrity(receipts, content_repo),
    }
    models: dict[str, int] = defaultdict(int)
    for receipt in receipts:
        models[str(receipt.get("model_fingerprint") or "unknown")] += 1

    return {
        "campaign_id": manifest.campaign_id,
        "max_parallel_jobs": int(manifest.execution_policy.get("max_parallel_jobs", 1)),
        "cells_verified": len(receipts),
        "models_used": dict(models),
        "checks": checks,
        "violations": sum(len(items) for items in checks.values()),
        "passed": all(not items for items in checks.values()) and bool(receipts),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-046 concurrency canary verification")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    report = verify(args.manifest, args.ledger_root)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")

    if not report["cells_verified"]:
        print("no receipts to verify -- canary produced nothing", file=sys.stderr)
        return 1
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
