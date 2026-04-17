#!/usr/bin/env python3
"""
Language Contamination Scanner for Aspose.net Repository

Scans translated markdown files to detect language contamination using
sentence-by-sentence language detection. Generates comprehensive reports
with purity percentages and contamination samples.

Usage:
    python scripts/scan_language_contamination.py --repo PATH --lang da
    python scripts/scan_language_contamination.py --repo PATH --all-languages
    python scripts/scan_language_contamination.py --help

Author: Agent-ML-D
Task: ML-004
Date: 2026-01-17
"""

import argparse
import logging
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Langdetect imports with error handling
try:
    import langdetect
    from langdetect import DetectorFactory
    # Set seed for deterministic results
    DetectorFactory.seed = 0
except ImportError:
    print("ERROR: langdetect library not found. Install with: pip install langdetect")
    sys.exit(1)

# Optional tqdm for progress bar
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("INFO: tqdm not found. Install for progress bars: pip install tqdm")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# All supported language codes — kept in sync with engine._ALL_LANGUAGE_CODES.
# Used to distinguish translated files from source files under both naming
# strategies (file-based and folder-based).
# ---------------------------------------------------------------------------
_ALL_LANGUAGE_CODES = frozenset([
    'af', 'ar', 'az', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'en', 'es', 'et',
    'fa', 'fi', 'fr', 'ga', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'ko',
    'lt', 'lv', 'ms', 'nb', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl',
    'sr', 'sv', 'th', 'tr', 'uk', 'vi', 'zh',
])

# ---------------------------------------------------------------------------
# Unicode script-range patterns — mirrors language_consistency_validator.py
# ---------------------------------------------------------------------------
_SCRIPT_ARABIC     = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]')
_SCRIPT_CYRILLIC   = re.compile(r'[\u0400-\u04FF]')
_SCRIPT_HEBREW     = re.compile(r'[\u0590-\u05FF]')
_SCRIPT_CHINESE    = re.compile(r'[\u4E00-\u9FFF]')
_SCRIPT_JAPANESE   = re.compile(r'[\u3040-\u30FF\u31F0-\u31FF]')
_SCRIPT_KOREAN     = re.compile(r'[\uAC00-\uD7AF]')
_SCRIPT_DEVANAGARI = re.compile(r'[\u0900-\u097F]')
_SCRIPT_THAI       = re.compile(r'[\u0E00-\u0E7F]')

_FORBIDDEN_SCRIPTS: dict[str, list] = {
    'bg': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ru': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'uk': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'sr': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'mk': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ar': [_SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'fa': [_SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ur': [_SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'fr': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'de': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'es': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'it': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'pt': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'nl': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'pl': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'cs': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'sk': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ro': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'hu': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'sv': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'da': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'fi': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'nb': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'no': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'tr': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'id': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ms': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'vi': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'af': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ca': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ga': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'az': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'et': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'lt': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'lv': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'hr': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'sl': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'zh': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ja': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ko': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'hi': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_THAI],
    'th': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI],
}

_STOP_WORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
    'to', 'was', 'will', 'with', 'we', 'you', 'they', 'this', 'these',
    'those', 'have', 'had', 'been', 'do', 'does', 'did',
    # German
    'der', 'die', 'das', 'ein', 'eine', 'und', 'oder', 'aber', 'wenn',
    'als', 'wie', 'auch', 'noch', 'nur', 'von', 'zu', 'mit', 'auf', 'ist',
    'sind', 'war', 'hat', 'haben', 'wird', 'sich', 'nicht',
    # French
    'le', 'la', 'les', 'un', 'une', 'des', 'et', 'ou', 'mais', 'si',
    'dans', 'de', 'du', 'pour', 'avec', 'sur', 'est', 'sont', 'se', 'ne',
    # Spanish
    'el', 'los', 'las', 'y', 'o', 'pero', 'en', 'del', 'para', 'con',
    'es', 'son', 'ha', 'han', 'no',
}


@dataclass
class FileAnalysis:
    """Analysis result for a single file."""
    file_path: str
    relative_path: str
    target_lang: str
    total_sentences: int
    correct_lang_count: int
    purity_percentage: float
    wrong_lang_samples: list[dict]
    script_mixing_issues: list[str] = field(default_factory=list)
    repetition_issues: list[str] = field(default_factory=list)
    action_taken: str = ""   # "deleted" or "" (scan only)
    error: str | None = None
    # TC-MLD-03: Multi-site and block-level additions
    site_id: str = ""        # From site profile discovery
    contaminated_blocks: list[dict] = field(default_factory=list)  # Block-level detail
    dominant_lang: str = ""  # Most common wrong language detected
    dominant_lang_confidence: float = 0.0

    @property
    def has_quality_issues(self) -> bool:
        return (
            (self.purity_percentage < 95.0 and self.total_sentences > 0)
            or bool(self.script_mixing_issues)
            or bool(self.repetition_issues)
        )


@dataclass
class ScanResult:
    """Overall scan results."""
    total_files: int
    scanned_files: int
    contaminated_files: int
    script_mixing_files: int
    repetition_files: int
    clean_files: int
    error_files: int
    deleted_files: int
    analyses: list[FileAnalysis]
    target_lang: str
    scan_timestamp: str
    repo_path: str


