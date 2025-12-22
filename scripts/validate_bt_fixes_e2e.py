#!/usr/bin/env python
"""
End-to-End Validation of FIX-BT-02 and FIX-BT-03 with Real Model and Real Data.

Tests:
1. FIX-BT-02: Zero language markers in output
2. FIX-BT-03: Frontmatter fields translated
3. No regressions in code block preservation
4. No regressions in structure preservation
5. Batch translation statistics
"""

import sys
import re
from pathlib import Path
import logging
import site
from copy import deepcopy

# Add user site-packages to path (for --user installed packages)
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

# ANSI colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BOLD = '\033[1m'
RESET = '\033[0m'


def print_header(text):
    """Print section header."""
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}{text}{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}\n")


def print_success(text):
    """Print success message."""
    print(f"{GREEN}[PASS]{RESET} {text}")


def print_error(text):
    """Print error message."""
    print(f"{RED}[FAIL]{RESET} {text}")


def print_info(text):
    """Print info message."""
    print(f"{YELLOW}[INFO]{RESET} {text}")


def validate_bt_02_no_markers(output_md: str) -> bool:
    """
    Validate FIX-BT-02: No language markers in output.

    Returns:
        True if validation passes, False otherwise
    """
    print_header("FIX-BT-02: Language Marker Sanitization")

    # Pattern for language markers: __xx__ where xx is 2 lowercase letters
    marker_pattern = r'__[a-z]{2}__'
    markers = re.findall(marker_pattern, output_md)

    if markers:
        print_error(f"Found {len(markers)} language markers in output")
        # Show unique markers
        unique_markers = set(markers)
        for marker in list(unique_markers)[:10]:
            print(f"  - {marker}")
        if len(unique_markers) > 10:
            print(f"  ... and {len(unique_markers) - 10} more unique markers")
        return False
    else:
        print_success("No language markers found in output")
        return True


def validate_bt_03_frontmatter(source_frontmatter: dict, translated_frontmatter: dict) -> bool:
    """
    Validate FIX-BT-03: Frontmatter fields translated.

    Returns:
        True if validation passes, False otherwise
    """
    print_header("FIX-BT-03: Frontmatter Translation")

    all_passed = True

    # Check translatable fields
    translatable_fields = ['title', 'description', 'keywords', 'step1', 'step2', 'step3', 'step4', 'step5']
    translated_count = 0

    for field in translatable_fields:
        if field in source_frontmatter and field in translated_frontmatter:
            source_value = source_frontmatter[field]
            translated_value = translated_frontmatter[field]

            # Check if translated (should be different from source)
            if isinstance(source_value, str) and isinstance(translated_value, str):
                if source_value != translated_value:
                    print_success(f"Field '{field}' translated: '{source_value[:50]}...' -> '{translated_value[:50]}...'")
                    translated_count += 1
                else:
                    print_error(f"Field '{field}' NOT translated (identical to source)")
                    all_passed = False

            elif isinstance(source_value, list) and isinstance(translated_value, list):
                if source_value != translated_value:
                    print_success(f"Field '{field}' translated: {len(source_value)} items")
                    # Debug: show first item comparison
                    if len(source_value) > 0 and len(translated_value) > 0:
                        print_info(f"  Example: '{source_value[0]}' -> '{translated_value[0]}'")
                    translated_count += 1
                else:
                    print_error(f"Field '{field}' NOT translated (identical to source)")
                    # Debug: show what we're comparing
                    print_info(f"  Source: {source_value}")
                    print_info(f"  Translated: {translated_value}")
                    all_passed = False

    # Check protected fields (should NOT be translated)
    protected_fields = ['slug', 'productkey', 'platformkey', 'date', 'weight', 'draft', 'type']

    for field in protected_fields:
        if field in source_frontmatter and field in translated_frontmatter:
            source_value = source_frontmatter[field]
            translated_value = translated_frontmatter[field]

            if source_value == translated_value:
                print_success(f"Protected field '{field}' unchanged: {source_value}")
            else:
                print_error(f"Protected field '{field}' was modified: {source_value} -> {translated_value}")
                all_passed = False

    # Overall frontmatter translation rate
    if translated_count > 0:
        print_info(f"Translated {translated_count} frontmatter fields")
    else:
        print_error("No frontmatter fields were translated")
        all_passed = False

    return all_passed


