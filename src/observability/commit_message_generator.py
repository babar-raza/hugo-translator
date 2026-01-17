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

    def __init__(self, config_service=None):
        """Initialize commit message generator.

        Args:
            config_service: Optional ConfigService instance for loading site profiles.
                          If None, will try to create one when needed.
        """
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
        self.config_service = config_service

    def generate(
        self,
        output_files: List[Path],
        target_langs: List[str],
        site_id: str,
        run_id: str,
        site_profile: Optional[Dict] = None,
        translation_result: Optional["DirectoryResult"] = None,
        model_id: Optional[str] = None,
        tm_stats: Optional[Dict] = None,
    ) -> Tuple[str, str]:
        """
        Generate commit message subject and body.

        Args:
            output_files: List of translated output file paths
            target_langs: Target languages (e.g., ['cs', 'de'])
            site_id: Site identifier (primary)
            run_id: Translation run ID
            site_profile: Optional site profile dict with display_name
            translation_result: Optional DirectoryResult with translation details
            model_id: Optional model identifier
            tm_stats: Optional TM statistics dict

        Returns:
            Tuple of (subject, body) strings
        """
        # Detect all sites represented in output_files
        site_ids = self._detect_sites_from_paths(output_files, site_id)
        is_multi_site = len(site_ids) > 1

        logger.debug(f"Site detection: site_id={site_id}, detected_sites={site_ids}")

        if is_multi_site:
            logger.info(f"Multi-site commit detected: {site_ids}")

        # Extract site display name (only meaningful for single-site commits)
        site_display_name = None
        if not is_multi_site:
            if site_profile and "display_name" in site_profile:
                site_display_name = site_profile["display_name"]
            else:
                logger.warning(f"No display_name in site profile for {site_id}")

        # Analyze file paths to extract structure
        analysis = self._analyze_paths(output_files)

        # Build subject line
        subject = self._build_subject(
            analysis=analysis,
            target_langs=target_langs,
            file_count=len(output_files),
            site_ids=site_ids,
            site_display_name=site_display_name,
        )

        # Build body with details
        body = self._build_body(
            output_files=output_files,
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

    def _detect_sites_from_paths(
        self,
        output_files: List[Path],
        primary_site_id: str,
    ) -> List[str]:
        """
        Detect which sites the output files belong to.

        Returns list of site_ids. If files span multiple sites, returns multiple IDs.
        If all files are from primary_site_id, returns single-item list.

        Strategy: Load all site profiles and check which content_roots match file paths.

        Args:
            output_files: List of output file paths
            primary_site_id: Primary site ID from caller

        Returns:
            List of detected site IDs
        """
        detected_sites = set()

        try:
            # Load all site profiles
            if self.config_service is None:
                # Try to create ConfigService if not provided
                from src.utils.config_loader import ConfigService
                try:
                    self.config_service = ConfigService("./config")
                except Exception as e:
                    logger.warning(f"Failed to create ConfigService: {e}")
                    return [primary_site_id]

            # First, check if primary_site_id matches the files
            # If it does, just use that and avoid false positives from generic profiles
            try:
                primary_profile = self.config_service.get_site_profile(primary_site_id)
                for file_path in output_files:
                    file_str = str(file_path).replace("\\", "/")
                    for content_root in primary_profile.content_roots:
                        content_root_normalized = content_root.replace("\\", "/")
                        if content_root_normalized in file_str:
                            # Primary site matches, use only this one
                            logger.debug(f"Primary site {primary_site_id} matches files, using only this site")
                            return [primary_site_id]
            except Exception as e:
                logger.warning(f"Failed to check primary site {primary_site_id}: {e}")

            # Primary site didn't match, check all sites
            site_ids = self.config_service.list_sites()

            # Load each profile and check content_roots
            for site_id in site_ids:
                # Skip default/generic profiles to avoid false positives
                if site_id in ["default", "example"]:
                    continue

                try:
                    profile = self.config_service.get_site_profile(site_id)

                    # Check if any output file matches this site's content_roots
                    for file_path in output_files:
                        file_str = str(file_path).replace("\\", "/")

                        for content_root in profile.content_roots:
                            # Normalize content_root
                            content_root_normalized = content_root.replace("\\", "/")

                            if content_root_normalized in file_str:
                                detected_sites.add(site_id)
                                break  # Found match for this site

                except Exception as e:
                    logger.warning(f"Failed to load profile {site_id}: {e}")
                    continue

            # Fallback to primary_site_id if no sites detected
            if not detected_sites:
                detected_sites.add(primary_site_id)

            return sorted(list(detected_sites))

        except Exception as e:
            logger.warning(f"Failed to detect sites from paths: {e}")
            return [primary_site_id]  # Fallback to single site

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

            # Detect Aspose product - look specifically for site patterns
            # Find the index of specific aspose.net sites (not just aspose.net repo name)
            aspose_idx = None
            for i, part in enumerate(parts):
                # Match more specific patterns to avoid false positives
                if part in ["docs.aspose.net", "products.aspose.net", "blog.aspose.net", "kb.aspose.net", "reference.aspose.net"]:
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
        site_ids: List[str],
        site_display_name: Optional[str] = None,
    ) -> str:
        """
        Build commit subject line.

        Format: (chore): Translated {N} {Product} {ContentType} to {Language}.

        Examples:
        - (chore): Translated 15 Aspose.Slides Documentations to Catalan.
        - (chore): Translated 13 Aspose.Slides Knowledge Base Articles to Czech.
        - (chore): Translated 25 Aspose.Words Blog posts to French.

        Args:
            analysis: Path analysis dict
            target_langs: Target languages
            file_count: Number of files
            site_ids: List of detected site IDs
            site_display_name: Optional human-readable site type

        Returns:
            Subject line string
        """
        is_multi_site = len(site_ids) > 1
        primary_site_id = site_ids[0]

        # Determine product name
        if analysis["product_display"]:
            product_name = analysis["product_display"]  # e.g., "Aspose.Slides"
        elif self._is_home_family(analysis, None):
            product_name = "Home"
        else:
            # Fallback: Use site_id as product name if no product detected
            product_name = primary_site_id

        # Determine content type based on site
        site_content_types = {
            "kb.aspose.net": "Knowledge Base Articles",
            "blog.aspose.net": "Blog Posts",
            "products.aspose.net": "Landing Pages",
            "docs.aspose.net": "Documentations",
            "reference.aspose.net": "References",
            "about.aspose.net": "Pages",
            "www.aspose.net": "Pages",
            "websites.aspose.net": "Pages",
        }

        # Use site-specific content type if available
        content_type = site_content_types.get(primary_site_id)

        logger.debug(f"Content type lookup: primary_site_id={primary_site_id}, content_type={content_type}, site_display_name={site_display_name}")

        if not content_type:
            # Fallback to display_name or "pages"
            if is_multi_site:
                content_type = "pages"
            elif site_display_name:
                content_type = site_display_name
            else:
                content_type = "pages"

        logger.debug(f"Final content_type={content_type}")

        # Determine language (singular if one, comma-separated if multiple)
        if len(target_langs) == 1:
            lang_name = self._get_language_names([target_langs[0]])[0]
        else:
            # Multiple languages: "German, French, and Spanish"
            lang_names = self._get_language_names(target_langs)
            if len(lang_names) == 2:
                lang_name = f"{lang_names[0]} and {lang_names[1]}"
            else:
                lang_name = f"{', '.join(lang_names[:-1])}, and {lang_names[-1]}"

        subject = f"(chore): Translated {file_count} {product_name} {content_type} to {lang_name}."

        # Ensure subject doesn't exceed 72 characters (git best practice)
        if len(subject) > 72:
            # Truncate before the period and add ellipsis
            subject = subject[:69] + "..."

        return subject

    def _is_home_family(self, analysis: Dict, output_files: Optional[List[Path]]) -> bool:
        """
        Check if files belong to 'home' product family.

        Strategy:
        1. Check if no product detected from paths
        2. Optionally verify by checking paths for 'home' keyword

        Args:
            analysis: Path analysis dict
            output_files: Optional list of output files for path verification

        Returns:
            True if content is from "home" family, False otherwise
        """
        # Strategy 1: Check if no product detected
        if not analysis["product"]:
            # Strategy 2: Verify by checking paths for 'home' keyword
            if output_files:
                for file_path in output_files[:5]:  # Sample first 5 files
                    parts = [p.lower() for p in file_path.parts]
                    if "home" in parts:
                        return True

            # If no product and no explicit 'home' in path, assume it's generic content
            return True

        return False

    def _build_body(
        self,
        output_files: List[Path],
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
            output_files: List of output file paths
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
        # Special handling for _index.md files
        index_files = [f for f in output_files if f.name == "_index.md"]
        is_all_index_files = len(index_files) == len(output_files) and len(output_files) > 0

        if is_all_index_files:
            # All files are _index.md - show parent directory names instead
            parent_dirs = sorted(set(f.parent.name for f in output_files))

            if len(parent_dirs) <= 5:
                dirs_str = ", ".join(parent_dirs)
                lines.append(f"- {len(output_files)} section index files ({dirs_str})")
            else:
                dirs_str = ", ".join(parent_dirs[:3])
                lines.append(f"- {len(output_files)} section index files ({dirs_str}, +{len(parent_dirs)-3} more)")
        else:
            # Mixed files or no index files - use existing path grouping logic
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
            # CRITICAL FIX: Filter file_results to only those in output_files
            # Problem: translation_result.file_results contains results for ALL languages,
            # but output_files only contains files for the current commit (one language).
            # This caused impossible ratios like "48/5 files passed".
            output_paths = set(output_files)

            # Match file_results to output_files by checking if any output path matches
            relevant_results = []
            for fr in translation_result.file_results:
                if hasattr(fr, 'outputs') and fr.outputs:
                    # Check if any output file in this result matches our output_files
                    for output_path in fr.outputs.values():
                        if output_path in output_paths:
                            relevant_results.append(fr)
                            break  # Found a match, no need to check other outputs

            if relevant_results:
                passed_count = sum(1 for fr in relevant_results if fr.success)
                failed_count = len(relevant_results) - passed_count

                lines.append(f"- Validation: {passed_count}/{len(relevant_results)} files passed")

                # Average validation score (if available)
                validation_scores = []
                for file_result in relevant_results:
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
            "ca": "Catalan",
            "bg": "Bulgarian",
            "hr": "Croatian",
            "sk": "Slovak",
            "sl": "Slovenian",
            "et": "Estonian",
            "lv": "Latvian",
            "lt": "Lithuanian",
            "mt": "Maltese",
            "ga": "Irish",
            "hu": "Hungarian",
            "ro": "Romanian",
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
    site_profile: Optional[Dict] = None,
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
        site_profile: Optional site profile dict with display_name
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
        site_profile=site_profile,
        translation_result=translation_result,
        model_id=model_id,
        tm_stats=tm_stats,
    )
