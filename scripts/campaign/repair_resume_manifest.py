"""Restore receipt-owned cells to a rebuilt missing-only campaign manifest.

The inventory builder quite correctly omits files that now exist.  For a
resumed campaign, accepted receipt-owned outputs must nevertheless remain in
the manifest so that resume verification and receipt-to-commit reconciliation
can prove their ownership.  This tool keeps only current missing cells plus
those immutable receipt-owned cells; it never turns unrelated existing output
into a replacement target.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest is not a mapping: {path}")
    return data


def outputs(manifest: dict) -> set[str]:
    return {
        str(output)
        for source in manifest.get("sources", [])
        for output in (source.get("outputs") or {}).values()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--missing-manifest", type=Path, required=True)
    parser.add_argument("--full-manifest", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    missing = load_yaml(args.missing_manifest)
    full = load_yaml(args.full_manifest)
    if missing.get("campaign_id") != full.get("campaign_id"):
        raise ValueError("campaign ids differ between missing and full manifests")

    receipt_outputs = {
        str(json.loads(line).get("output_path"))
        for line in args.receipts.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("output_path")
    }
    desired = outputs(missing) | receipt_outputs
    full_outputs = outputs(full)
    unknown = receipt_outputs - full_outputs
    if unknown:
        raise ValueError(f"receipt outputs absent from full manifest: {sorted(unknown)[:5]}")

    filtered_sources = []
    for source in full.get("sources", []):
        kept = {
            locale: output
            for locale, output in (source.get("outputs") or {}).items()
            if str(output) in desired
        }
        if not kept:
            continue
        rebuilt = dict(source)
        rebuilt["outputs"] = kept
        rebuilt["replace_existing"] = {
            locale: value
            for locale, value in (source.get("replace_existing") or {}).items()
            if locale in kept
        }
        filtered_sources.append(rebuilt)

    repaired = dict(full)
    # The repaired manifest deliberately carries a subset of locales for each
    # source: currently missing cells plus receipt-owned resume cells.  Make
    # that shape explicit so CampaignManifest validates it as missing-only
    # rather than requiring all 25 locales for every source.
    execution_policy = dict(repaired.get("execution_policy") or {})
    execution_policy["output_selection"] = "missing_only"
    repaired["execution_policy"] = execution_policy
    repaired["sources"] = filtered_sources
    repaired["expected_source_count"] = len(filtered_sources)
    repaired["expected_output_count"] = sum(len(source["outputs"]) for source in filtered_sources)
    repaired_outputs = outputs(repaired)
    if receipt_outputs - repaired_outputs:
        raise ValueError("repair lost one or more receipt-owned outputs")
    if repaired_outputs != desired:
        raise ValueError("repair output set differs from missing-plus-receipt intent")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(repaired, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(json.dumps({
        "campaign": repaired["campaign_id"],
        "missing_outputs": len(outputs(missing)),
        "receipt_outputs": len(receipt_outputs),
        "expected_outputs": repaired["expected_output_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
