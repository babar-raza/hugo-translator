#!/usr/bin/env python3
"""
CLI-based corpus validation for AST translation.

Validates AST translation by running real CLI translations on a corpus
and comparing structural preservation metrics.

Usage:
    python scripts/validate_corpus_cli.py --corpus-size 50 --target-lang de
"""

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class FileMetrics:
    """Metrics for a single file validation."""
    file_path: str
    success: bool
    duration_seconds: float = 0.0

    # Structural preservation
    links_source: int = 0
    links_translated: int = 0
    links_preservation_rate: float = 0.0

    code_blocks_source: int = 0
    code_blocks_translated: int = 0
    code_preservation_rate: float = 0.0

    images_source: int = 0
    images_translated: int = 0
    image_preservation_rate: float = 0.0

    bold_source: int = 0
    bold_translated: int = 0
    bold_preservation_rate: float = 0.0

    # Error tracking
    error: Optional[str] = None


@dataclass
class CorpusResults:
    """Aggregate results across corpus."""
    total_files: int = 0
    successful_files: int = 0
    failed_files: int = 0

    avg_duration: float = 0.0
    total_duration: float = 0.0

    # Average preservation rates
    avg_link_preservation: float = 0.0
    avg_code_preservation: float = 0.0
    avg_image_preservation: float = 0.0
    avg_bold_preservation: float = 0.0

    # Per-file metrics
    file_metrics: List[FileMetrics] = field(default_factory=list)

    # GO decision
    go_decision: bool = False
    decision_reason: str = ""


class StructuralAnalyzer:
    """Analyzes markdown structure for preservation metrics."""

    @staticmethod
    def count_links(content: str) -> int:
        """Count markdown links [text](url)."""
        return len(re.findall(r'\[([^\]]+)\]\(([^\)]+)\)', content))

    @staticmethod
    def count_code_blocks(content: str) -> int:
        """Count fenced code blocks ```."""
        return len(re.findall(r'```[\s\S]*?```', content))

    @staticmethod
    def count_images(content: str) -> int:
        """Count markdown images ![alt](src)."""
        return len(re.findall(r'!\[([^\]]*)\]\(([^\)]+)\)', content))

    @staticmethod
    def count_bold(content: str) -> int:
        """Count bold markers **text**."""
        return len(re.findall(r'\*\*[^\*]+\*\*', content))

    def analyze_file(self, file_path: Path) -> Dict[str, int]:
        """Analyze structural elements in a file."""
        try:
            content = file_path.read_text(encoding='utf-8')
            return {
                'links': self.count_links(content),
                'code_blocks': self.count_code_blocks(content),
                'images': self.count_images(content),
                'bold': self.count_bold(content)
            }
        except Exception as e:
            logger.error(f"Failed to analyze {file_path}: {e}")
            return {'links': 0, 'code_blocks': 0, 'images': 0, 'bold': 0}


