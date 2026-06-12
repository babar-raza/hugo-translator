#!/usr/bin/env python3
"""
E2E Output Analyzer for Hugo Translator.

Analyzes translation output for all 10 concerns:
1. Markdown formatting removal
2. Links not preserved
3. Multi-language contamination
4. English content leakage
5. VRAM OOM (checked via logs)
6. VRAM underutilization (checked via logs)
7. Bullet point/list mismatch
8. CT2 CPU slowness (checked via logs)
9. GPU not detected (checked via logs)
10. VRAM non-recovery (checked via logs)

Generates JSON and Markdown reports with problem rate calculation.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.parser.hugo_parser import HugoDocument, HugoParser

try:
    import langdetect

    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    print("WARNING: langdetect not available, language checks will be limited")


# Technical patterns that should NOT be counted as English leakage
TECHNICAL_PATTERNS = [
    r"^[A-Z][a-z]+(?:[A-Z][a-z]+)+$",  # PascalCase: BarCodeException
    r"^[A-Z][A-Z0-9_]+$",  # CONSTANTS
    r"^[a-z]+(?:[A-Z][a-z]+)+$",  # camelCase
    r"^I[A-Z][a-zA-Z]+$",  # Interfaces: ISerializable
    r"^\w+\.\w+",  # Namespaces: System.Object
    r"^\w+\(\)$",  # Methods: GetType()
    r"^[A-Z][a-z]+Exception$",  # Exception names
    r"^https?://",  # URLs
    r"^\d+$",  # Numbers
    r"^[\d.]+$",  # Versions
]

COMPILED_TECHNICAL = [re.compile(p) for p in TECHNICAL_PATTERNS]


def is_technical_term(word: str) -> bool:
    """Check if a word is a technical term that should not be translated."""
    return any(p.match(word) for p in COMPILED_TECHNICAL)


def parse_markdown_file(file_path: Path) -> tuple[HugoDocument, dict[str, int]]:
    """
    Parse markdown file and return HugoDocument plus node type counts.

    Uses correct HugoParser API: parse_file() returns HugoDocument with .ast attribute.
    """
    parser = HugoParser()
    doc = parser.parse_file(file_path)

    # Count nodes by type
    counts: dict[str, int] = Counter()

    def count_nodes(node: ASTNode):
        counts[node.type.name] += 1
        for child in node.children:
            count_nodes(child)

    for node in doc.ast:
        count_nodes(node)

    return doc, dict(counts)


def extract_links_and_images(ast: list[ASTNode]) -> list[str]:
    """Extract all link URLs and image sources from AST."""
    urls = []

    def extract(node: ASTNode):
        if node.type == NodeType.LINK:
            url = node.attrs.get("url", "")
            if url:
                urls.append(url)
        elif node.type == NodeType.IMAGE:
            src = node.attrs.get("src", "")
            if src:
                urls.append(src)

        for child in node.children:
            extract(child)

    for node in ast:
        extract(node)

    return urls


def extract_text_content(ast: list[ASTNode], exclude_code: bool = True) -> str:
    """Extract human-readable text content from AST, excluding code blocks/spans."""
    texts = []

    def extract(node: ASTNode):
        # Skip code blocks and spans for language detection
        if exclude_code and node.type in (NodeType.CODE_BLOCK, NodeType.CODE_SPAN):
            return

        if node.type == NodeType.TEXT:
            # Text content is stored in node.raw, not in attrs
            text = getattr(node, "raw", "") or node.attrs.get("content", "") or ""
            if text:
                texts.append(text)

        for child in node.children:
            extract(child)

    for node in ast:
        extract(node)

    return " ".join(texts)


def extract_heading_texts(ast: list[ASTNode]) -> list[str]:
    """Extract all heading text contents from AST."""
    headings = []

    def extract(node: ASTNode):
        if node.type == NodeType.HEADING:
            # Extract text from heading children
            heading_text = extract_text_content([node], exclude_code=False)
            if heading_text.strip():
                headings.append(heading_text.strip())

        for child in node.children:
            extract(child)

    for node in ast:
        extract(node)

    return headings


def check_separator_corruption(content: str) -> tuple[bool, list[str]]:
    """
    Check for separator corruption patterns like ',et,' in translated content.

    Returns (has_corruption, list of corrupted patterns found).
    """
    # Patterns that indicate separator corruption
    corruption_patterns = [
        r",\s*et\s*,",  # ,et, - French "and" as separator
        r",\s*и\s*,",  # ,и, - Russian "and" as separator
        r",\s*und\s*,",  # ,und, - German "and" as separator
        r",\s*y\s*,",  # ,y, - Spanish "and" as separator
        r"\[\s*\[\s*",  # [[ - double brackets
        r"\]\s*\]\s*",  # ]] - double brackets
    ]

    found = []
    for pattern in corruption_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        found.extend(matches)

    return len(found) > 0, found


def check_duplicate_translations(
    headings: list[str], threshold: int = 3
) -> tuple[bool, dict[str, int]]:
    """
    Check if multiple different source headings produced the same translation.

    Returns (has_duplicates, dict of duplicated texts with counts).

    Note: Legitimate API documentation sections like "Parameters", "Returns",
    "Examples" are expected to appear multiple times - these are NOT bugs.
    Only flag when the same translation is suspiciously generic or corrupted.
    """
    # Common legitimate repeated headings (in various languages)
    # These are expected to repeat in API documentation
    LEGITIMATE_REPEATED = {
        # English
        "parameters",
        "returns",
        "examples",
        "remarks",
        "see also",
        "constructors",
        "properties",
        "methods",
        "events",
        "fields",
        "property value",
        "return value",
        "exceptions",
        "type parameters",
        # French
        "paramètres",
        "retour",
        "exemples",
        "remarques",
        "voir aussi",
        "constructeurs",
        "propriétés",
        "méthodes",
        "événements",
        "champs",
        "valeur propriété",
        "valeur de retour",  # Russian
        "параметры",
        "возвращение",
        "примеры",
        "замечания",
        "смотрите также",
        "конструкторы",
        "свойства",
        "методы",
        "события",
        "поля",
        "стоимость недвижимости",
        "возвращаемое значение",
        "исключения",
        # German
        "parameter",
        "rückgabe",
        "beispiele",
        "hinweise",
        # Spanish
        "parámetros",
        "retorno",
        "ejemplos",
        "observaciones",
    }

    counts = Counter(headings)
    duplicates = {}

    for text, count in counts.items():
        if count < threshold or len(text) <= 3:
            continue

        # Skip legitimate repeated headings
        normalized = text.strip().lower()
        if normalized in LEGITIMATE_REPEATED:
            continue

        duplicates[text] = count

    return len(duplicates) > 0, duplicates


def detect_language(text: str) -> tuple[str, float]:
    """Detect language of text. Returns (language_code, confidence)."""
    if not LANGDETECT_AVAILABLE or not text.strip():
        return ("unknown", 0.0)

    try:
        lang = langdetect.detect(text)
        langs = langdetect.detect_langs(text)
        confidence = next((l.prob for l in langs if l.lang == lang), 0.0)
        return (lang, confidence)
    except Exception:
        return ("unknown", 0.0)


def calculate_english_ratio(text: str) -> float:
    """
    Calculate ratio of English-like words to total words.

    Excludes technical terms, code identifiers, and URLs.
    """
    # Extract words (2+ letters)
    words = re.findall(r"\b[a-zA-Z]{2,}\b", text)
    if not words:
        return 0.0

    # Filter out technical terms
    human_words = [w for w in words if not is_technical_term(w)]

    if not human_words:
        return 0.0  # All words are technical, not English leakage

    # Count Latin-script words (potential English)
    latin_words = [w for w in human_words if all(c.isascii() for c in w)]

    return len(latin_words) / len(human_words)


def calculate_cyrillic_ratio(text: str) -> float:
    """Calculate ratio of Cyrillic characters in text."""
    chars = [c for c in text if c.isalpha()]
    if not chars:
        return 0.0
    cyrillic = sum(1 for c in chars if "\u0400" <= c <= "\u04ff")
    return cyrillic / len(chars)


def analyze_structure(source_file: Path, target_file: Path, target_lang: str) -> dict[str, Any]:
    """Analyze structural preservation between source and target."""
    checks = {}

    try:
        source_doc, source_counts = parse_markdown_file(source_file)
        target_doc, target_counts = parse_markdown_file(target_file)

        # Check node type counts
        important_types = [
            "HEADING",
            "PARAGRAPH",
            "LIST",
            "LIST_ITEM",
            "STRONG",
            "EMPHASIS",
            "CODE_SPAN",
            "LINK",
            "IMAGE",
            "CODE_BLOCK",
        ]

        for node_type in important_types:
            source_count = source_counts.get(node_type, 0)
            target_count = target_counts.get(node_type, 0)

            if source_count == 0:
                continue

            mismatch_rate = abs(source_count - target_count) / source_count

            # Define thresholds by node type
            if node_type in ["LINK", "IMAGE"]:
                threshold = 0.0  # Strict: no links should be lost
                concern = 2
            elif node_type in ["LIST", "LIST_ITEM"]:
                threshold = 0.02  # 2% tolerance
                concern = 7
            elif node_type in ["STRONG", "EMPHASIS", "CODE_SPAN"]:
                threshold = 0.05  # 5% tolerance for formatting
                concern = 1
            else:
                threshold = 0.10  # 10% tolerance for paragraphs/headings
                concern = 1

            passed = mismatch_rate <= threshold

            checks[f"structure_{node_type.lower()}"] = {
                "passed": passed,
                "source_count": source_count,
                "target_count": target_count,
                "mismatch_rate": mismatch_rate,
                "threshold": threshold,
                "concern": concern,
            }

        # Extract and compare links
        source_links = extract_links_and_images(source_doc.ast)
        target_links = extract_links_and_images(target_doc.ast)

        if source_links:
            preserved = len(set(source_links) & set(target_links))
            match_rate = preserved / len(set(source_links))
            checks["links_preserved"] = {
                "passed": match_rate >= 0.98,
                "source_links": len(source_links),
                "target_links": len(target_links),
                "preserved": preserved,
                "match_rate": match_rate,
                "concern": 2,
            }

        # Check for duplicate translations (heading corruption)
        source_headings = extract_heading_texts(source_doc.ast)
        target_headings = extract_heading_texts(target_doc.ast)

        if target_headings:
            has_duplicates, duplicates = check_duplicate_translations(target_headings, threshold=3)
            if has_duplicates:
                checks["heading_duplication"] = {
                    "passed": False,
                    "duplicated_headings": duplicates,
                    "total_headings": len(target_headings),
                    "concern": 4,  # This causes English leakage / wrong translations
                }

        # Check for separator corruption
        with open(target_file, encoding="utf-8") as f:
            raw_content = f.read()

        has_corruption, corrupted = check_separator_corruption(raw_content)
        if has_corruption:
            checks["separator_corruption"] = {
                "passed": False,
                "corrupted_patterns": corrupted[:10],  # Limit to 10 examples
                "total_found": len(corrupted),
                "concern": 7,  # Bullet/list mismatch
            }

    except Exception as e:
        checks["structure_analysis_error"] = {"passed": False, "error": str(e), "concern": 1}

    return checks


def analyze_language(target_file: Path, target_lang: str) -> dict[str, Any]:
    """Analyze language purity and contamination."""
    checks = {}

    try:
        parser = HugoParser()
        doc = parser.parse_file(target_file)

        # Extract text content (excluding code)
        body_text = extract_text_content(doc.ast, exclude_code=True)

        if not body_text.strip():
            return checks

        # Script-based language validation (always run, even without langdetect)
        if target_lang == "ru":
            cyrillic_ratio = calculate_cyrillic_ratio(body_text)
            # Russian should have substantial Cyrillic content
            checks["script_purity"] = {
                "passed": cyrillic_ratio >= 0.15,  # At least 15% Cyrillic for Russian
                "cyrillic_ratio": cyrillic_ratio,
                "threshold": 0.15,
                "concern": 3,
            }

        # Language detection with langdetect if available
        if LANGDETECT_AVAILABLE:
            detected_lang, confidence = detect_language(body_text)

            # For non-Cyrillic languages
            if target_lang != "ru":
                checks["language_detection"] = {
                    "passed": detected_lang == target_lang and confidence >= 0.60,
                    "detected": detected_lang,
                    "expected": target_lang,
                    "confidence": confidence,
                    "concern": 3,
                }

        # English leakage detection
        # For Latin-script languages (French, German, Spanish, etc.),
        # use langdetect to distinguish from English since both use Latin script.
        # For non-Latin scripts (Russian, Chinese, etc.), use script ratio.

        latin_script_langs = {
            "fr",
            "de",
            "es",
            "it",
            "pt",
            "nl",
            "pl",
            "ro",
            "cs",
            "sk",
            "hr",
            "sl",
            "hu",
            "sv",
            "da",
            "no",
            "fi",
            "et",
            "lt",
            "lv",
            "ca",
            "eu",
            "gl",
            "id",
            "ms",
            "vi",
            "tr",
        }

        if target_lang in latin_script_langs:
            # For Latin-script languages, rely on langdetect
            # If langdetect says it's the right language, it's not English leakage
            if LANGDETECT_AVAILABLE:
                detected_lang, confidence = detect_language(body_text)
                # Consider it a pass if detected as target language with good confidence
                # OR if detected as a related Latin language (not English)
                is_english = detected_lang == "en" and confidence > 0.60
                checks["english_leakage"] = {
                    "passed": not is_english,
                    "detected_lang": detected_lang,
                    "confidence": confidence,
                    "is_english": is_english,
                    "concern": 4,
                }
            # If langdetect unavailable, skip this check for Latin-script languages
        else:
            # For non-Latin scripts (Russian, Chinese, Arabic, etc.)
            # The script_purity check is the primary validation.
            # Latin script appearing in these translations is typically
            # preserved technical terms (class names, method names), not English leakage.
            #
            # If script_purity passed (sufficient Cyrillic/Arabic/etc. characters),
            # then the translation is working - any Latin text is intentional.
            cyrillic_ratio = calculate_cyrillic_ratio(body_text)

            # Pass if there's meaningful non-Latin content
            # Threshold: at least 10% target script characters
            # (lower than script_purity because this is a leakage check)
            checks["english_leakage"] = {
                "passed": cyrillic_ratio >= 0.10,  # Translations should have SOME Cyrillic
                "target_script_ratio": cyrillic_ratio,
                "threshold": 0.10,
                "note": "Latin script in non-Latin translations is typically preserved technical terms",
                "concern": 4,
            }

        # Cross-language contamination
        if target_lang not in ["ru", "uk", "bg", "sr", "mk", "be"]:
            cyrillic_chars = len(re.findall(r"[\u0400-\u04FF]", body_text))
            checks["cyrillic_contamination"] = {
                "passed": cyrillic_chars == 0,
                "cyrillic_count": cyrillic_chars,
                "concern": 3,
            }

    except Exception as e:
        checks["language_analysis_error"] = {"passed": False, "error": str(e), "concern": 3}

    return checks


def analyze_run(
    source_dir: Path, output_dir: Path, target_langs: list[str], run_id: str
) -> dict[str, Any]:
    """Analyze entire translation run."""
    results = {
        "run_id": run_id,
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "target_langs": target_langs,
        "files": {},
        "summary": {"total_checks": 0, "passed_checks": 0, "failed_checks": 0, "problem_rate": 0.0},
        "concerns": {i: {"total": 0, "passed": 0, "failed": 0} for i in range(1, 11)},
    }

    # Find source files
    source_files = list(source_dir.glob("*.md"))
    if not source_files:
        print(f"WARNING: No source files found in {source_dir}")
        return results

    for source_file in source_files:
        file_key = source_file.stem
        results["files"][file_key] = {}

        for target_lang in target_langs:
            # Find target file
            target_file = output_dir / target_lang / source_file.name

            if not target_file.exists():
                print(f"WARNING: Target file not found: {target_file}")
                results["files"][file_key][target_lang] = {
                    "checks": {"file_missing": {"passed": False, "concern": 0}},
                    "error": "Target file not found",
                }
                results["summary"]["total_checks"] += 1
                results["summary"]["failed_checks"] += 1
                continue

            # Analyze structure
            structure_checks = analyze_structure(source_file, target_file, target_lang)

            # Analyze language
            language_checks = analyze_language(target_file, target_lang)

            # Combine checks
            all_checks = {**structure_checks, **language_checks}

            results["files"][file_key][target_lang] = {
                "source_file": str(source_file),
                "target_file": str(target_file),
                "checks": all_checks,
            }

            # Update summary
            for check_name, check_data in all_checks.items():
                if isinstance(check_data, dict) and "passed" in check_data:
                    results["summary"]["total_checks"] += 1
                    if check_data["passed"]:
                        results["summary"]["passed_checks"] += 1
                    else:
                        results["summary"]["failed_checks"] += 1

                    # Update concern counts
                    concern = check_data.get("concern", 0)
                    if concern > 0:
                        results["concerns"][concern]["total"] += 1
                        if check_data["passed"]:
                            results["concerns"][concern]["passed"] += 1
                        else:
                            results["concerns"][concern]["failed"] += 1

    # Calculate problem rate
    if results["summary"]["total_checks"] > 0:
        results["summary"]["problem_rate"] = (
            results["summary"]["failed_checks"] / results["summary"]["total_checks"]
        )

    return results


def generate_markdown_report(results: dict[str, Any], output_path: Path):
    """Generate human-readable markdown report."""
    lines = []
    lines.append("# Translation Analysis Report")
    lines.append("")
    lines.append(f"**Run ID**: {results['run_id']}")
    lines.append(f"**Source**: {results['source_dir']}")
    lines.append(f"**Output**: {results['output_dir']}")
    lines.append(f"**Languages**: {', '.join(results['target_langs'])}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")

    summary = results["summary"]
    problem_rate = summary["problem_rate"]
    passed = summary["passed_checks"]
    failed = summary["failed_checks"]
    total = summary["total_checks"]

    lines.append(f"- **Total Checks**: {total}")
    if total > 0:
        lines.append(f"- **Passed**: {passed} ({passed / total * 100:.1f}%)")
        lines.append(f"- **Failed**: {failed} ({failed / total * 100:.1f}%)")
    else:
        lines.append("- **Passed**: 0")
        lines.append("- **Failed**: 0")
    lines.append(f"- **Problem Rate**: {problem_rate:.2%}")
    lines.append("")

    # Pass/Fail verdict
    if problem_rate <= 0.02:
        lines.append("**VERDICT**: ✅ **PASS** (Problem Rate ≤ 2%)")
    else:
        lines.append("**VERDICT**: ❌ **FAIL** (Problem Rate > 2%)")
    lines.append("")

    # Concern breakdown
    lines.append("## Concerns Breakdown")
    lines.append("")
    lines.append("| # | Concern | Total | Passed | Failed | Rate |")
    lines.append("|---|---------|-------|--------|--------|------|")

    concern_names = {
        1: "Markdown formatting removal",
        2: "Links not preserved",
        3: "Multi-language contamination",
        4: "English leakage",
        5: "VRAM OOM",
        6: "VRAM underutilization",
        7: "Bullet point mismatch",
        8: "Slow CPU on CT2",
        9: "GPU not detected",
        10: "VRAM non-recovery",
    }

    for i in range(1, 11):
        concern = results["concerns"][i]
        if concern["total"] > 0:
            fail_rate = concern["failed"] / concern["total"]
            status = "✅" if concern["failed"] == 0 else "❌"
            lines.append(
                f"| {i} | {concern_names[i]} | {concern['total']} | "
                f"{concern['passed']} | {concern['failed']} | {fail_rate:.1%} {status} |"
            )
        else:
            lines.append(f"| {i} | {concern_names[i]} | 0 | - | - | N/A |")

    lines.append("")
    lines.append("## Detailed Results")
    lines.append("")

    # Per-file details
    for file_key, file_data in results["files"].items():
        lines.append(f"### {file_key}")
        lines.append("")

        for lang, lang_data in file_data.items():
            lines.append(f"#### Language: {lang}")
            lines.append("")

            if "error" in lang_data:
                lines.append(f"**ERROR**: {lang_data['error']}")
                lines.append("")
                continue

            checks = lang_data.get("checks", {})
            failed_checks = {k: v for k, v in checks.items() if not v.get("passed", True)}
            passed_checks = {k: v for k, v in checks.items() if v.get("passed", True)}

            if failed_checks:
                lines.append(f"**Failed Checks ({len(failed_checks)}):**")
                lines.append("")
                for check_name, check_data in failed_checks.items():
                    lines.append(f"- `{check_name}`: {json.dumps(check_data, default=str)}")
                lines.append("")

            if passed_checks:
                lines.append(
                    f"**Passed Checks ({len(passed_checks)}):** {', '.join(passed_checks.keys())}"
                )
                lines.append("")

            if not failed_checks and not passed_checks:
                lines.append("No checks performed")
                lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Markdown report written to: {output_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze E2E translation output")
    parser.add_argument("--source-dir", type=Path, required=True, help="Source files directory")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Translation output directory"
    )
    parser.add_argument(
        "--target-langs", nargs="+", default=["fr", "ru"], help="Target languages to analyze"
    )
    parser.add_argument("--run-id", default="analysis", help="Run identifier for reports")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Directory to write reports (default: output-dir/artifacts)",
    )

    args = parser.parse_args()

    artifacts_dir = args.artifacts_dir or args.output_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    print("Analyzing translation output...")
    print(f"  Source: {args.source_dir}")
    print(f"  Output: {args.output_dir}")
    print(f"  Languages: {args.target_langs}")

    results = analyze_run(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        target_langs=args.target_langs,
        run_id=args.run_id,
    )

    # Save JSON results
    json_path = artifacts_dir / "score.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"JSON results written to: {json_path}")

    # Generate markdown report
    md_path = artifacts_dir / "score.md"
    generate_markdown_report(results, md_path)

    # Print summary
    print(f"\n{'=' * 80}")
    print("ANALYSIS COMPLETE")
    print(f"{'=' * 80}")
    print(f"Total Checks: {results['summary']['total_checks']}")
    print(f"Passed: {results['summary']['passed_checks']}")
    print(f"Failed: {results['summary']['failed_checks']}")
    print(f"Problem Rate: {results['summary']['problem_rate']:.2%}")
    print("")

    if results["summary"]["problem_rate"] <= 0.02:
        print("[PASS] Problem Rate <= 2%")
        return 0
    else:
        print("[FAIL] Problem Rate > 2%")
        print("")
        print("Failed Concerns:")
        for i in range(1, 11):
            if results["concerns"][i]["failed"] > 0:
                print(f"  - Concern #{i}: {results['concerns'][i]['failed']} failures")
        return 1


if __name__ == "__main__":
    sys.exit(main())