# ---------------------------------------------------------------------------
# TC-MLD-03: Enhanced false-positive filter for technical identifiers
# Applied before langdetect on both sentence and block level.
# ---------------------------------------------------------------------------
_RE_ASPOSE_PRODUCT = re.compile(r'Aspose\.[A-Z]\w+')
_RE_PASCAL_CASE = re.compile(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b')
_RE_ALLCAPS_ACRONYM = re.compile(r'\b[A-Z]{2,8}\b')
_RE_API_CALL = re.compile(r'\b[A-Z]\w+\.[a-zA-Z]\w+\(?[^)]*\)?')
_RE_SHORT_TOKEN = re.compile(r'\b\w{1,3}\b')


def _clean_technical_identifiers(text: str) -> str:
    """
    Strip technical identifiers from text before language detection.
    Reduces false positives from English product names, class names, and API identifiers
    appearing in otherwise correctly-translated documents.
    """
    text = _RE_ASPOSE_PRODUCT.sub(' ', text)   # Aspose.Words, Aspose.Cells…
    text = _RE_API_CALL.sub(' ', text)         # ClassName.method() before PascalCase
    text = _RE_PASCAL_CASE.sub(' ', text)      # PascalCase identifiers
    text = _RE_ALLCAPS_ACRONYM.sub(' ', text)  # PDF, ZIP, API, HTML…
    return text.strip()


def _discover_files_from_profiles(
    profiles_dir: Path,
    workers_n: int = 1,
) -> list[tuple[Path, str, str]]:
    """
    TC-MLD-03: Discover all translated files from site profile YAML configs.

    Loads each non-disabled YAML profile, expands ${ASPOSE_NET_CONTENT} in content_roots,
    and collects (file_path, lang, site_id) triples from both file-based and folder-based
    naming strategies.

    Args:
        profiles_dir: Directory containing *.yaml site profiles
        workers_n: Unused (for future parallel discovery); present for API consistency

    Returns:
        List of (file_path, lang_code, site_id) triples
    """
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass  # dotenv optional; env vars must be set externally
    try:
        import yaml
    except ImportError:
        logger.error("PyYAML not installed. Install with: pip install pyyaml")
        return []

    results: list[tuple[Path, str, str]] = []

    # Test/fixture profiles to skip (not production content)
    _SKIP_PROFILES = {
        'default', 'example', 'blog-test', 'products-test', 'golden-test',
        'e2e-reference-fixture', 'nested-list-test', 'stage-b-canary',
        'realworld_profile', 'realworld-release-candidate', 'ws5-test',
    }

    scanner = LanguageContaminationScanner()

    for yaml_file in sorted(profiles_dir.glob('*.yaml')):
        stem = yaml_file.stem
        if stem in _SKIP_PROFILES:
            logger.debug(f"Skipping non-production profile: {yaml_file.name}")
            continue

        try:
            raw = yaml.safe_load(yaml_file.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"Could not parse profile {yaml_file.name}: {e}")
            continue

        site_id = raw.get('site_id', stem)
        content_roots = raw.get('content_roots', [])

        for root_template in content_roots:
            root = Path(os.path.expandvars(str(root_template)))
            if not root.exists():
                logger.warning(f"[{site_id}] content_root missing: {root}")
                continue

            # Use existing dual-strategy file discovery
            pairs = scanner._find_all_translated_files(root)
            logger.info(f"[{site_id}] {root.name}: {len(pairs)} translated files")
            for fp, lang in pairs:
                results.append((fp, lang, site_id))

    logger.info(f"Profile discovery total: {len(results)} translated files from {profiles_dir}")
    return results


class LanguageContaminationScanner:
    """Scanner for detecting language contamination in translated files."""

    def __init__(self, min_purity: float = 95.0, min_sentence_length: int = 15):
        """
        Initialize scanner.

        Args:
            min_purity: Minimum purity percentage to consider clean (default 95%)
            min_sentence_length: Minimum sentence length for detection (default 15 chars)
        """
        self.min_purity = min_purity
        self.min_sentence_length = min_sentence_length

    def scan_repository(
        self,
        repo_path: Path,
        target_lang: str,
        all_languages: bool = False,
        check_repetition: bool = False,
        repair: bool = False,
        since_commit: str | None = None,
        fast_mode: bool = False,
    ) -> ScanResult:
        """
        Scan repository for language contamination and other quality issues.

        Args:
            repo_path: Path to repository
            target_lang: Target language code (e.g., 'da'), ignored if all_languages=True
            all_languages: If True, scan all translated language files
            check_repetition: If True, also run repetition detection
            repair: If True, delete files that fail quality checks
            since_commit: Only check files modified since this git commit SHA
            fast_mode: If True, skip the langdetect pass (regex only, ~100x faster for large repos)

        Returns:
            ScanResult with all findings
        """
        logger.info(f"Scanning repository: {repo_path}")

        # Find all target files — use the two-strategy detection that mirrors
        # the production engine (file-based naming + folder-based naming).
        if all_languages:
            file_lang_pairs = self._find_all_translated_files(repo_path)
            logger.info(f"Found {len(file_lang_pairs)} translated files")
        else:
            file_lang_pairs = self._find_translated_files_for_lang(repo_path, target_lang)
            logger.info(f"Found {len(file_lang_pairs)} {target_lang} files")

        # Filter to only files changed since a specific commit (if requested)
        if since_commit:
            changed = self._get_files_since_commit(repo_path, since_commit)
            file_lang_pairs = [
                (fp, lang) for fp, lang in file_lang_pairs
                if str(fp) in changed
            ]
            logger.info(f"After commit filter: {len(file_lang_pairs)} files to scan")

        if not file_lang_pairs:
            logger.warning("No translated files found to scan")
            return ScanResult(
                total_files=0,
                scanned_files=0,
                contaminated_files=0,
                script_mixing_files=0,
                repetition_files=0,
                clean_files=0,
                error_files=0,
                deleted_files=0,
                analyses=[],
                target_lang=target_lang,
                scan_timestamp=datetime.now().isoformat(),
                repo_path=str(repo_path),
            )

        analyses = []
        error_count = 0

        iterator = tqdm(file_lang_pairs, desc="Scanning files") if HAS_TQDM else file_lang_pairs

        for file_path, lang in iterator:
            try:
                analysis = self._analyze_file(
                    file_path, lang, repo_path,
                    check_repetition=check_repetition,
                    fast_mode=fast_mode,
                )
                # Repair mode: delete bad files
                if repair and analysis.has_quality_issues and not analysis.error:
                    try:
                        file_path.unlink()
                        analysis.action_taken = "deleted"
                        logger.info(f"Deleted bad translation: {analysis.relative_path}")
                    except OSError as e:
                        logger.warning(f"Could not delete {analysis.relative_path}: {e}")
                analyses.append(analysis)
                if analysis.error:
                    error_count += 1
            except Exception as e:
                logger.error(f"Unexpected error analyzing {file_path}: {e}")
                error_count += 1
                analyses.append(FileAnalysis(
                    file_path=str(file_path),
                    relative_path=str(file_path.relative_to(repo_path)),
                    target_lang=lang,
                    total_sentences=0,
                    correct_lang_count=0,
                    purity_percentage=100.0,
                    wrong_lang_samples=[],
                    error=str(e),
                ))

        successful = [a for a in analyses if not a.error]
        contaminated = [a for a in successful if a.purity_percentage < self.min_purity and a.total_sentences > 0]
        script_mixing = [a for a in successful if a.script_mixing_issues]
        repetition = [a for a in successful if a.repetition_issues]
        bad = {a.file_path for a in successful if a.has_quality_issues}
        clean = [a for a in successful if not a.has_quality_issues]
        deleted = [a for a in analyses if a.action_taken == "deleted"]

        return ScanResult(
            total_files=len(file_lang_pairs),
            scanned_files=len(successful),
            contaminated_files=len(contaminated),
            script_mixing_files=len(script_mixing),
            repetition_files=len(repetition),
            clean_files=len(clean),
            error_files=error_count,
            deleted_files=len(deleted),
            analyses=analyses,
            target_lang=target_lang,
            scan_timestamp=datetime.now().isoformat(),
            repo_path=str(repo_path),
        )

    # ------------------------------------------------------------------
    # TC-MLD-03: Multi-site profile scan and JSON output
    # ------------------------------------------------------------------

    def scan_all_profiles(
        self,
        profiles_dir: Path,
        block_level: bool = False,
        workers: int = 8,
        fast_mode: bool = False,
        check_repetition: bool = False,
    ) -> ScanResult:
        """
        Scan ALL production site profiles for contamination.

        Discovers files from each site profile YAML and produces a unified
        ScanResult. FileAnalysis entries include site_id for grouping.

        Args:
            profiles_dir: Directory containing site profile YAML files
            block_level: If True, run block-level detection per file
            workers: Number of parallel analysis threads
            fast_mode: If True, skip langdetect (regex only)
            check_repetition: If True, also run repetition detection
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        file_triples = _discover_files_from_profiles(profiles_dir)
        if not file_triples:
            logger.warning("No files discovered from profiles.")
            return ScanResult(
                total_files=0, scanned_files=0, contaminated_files=0,
                script_mixing_files=0, repetition_files=0, clean_files=0,
                error_files=0, deleted_files=0, analyses=[],
                target_lang='all', scan_timestamp=datetime.now().isoformat(),
                repo_path=str(profiles_dir),
            )

        logger.info(f"Starting multi-site scan: {len(file_triples)} files, {workers} workers")

        analyses: list[FileAnalysis] = []
        error_count = 0

        def _analyze_one(fp: Path, lang: str, site_id: str) -> FileAnalysis:
            try:
                # Use a common dummy root for relative paths
                root = fp.parent
                analysis = self._analyze_file(
                    fp, lang, root,
                    check_repetition=check_repetition,
                    fast_mode=fast_mode,
                )
                analysis.site_id = site_id
                if block_level and not analysis.error and not fast_mode:
                    analysis.contaminated_blocks = self._analyze_blocks(fp, lang)
                    # Update dominant lang from blocks if available
                    if analysis.contaminated_blocks:
                        from collections import Counter
                        lang_counts = Counter(b['detected_lang'] for b in analysis.contaminated_blocks)
                        if lang_counts:
                            top_lang, top_count = lang_counts.most_common(1)[0]
                            analysis.dominant_lang = top_lang
                return analysis
            except Exception as e:
                logger.error(f"Error analyzing {fp}: {e}")
                return FileAnalysis(
                    file_path=str(fp),
                    relative_path=fp.name,
                    target_lang=lang,
                    total_sentences=0,
                    correct_lang_count=0,
                    purity_percentage=100.0,
                    wrong_lang_samples=[],
                    error=str(e),
                    site_id=site_id,
                )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_analyze_one, fp, lang, site_id): (fp, lang, site_id)
                for fp, lang, site_id in file_triples
            }
            completed = 0
            for fut in as_completed(futures):
                completed += 1
                if completed % 1000 == 0:
                    logger.info(f"Multi-site scan: {completed}/{len(file_triples)} files processed")
                result = fut.result()
                analyses.append(result)
                if result.error:
                    error_count += 1

        successful = [a for a in analyses if not a.error]
        contaminated = [a for a in successful if a.purity_percentage < self.min_purity and a.total_sentences > 0]
        script_mixing = [a for a in successful if a.script_mixing_issues]
        repetition = [a for a in successful if a.repetition_issues]
        clean = [a for a in successful if not a.has_quality_issues]

        return ScanResult(
            total_files=len(file_triples),
            scanned_files=len(successful),
            contaminated_files=len(contaminated),
            script_mixing_files=len(script_mixing),
            repetition_files=len(repetition),
            clean_files=len(clean),
            error_files=error_count,
            deleted_files=0,
            analyses=analyses,
            target_lang='all',
            scan_timestamp=datetime.now().isoformat(),
            repo_path=str(profiles_dir),
        )

    def _analyze_blocks(self, file_path: Path, target_lang: str) -> list[dict]:
        """
        TC-MLD-03: Block-level contamination detection.

        Splits file into structural blocks (paragraph, heading, list item, table cell)
        and runs langdetect on each. Returns list of contaminated block records.

        Args:
            file_path: Path to translated Markdown file
            target_lang: Expected target language code

        Returns:
            List of dicts: {block_type, line_number, preview, detected_lang, confidence}
        """
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            return []

        contaminated_blocks = []
        lines = content.split('\n')
        in_code_block = False
        in_frontmatter = False
        frontmatter_seen = False

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Track frontmatter
            if stripped == '---' and not frontmatter_seen:
                in_frontmatter = not in_frontmatter
                if not in_frontmatter:
                    frontmatter_seen = True
                continue
            if in_frontmatter:
                continue

            # Track code blocks
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            if not stripped or len(stripped) < 15:
                continue

            # Classify block type
            if re.match(r'^#{1,6}\s', stripped):
                block_type = 'heading'
                text = re.sub(r'^#+\s+', '', stripped)
            elif re.match(r'^[-*+]\s', stripped):
                block_type = 'list_item'
                text = re.sub(r'^[-*+]\s+', '', stripped)
            elif re.match(r'^\d+\.\s', stripped):
                block_type = 'list_item'
                text = re.sub(r'^\d+\.\s+', '', stripped)
            elif '|' in stripped and stripped.startswith('|'):
                block_type = 'table_cell'
                # Extract first non-empty cell
                cells = [c.strip() for c in stripped.split('|') if c.strip() and c.strip() != '---']
                text = cells[0] if cells else stripped
            else:
                block_type = 'paragraph'
                text = stripped

            if len(text) < 15:
                continue

            # Apply false-positive filter
            cleaned = _clean_technical_identifiers(text)
            if len(cleaned) < 15:
                continue

            # Detect language
            try:
                from langdetect import detect_langs
                results = detect_langs(cleaned)
                if not results:
                    continue
                detected_lang = str(results[0].lang)
                conf = float(results[0].prob)

                if detected_lang != target_lang and conf >= 0.70:
                    contaminated_blocks.append({
                        'block_type': block_type,
                        'line_number': line_num,
                        'preview': text[:120],
                        'detected_lang': detected_lang,
                        'confidence': round(conf, 3),
                    })
            except Exception:
                continue

        return contaminated_blocks

    @staticmethod
    def result_to_json(result: ScanResult, min_purity: float = 95.0) -> dict:
        """
        TC-MLD-03: Serialize ScanResult to JSON-compatible dict for --json-output.

        Only includes files that have quality issues (contaminated or error files)
        in the 'files' list to keep the output manageable.
        """
        contaminated_files = [
            {
                'file_path': a.file_path,
                'site_id': a.site_id,
                'target_lang': a.target_lang,
                'purity_percentage': round(a.purity_percentage, 2),
                'threshold': min_purity,
                'dominant_lang': a.dominant_lang or (
                    a.wrong_lang_samples[0].get('detected', a.wrong_lang_samples[0].get('detected_lang', ''))
                    if a.wrong_lang_samples else ''
                ),
                'dominant_lang_confidence': a.dominant_lang_confidence,
                'contaminated_blocks': a.contaminated_blocks,
                'script_mixing': a.script_mixing_issues,
                'repetition': a.repetition_issues,
                'error': a.error,
            }
            for a in result.analyses
            if a.has_quality_issues
        ]

        return {
            'scan_timestamp': result.scan_timestamp,
            'total_files': result.total_files,
            'scanned_files': result.scanned_files,
            'contaminated_count': result.contaminated_files,
            'script_mixing_count': result.script_mixing_files,
            'error_count': result.error_files,
            'threshold': min_purity,
            'files': contaminated_files,
        }

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------

    def _find_all_translated_files(self, repo_path: Path) -> list[tuple[Path, str]]:
        """Find ALL translated markdown files using both naming strategies.

        Strategy 1 — file-based (blog.aspose.net):
            index.bg.md  →  detected lang = 'bg'
            index.md     →  source file, skip

        Strategy 2 — folder-based (docs, products, reference, …):
            /bg/products/slides/…/*.md  →  detected lang = 'bg'
            /en/products/slides/…/*.md  →  source file, skip
        """
        results: list[tuple[Path, str]] = []
        seen: set = set()

        for md in repo_path.rglob("*.md"):
            if md in seen:
                continue

            # Strategy 1: file-based  (stem ends with .{lang})
            stem = md.stem   # e.g. "index.bg"
            if '.' in stem:
                lang_candidate = stem.rsplit('.', 1)[-1].lower()
                if lang_candidate in _ALL_LANGUAGE_CODES and lang_candidate != 'en':
                    results.append((md, lang_candidate))
                    seen.add(md)
                    continue

            # Strategy 2: folder-based  (a path component is a known lang code)
            for part in md.parts:
                p = part.lower()
                if p in _ALL_LANGUAGE_CODES and p != 'en':
                    results.append((md, p))
                    seen.add(md)
                    break

        return results

    def _find_translated_files_for_lang(
        self, repo_path: Path, lang: str
    ) -> list[tuple[Path, str]]:
        """Find translated files for a specific target language."""
        results: list[tuple[Path, str]] = []
        seen: set = set()

        # Strategy 1: file-based  (*.{lang}.md)
        for md in repo_path.rglob(f"*.{lang}.md"):
            results.append((md, lang))
            seen.add(md)

        # Strategy 2: folder-based  (/{lang}/**/*.md)
        lang_dir = repo_path / lang
        if lang_dir.is_dir():
            for md in lang_dir.rglob("*.md"):
                if md not in seen:
                    results.append((md, lang))

        return results

    def _get_files_since_commit(self, repo_path: Path, since_commit: str) -> set:
        """Return absolute paths of files changed since the given commit."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since_commit, "HEAD"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            files = set()
            for line in result.stdout.splitlines():
                files.add(str(repo_path / line))
            return files
        except Exception as e:
            logger.warning(f"Could not get git diff since {since_commit}: {e}")
            return set()

    # ------------------------------------------------------------------
    # File analysis
    # ------------------------------------------------------------------

    def _analyze_file(
        self,
        file_path: Path,
        target_lang: str,
        repo_path: Path,
        check_repetition: bool = False,
        fast_mode: bool = False,
    ) -> FileAnalysis:
        """
        Analyze a single file for language contamination and other quality issues.

        Args:
            file_path: Path to file
            target_lang: Expected language code
            repo_path: Repository root path for relative paths
            check_repetition: If True, also run repetition detection
            fast_mode: If True, skip langdetect (regex checks only)

        Returns:
            FileAnalysis with results
        """
        relative_path = str(file_path.relative_to(repo_path))

        try:
            try:
                content = file_path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                logger.warning(f"UTF-8 decode failed for {relative_path}, trying latin-1")
                content = file_path.read_text(encoding='latin-1')

            # --- Script-mixing check (Unicode ranges, no ML, fast) ---
            script_mixing_issues = self._check_script_mixing_unicode(content, target_lang)

            # --- Repetition check (optional, inline implementation) ---
            repetition_issues: list[str] = []
            if check_repetition:
                repetition_issues = self._check_repetition(content)

            # --- Langdetect sentence purity check (skipped in fast mode) ---
            if fast_mode:
                return FileAnalysis(
                    file_path=str(file_path),
                    relative_path=relative_path,
                    target_lang=target_lang,
                    total_sentences=0,
                    correct_lang_count=0,
                    purity_percentage=100.0,
                    wrong_lang_samples=[],
                    script_mixing_issues=script_mixing_issues,
                    repetition_issues=repetition_issues,
                )

            cleaned_text = self._clean_text_for_detection(content)

            if len(cleaned_text) < 20:
                return FileAnalysis(
                    file_path=str(file_path),
                    relative_path=relative_path,
                    target_lang=target_lang,
                    total_sentences=0,
                    correct_lang_count=0,
                    purity_percentage=100.0,
                    wrong_lang_samples=[],
                    script_mixing_issues=script_mixing_issues,
                    repetition_issues=repetition_issues,
                    error="Text too short for langdetect analysis",
                )

            sentences = self._split_into_sentences(cleaned_text)
            total_sentences = 0
            correct_lang_count = 0
            wrong_lang_sentences = []

            for i, sentence in enumerate(sentences):
                if len(sentence.strip()) < self.min_sentence_length:
                    continue
                total_sentences += 1
                try:
                    detected_langs = langdetect.detect_langs(sentence)
                    if not detected_langs:
                        continue
                    top = detected_langs[0]
                    if top.lang == target_lang and top.prob >= 0.7:
                        correct_lang_count += 1
                    else:
                        snippet = sentence[:200] + "..." if len(sentence) > 200 else sentence
                        wrong_lang_sentences.append({
                            "sentence_num": i + 1,
                            "snippet": snippet,
                            "detected": top.lang,
                            "confidence": top.prob,
                        })
                except langdetect.LangDetectException:
                    continue

            if total_sentences == 0:
                return FileAnalysis(
                    file_path=str(file_path),
                    relative_path=relative_path,
                    target_lang=target_lang,
                    total_sentences=0,
                    correct_lang_count=0,
                    purity_percentage=100.0,
                    wrong_lang_samples=[],
                    script_mixing_issues=script_mixing_issues,
                    repetition_issues=repetition_issues,
                    error="No sentences long enough for langdetect analysis",
                )

            purity_pct = (correct_lang_count / total_sentences) * 100

            return FileAnalysis(
                file_path=str(file_path),
                relative_path=relative_path,
                target_lang=target_lang,
                total_sentences=total_sentences,
                correct_lang_count=correct_lang_count,
                purity_percentage=purity_pct,
                wrong_lang_samples=wrong_lang_sentences[:10],
                script_mixing_issues=script_mixing_issues,
                repetition_issues=repetition_issues,
            )

        except Exception as e:
            logger.error(f"Error analyzing {relative_path}: {e}")
            return FileAnalysis(
                file_path=str(file_path),
                relative_path=relative_path,
                target_lang=target_lang,
                total_sentences=0,
                correct_lang_count=0,
                purity_percentage=0.0,
                wrong_lang_samples=[],
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def _check_script_mixing_unicode(
        self, content: str, target_lang: str
    ) -> list[str]:
        """Check for Unicode-script contamination (no ML required).

        Returns a list of human-readable issue descriptions, empty if clean.
        """
        forbidden = _FORBIDDEN_SCRIPTS.get(target_lang)
        if not forbidden:
            return []

        clean = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
        clean = re.sub(r'`[^`]+`', '', clean)
        clean = re.sub(r'^---.*?^---', '', clean, flags=re.DOTALL | re.MULTILINE)
        clean = re.sub(r'https?://\S+', '', clean)
        clean = re.sub(r'\{\{[<{%].*?[>}%]\}\}', '', clean, flags=re.DOTALL)

        lines = [ln for ln in clean.splitlines() if len(ln.strip()) >= 15]
        if not lines:
            return []

        contaminated: list[str] = []
        for line in lines:
            for pattern in forbidden:
                if pattern.search(line):
                    contaminated.append(line.strip()[:120])
                    break

        if not contaminated:
            return []

        ratio = len(contaminated) / len(lines)
        if ratio <= 0.06:
            return []

        return [
            f"Script mixing: {len(contaminated)}/{len(lines)} lines ({ratio*100:.1f}%) "
            f"contain a forbidden script for '{target_lang}'. "
            f"First example: {contaminated[0]}"
        ] + [f"  Line: {c}" for c in contaminated[1:3]]

    def _check_repetition(self, content: str) -> list[str]:
        """Check for excessive word repetition (inline, no external imports).

        Returns a list of human-readable issue descriptions, empty if clean.
        """
        # Strip code blocks and frontmatter
        clean = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
        clean = re.sub(r'`[^`]+`', '', clean)
        clean = re.sub(r'^---.*?^---', '', clean, flags=re.DOTALL | re.MULTILINE)

        issues: list[str] = []

        # 1. Heading-word repetition (> 4× same word in a heading line)
        heading_threshold = 4
        for line in clean.splitlines():
            stripped = line.strip()
            if not stripped.startswith('#'):
                continue
            heading_text = stripped.lstrip('#').strip()
            words = re.findall(r'\b\w+\b', heading_text.lower())
            counts = Counter(words)
            for word, count in counts.items():
                if word in _STOP_WORDS:
                    continue
                if count > heading_threshold:
                    issues.append(
                        f"Heading repetition: '{word}' repeated {count}× in: "
                        f"'{heading_text[:80]}'"
                    )

        # 2. Document-level word-frequency anomaly (> 30% of non-stop words)
        all_words = re.findall(r'\b\w+\b', clean.lower())
        content_words = [w for w in all_words if w not in _STOP_WORDS and len(w) > 1]
        if len(content_words) >= 20:
            counts = Counter(content_words)
            top_word, top_count = counts.most_common(1)[0]
            ratio = top_count / len(content_words)
            if ratio > 0.30:
                issues.append(
                    f"Word frequency anomaly: '{top_word}' is {ratio*100:.1f}% "
                    f"of all content words ({top_count}/{len(content_words)})"
                )

        return issues

    def _split_into_sentences(self, text: str) -> list[str]:
        """
        Split text into sentences using simple heuristic.

        Args:
            text: Text to split

        Returns:
            List of sentences
        """
        # Split on period, exclamation, question mark followed by space and capital letter
        # or end of string
        sentences = re.split(r'[.!?]+(?:\s+(?=[A-Z])|$)', text)

        # Filter out empty strings and strip whitespace
        sentences = [s.strip() for s in sentences if s.strip()]

        return sentences

    def _clean_text_for_detection(self, text: str) -> str:
        """
        Remove code blocks, URLs, and shortcodes from text.

        Args:
            text: Raw translation text

        Returns:
            Cleaned text suitable for language detection
        """
        # Remove code blocks (``` ... ```)
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

        # Remove inline code (`...`)
        text = re.sub(r"`[^`]+`", "", text)

        # Remove markdown links but keep text (BEFORE removing URLs to preserve link text)
        text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)

        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)

        # Remove Hugo shortcodes ({{< ... >}}, {{/* ... */}})
        text = re.sub(r"\{\{[<{%].*?[>}%]\}\}", "", text, flags=re.DOTALL)

        # Remove placeholders
        text = re.sub(r"\{(?:PLACEHOLDER|TERM|SHORTCODE)_\d+\}", "", text)

        # Remove YAML frontmatter
        text = re.sub(r"^---\s*$.*?^---\s*$", "", text, flags=re.MULTILINE | re.DOTALL)

        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text).strip()

        return text


class ReportGenerator:
    """Generate markdown reports from scan results."""

    def generate_report(self, result: ScanResult, output_path: Path) -> None:
        """
        Generate contamination report in markdown format.

        Args:
            result: Scan results
            output_path: Path to save report
        """
        logger.info(f"Generating report: {output_path}")

        # Sort all bad analyses by purity (worst first), then append those with
        # other issues (script mixing / repetition) that passed purity check.
        contaminated = [
            a for a in result.analyses
            if not a.error and a.total_sentences > 0 and a.purity_percentage < 95.0
        ]
        contaminated_sorted = sorted(contaminated, key=lambda a: a.purity_percentage)

        # Group by priority
        critical = [a for a in contaminated_sorted if a.purity_percentage < 50.0]
        high = [a for a in contaminated_sorted if 50.0 <= a.purity_percentage < 75.0]
        medium = [a for a in contaminated_sorted if 75.0 <= a.purity_percentage < 90.0]
        low = [a for a in contaminated_sorted if 90.0 <= a.purity_percentage < 95.0]

        script_only = [
            a for a in result.analyses
            if not a.error and a.script_mixing_issues and a.purity_percentage >= 95.0
        ]
        repetition_only = [
            a for a in result.analyses
            if not a.error and a.repetition_issues and not a.script_mixing_issues
               and a.purity_percentage >= 95.0
        ]

        # Generate report content
        lines = []
        lines.append("# Translation Quality Scan Report")
        lines.append("")
        lines.append(f"**Generated:** {result.scan_timestamp}")
        lines.append(f"**Repository:** {result.repo_path}")
        lines.append(f"**Target Language:** {result.target_lang if result.target_lang != 'all' else 'all languages'}")
        lines.append("**Minimum Purity Threshold:** 95.0%  |  **Script-mixing threshold:** 6%")
        lines.append("")

        # Executive Summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append("| Metric | Count |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Files Found | {result.total_files} |")
        lines.append(f"| Successfully Scanned | {result.scanned_files} |")
        lines.append(f"| Clean Files | {result.clean_files} |")
        lines.append(f"| Language-Contaminated Files (langdetect) | {result.contaminated_files} |")
        lines.append(f"| Script-Mixing Files (Unicode) | {result.script_mixing_files} |")
        lines.append(f"| Repetition Files | {result.repetition_files} |")
        lines.append(f"| Error Files | {result.error_files} |")
        lines.append(f"| Deleted Files (repair mode) | {result.deleted_files} |")

        if result.scanned_files > 0:
            bad_total = len({
                a.file_path for a in result.analyses
                if not a.error and a.has_quality_issues
            })
            contamination_rate = (bad_total / result.scanned_files) * 100
            lines.append(f"| Overall Bad-Quality Rate | {contamination_rate:.1f}% |")

        lines.append("")

        # Priority Summary
        lines.append("## Priority Summary")
        lines.append("")
        lines.append("| Priority | Range | Count |")
        lines.append("|----------|-------|-------|")
        lines.append(f"| Critical | < 50% | {len(critical)} |")
        lines.append(f"| High | 50-75% | {len(high)} |")
        lines.append(f"| Medium | 75-90% | {len(medium)} |")
        lines.append(f"| Low | 90-95% | {len(low)} |")
        lines.append("")

        # Detailed Findings
        if contaminated_sorted:
            lines.append("## Detailed Contamination Findings")
            lines.append("")
            lines.append("Files sorted by contamination severity (worst first).")
            lines.append("")

            for i, analysis in enumerate(contaminated_sorted, 1):
                # Determine priority
                if analysis.purity_percentage < 50.0:
                    priority = "CRITICAL"
                elif analysis.purity_percentage < 75.0:
                    priority = "HIGH"
                elif analysis.purity_percentage < 90.0:
                    priority = "MEDIUM"
                else:
                    priority = "LOW"

                lines.append(f"### {i}. {analysis.relative_path}")
                lines.append("")
                lines.append(f"**Priority:** {priority}")
                lines.append(f"**Purity:** {analysis.purity_percentage:.1f}%")
                lines.append(f"**Sentences:** {analysis.total_sentences} total, {analysis.correct_lang_count} correct")
                lines.append("")

                if analysis.wrong_lang_samples:
                    lines.append("**Sample Contaminated Content:**")
                    lines.append("")
                    for sample in analysis.wrong_lang_samples[:3]:  # Show first 3
                        snippet = sample['snippet'][:200]  # Limit to 200 chars
                        lines.append(f"- Detected: `{sample['detected']}` (confidence: {sample['confidence']:.2f})")
                        lines.append("  ```")
                        lines.append(f"  {snippet}")
                        lines.append("  ```")
                        lines.append("")

                lines.append("---")
                lines.append("")

        else:
            lines.append("## Detailed Contamination Findings")
            lines.append("")
            lines.append(f"No contaminated files found. All scanned files meet the {95.0}% purity threshold.")
            lines.append("")

        # Script-mixing findings
        if script_only:
            lines.append("## Script-Mixing Issues (Unicode analysis)")
            lines.append("")
            lines.append("These files contain characters from an incompatible Unicode script "
                         "(e.g. Arabic text inside a Bulgarian translation). "
                         "The langdetect purity score passed, but script analysis flagged them.")
            lines.append("")
            for i, analysis in enumerate(script_only, 1):
                action = f" — **{analysis.action_taken.upper()}**" if analysis.action_taken else ""
                lines.append(f"### {i}. {analysis.relative_path}{action}")
                lines.append("")
                lines.append(f"**Language:** {analysis.target_lang}")
                lines.append("")
                for issue in analysis.script_mixing_issues:
                    lines.append(f"- {issue}")
                lines.append("")
                lines.append("---")
                lines.append("")

        # Repetition findings
        if repetition_only:
            lines.append("## Repetition Issues")
            lines.append("")
            lines.append("These files contain excessive word repetition (likely model hallucination).")
            lines.append("")
            for i, analysis in enumerate(repetition_only, 1):
                action = f" — **{analysis.action_taken.upper()}**" if analysis.action_taken else ""
                lines.append(f"### {i}. {analysis.relative_path}{action}")
                lines.append("")
                lines.append(f"**Language:** {analysis.target_lang}")
                lines.append("")
                for issue in analysis.repetition_issues:
                    lines.append(f"- {issue}")
                lines.append("")
                lines.append("---")
                lines.append("")

        # Errors
        error_analyses = [a for a in result.analyses if a.error and not a.has_quality_issues]
        if error_analyses:
            lines.append("## Errors and Warnings")
            lines.append("")
            lines.append("The following files encountered errors during analysis:")
            lines.append("")

            for analysis in error_analyses:
                lines.append(f"- **{analysis.relative_path}**")
                lines.append(f"  - Error: {analysis.error}")
                lines.append("")

        # Recommendations
        lines.append("## Recommendations")
        lines.append("")

        if len(critical) > 0:
            lines.append("### Critical Action Required")
            lines.append("")
            lines.append(f"{len(critical)} file(s) have severe contamination (<50% purity). These files are mostly in the wrong language and require immediate re-translation.")
            lines.append("")

        if len(high) > 0:
            lines.append("### High Priority")
            lines.append("")
            lines.append(f"{len(high)} file(s) have significant contamination (50-75% purity). Review and re-translate affected sections.")
            lines.append("")

        if len(medium) > 0:
            lines.append("### Medium Priority")
            lines.append("")
            lines.append(f"{len(medium)} file(s) have moderate contamination (75-90% purity). Review contaminated sentences and correct as needed.")
            lines.append("")

        if len(low) > 0:
            lines.append("### Low Priority")
            lines.append("")
            lines.append(f"{len(low)} file(s) have minor contamination (90-95% purity). These are close to the threshold and may contain technical terms or proper nouns detected as other languages.")
            lines.append("")

        if result.contaminated_files == 0:
            lines.append("All scanned files are clean. No action required.")
            lines.append("")

        # Footer
        lines.append("---")
        lines.append("")
        lines.append("**Report generated by:** Language Contamination Scanner (Agent-ML-D, Task ML-004)")
        lines.append(f"**Scan completed:** {result.scan_timestamp}")

        # Write report
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('\n'.join(lines), encoding='utf-8')

        logger.info(f"Report saved to: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Scan aspose.net content repo for translation quality issues.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan Bulgarian files only
  python scripts/scan_language_contamination.py --repo "D:\\path\\to\\content" --lang bg

  # Scan ALL translated files with repetition detection (report mode)
  python scripts/scan_language_contamination.py --repo "D:\\path\\to\\content" --all-languages --check-repetition

  # Scan all and DELETE bad files (repair mode)
  python scripts/scan_language_contamination.py --repo "D:\\path\\to\\content" --all-languages --check-repetition --repair

  # Only check files changed since a specific commit
  python scripts/scan_language_contamination.py --repo "D:\\path\\to\\content" --all-languages --since-commit abc1234
        """
    )

    parser.add_argument(
        '--repo',
        type=str,
        required=False,
        default=None,
        help='Path to content repository root (mutually exclusive with --profiles-dir)'
    )

    parser.add_argument(
        '--profiles-dir',
        type=str,
        default=None,
        metavar='DIR',
        help='TC-MLD-03: Scan ALL production sites from profile YAMLs in DIR '
             '(default: config/site_profiles/ when --repo is not given). '
             'Mutually exclusive with --repo.'
    )

    parser.add_argument(
        '--lang',
        type=str,
        default='da',
        help='Target language code (default: da). Ignored when --all-languages is set.'
    )

    parser.add_argument(
        '--all-languages',
        action='store_true',
        help='Scan all translated language files using both file-based and folder-based detection'
    )

    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output report path (default: reports/TRANSLATION_QUALITY_SCAN_YYYYMMDD.md)'
    )

    parser.add_argument(
        '--min-purity',
        type=float,
        default=95.0,
        help='Minimum langdetect sentence purity %% threshold (default: 95.0)'
    )

    parser.add_argument(
        '--check-repetition',
        action='store_true',
        help='Also run repetition detection on each file (heading word loops, word-frequency anomalies)'
    )

    parser.add_argument(
        '--repair',
        action='store_true',
        help='Delete files that fail quality checks so they get re-translated on the next worker run'
    )

    parser.add_argument(
        '--since-commit',
        type=str,
        default=None,
        metavar='SHA',
        help='Only check files modified since this git commit SHA'
    )

    parser.add_argument(
        '--fast',
        action='store_true',
        help='Fast mode: skip langdetect sentence analysis (regex checks only). ~100x faster, suitable for large repos'
    )

    # TC-MLD-03: New arguments for multi-site, block-level, parallelism, JSON output
    parser.add_argument(
        '--block-level',
        action='store_true',
        help='TC-MLD-03: Enable per-block (paragraph/heading/list/table) contamination detection. '
             'Slower but gives contaminated_blocks detail in JSON output.'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=8,
        metavar='N',
        help='TC-MLD-03: Number of parallel analysis threads when using --profiles-dir (default: 8). '
             'Use --workers 32 in --fast mode for large repos.'
    )

    parser.add_argument(
        '--json-output',
        type=str,
        default=None,
        metavar='PATH',
        help='TC-MLD-03: Write JSON inventory of contaminated files to this path. '
             'Used as input for force_retranslate_contaminated.py.'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine scan mode: profile-based or single-repo
    use_profiles = args.profiles_dir is not None or args.repo is None

    if not use_profiles:
        # Original single-repo mode
        repo_path = Path(args.repo)
        if not repo_path.exists():
            logger.error(f"Repository path does not exist: {repo_path}")
            sys.exit(1)
        if not repo_path.is_dir():
            logger.error(f"Repository path is not a directory: {repo_path}")
            sys.exit(1)
    else:
        # Profile-based mode — --repo not required
        profiles_dir_str = args.profiles_dir or 'config/site_profiles'
        profiles_dir = Path(profiles_dir_str)
        if not profiles_dir.exists():
            logger.error(f"Profiles directory does not exist: {profiles_dir}")
            sys.exit(1)

    if args.repair:
        logger.warning("REPAIR MODE: bad translation files will be DELETED")

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"reports/TRANSLATION_QUALITY_SCAN_{date_str}.md")

    # Initialize scanner
    scanner = LanguageContaminationScanner(min_purity=args.min_purity)

    # Perform scan
    if use_profiles:
        logger.info(f"Starting multi-site profile scan from {profiles_dir} ...")
        result = scanner.scan_all_profiles(
            profiles_dir=profiles_dir,
            block_level=args.block_level,
            workers=args.workers,
            fast_mode=args.fast,
            check_repetition=args.check_repetition,
        )
    else:
        logger.info("Starting translation quality scan...")
        result = scanner.scan_repository(
            repo_path=repo_path,
            target_lang=args.lang,
            all_languages=args.all_languages,
            check_repetition=args.check_repetition,
            repair=args.repair,
            since_commit=args.since_commit,
            fast_mode=args.fast,
        )

    # Generate Markdown report
    generator = ReportGenerator()
    generator.generate_report(result, output_path)

    # TC-MLD-03: Write JSON inventory if requested
    if args.json_output:
        import json
        json_path = Path(args.json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_data = LanguageContaminationScanner.result_to_json(result, min_purity=args.min_purity)
        json_path.write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        logger.info(f"JSON inventory written to: {json_path}")
        print(f"JSON inventory: {json_path.absolute()}")

    # Print summary
    bad_total = len({
        a.file_path for a in result.analyses
        if not a.error and a.has_quality_issues
    })
    print("\n" + "="*60)
    print("SCAN COMPLETE")
    print("="*60)
    print(f"Total files scanned:          {result.scanned_files}")
    print(f"Clean files:                  {result.clean_files}")
    print(f"Language-contaminated:        {result.contaminated_files}")
    print(f"Script-mixing issues:         {result.script_mixing_files}")
    print(f"Repetition issues:            {result.repetition_files}")
    print(f"Total bad-quality files:      {bad_total}")
    if args.repair:
        print(f"Deleted (repair mode):        {result.deleted_files}")
    print(f"Error files:                  {result.error_files}")
    print(f"\nReport saved to: {output_path.absolute()}")
    if args.json_output:
        print(f"JSON inventory:    {Path(args.json_output).absolute()}")
    print("="*60)

    if bad_total > 0 and args.json_output:
        print(f"\nTo queue contaminated files for retranslation:")
        print(f"  python scripts/force_retranslate_contaminated.py --inventory {args.json_output} --delete-outputs")

    # Exit with error code if any quality issues found (useful for CI)
    if bad_total > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