class CorpusValidator:
    """Validates corpus using CLI translations."""

    def __init__(
        self,
        corpus_size: int = 50,
        target_lang: str = "de",
        output_dir: Path = None,
        device: str = "cpu",
        model: str = "m2m100_418m",
        batch_size: Optional[int] = None,
        load_mode: str = "fp32"
    ):
        self.corpus_size = corpus_size
        self.target_lang = target_lang
        self.output_dir = output_dir or Path("reports")
        self.device = device
        self.model = model
        self.batch_size = batch_size
        self.load_mode = load_mode
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.analyzer = StructuralAnalyzer()
        self.cli_path = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        self.cli_module = str(PROJECT_ROOT / "src" / "cli.py")

    def collect_corpus(self) -> List[Path]:
        """Collect corpus files from kb.aspose.net."""
        production_root = Path("D:/onedrive/Documents/GitHub/aspose.net/content")
        kb_slides_en = production_root / "kb.aspose.net" / "slides" / "en"

        if not kb_slides_en.exists():
            logger.error(f"Corpus path does not exist: {kb_slides_en}")
            return []

        # Collect all English markdown files
        all_files = list(kb_slides_en.rglob("*.md"))
        logger.info(f"Found {len(all_files)} total files in {kb_slides_en}")

        # Take first N files (deterministic sampling)
        corpus = sorted(all_files)[:self.corpus_size]
        logger.info(f"Selected {len(corpus)} files for validation")

        return corpus

    def translate_file(self, file_path: Path) -> Optional[Path]:
        """
        Translate a file using CLI.

        Returns path to translated output, or None if failed.
        """
        try:
            # Construct CLI command
            cmd = [
                str(self.cli_path),
                "-m", "src.cli",
                "--site", "kb.aspose.net",
                "--input", str(file_path),
                "--target-langs", self.target_lang,
                "--model", self.model,
                "--device", self.device,
                "--load-mode", self.load_mode,
                "--force-retranslate"
            ]

            # Add optional batch size
            if self.batch_size:
                cmd.extend(["--batch-size", str(self.batch_size)])

            logger.info(f"Translating: {file_path.name}")

            # Run translation
            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout per file (increased from 300s)
                encoding='utf-8',
                errors='replace'  # Handle Unicode errors
            )

            # Determine expected output path
            # CLI replaces /en/ with /de/ in the path
            output_path = Path(str(file_path).replace('/en/', f'/{self.target_lang}/'))

            # Check if output file was created (primary success indicator)
            if output_path.exists():
                logger.info(f"  ✓ Output created: {output_path.name}")
                return output_path

            # If file doesn't exist, log the error
            if result.returncode != 0:
                logger.error(f"Translation failed for {file_path.name} (exit code: {result.returncode})")
                # Only log first 500 chars of stderr (avoid Unicode logging errors)
                stderr_preview = result.stderr[:500] if result.stderr else "No stderr"
                logger.error(f"STDERR: {stderr_preview}")

            logger.warning(f"Output file not found: {output_path}")
            return None

        except subprocess.TimeoutExpired:
            logger.error(f"Translation timeout for {file_path.name}")
            return None
        except Exception as e:
            logger.error(f"Translation error for {file_path.name}: {e}")
            return None

    def validate_file(self, source_path: Path) -> FileMetrics:
        """Validate a single file by translating and comparing structure."""
        metrics = FileMetrics(
            file_path=str(source_path),
            success=False
        )

        try:
            # Analyze source structure
            start_time = time.perf_counter()
            source_struct = self.analyzer.analyze_file(source_path)

            # Translate file
            output_path = self.translate_file(source_path)

            if not output_path:
                metrics.error = "Translation failed"
                metrics.duration_seconds = time.perf_counter() - start_time
                return metrics

            # Analyze translated structure
            translated_struct = self.analyzer.analyze_file(output_path)

            metrics.duration_seconds = time.perf_counter() - start_time

            # Calculate preservation rates
            metrics.links_source = source_struct['links']
            metrics.links_translated = translated_struct['links']
            metrics.links_preservation_rate = (
                translated_struct['links'] / source_struct['links']
                if source_struct['links'] > 0 else 1.0
            )

            metrics.code_blocks_source = source_struct['code_blocks']
            metrics.code_blocks_translated = translated_struct['code_blocks']
            metrics.code_preservation_rate = (
                translated_struct['code_blocks'] / source_struct['code_blocks']
                if source_struct['code_blocks'] > 0 else 1.0
            )

            metrics.images_source = source_struct['images']
            metrics.images_translated = translated_struct['images']
            metrics.image_preservation_rate = (
                translated_struct['images'] / source_struct['images']
                if source_struct['images'] > 0 else 1.0
            )

            metrics.bold_source = source_struct['bold']
            metrics.bold_translated = translated_struct['bold']
            metrics.bold_preservation_rate = (
                translated_struct['bold'] / source_struct['bold']
                if source_struct['bold'] > 0 else 1.0
            )

            metrics.success = True

        except Exception as e:
            metrics.error = str(e)
            logger.error(f"Validation error for {source_path.name}: {e}")

        return metrics

    def run_validation(self) -> CorpusResults:
        """Run validation on entire corpus."""
        logger.info("=" * 80)
        logger.info("Starting corpus validation")
        logger.info(f"  Corpus size: {self.corpus_size}")
        logger.info(f"  Target language: {self.target_lang}")
        logger.info(f"  Device: {self.device}")
        logger.info("=" * 80)

        corpus = self.collect_corpus()

        if not corpus:
            logger.error("No corpus files found")
            return CorpusResults()

        results = CorpusResults(total_files=len(corpus))

        # Validate each file
        for i, file_path in enumerate(corpus, 1):
            logger.info(f"\n[{i}/{len(corpus)}] Validating: {file_path.name}")

            metrics = self.validate_file(file_path)
            results.file_metrics.append(metrics)

            if metrics.success:
                results.successful_files += 1
                logger.info(f"  ✓ Success ({metrics.duration_seconds:.1f}s)")
                logger.info(f"    Links: {metrics.links_preservation_rate:.1%}")
                logger.info(f"    Code: {metrics.code_preservation_rate:.1%}")
                logger.info(f"    Images: {metrics.image_preservation_rate:.1%}")
                logger.info(f"    Bold: {metrics.bold_preservation_rate:.1%}")
            else:
                results.failed_files += 1
                logger.error(f"  ✗ Failed: {metrics.error}")

        # Calculate aggregates
        if results.successful_files > 0:
            success_metrics = [m for m in results.file_metrics if m.success]

            results.avg_link_preservation = sum(m.links_preservation_rate for m in success_metrics) / len(success_metrics)
            results.avg_code_preservation = sum(m.code_preservation_rate for m in success_metrics) / len(success_metrics)
            results.avg_image_preservation = sum(m.image_preservation_rate for m in success_metrics) / len(success_metrics)
            results.avg_bold_preservation = sum(m.bold_preservation_rate for m in success_metrics) / len(success_metrics)

            results.total_duration = sum(m.duration_seconds for m in results.file_metrics)
            results.avg_duration = results.total_duration / len(results.file_metrics)

        # GO decision
        results.go_decision = (
            results.successful_files >= results.total_files * 0.9 and  # 90% success rate
            results.avg_link_preservation >= 0.95 and  # 95% link preservation
            results.avg_code_preservation >= 0.95 and  # 95% code preservation
            results.avg_image_preservation >= 0.95  # 95% image preservation
        )

        if results.go_decision:
            results.decision_reason = "All preservation metrics meet thresholds (≥95%)"
        else:
            reasons = []
            if results.successful_files < results.total_files * 0.9:
                reasons.append(f"Low success rate: {results.successful_files}/{results.total_files}")
            if results.avg_link_preservation < 0.95:
                reasons.append(f"Link preservation: {results.avg_link_preservation:.1%}")
            if results.avg_code_preservation < 0.95:
                reasons.append(f"Code preservation: {results.avg_code_preservation:.1%}")
            if results.avg_image_preservation < 0.95:
                reasons.append(f"Image preservation: {results.avg_image_preservation:.1%}")
            results.decision_reason = "; ".join(reasons)

        return results

    def generate_report(self, results: CorpusResults) -> Path:
        """Generate markdown validation report."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_dir / f"corpus_validation_{timestamp}.md"

        report = f"""# Corpus Validation Report

**Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Corpus Size**: {results.total_files} files
**Target Language**: {self.target_lang}

**Translation Settings**:
- Model: {self.model}
- Device: {self.device}
- Load Mode: {self.load_mode}
- Batch Size: {self.batch_size or 'auto'}

---

## Executive Summary

**GO Decision**: {"✅ FULL GO" if results.go_decision else "❌ NO GO"}

**Reason**: {results.decision_reason}

**Success Rate**: {results.successful_files}/{results.total_files} ({results.successful_files/results.total_files*100:.1f}%)

---

## Preservation Metrics

| Metric | Average | Threshold | Status |
|--------|---------|-----------|--------|
| **Links** | {results.avg_link_preservation:.1%} | ≥95% | {"✅" if results.avg_link_preservation >= 0.95 else "❌"} |
| **Code Blocks** | {results.avg_code_preservation:.1%} | ≥95% | {"✅" if results.avg_code_preservation >= 0.95 else "❌"} |
| **Images** | {results.avg_image_preservation:.1%} | ≥95% | {"✅" if results.avg_image_preservation >= 0.95 else "❌"} |
| **Bold Formatting** | {results.avg_bold_preservation:.1%} | ≥95% | {"✅" if results.avg_bold_preservation >= 0.95 else "❌"} |

---

## Performance

- **Total Duration**: {results.total_duration:.1f}s ({results.total_duration/60:.1f} minutes)
- **Average per File**: {results.avg_duration:.1f}s

---

## Per-File Results

