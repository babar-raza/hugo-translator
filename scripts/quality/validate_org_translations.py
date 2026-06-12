#!/usr/bin/env python3
"""
TC-ORG-06: Structural validator for www.aspose.org translated files.

Validates that a translated _index.{lang}.md file matches the English source
structurally: product identity, field completeness, array lengths, URL preservation.

Usage:
    python scripts/validate_org_translations.py \
        --file path/to/_index.de.md \
        --source path/to/_index.md

    python scripts/validate_org_translations.py \
        --dir path/to/www.aspose.org/ \
        --source path/to/_index.md
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

# Brand tokens that may remain in English in translations
ENGLISH_PRESERVED_TOKENS = {
    "Aspose",
    "FOSS",
    "SDK",
    "API",
    "PDF",
    "Excel",
    "PowerPoint",
    "OneNote",
    "Word",
    "PPTX",
    "OBJ",
    "STL",
    "glTF",
    "COLLADA",
    "3MF",
    "FBX",
    "AES-256",
    "MAPI",
    "MSG",
    "Python",
    ".NET",
    "Java",
    "C++",
    "Go",
    "PHP",
    "QR",
    "UPC",
    "GitHub",
    "File Format FOSS",
}


def parse_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter from a Hugo Markdown file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"No frontmatter delimiter in {path}")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Malformed frontmatter in {path}")
    return yaml.safe_load(parts[1])


def get_product_families(fm: dict) -> list[str]:
    """Extract ordered list of product family identifiers."""
    items = fm.get("products", {}).get("items", [])
    return [item.get("app", {}).get("family", "MISSING") for item in items]


def validate_file(source_path: Path, target_path: Path) -> dict:
    """Run all structural checks on a single translated file."""
    result = {
        "file": str(target_path),
        "checks": [],
        "pass": True,
    }

    def check(name: str, passed: bool, detail: str = ""):
        result["checks"].append({"name": name, "pass": passed, "detail": detail})
        if not passed:
            result["pass"] = False

    # 1. YAML parses
    try:
        src_fm = parse_frontmatter(source_path)
    except Exception as e:
        result["checks"].append({"name": "source_parse", "pass": False, "detail": str(e)})
        result["pass"] = False
        return result

    try:
        tgt_fm = parse_frontmatter(target_path)
    except Exception as e:
        check("yaml_parse", False, str(e))
        return result
    check("yaml_parse", True)

    # 2. Product identity set matches
    src_families = get_product_families(src_fm)
    tgt_families = get_product_families(tgt_fm)
    check(
        "product_identity",
        set(src_families) == set(tgt_families),
        f"src={sorted(src_families)} tgt={sorted(tgt_families)}"
        if set(src_families) != set(tgt_families)
        else "",
    )

    # 3. Product count
    src_count = len(src_families)
    tgt_count = len(tgt_families)
    check("product_count", src_count == tgt_count, f"src={src_count} tgt={tgt_count}")

    # 4. Product family order
    check(
        "product_order",
        src_families == tgt_families,
        f"src={src_families} tgt={tgt_families}" if src_families != tgt_families else "",
    )

    # 5. Translate fields present and non-empty
    translate_fields = [
        "title",
        "description",
        "header.title",
        "header.subtitle",
        "header.image.alt_text",
        "popular_features.heading",
        "popular_features.text",
        "products.available_title",
        "products.available_subtitle",
        "products.coming_soon_title",
        "products.coming_soon_subtitle",
        "products.platform_suffix",
        "products.platform_conjunction",
        "products.platform_pair",
        "why_choose.heading",
        "why_choose.total_link.text",
    ]
    for field in translate_fields:
        val = _get_nested(tgt_fm, field)
        check(
            f"field_present:{field}",
            val is not None and (not isinstance(val, str) or val.strip()),
            "missing or empty" if not val else "",
        )

    # 6. Per-product translated fields
    src_items = src_fm.get("products", {}).get("items", [])
    tgt_items = tgt_fm.get("products", {}).get("items", [])
    for i, (si, ti) in enumerate(zip(src_items, tgt_items)):
        sa = si.get("app", {})
        ta = ti.get("app", {})
        family = sa.get("family", f"item{i}")

        # subtitle must be present
        check(
            f"product[{i}].subtitle",
            bool(ta.get("subtitle", "").strip()),
            f"family={family}",
        )

        # description or base_description must be present
        has_desc = bool(ta.get("description", "").strip()) or bool(
            ta.get("base_description", "").strip()
        )
        check(f"product[{i}].desc", has_desc, f"family={family}")

        # family preserved
        check(f"product[{i}].family", sa.get("family") == ta.get("family"), f"family={family}")

        # URL preserved
        src_url = sa.get("url")
        tgt_url = ta.get("url")
        check(f"product[{i}].url", src_url == tgt_url, f"src={src_url} tgt={tgt_url}")

        # image preserved
        check(f"product[{i}].image", sa.get("image") == ta.get("image"))

    # 7. Array lengths match for key sections
    for array_path in [
        "products.items",
        "why_choose.reasons",
        "popular_features.features",
    ]:
        src_arr = _get_nested(src_fm, array_path)
        tgt_arr = _get_nested(tgt_fm, array_path)
        src_len = len(src_arr) if isinstance(src_arr, list) else -1
        tgt_len = len(tgt_arr) if isinstance(tgt_arr, list) else -1
        check(f"array_len:{array_path}", src_len == tgt_len, f"src={src_len} tgt={tgt_len}")

    # 8. Passthrough fields match
    for field in ["draft", "type", "layout"]:
        src_val = src_fm.get(field)
        tgt_val = tgt_fm.get(field)
        if src_val is not None:
            check(f"passthrough:{field}", src_val == tgt_val, f"src={src_val} tgt={tgt_val}")

    # 9. Why_choose reason points count
    src_reasons = _get_nested(src_fm, "why_choose.reasons") or []
    tgt_reasons = _get_nested(tgt_fm, "why_choose.reasons") or []
    for i, (sr, tr) in enumerate(zip(src_reasons, tgt_reasons)):
        src_pts = sr.get("points", []) if isinstance(sr, dict) else []
        tgt_pts = tr.get("points", []) if isinstance(tr, dict) else []
        check(
            f"reason[{i}].points_count",
            len(src_pts) == len(tgt_pts),
            f"src={len(src_pts)} tgt={len(tgt_pts)}",
        )

    return result


def _get_nested(data: dict, key: str):
    """Get nested value using dot notation."""
    parts = key.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def main():
    parser = argparse.ArgumentParser(description="Validate www.aspose.org translations")
    parser.add_argument("--file", type=Path, help="Single translated file to validate")
    parser.add_argument("--dir", type=Path, help="Directory containing all _index.*.md files")
    parser.add_argument("--source", type=Path, required=True, help="English source _index.md")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"ERROR: Source file not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    results = []

    if args.file:
        if not args.file.exists():
            print(f"ERROR: Target file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        results.append(validate_file(args.source, args.file))
    elif args.dir:
        for f in sorted(args.dir.glob("_index.*.md")):
            if f.name == "_index.md":
                continue
            results.append(validate_file(args.source, f))
    else:
        print("ERROR: Provide --file or --dir", file=sys.stderr)
        sys.exit(1)

    # Output
    all_pass = all(r["pass"] for r in results)

    if args.json:
        print(json.dumps({"results": results, "all_pass": all_pass}, indent=2))
    else:
        for r in results:
            lang = Path(r["file"]).stem.split(".")[-1]
            status = "PASS" if r["pass"] else "FAIL"
            failed = [c for c in r["checks"] if not c["pass"]]
            if failed:
                print(f"  {lang}: {status} — {len(failed)} failures:")
                for f in failed:
                    detail = f" ({f['detail']})" if f.get("detail") else ""
                    print(f"    - {f['name']}{detail}")
            else:
                print(f"  {lang}: {status} ({len(r['checks'])} checks)")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
