#!/usr/bin/env python
"""
TC-P7-09: Gate 31 (partial script contamination) term classification.

Dedupes the 56 findings to their unique leaked terms and classifies each
against direct file inspection (see plan Deliverable 3 row for Gate 31):

- Legitimate technical passthrough (PDF-spec `/LE` dictionary entry,
  ASN.1/PKCS7 `DER` encoding terminology) -- confirmed by reading the
  surrounding sentence in context, e.g. LineEndingStyle.md (ar):
  "...ISO 32000-1 12.5.6.7 ... /Line annotations' /LE entry." -- this is a
  literal PDF-format spec term, not translatable prose. NOT a content bug;
  candidate for a Gate 31 allowlist addition (separate follow-up, touches
  live write_gate.py, out of this mission's scope).
- Genuine leak: camelCase/snake_case API identifiers being split into
  word fragments during translation (e.g. `kAEndParaRPr` -> "k a end para
  r pr", `para_props` -> "para props", a mangled `{@link
  ColorType#Placeholder}` -> "P LA CHE HOLE D"). This IS a real defect --
  routed to the backlog, not mechanically fixable without retranslation.

No LLM/MT calls -- classification is a fixed lookup table built from the
direct file-inspection evidence above, not live language detection.
"""
from __future__ import annotations

import ast
import csv
import re
from pathlib import Path

DETAIL_TERM_RE = re.compile(r"content: (\[.*\])")

# Evidence-based classification (see module docstring).
LEGITIMATE_PASSTHROUGH_TERMS = {
    "LE entry",
    "LE entry elements",
    "LE bytes",
    "DER byte",
    "DER bytes",
    "issuer der",
    "bytes DER",
}
GENUINE_LEAK_TERMS = {
    "end para",
    "para props",
    "LA CHE HOLE",
}


def classify(term: str) -> str:
    if term in LEGITIMATE_PASSTHROUGH_TERMS:
        return "legitimate_passthrough"
    if term in GENUINE_LEAK_TERMS:
        return "genuine_leak"
    return "unclassified_needs_inspection"


def main() -> int:
    detail_path = Path("reports/audit/findings_detail.csv")
    rows = []
    with detail_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] == "partial_script_contamination_gate31":
                rows.append(r)

    out_rows = []
    for r in rows:
        m = DETAIL_TERM_RE.search(r["detail"])
        terms = []
        if m:
            try:
                terms = ast.literal_eval(m.group(1))
            except (ValueError, SyntaxError):
                terms = [m.group(1)]
        classifications = {classify(t) for t in terms} or {"unclassified_needs_inspection"}
        # A file is routed to backlog if ANY of its leaked terms are a genuine leak
        # or unclassified; only files where every term is confirmed legitimate
        # passthrough are left untouched.
        verdict = (
            "legitimate_passthrough"
            if classifications == {"legitimate_passthrough"}
            else "genuine_leak_or_unclassified"
        )
        out_rows.append(
            {
                "site_id": r["site_id"],
                "locale": r["locale"],
                "file_path": r["file_path"],
                "terms": "; ".join(terms),
                "verdict": verdict,
            }
        )

    out_dir = Path("reports/audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "gate31_classification.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["site_id", "locale", "file_path", "terms", "verdict"])
        w.writeheader()
        w.writerows(out_rows)

    backlog_path = out_dir / "gate31_backlog.csv"
    backlog_rows = [r for r in out_rows if r["verdict"] == "genuine_leak_or_unclassified"]
    with backlog_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["site_id", "locale", "file_path", "terms", "verdict"])
        w.writeheader()
        w.writerows(backlog_rows)

    print(f"Gate 31 findings: {len(rows)}")
    print(f"Wrote {out_path} ({len(out_rows)} rows)")
    print(f"Wrote {backlog_path} ({len(backlog_rows)} rows routed to backlog)")
    print(f"Legitimate passthrough (no action, allowlist candidate): {len(out_rows) - len(backlog_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