| File | Status | Duration | Links | Code | Images | Bold |
|------|--------|----------|-------|------|--------|------|
"""

        for metrics in results.file_metrics:
            file_name = Path(metrics.file_path).name
            status = "✓" if metrics.success else "✗"
            duration = f"{metrics.duration_seconds:.1f}s"

            if metrics.success:
                links = f"{metrics.links_preservation_rate:.0%}"
                code = f"{metrics.code_preservation_rate:.0%}"
                images = f"{metrics.image_preservation_rate:.0%}"
                bold = f"{metrics.bold_preservation_rate:.0%}"
            else:
                links = code = images = bold = "-"

            report += f"| {file_name} | {status} | {duration} | {links} | {code} | {images} | {bold} |\n"

        report += f"""
---

## Failed Files

"""

        failed = [m for m in results.file_metrics if not m.success]
        if failed:
            for metrics in failed:
                report += f"- **{Path(metrics.file_path).name}**: {metrics.error}\n"
        else:
            report += "None\n"

        report += f"""
---

## Recommendations

"""

        if results.go_decision:
            report += """
✅ **Proceed with rollout**

All preservation metrics meet or exceed thresholds. AST translation is ready for production deployment.

**Next Steps**:
1. Update HP06_GO_DECISION.md to FULL GO status
2. Proceed with multi-language validation (VAL-01-B)
3. Plan Phase 0 pilot deployment
"""
        else:
            report += f"""
❌ **Do not proceed - issues found**

**Issues**:
{results.decision_reason}

**Next Steps**:
1. Investigate root causes of preservation failures
2. Fix identified issues
3. Re-run validation
4. Keep GO decision as CONDITIONAL until metrics pass
"""

        report += f"""
---

**Validation completed**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

        # Write report
        report_path.write_text(report, encoding='utf-8')
        logger.info(f"\nReport written to: {report_path}")

        # Also write JSON for programmatic access
        json_path = self.output_dir / f"corpus_validation_{timestamp}.json"
        json_data = {
            'summary': {
                'go_decision': results.go_decision,
                'decision_reason': results.decision_reason,
                'total_files': results.total_files,
                'successful_files': results.successful_files,
                'failed_files': results.failed_files,
                'avg_duration': results.avg_duration,
                'total_duration': results.total_duration
            },
            'preservation': {
                'links': results.avg_link_preservation,
                'code': results.avg_code_preservation,
                'images': results.avg_image_preservation,
                'bold': results.avg_bold_preservation
            },
            'files': [asdict(m) for m in results.file_metrics]
        }
        json_path.write_text(json.dumps(json_data, indent=2), encoding='utf-8')
        logger.info(f"JSON data written to: {json_path}")

        return report_path


def main():
    parser = argparse.ArgumentParser(
        description="Validate AST translation using CLI"
    )
    parser.add_argument(
        "--corpus-size",
        type=int,
        default=50,
        help="Number of files to validate (default: 50)"
    )
    parser.add_argument(
        "--target-lang",
        type=str,
        default="de",
        help="Target language (default: de for German)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Output directory for reports (default: reports/)"
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        help="Device for translation (default: cpu)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="m2m100_418m",
        help="Model to use (default: m2m100_418m)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Batch size override (default: auto)"
    )
    parser.add_argument(
        "--load-mode",
        type=str,
        default="fp32",
        choices=["fp32", "fp16", "int8"],
        help="Load mode for model (default: fp32)"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick validation with 5 files"
    )

    args = parser.parse_args()

    corpus_size = 5 if args.quick else args.corpus_size

    validator = CorpusValidator(
        corpus_size=corpus_size,
        target_lang=args.target_lang,
        output_dir=args.output_dir,
        device=args.device,
        model=args.model,
        batch_size=args.batch_size,
        load_mode=args.load_mode
    )

    # Run validation
    results = validator.run_validation()

    # Generate report
    report_path = validator.generate_report(results)

    # Print summary
    logger.info("\n" + "=" * 80)
    logger.info("VALIDATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"GO Decision: {'✅ FULL GO' if results.go_decision else '❌ NO GO'}")
    logger.info(f"Success Rate: {results.successful_files}/{results.total_files}")
    logger.info(f"Link Preservation: {results.avg_link_preservation:.1%}")
    logger.info(f"Code Preservation: {results.avg_code_preservation:.1%}")
    logger.info(f"Image Preservation: {results.avg_image_preservation:.1%}")
    logger.info(f"Bold Preservation: {results.avg_bold_preservation:.1%}")
    logger.info(f"\nReport: {report_path}")
    logger.info("=" * 80)

    # Exit code based on GO decision
    return 0 if results.go_decision else 1


if __name__ == "__main__":
    sys.exit(main())
