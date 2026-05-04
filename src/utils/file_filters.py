"""
File filtering utilities for source vs. translated file detection.

This module provides utilities to filter markdown files based on localization strategy,
separating source files from already-translated files.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Comprehensive set of supported language codes
_ALL_LANGUAGE_CODES = frozenset([
    'af', 'ar', 'az', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'en', 'es', 'et',
    'fa', 'fi', 'fr', 'ga', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'ko',
    'lt', 'lv', 'ms', 'nb', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl',
    'sr', 'sv', 'th', 'tr', 'uk', 'vi', 'zh'
])


def filter_source_files(
    files: list[Path],
    site_profile,
    target_langs: list[str],
    source_lang: str = 'en'
) -> list[Path]:
    """
    Filter files to only include source files, excluding already-translated files.

    Supports two localization strategies:

    **File-based localization** (per_language_folders=False):
        - Include: index.md, _index.md, post.md
        - Exclude: index.es.md, index.de.md (files with language codes)

    **Folder-based localization** (per_language_folders=True):
        - Include: files in source language folder (e.g., /en/)
        - Exclude: files in target language folders (e.g., /de/, /es/)

    Args:
        files: List of markdown file paths to filter
        site_profile: Site profile with localization settings
            Expected attributes:
            - output_layout.per_language_folders (bool): Localization strategy
            - default_source_lang (str): Source language code
        target_langs: List of target language codes to filter out
        source_lang: Source language code (default: 'en')

    Returns:
        Filtered list containing only source files

    Raises:
        ValueError: If site_profile is None or files is not a list
        TypeError: If target_langs is not a list

    Example:
        >>> files = [Path("index.md"), Path("index.ro.md"), Path("post.md")]
        >>> result = filter_source_files(files, site_profile, ["ro"])
        >>> # Returns: [Path("index.md"), Path("post.md")]

    Performance:
        O(n) for n files in file-based mode
        O(n*m) for n files and m language codes in folder-based mode
    """
    # Validation
    if site_profile is None:
        raise ValueError("site_profile cannot be None")

    if not isinstance(files, list):
        raise TypeError(f"files must be a list, got {type(files).__name__}")

    if not isinstance(target_langs, list):
        raise TypeError(f"target_langs must be a list, got {type(target_langs).__name__}")

    if not files:
        logger.debug("Empty file list provided to filter_source_files")
        return []

    if not target_langs:
        logger.debug("Empty target_langs provided, returning all files")
        return files

    # Import here to avoid circular dependency
    from src.translation_engine.engine import _is_translated_filename

    # Extract localization strategy from site profile
    output_layout = getattr(site_profile, 'output_layout', None)
    per_language_folders = False
    if output_layout:
        per_language_folders = (
            getattr(output_layout, 'per_language_folders', False)
            if hasattr(output_layout, 'per_language_folders')
            else output_layout.get('per_language_folders', False)
        )

    # Get source language from profile
    source_lang = getattr(site_profile, 'default_source_lang', source_lang)

    filtered_files = []

    if per_language_folders:
        # Folder-based localization: ONLY include files from source language folder.
        # Files not in any language folder are ambiguous and excluded.
        source_folder_patterns = [f'/{source_lang}/', f'\\{source_lang}\\']

        for file_path in files:
            path_str = str(file_path)
            if any(pattern in path_str for pattern in source_folder_patterns):
                filtered_files.append(file_path)
    else:
        # File-based localization: use helper to exclude translated files
        for file_path in files:
            is_translated, detected_lang = _is_translated_filename(
                file_path.name, target_langs, source_lang
            )

            if is_translated:
                logger.debug(
                    f"Filtering out translated file: {file_path.name} (lang={detected_lang})"
                )
            else:
                filtered_files.append(file_path)

    # OBS-01: Summary logging for filtering operations
    filtered_count = len(files) - len(filtered_files)
    if filtered_count > 0:
        logger.info(
            f"Source file filtering: {len(filtered_files)} to translate, "
            f"{filtered_count} already-translated skipped"
        )

        # OBS-02: Warning for unusually high filter rate (potential configuration issue)
        if filtered_count > len(filtered_files) and filtered_count > 10:
            filter_pct = (filtered_count / len(files)) * 100
            logger.warning(
                f"Filtered {filtered_count} files ({filter_pct:.0f}%) - "
                f"unusually high. Verify input directory contains source files."
            )

    return filtered_files


def git_changed_files(content_root: Path, since_sha: str) -> set[Path] | None:
    """Return absolute paths of files changed since a given commit SHA.

    Runs ``git diff --name-only <since_sha> HEAD`` inside *content_root*.
    Uses ``git rev-parse --show-toplevel`` to find the repo root so that
    returned paths are correct even when *content_root* is a subdirectory.

    Args:
        content_root: Directory inside the content git repository.
        since_sha: Commit SHA to diff against HEAD.

    Returns:
        Set of absolute, resolved Paths for changed files, or None on any
        git failure (caller should treat None as "don't filter").

    Source: Pattern from GitLab project 368 (ai-powered-multilingual-translation).
    """
    try:
        # Find git repo root (content_root may be a subdirectory)
        repo_root_result = subprocess.run(
            ["git", "-C", str(content_root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30,
        )
        if repo_root_result.returncode != 0:
            logger.warning(
                "git rev-parse failed in %s: %s",
                content_root, repo_root_result.stderr.strip(),
            )
            return None
        repo_root = Path(repo_root_result.stdout.strip()).resolve()

        # Run git diff from repo root
        diff_result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-only", since_sha, "HEAD"],
            capture_output=True, text=True, timeout=60,
        )
        if diff_result.returncode != 0:
            logger.warning(
                "git diff failed (sha=%s): %s",
                since_sha, diff_result.stderr.strip(),
            )
            return None

        changed: set[Path] = set()
        for line in diff_result.stdout.splitlines():
            line = line.strip()
            if line:
                changed.add((repo_root / line).resolve())

        logger.info(
            "git diff %s..HEAD: %d changed files in %s",
            since_sha[:12], len(changed), repo_root,
        )
        return changed

    except subprocess.TimeoutExpired:
        logger.warning("git diff timed out for %s", content_root)
        return None
    except FileNotFoundError:
        logger.warning("git not found on PATH")
        return None
    except Exception as exc:
        logger.warning("git_changed_files error: %s", exc)
        return None