def validate_code_preservation(source_md: str, output_md: str) -> bool:
    """
    Validate that code blocks are preserved.

    Returns:
        True if validation passes, False otherwise
    """
    print_header("Code Block Preservation")

    # Count code blocks in source
    source_code_blocks = re.findall(r'```', source_md)
    output_code_blocks = re.findall(r'```', output_md)

    source_count = len(source_code_blocks)
    output_count = len(output_code_blocks)

    if source_count == output_count:
        print_success(f"Code blocks preserved: {source_count // 2} blocks")
        return True
    else:
        print_error(f"Code block count mismatch: source={source_count // 2}, output={output_count // 2}")
        return False


def validate_structure(source_md: str, output_md: str) -> bool:
    """
    Validate that markdown structure is preserved.

    Returns:
        True if validation passes, False otherwise
    """
    print_header("Structure Preservation")

    all_passed = True

    # Check headings
    source_headings = re.findall(r'^#{1,6}\s', source_md, re.MULTILINE)
    output_headings = re.findall(r'^#{1,6}\s', output_md, re.MULTILINE)

    if len(source_headings) == len(output_headings):
        print_success(f"Headings preserved: {len(source_headings)} headings")
    else:
        print_error(f"Heading count mismatch: source={len(source_headings)}, output={len(output_headings)}")
        all_passed = False

    # Check lists
    source_lists = re.findall(r'^[\-\*]\s', source_md, re.MULTILINE)
    output_lists = re.findall(r'^[\-\*]\s', output_md, re.MULTILINE)

    if len(source_lists) == len(output_lists):
        print_success(f"List items preserved: {len(source_lists)} items")
    else:
        print_error(f"List item count mismatch: source={len(source_lists)}, output={len(output_lists)}")
        all_passed = False

    # Check links
    source_links = re.findall(r'\[([^\]]+)\]\(([^\)]+)\)', source_md)
    output_links = re.findall(r'\[([^\]]+)\]\(([^\)]+)\)', output_md)

    if len(source_links) == len(output_links):
        print_success(f"Links preserved: {len(source_links)} links")
    else:
        print_error(f"Link count mismatch: source={len(source_links)}, output={len(output_links)}")
        all_passed = False

    return all_passed


