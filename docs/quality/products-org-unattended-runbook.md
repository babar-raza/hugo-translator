# products.aspose.org Unattended Translation Runbook

This repo encodes the production bar learned from the 2026-07-01 manual review and repair run. The governed verifier, not the raw translator exit code, is the acceptance authority.

## Quality Bar

The run is acceptable only when every required `products.aspose.org` English page has a target page for every configured locale and each target passes the governed checks:

- Hugo frontmatter parses and preserves material structure.
- Protected fields such as `layout`, `family_name`, `plugin_platform`, URLs, slugs, dates, and enable flags remain unchanged.
- `Aspose.*` product identities remain exact.
- Fenced code blocks, inline code, placeholders, file paths, Markdown links, anchors, HTML, and Hugo shortcodes are preserved.
- Translatable prose is localized and does not contain substantial English residue.
- Repetition/model-degeneration loops are rejected.
- English source files are not modified.

The durable machine-readable policy is `config/quality/products_aspose_org_policy.yaml`.

## Unattended Command

From the repo root:

```powershell
$env:ASPOSE_ORG_CONTENT = "C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content"
C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\.venv\Scripts\python.exe scripts\quality\products_org_unattended_retranslate.py --run-id products_org_unattended_YYYYMMDD_HHMM --device cuda
```

The wrapper auto-detects `ASPOSE_ORG_CONTENT` and a usable Python interpreter when possible. It snapshots source hashes, plans inventory, re-verifies accepted receipts, retries failures without stopping the campaign, and writes final evidence.

## Evidence

Evidence is written under:

```text
.local/evidences/hugo-translator-retranslation-<run-id>/
```

Important files:

- `baseline/inventory.json`: required source/locale pairs.
- `checkpoints/checkpoint.json`: accepted/failed state.
- `per-file/<locale>/*.comparison.json`: source/target gate comparison.
- `failures/*.json`: typed failure records.
- `resolved-failures/*.json`: repaired failure records.
- `final/accepted-reverification.json`: final accepted-policy recheck.
- `final/unattended-report.json`: wrapper-level closeout report.

## Operational Rules

- Do not weaken gates to complete a run.
- Do not delete failed pages to hide them.
- Do not mark completion while failures remain.
- Safe repairs may restore immutable assets or retry prose at smaller granularity.
- If progress stalls, preserve evidence and return `ACCEPTED_WITH_KNOWN_BLOCKERS` only when the blocker is explicit and reproducible.
