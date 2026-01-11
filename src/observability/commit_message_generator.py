"""
Enhanced commit message generator for translation operations.

Generates detailed, informative commit messages that include:
- Product/section identification from file paths
- File count and path patterns
- Target language information
- Translation quality metrics (TM hit rates, validation results)
- Model information

Example output:
    Subject: chore: translate 13 Aspose.Slides presentation-converter files to CS

    Body:
        Translates Aspose.Slides presentation converter documentation to Czech:
        - products.aspose.net/slides/en/presentation-converter/ (13 files)
        - Topics: PowerPoint conversion, file formats, API usage

        Translation quality:
        - Model: facebook/nllb-200-distilled-600M (600M params)
        - TM cache hit rate: 78% (L2: 45%, L3: 33%)
        - Validators: 13/13 passed
        - Average validation score: 0.94

        Co-authored-by: Hugo Translator <hugo-translator@aspose.net>
"""
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.translation_engine.models import DirectoryResult, TranslationResult

logger = logging.getLogger(__name__)


class CommitMessageGenerator:
    """
    Generates structured, detailed commit messages for translation operations.

    Key Features:
    - Automatic product/section detection from file paths
    - Path pattern analysis and grouping
    - Quality metrics aggregation
    - Conventional commit format (chore/fix/feat)
    - Multi-language support
    """

    def __init__(self):
        """Initialize commit message generator."""
        self.product_patterns = [
            "aspose.words",
            "aspose.slides",
            "aspose.cells",
            "aspose.pdf",
            "aspose.diagram",
            "aspose.email",
            "aspose.imaging",
            "aspose.barcode",
            "aspose.tasks",
            "aspose.note",
            "aspose.3d",
            "aspose.html",
            "aspose.gis",
            "aspose.zip",
            "aspose.page",
            "aspose.psd",
            "aspose.omr",
            "aspose.svg",
            "aspose.finance",
            "aspose.drawing",
        ]

    def generate(
        self,
        output_files: List[Path],
        target_langs: List[str],
        site_id: str,
        run_id: str,
        translation_result: Optional["DirectoryResult"] = None,
        model_id: Optional[str] = None,
        tm_stats: Optional[Dict] = None,
    ) -> Tuple[str, str]:
        """
        Generate commit message subject and body.

        Args:
            output_files: List of translated output file paths
            target_langs: Target languages (e.g., ['cs', 'de'])
            site_id: Site identifier
            run_id: Translation run ID
            translation_result: Optional DirectoryResult with translation details
            model_id: Optional model identifier
            tm_stats: Optional TM statistics dict

        Returns:
            Tuple of (subject, body) strings
        """
        # Analyze file paths to extract structure
        analysis = self._analyze_paths(output_files)

        # Build subject line
        subject = self._build_subject(
            analysis=analysis,
            target_langs=target_langs,
            file_count=len(output_files),
        )

        # Build body with details
        body = self._build_body(
            analysis=analysis,
            target_langs=target_langs,
            file_count=len(output_files),
            translation_result=translation_result,
            model_id=model_id,
            tm_stats=tm_stats,
            site_id=site_id,
            run_id=run_id,
        )

        return subject, body

    def _analyze_paths(self, output_files: List[Path]) -> Dict:
        """
        Analyze output file paths to extract structure and patterns.

        Args:
            output_files: List of output file paths

        Returns:
            Analysis dict with structure information
        """
        analysis = {
            "product": None,
            "product_display": None,
            "section": None,
            "section_display": None,
            "path_groups": defaultdict(list),  # Group files by directory
            "common_ancestor": None,
            "topics": set(),
            "file_types": set(),
        }

        if not output_files:
            return analysis

        # Extract common path components
        all_parts = [list(f.parts) for f in output_files]

        # Find common ancestor path
        if len(all_parts) > 0:
            common_parts = []
            for i in range(min(len(parts) for parts in all_parts)):
                if all(parts[i] == all_parts[0][i] for parts in all_parts):
                    common_parts.append(all_parts[0][i])
                else:
                    break
            if common_parts:
                analysis["common_ancestor"] = Path(*common_parts)

        # Detect product and section from paths
        for file_path in output_files:
            parts = [p.lower() for p in file_path.parts]
            parts_str = "/".join(parts)

            # Detect Aspose product - look specifically for "products.aspose.net" or "blog.aspose.net"
            # Find the index of products.aspose.net or blog.aspose.net (not just aspose.net repo name)
            aspose_idx = None
            for i, part in enumerate(parts):
                # Match more specific patterns to avoid false positives
                if part in ["products.aspose.net", "blog.aspose.net", "kb.aspose.net", "reference.aspose.net"]:
                    if i + 1 < len(parts):
                        aspose_idx = i + 1  # The next part is the product name
                        break

            if aspose_idx and aspose_idx < len(parts):
                product_part = parts[aspose_idx]
                # Match against known products
                for product in self.product_patterns:
                    product_short = product.replace("aspose.", "")
                    if product_short in product_part:
                        product_name = product_short.title()
                        analysis["product"] = product
                        analysis["product_display"] = f"Aspose.{product_name}"
                        break

                # Look for section after product name (usually 2-3 parts after aspose_idx)
                # Skip language codes
                for i in range(aspose_idx + 1, min(aspose_idx + 4, len(parts))):
                    part = parts[i]
                    # Skip language codes and common directories
                    if part in ["en", "de", "cs", "fr", "es", "zh", "ja", "ru", "net", "java", "cpp", "python"]:
                        continue
                    # This is likely the section
                    if len(part) > 3:
                        section = part.replace("-", " ").replace("_", " ").title()
                        if not analysis["section"] and section not in ["Products", "Content", "Blog"]:
                            analysis["section"] = part
                            analysis["section_display"] = section
                            break

            # Group files by parent directory (for path pattern display)
            parent = file_path.parent
            analysis["path_groups"][parent].append(file_path)

            # Extract file types
            analysis["file_types"].add(file_path.suffix)

        # Infer topics from section names
        if analysis["section"]:
            # Common topic keywords
            topic_keywords = {
                "converter": "format conversion",
                "api": "API reference",
                "tutorial": "tutorials",
                "guide": "user guides",
                "installation": "setup and installation",
                "example": "code examples",
                "troubleshoot": "troubleshooting",
                "feature": "feature documentation",
                "reference": "API reference",
                "getting-started": "getting started",
            }
            section_lower = analysis["section"].lower()
            for keyword, topic in topic_keywords.items():
                if keyword in section_lower:
                    analysis["topics"].add(topic)

        return analysis

    def _build_subject(
        self,
        analysis: Dict,
        target_langs: List[str],
        file_count: int,
    ) -> str:
        """
        Build concise commit subject line.

        Format: chore: translate <count> <product> <section> files to <LANGS>

        Examples:
        - chore: translate 13 Aspose.Slides presentation-converter files to CS
        - chore: translate 25 kb.aspose.net documentation files to DE, FR
        - chore: translate 5 API reference files to CS

        Args:
            analysis: Path analysis dict
            target_langs: Target languages
            file_count: Number of files

        Returns:
            Subject line string
        """
        # Build language string
        langs_upper = ", ".join(sorted([lang.upper() for lang in target_langs]))

        # Build product/section identifier
        identifier_parts = []

        if analysis["product_display"]:
            identifier_parts.append(analysis["product_display"])

        if analysis["section"]:
            identifier_parts.append(analysis["section"])

        # Combine identifier
        if identifier_parts:
            identifier = " ".join(identifier_parts) + " files"
        else:
            identifier = "files"

        subject = f"chore: translate {file_count} {identifier} to {langs_upper}"

        # Ensure subject doesn't exceed 72 characters (conventional commit guideline)
        if len(subject) > 72:
            # Truncate section name if too long
            if analysis["section"] and len(analysis["section"]) > 20:
                short_section = analysis["section"][:17] + "..."
                identifier = f"{analysis['product_display']} {short_section} files" if analysis["product_display"] else f"{short_section} files"
                subject = f"chore: translate {file_count} {identifier} to {langs_upper}"

        return subject

    def _build_body(
        self,
        analysis: Dict,
        target_langs: List[str],
        file_count: int,
        translation_result: Optional["DirectoryResult"],
        model_id: Optional[str],
        tm_stats: Optional[Dict],
        site_id: str,
        run_id: str,
    ) -> str:
        """
        Build detailed commit message body.

        Includes:
        - Human-readable description
        - Path patterns and file counts
        - Topics covered
        - Translation quality metrics
        - Model information
        - TM cache statistics

        Args:
            analysis: Path analysis dict
            target_langs: Target languages
            file_count: Number of files
            translation_result: Optional DirectoryResult
            model_id: Optional model ID
            tm_stats: Optional TM statistics
            site_id: Site identifier
            run_id: Translation run ID

        Returns:
            Commit body string
        """
        lines = []

        # Section 1: High-level description
        lang_names = self._get_language_names(target_langs)
        product_section = ""
        if analysis["product_display"]:
            product_section = f" {analysis['product_display']}"
            if analysis["section_display"]:
                product_section += f" {analysis['section_display'].lower()}"

        lang_str = " and ".join(lang_names) if len(lang_names) <= 2 else f"{', '.join(lang_names[:-1])}, and {lang_names[-1]}"

        description = f"Translates{product_section} documentation to {lang_str}:"
        lines.append(description)
        lines.append("")

        # Section 2: Path patterns (show top 3 directories)
        path_groups_sorted = sorted(
            analysis["path_groups"].items(),
            key=lambda x: len(x[1]),
            reverse=True
        )[:3]

        for parent_dir, files in path_groups_sorted:
            # Show relative path from common ancestor if available
            if analysis["common_ancestor"]:
                try:
                    rel_path = parent_dir.relative_to(analysis["common_ancestor"])
                    display_path = str(rel_path).replace("\\", "/")
                except ValueError:
                    display_path = parent_dir.name
            else:
                display_path = parent_dir.name

            lines.append(f"- {display_path}/ ({len(files)} files)")

        # Show "and X more" if there are more directories
        if len(analysis["path_groups"]) > 3:
            remaining = len(analysis["path_groups"]) - 3
            lines.append(f"- ... and {remaining} more directories")

        lines.append("")

        # Section 3: Topics (if detected)
        if analysis["topics"]:
            topics_str = ", ".join(sorted(analysis["topics"]))
            lines.append(f"Topics: {topics_str}")
            lines.append("")

        # Section 4: Translation quality metrics
        lines.append("Translation quality:")

        # Model information
        if model_id:
            # Extract model name and parameters
            model_display = self._format_model_name(model_id)
            lines.append(f"- Model: {model_display}")

        # TM cache hit rates
        if tm_stats:
            hit_rate = tm_stats.get("hit_rate", 0.0)
            l1_hits = tm_stats.get("l1_hits", 0)
            l2_hits = tm_stats.get("l2_hits", 0)
            l3_hits = tm_stats.get("l3_hits", 0)
            total_lookups = tm_stats.get("total_lookups", 1)

            if total_lookups > 0:
                l1_rate = (l1_hits / total_lookups) * 100
                l2_rate = (l2_hits / total_lookups) * 100
                l3_rate = (l3_hits / total_lookups) * 100

                lines.append(f"- TM cache hit rate: {hit_rate:.1%} (L1: {l1_rate:.0f}%, L2: {l2_rate:.0f}%, L3: {l3_rate:.0f}%)")

        # Validation results
        if translation_result:
            passed_count = sum(1 for fr in translation_result.file_results if fr.success)
            failed_count = translation_result.failed_files

            if passed_count > 0:
                lines.append(f"- Validation: {passed_count}/{file_count} files passed")

            # Average validation score (if available)
            validation_scores = []
            for file_result in translation_result.file_results:
                if hasattr(file_result, "validation_score") and file_result.validation_score:
                    validation_scores.append(file_result.validation_score)

            if validation_scores:
                avg_score = sum(validation_scores) / len(validation_scores)
                lines.append(f"- Average quality score: {avg_score:.2f}")

        lines.append("")

        # Section 5: Metadata footer
        lines.append(f"Run ID: {run_id}")
        lines.append(f"Site: {site_id}")

        return "\n".join(lines)

    def _get_language_names(self, lang_codes: List[str]) -> List[str]:
        """
        Convert language codes to full names.

        Args:
            lang_codes: List of ISO 639-1 codes (e.g., ['cs', 'de'])

        Returns:
            List of language names (e.g., ['Czech', 'German'])
        """
        lang_map = {
            "cs": "Czech",
            "de": "German",
            "fr": "French",
            "es": "Spanish",
            "it": "Italian",
            "pt": "Portuguese",
            "ru": "Russian",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
            "ar": "Arabic",
            "pl": "Polish",
            "nl": "Dutch",
            "sv": "Swedish",
            "da": "Danish",
            "fi": "Finnish",
            "no": "Norwegian",
            "tr": "Turkish",
            "el": "Greek",
            "he": "Hebrew",
        }
        return [lang_map.get(code, code.upper()) for code in lang_codes]

    def _format_model_name(self, model_id: str) -> str:
        """
        Format model ID for human-readable display.

        Args:
            model_id: HuggingFace model ID (e.g., 'facebook/nllb-200-distilled-600M')

        Returns:
            Formatted model name with parameter count
        """
        # Extract parameter count
        param_patterns = {
            "418M": "418M params",
            "600M": "600M params",
            "1.2B": "1.2B params",
            "1.3B": "1.3B params",
            "3B": "3B params",
        }

        for pattern, display in param_patterns.items():
            if pattern in model_id:
                return f"{model_id} ({display})"

        return model_id


def generate_commit_message(
    output_files: List[Path],
    target_langs: List[str],
    site_id: str,
    run_id: str,
    translation_result: Optional["DirectoryResult"] = None,
    model_id: Optional[str] = None,
    tm_stats: Optional[Dict] = None,
) -> Tuple[str, str]:
    """
    Convenience function to generate commit message.

    Args:
        output_files: List of output file paths
        target_langs: Target languages
        site_id: Site identifier
        run_id: Translation run ID
        translation_result: Optional DirectoryResult
        model_id: Optional model ID
        tm_stats: Optional TM statistics

    Returns:
        Tuple of (subject, body) strings
    """
    generator = CommitMessageGenerator()
    return generator.generate(
        output_files=output_files,
        target_langs=target_langs,
        site_id=site_id,
        run_id=run_id,
        translation_result=translation_result,
        model_id=model_id,
        tm_stats=tm_stats,
    )