def main():
    """Run end-to-end validation with real model and real data."""
    print_header("End-to-End Validation: FIX-BT-02 + FIX-BT-03")
    print_info("Testing with REAL M2M100 model and REAL data")
    print_info("Target: Zero language markers + Frontmatter translation")

    # Source file
    source_path = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides/en/presentation-converter/how-to-convert-odp-to-powerpoint-pptx-csharp.md")

    if not source_path.exists():
        print_error(f"Source file not found: {source_path}")
        return 1

    print_info(f"Source file: {source_path.name}")

    # Read source
    with open(source_path, 'r', encoding='utf-8') as f:
        source_content = f.read()

    print_info(f"Source size: {len(source_content)} characters")

    # Parse
    print_info("Parsing source document...")
    parser = HugoParser()
    doc = parser.parse_string(source_content)

    if not doc or not doc.ast:
        print_error("Failed to parse source document")
        return 1

    print_success(f"Parsed successfully: {len(doc.ast)} root nodes")

    # Extract source frontmatter for validation (deep copy to preserve original)
    source_frontmatter = deepcopy(doc.frontmatter) if doc.frontmatter else {}

    # Load real translation model
    print_info("Loading M2M100 translation model...")
    try:
        # Create model registry and loader
        registry_path = Path("config/model_registry.yaml")
        model_registry = ModelRegistry(registry_path)

        # Auto-detect device
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print_info(f"Using device: {device}")

        model_loader = ModelLoader(registry=model_registry, device=device)
        mt_model = model_loader.load_model("m2m100_1.2b")
        print_success("Model loaded successfully")
    except Exception as e:
        print_error(f"Failed to load model: {e}")
        print_info("Make sure M2M100 model is downloaded:")
        print_info("  python scripts/download_m2m100_model.py")
        return 1

    # Extract text units
    print_info("Extracting text units from AST and frontmatter...")
    extractor = TextUnitExtractor(segmentation_strategy="leaf_only", mt_model=mt_model)
    plan = extractor.extract_from_ast(doc.ast, frontmatter=doc.frontmatter)
    units = plan.units

    translatable_units = [u for u in units if not u.do_not_translate]
    frontmatter_units = [u for u in units if u.node_addr and u.node_addr.startswith('frontmatter.')]

    print_success(f"Extracted {len(units)} total units:")
    print_info(f"  - {len(translatable_units)} translatable")
    print_info(f"  - {len(frontmatter_units)} frontmatter")
    print_info(f"  - {len(units) - len(translatable_units)} non-translatable (code, etc.)")

    # Translate with REAL model
    print_info("Translating with M2M100 (this may take a minute)...")
    translated_units = extractor.batch_translate_units(
        units,
        mt_model,
        src_lang="en",
        tgt_lang="de",
        batch_size=20  # Reasonable batch size
    )

    # Get batch statistics
    stats = extractor.batch_stats
    print_success("Translation completed")
    print_info(f"  - Total batches: {stats.get('total_batches', 0)}")
    print_info(f"  - Successful batches: {stats.get('successful_batches', 0)}")
    print_info(f"  - Fallback batches: {stats.get('fallback_batches', 0)}")
    print_info(f"  - Delimiter corruptions: {stats.get('delimiter_corruptions', 0)}")

    # Calculate fallback rate
    total_batches = stats.get('total_batches', 0)
    fallback_batches = stats.get('fallback_batches', 0)
    if total_batches > 0:
        fallback_rate = (fallback_batches / total_batches) * 100
        print_info(f"  - Fallback rate: {fallback_rate:.1f}%")

    # Apply translations
    print_info("Applying translations to AST and frontmatter...")
    renderer = ASTRenderer()
    renderer.apply_translations(doc.ast, translated_units, frontmatter=doc.frontmatter)

    # Render to markdown
    print_info("Rendering translated markdown...")
    output_md = renderer.render_to_markdown(doc.ast)

    print_success(f"Rendered output: {len(output_md)} characters")

    # Save output
    output_path = Path("c:/Users/prora/OneDrive/Documents/GitHub/hugo-translator/validation_output_de.md")
    with open(output_path, 'w', encoding='utf-8') as f:
        # Write frontmatter
        f.write("---\n")
        for key, value in doc.frontmatter.items():
            if isinstance(value, list):
                f.write(f"{key}: {value}\n")
            else:
                f.write(f"{key}: \"{value}\"\n")
        f.write("---\n\n")
        # Write body
        f.write(output_md)

    print_success(f"Output saved to: {output_path}")

    # Run validations
    print("\n")
    results = {
        "FIX-BT-02 (No Markers)": validate_bt_02_no_markers(output_md),
        "FIX-BT-03 (Frontmatter)": validate_bt_03_frontmatter(source_frontmatter, doc.frontmatter),
        "Code Preservation": validate_code_preservation(source_content, output_md),
        "Structure Preservation": validate_structure(source_content, output_md),
    }

    # Summary
    print_header("Validation Summary")
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_test in results.items():
        if passed_test:
            print_success(f"{test_name}")
        else:
            print_error(f"{test_name}")

    print(f"\n{BOLD}Result: {passed}/{total} validations passed{RESET}")

    if passed == total:
        print(f"\n{GREEN}{BOLD}ALL VALIDATIONS PASSED{RESET}")
        print(f"\n{BOLD}Next Steps:{RESET}")
        print("  1. Review translated output: validation_output_de.md")
        print("  2. Proceed with FIX-BT-01 (Delimiter Corruption fix)")
        print("  3. Run full test suite: pytest tests/")
        return 0
    else:
        print(f"\n{RED}{BOLD}VALIDATIONS FAILED{RESET}")
        print(f"\n{BOLD}Failed: {total - passed} validation(s){RESET}")
        print("Review errors above and investigate issues")
        return 1


if __name__ == "__main__":
    sys.exit(main())
