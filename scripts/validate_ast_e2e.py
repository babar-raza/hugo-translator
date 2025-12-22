#!/usr/bin/env python3
"""
End-to-End AST Translation Validation Script (SR-01).

Standalone script to validate AST translation pipeline end-to-end.
Runs actual translations with AST enabled and generates structured report.

Usage:
    python scripts/validate_ast_e2e.py [--output REPORT_PATH] [--fixtures FIXTURE_DIR]

Exit Codes:
    0: All validations passed
    1: One or more validations failed
    2: Configuration or setup error
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any
from datetime import datetime
import re


def setup_paths():
    """Add project root to path for imports."""
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))


setup_paths()


from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.tm import TranslationMemory, L1Cache, L2PersistentTM
from src.model_runtime import ModelLoader, ModelRegistry


class ValidationResult:
    """Container for validation results."""

    def __init__(self, name: str):
        self.name = name
        self.success = False
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.metrics: Dict[str, Any] = {}
        self.duration: float = 0.0

    def add_error(self, message: str):
        """Add error message."""
        self.errors.append(message)
        self.success = False

    def add_warning(self, message: str):
        """Add warning message."""
        self.warnings.append(message)

    def add_metric(self, key: str, value: Any):
        """Add metric."""
        self.metrics[key] = value

    def mark_success(self):
        """Mark as successful if no errors."""
        if not self.errors:
            self.success = True


class ASTEndToEndValidator:
    """End-to-end validator for AST translation pipeline."""

    def __init__(
        self,
        config_root: Path,
        fixture_dir: Path,
        site_id: str = "kb.aspose.net",
        device: str = "cpu",
        model_id: str | None = None,
        translation_output: Path | None = None,
    ):
        """
        Initialize validator.

        Args:
            config_root: Path to config directory
            fixture_dir: Path to test fixtures directory
            site_id: Site profile ID to use for translation
            device: Model device (auto/cpu/cuda)
            model_id: Optional model override
            translation_output: Optional output directory override
        """
        self.config_root = config_root
        self.fixture_dir = fixture_dir
        self.site_id = site_id
        self.device = device
        self.model_id = model_id
        self.translation_output = translation_output
        self.config_service = ConfigService(config_root)
        self.engine = None
        self._setup_engine()

    def _setup_engine(self):
        """Initialize translation engine."""
        # Initialize TM (minimal for testing)
        tm_data_dir = self.config_root.parent / "data" / "tm_test"
        tm_data_dir.mkdir(parents=True, exist_ok=True)

        l1_cache = L1Cache(max_size=1000)
        l2_path = tm_data_dir / "l2_lmdb"
        l2_path.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(l2_path))

        tm = TranslationMemory(
            l1_cache=l1_cache,
            l2_persistent=l2_persistent,
            l3_semantic=None
        )

        # Initialize model loader
        registry_path = self.config_root / "model_registry.yaml"
        model_registry = ModelRegistry(registry_path)

        device = self.device
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        elif device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    print("CUDA requested but not available, falling back to CPU")
                    device = "cpu"
            except ImportError:
                print("PyTorch not available, falling back to CPU")
                device = "cpu"

        model_loader = ModelLoader(registry=model_registry, device=device)

        engine_kwargs = {"enable_validation": False}
        if self.model_id:
            engine_kwargs["model_id"] = self.model_id
        if self.translation_output:
            self.translation_output.mkdir(parents=True, exist_ok=True)
            engine_kwargs["output_dir_override"] = self.translation_output

        # Create engine
        self.engine = TranslationEngine(
            config_service=self.config_service,
            tm=tm,
            model_loader=model_loader,
            **engine_kwargs,
        )

    def _translate_file(self, input_file: Path, target_lang: str, use_ast: bool) -> str:
        """
        Translate file with engine.

        Args:
            input_file: Source file path
            target_lang: Target language code
            use_ast: Whether to enable AST reconstruction

        Returns:
            Translated content

        Raises:
            RuntimeError: If translation fails
        """
        # Get site profile and modify AST flag
        site_profile = self.config_service.get_site_profile(self.site_id)
        original_ast = getattr(site_profile.body, "use_ast_body_reconstruction", None)
        original_strategy = getattr(site_profile.body, "ast_segmentation_strategy", None)
        site_profile.body.use_ast_body_reconstruction = use_ast
        if use_ast and original_strategy is not None:
            site_profile.body.ast_segmentation_strategy = "adaptive"

        try:
            # Translate
            result = self.engine.translate_file(
                site_id=self.site_id,
                file_path=input_file,
                target_langs=[target_lang],
                force=False,
            )
        finally:
            if original_ast is not None:
                site_profile.body.use_ast_body_reconstruction = original_ast
            if original_strategy is not None:
                site_profile.body.ast_segmentation_strategy = original_strategy

        if result.success and result.outputs:
            output_path = result.outputs.get(target_lang)
            if output_path.exists():
                return output_path.read_text(encoding='utf-8')

        raise RuntimeError(f"Translation failed: {result.errors}")

    def _extract_indented_code_blocks(self, content: str) -> List[str]:
        """Extract indented code blocks (4-space or tab) outside fenced blocks."""
        lines = content.splitlines()
        blocks: List[str] = []
        current: List[str] = []
        in_fence = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                if current:
                    blocks.append("\n".join(current).rstrip())
                    current = []
                continue

            if in_fence:
                continue

            if line.startswith("    "):
                current.append(line[4:])
            elif line.startswith("\t"):
                current.append(line[1:])
            else:
                if current:
                    blocks.append("\n".join(current).rstrip())
                    current = []

        if current:
            blocks.append("\n".join(current).rstrip())

        return blocks

    def _extract_code_blocks(self, content: str) -> List[str]:
        """Extract fenced and indented code blocks as raw text blocks."""
        fenced_blocks = re.findall(r'```[\w]*\n(.*?)```', content, re.DOTALL)
        indented_blocks = self._extract_indented_code_blocks(content)
        return fenced_blocks + indented_blocks

    def validate_code_blocks(self, input_file: Path, target_lang: str = 'de') -> ValidationResult:
        """
        Validate code block preservation.

        Args:
            input_file: Path to code_blocks.md fixture
            target_lang: Target language for translation

        Returns:
            ValidationResult with test results
        """
        result = ValidationResult("Code Blocks Preservation")
        start_time = time.perf_counter()

        try:
            # Read source
            source_content = input_file.read_text(encoding='utf-8')

            # Translate with AST
            translated_content = self._translate_file(input_file, target_lang, use_ast=True)

            # Verify inline code
            inline_codes = ['`SaveFormat.Pptx`', '`Aspose.Slides.LowCode.Convert`']
            for code in inline_codes:
                if code not in translated_content:
                    result.add_error(f"Inline code '{code}' not preserved")

            # Verify code blocks (fenced + indented)
            source_code_blocks = self._extract_code_blocks(source_content)
            trans_code_blocks = self._extract_code_blocks(translated_content)

            result.add_metric("source_code_blocks", len(source_code_blocks))
            result.add_metric("translated_code_blocks", len(trans_code_blocks))

            if len(source_code_blocks) != len(trans_code_blocks):
                result.add_error(
                    f"Code block count mismatch: {len(source_code_blocks)} -> {len(trans_code_blocks)}"
                )

            # Verify code content unchanged
            for i, (src, trans) in enumerate(zip(source_code_blocks, trans_code_blocks)):
                if src.strip() != trans.strip():
                    result.add_error(f"Code block {i} content changed")

            # Verify language tags
            source_lang_tags = re.findall(r'```(\w+)', source_content)
            trans_lang_tags = re.findall(r'```(\w+)', translated_content)

            if source_lang_tags != trans_lang_tags:
                result.add_error(f"Language tags changed: {source_lang_tags} -> {trans_lang_tags}")

            result.mark_success()

        except Exception as e:
            result.add_error(f"Exception during validation: {e}")

        result.duration = time.perf_counter() - start_time
        return result

    def validate_links_images(self, input_file: Path, target_lang: str = 'de') -> ValidationResult:
        """
        Validate link and image preservation.

        Args:
            input_file: Path to links_images.md fixture
            target_lang: Target language for translation

        Returns:
            ValidationResult with test results
        """
        result = ValidationResult("Links and Images Preservation")
        start_time = time.perf_counter()

        try:
            # Read source
            source_content = input_file.read_text(encoding='utf-8')

            # Translate with AST
            translated_content = self._translate_file(input_file, target_lang, use_ast=True)

            # Verify URLs preserved
            urls_to_check = [
                'https://docs.aspose.com/',
                'https://api.aspose.com',
                'https://docs.aspose.com/slides/',
                'https://example.com',
                'https://www.aspose.com/logo.png',
                './images/screenshot.png',
                'https://www.aspose.com',
                'https://support.aspose.com',
            ]

            for url in urls_to_check:
                if url not in translated_content:
                    result.add_error(f"URL '{url}' not preserved")

            # Verify link counts (allow normalization to inline links)
            source_links = source_content.count('](')
            trans_links = translated_content.count('](')
            result.add_metric("source_links", source_links)
            result.add_metric("translated_links", trans_links)

            if source_links != trans_links:
                result.add_warning(f"Link count mismatch: {source_links} -> {trans_links}")

            # Verify image counts
            source_images = source_content.count('![')
            trans_images = translated_content.count('![')
            result.add_metric("source_images", source_images)
            result.add_metric("translated_images", trans_images)

            if source_images != trans_images:
                result.add_error(f"Image count mismatch: {source_images} -> {trans_images}")

            # Reference links and autolinks may be normalized to inline links
            if '[aspose-link]: https://www.aspose.com' not in translated_content:
                result.add_warning("Reference-style link definition not preserved")

            if '<https://support.aspose.com>' not in translated_content:
                result.add_warning("Autolink not preserved")

            result.mark_success()

        except Exception as e:
            result.add_error(f"Exception during validation: {e}")

        result.duration = time.perf_counter() - start_time
        return result

    def validate_formatting(self, input_file: Path, target_lang: str = 'de') -> ValidationResult:
        """
        Validate inline formatting preservation.

        Args:
            input_file: Path to inline_formatting.md fixture
            target_lang: Target language for translation

        Returns:
            ValidationResult with test results
        """
        result = ValidationResult("Inline Formatting Preservation")
        start_time = time.perf_counter()

        try:
            # Read source
            source_content = input_file.read_text(encoding='utf-8')

            # Translate with AST
            translated_content = self._translate_file(input_file, target_lang, use_ast=True)

            # Verify bold markers
            source_bold = source_content.count('**')
            trans_bold = translated_content.count('**')
            result.add_metric("source_bold_markers", source_bold)
            result.add_metric("translated_bold_markers", trans_bold)

            if source_bold != trans_bold:
                result.add_error(f"Bold marker count mismatch: {source_bold} -> {trans_bold}")

            # Verify italic markers
            source_italic = len(re.findall(r'(?<!\*)\*(?!\*)', source_content))
            trans_italic = len(re.findall(r'(?<!\*)\*(?!\*)', translated_content))
            result.add_metric("source_italic_markers", source_italic)
            result.add_metric("translated_italic_markers", trans_italic)

            if source_italic != trans_italic:
                result.add_error(f"Italic marker count mismatch: {source_italic} -> {trans_italic}")

            # Verify code within formatting
            inline_codes = ['`SaveFormat.Pptx`', '`Aspose.Slides.LowCode`']
            for code in inline_codes:
                if code not in translated_content:
                    result.add_error(f"Inline code '{code}' not preserved in formatting")

            # Verify nested formatting patterns
            if '***' not in translated_content:
                result.add_error("Bold italic markers (***) not preserved")

            if not re.search(r'\*\*.*`.*`.*\*\*', translated_content):
                result.add_warning("Bold with code inside pattern not found")

            result.mark_success()

        except Exception as e:
            result.add_error(f"Exception during validation: {e}")

        result.duration = time.perf_counter() - start_time
        return result

    def run_all_validations(self) -> List[ValidationResult]:
        """
        Run all validation tests.

        Returns:
            List of ValidationResult objects
        """
        results = []

        # Define test fixtures
        test_cases = [
            ("code_blocks.md", self.validate_code_blocks),
            ("links_images.md", self.validate_links_images),
            ("inline_formatting.md", self.validate_formatting),
        ]

        for fixture_name, validator_func in test_cases:
            fixture_path = self.fixture_dir / fixture_name

            if not fixture_path.exists():
                result = ValidationResult(f"Fixture: {fixture_name}")
                result.add_error(f"Fixture file not found: {fixture_path}")
                results.append(result)
                continue

            try:
                result = validator_func(fixture_path)
                results.append(result)
            except Exception as e:
                result = ValidationResult(f"Fixture: {fixture_name}")
                result.add_error(f"Unexpected error: {e}")
                results.append(result)

        return results


def generate_report(results: List[ValidationResult], output_path: Path):
    """
    Generate validation report.

    Args:
        results: List of validation results
        output_path: Path to write report
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Calculate summary
    total_tests = len(results)
    passed_tests = sum(1 for r in results if r.success)
    failed_tests = total_tests - passed_tests
    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    total_duration = sum(r.duration for r in results)

    # Build report
    report_lines = [
        "# AST End-to-End Translation Validation Report",
        "",
        f"**Generated**: {timestamp}",
        f"**Taskcard**: SR-01 - End-to-End AST Translation Validation",
        "",
        "## Summary",
        "",
        f"- **Total Tests**: {total_tests}",
        f"- **Passed**: {passed_tests}",
        f"- **Failed**: {failed_tests}",
        f"- **Total Errors**: {total_errors}",
        f"- **Total Warnings**: {total_warnings}",
        f"- **Total Duration**: {total_duration:.2f}s",
        "",
        f"**Status**: {'PASS' if failed_tests == 0 else 'FAIL'}",
        "",
        "## Test Results",
        "",
    ]

    # Add individual test results
    for result in results:
        status_icon = "PASS" if result.success else "FAIL"
        report_lines.extend([
            f"### {status_icon} {result.name}",
            "",
            f"- **Duration**: {result.duration:.2f}s",
            f"- **Status**: {'PASS' if result.success else 'FAIL'}",
            "",
        ])

        if result.metrics:
            report_lines.append("**Metrics**:")
            report_lines.append("")
            for key, value in result.metrics.items():
                report_lines.append(f"- `{key}`: {value}")
            report_lines.append("")

        if result.errors:
            report_lines.append("**Errors**:")
            report_lines.append("")
            for error in result.errors:
                report_lines.append(f"- ERROR {error}")
            report_lines.append("")

        if result.warnings:
            report_lines.append("**Warnings**:")
            report_lines.append("")
            for warning in result.warnings:
                report_lines.append(f"- WARN {warning}")
            report_lines.append("")

    # Add acceptance criteria checklist
    report_lines.extend([
        "## Acceptance Criteria",
        "",
        "### SR-01 Checklist",
        "",
        f"- [{'x' if passed_tests >= 3 else ' '}] At least 3 fixture files tested end-to-end",
        f"- [{'x' if any('Code Blocks' in r.name and r.success for r in results) else ' '}] Code blocks preserved unchanged",
        f"- [{'x' if any('Links' in r.name and r.success for r in results) else ' '}] Links preserved with correct URLs",
        f"- [{'x' if any('Links' in r.name and r.success for r in results) else ' '}] Images preserved",
        f"- [{'x' if any('Formatting' in r.name and r.success for r in results) else ' '}] Inline formatting preserved",
        f"- [{'x' if failed_tests == 0 else ' '}] All tests pass",
        "",
    ])

    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text('\n'.join(report_lines), encoding='utf-8')

    print(f"\nReport written to: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="End-to-End AST Translation Validation (SR-01)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output report path (default: reports/ast_e2e_validation_TIMESTAMP.md)"
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path(__file__).parent.parent / "tests" / "fixtures" / "hp06",
        help="Path to fixture directory (default: tests/fixtures/hp06)"
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        default=Path(__file__).parent.parent / "config",
        help="Path to config root (default: config)"
    )
    parser.add_argument(
        "--site-id",
        type=str,
        default="kb.aspose.net",
        help="Site profile ID to use for translation (default: kb.aspose.net)"
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda"],
        default="cpu",
        help="Device for model inference (default: cpu)"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override model ID from registry (e.g., nllb_200_600m)"
    )
    parser.add_argument(
        "--translation-output",
        type=Path,
        default=None,
        help="Output directory override for translated files"
    )

    args = parser.parse_args()

    # Determine output path
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = Path(__file__).parent.parent / "reports" / f"ast_e2e_validation_{timestamp}.md"

    print("=" * 80)
    print("AST End-to-End Translation Validation (SR-01)")
    print("=" * 80)
    print(f"Fixture directory: {args.fixtures}")
    print(f"Config root: {args.config_root}")
    print(f"Output report: {args.output}")
    print(f"Site ID: {args.site_id}")
    print(f"Device: {args.device}")
    print(f"Model override: {args.model}")
    print(f"Translation output: {args.translation_output}")
    print()

    # Validate setup
    if not args.fixtures.exists():
        print(f"ERROR: Fixture directory not found: {args.fixtures}")
        return 2

    if not args.config_root.exists():
        print(f"ERROR: Config root not found: {args.config_root}")
        return 2

    # Create validator
    try:
        print("Initializing validator...")
        validator = ASTEndToEndValidator(
            config_root=args.config_root,
            fixture_dir=args.fixtures,
            site_id=args.site_id,
            device=args.device,
            model_id=args.model,
            translation_output=args.translation_output,
        )
        print("Validator initialized")
        print()
    except Exception as e:
        print(f"ERROR: Failed to initialize validator: {e}")
        return 2

    # Run validations
    print("Running validations...")
    print()
    results = validator.run_all_validations()

    # Print summary
    print()
    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    for result in results:
        status = "PASS" if result.success else "FAIL"
        print(f"{status} - {result.name} ({result.duration:.2f}s)")
        if result.errors:
            for error in result.errors:
                print(f"  ERROR {error}")

    print()

    # Generate report
    generate_report(results, args.output)

    # Determine exit code
    failed_tests = sum(1 for r in results if not r.success)
    if failed_tests > 0:
        print(f"\nVALIDATION FAILED: {failed_tests} test(s) failed")
        return 1
    else:
        print("\nVALIDATION PASSED: All tests successful")
        return 0


if __name__ == "__main__":
    sys.exit(main())
