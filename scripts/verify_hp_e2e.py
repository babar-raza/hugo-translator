#!/usr/bin/env python3
"""
End-to-end HP validation script.

Re-translates test corpus and verifies all HP fixes work in production pipeline.
"""

import sys
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Add user site-packages if not already in path
import site
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.append(user_site)

from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.parser.ast_nodes import NodeType
from src.translation_engine.extractor import SegmentExtractor
from src.translation_engine.models import TranslationStats
from src.utils.config_loader import ConfigService
from src.tm import TranslationMemory, L1Cache, L2PersistentTM
from src.model_runtime import ModelLoader, ModelRegistry
from src.translation_engine.engine import TranslationEngine


@dataclass
class HPValidationResult:
    """Results for a single HP fix validation."""
    hp_id: str
    description: str
    source_count: int
    translated_count: int
    preservation_rate: float
    passed: bool
    details: str = ""


class HPEndToEndValidator:
    """End-to-end validator for HP fixes."""

    def __init__(self, site_id: str, target_lang: str, config_root: Path):
        self.site_id = site_id
        self.target_lang = target_lang

        # Initialize config service
        self.config_service = ConfigService(config_root)
        self.site_profile = self.config_service.get_site_profile(site_id)

        # Initialize TM (minimal for validation)
        tm_data_dir = config_root / "data" / "tm"
        tm_data_dir.mkdir(parents=True, exist_ok=True)

        l1_cache = L1Cache(max_size=1000)
        l2_path = tm_data_dir / "l2_lmdb"
        l2_path.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(l2_path))

        self.tm = TranslationMemory(
            l1_cache=l1_cache,
            l2_persistent=l2_persistent,
            l3_semantic=None
        )

        # Initialize model loader
        registry_path = config_root / "model_registry.yaml"
        model_registry = ModelRegistry(registry_path)

        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

        self.model_loader = ModelLoader(registry=model_registry, device=device)

        # Initialize engine
        self.engine = TranslationEngine(
            config_service=self.config_service,
            tm=self.tm,
            model_loader=self.model_loader
        )

        self.parser = HugoParser()

    def count_ast_nodes(self, ast_list, node_type: NodeType) -> int:
        """Recursively count nodes of specific type."""
        count = 0
        for node in ast_list:
            if node.type == node_type:
                count += 1
            if hasattr(node, 'children') and node.children:
                count += self.count_ast_nodes(node.children, node_type)
        return count

    def count_text_patterns(self, text: str, pattern: str) -> int:
        """Count occurrences of text pattern."""
        return text.count(pattern)

    def validate_hp01_lists(
        self,
        source_files: List[Path],
        translated_files: List[Path]
    ) -> HPValidationResult:
        """Validate HP-01: List parsing and preservation."""

        source_ordered = 0
        source_bullets = 0
        trans_ordered = 0
        trans_bullets = 0

        for src_file, trans_file in zip(source_files, translated_files):
            src_text = src_file.read_text(encoding='utf-8')
            trans_text = trans_file.read_text(encoding='utf-8')

            # Count ordered lists
            src_lines = src_text.split('\n')
            trans_lines = trans_text.split('\n')

            source_ordered += sum(1 for line in src_lines if line.strip().startswith(('1.', '2.', '3.', '4.', '5.')))
            source_bullets += sum(1 for line in src_lines if line.strip().startswith(('- ', '* ', '+ ')))

            trans_ordered += sum(1 for line in trans_lines if line.strip().startswith(('1.', '2.', '3.', '4.', '5.')))
            trans_bullets += sum(1 for line in trans_lines if line.strip().startswith(('- ', '* ', '+ ')))

        total_source = source_ordered + source_bullets
        total_trans = trans_ordered + trans_bullets

        if total_source > 0:
            preservation = (total_trans / total_source) * 100
        else:
            preservation = 100.0

        passed = preservation >= 95.0

        return HPValidationResult(
            hp_id="HP-01",
            description="List Parsing and Preservation",
            source_count=total_source,
            translated_count=total_trans,
            preservation_rate=preservation,
            passed=passed,
            details=f"Ordered: {source_ordered}->{trans_ordered}, Bullets: {source_bullets}->{trans_bullets}"
        )

    def validate_hp02_inline_parsing(
        self,
        source_files: List[Path],
        translated_files: List[Path]
    ) -> Dict[str, HPValidationResult]:
        """Validate HP-02: Inline element parsing (links, bold)."""

        results = {}

        # Links
        source_links = sum(
            self.count_text_patterns(f.read_text(encoding='utf-8'), '](')
            for f in source_files
        )
        trans_links = sum(
            self.count_text_patterns(f.read_text(encoding='utf-8'), '](')
            for f in translated_files
        )

        link_preservation = (trans_links / source_links * 100) if source_links > 0 else 100.0

        results['links'] = HPValidationResult(
            hp_id="HP-02",
            description="Link Parsing and Preservation",
            source_count=source_links,
            translated_count=trans_links,
            preservation_rate=link_preservation,
            passed=link_preservation >= 95.0
        )

        # Bold markers
        source_bold = sum(
            self.count_text_patterns(f.read_text(encoding='utf-8'), '**') // 2
            for f in source_files
        )
        trans_bold = sum(
            self.count_text_patterns(f.read_text(encoding='utf-8'), '**') // 2
            for f in translated_files
        )

        bold_preservation = (trans_bold / source_bold * 100) if source_bold > 0 else 100.0

        results['bold'] = HPValidationResult(
            hp_id="HP-02",
            description="Bold Marker Preservation",
            source_count=source_bold,
            translated_count=trans_bold,
            preservation_rate=bold_preservation,
            passed=bold_preservation >= 95.0
        )

        return results

    def validate_hp04_terminology(
        self,
        source_files: List[Path],
        translated_files: List[Path]
    ) -> HPValidationResult:
        """Validate HP-04: Terminology protection."""

        protected_terms = [
            'Aspose.Slides',
            '.NET Framework',
            '.NET Core',
            'NuGet',
            'Visual Studio'
        ]

        violations = 0
        term_instances = 0

        for trans_file in translated_files:
            trans_text = trans_file.read_text(encoding='utf-8')

            for term in protected_terms:
                count = trans_text.count(term)
                term_instances += count

                # Check for common mistranslations
                if term == 'Aspose.Slides' and 'Asposa' in trans_text:
                    violations += trans_text.count('Asposa')

        passed = violations == 0

        return HPValidationResult(
            hp_id="HP-04",
            description="Terminology Protection",
            source_count=term_instances,
            translated_count=term_instances - violations,
            preservation_rate=(1 - violations/term_instances)*100 if term_instances > 0 else 100.0,
            passed=passed,
            details=f"Violations: {violations}"
        )

    def translate_corpus(
        self,
        source_dir: Path,
        output_dir: Path
    ) -> List[Path]:
        """Translate all files in source directory."""

        output_dir.mkdir(parents=True, exist_ok=True)
        translated_files = []

        for source_file in sorted(source_dir.glob('*.md')):
            logging.info(f"Translating {source_file.name}...")

            source_text = source_file.read_text(encoding='utf-8')
            parsed = self.parser.parse_string(source_text)

            # Extract segments
            extractor = SegmentExtractor(self.site_profile)
            segments = extractor.extract_all(parsed, self.site_profile.default_source_lang)

            # Create stats tracker
            stats = TranslationStats()

            # Translate using internal method
            translated_doc = self.engine._translate_to_language(
                site_id=self.site_id,
                site_profile=self.site_profile,
                doc=parsed,
                segments=segments,
                source_lang=self.site_profile.default_source_lang,
                target_lang=self.target_lang,
                force=False,
                stats=stats
            )

            output_file = output_dir / source_file.name
            output_file.write_text(translated_doc, encoding='utf-8')
            translated_files.append(output_file)

            logging.info(f"  -> {output_file.name} (done)")

        return translated_files

    def generate_report(
        self,
        results: Dict[str, HPValidationResult],
        report_path: Path
    ):
        """Generate validation report."""

        report = []
        report.append("# HP End-to-End Validation Report\n\n")
        report.append(f"**Site**: {self.site_id}\n")
        report.append(f"**Target Language**: {self.target_lang}\n\n")
        report.append("---\n\n")

        all_passed = True

        for hp_id, result in results.items():
            status = "[OK] PASS" if result.passed else "[FAIL] FAIL"
            all_passed = all_passed and result.passed

            report.append(f"## {result.hp_id}: {result.description}\n\n")
            report.append(f"- **Source Count**: {result.source_count}\n")
            report.append(f"- **Translated Count**: {result.translated_count}\n")
            report.append(f"- **Preservation Rate**: {result.preservation_rate:.1f}%\n")
            report.append(f"- **Status**: {status}\n")

            if result.details:
                report.append(f"- **Details**: {result.details}\n")

            report.append("\n")

        report.append("---\n\n")
        report.append(f"## Overall Result\n\n")

        if all_passed:
            report.append("**[OK] ALL HP FIXES VERIFIED IN PRODUCTION PIPELINE**\n")
        else:
            report.append("**[FAIL] SOME HP FIXES FAILED - REVIEW REQUIRED**\n")

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(''.join(report), encoding='utf-8')
        print(f"\nReport written to: {report_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='HP end-to-end validation')
    parser.add_argument('--source', type=Path, required=True, help='Source directory')
    parser.add_argument('--site', required=True, help='Site ID')
    parser.add_argument('--target', required=True, help='Target language')
    parser.add_argument('--output', type=Path, required=True, help='Output directory')
    parser.add_argument('--report', type=Path, default=Path('reports/hp_e2e_validation.md'))
    parser.add_argument('--config-root', type=Path, default=project_root / 'config')

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    print(f"\n{'='*60}")
    print(f"HP End-to-End Validation")
    print(f"{'='*60}\n")

    # Initialize validator
    validator = HPEndToEndValidator(args.site, args.target, args.config_root)

    # Translate corpus
    print(f"Translating test corpus...")
    source_files = sorted(args.source.glob('*.md'))
    translated_files = validator.translate_corpus(args.source, args.output)

    print(f"\nValidating HP fixes...\n")

    # Validate each HP fix
    results = {}

    hp01_result = validator.validate_hp01_lists(source_files, translated_files)
    results['hp01'] = hp01_result
    status = '[OK]' if hp01_result.passed else '[FAIL]'
    print(f"HP-01 (Lists): {hp01_result.preservation_rate:.1f}% {status}")

    hp02_results = validator.validate_hp02_inline_parsing(source_files, translated_files)
    results['hp02_links'] = hp02_results['links']
    results['hp02_bold'] = hp02_results['bold']
    status_links = '[OK]' if hp02_results['links'].passed else '[FAIL]'
    status_bold = '[OK]' if hp02_results['bold'].passed else '[FAIL]'
    print(f"HP-02 (Links): {hp02_results['links'].preservation_rate:.1f}% {status_links}")
    print(f"HP-02 (Bold): {hp02_results['bold'].preservation_rate:.1f}% {status_bold}")

    hp04_result = validator.validate_hp04_terminology(source_files, translated_files)
    results['hp04'] = hp04_result
    status = '[OK]' if hp04_result.passed else '[FAIL]'
    print(f"HP-04 (Terminology): {hp04_result.preservation_rate:.1f}% {status}")

    # Generate report
    validator.generate_report(results, args.report)

    print(f"\n{'='*60}")

    # Exit code
    all_passed = all(r.passed for r in results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == '__main__':
    main()
