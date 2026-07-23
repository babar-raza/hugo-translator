"""
Canonical, config-driven content discovery for site profiles.

Single source of truth for "how do I enumerate a site's content and pair
each source file with its per-locale translated counterpart," keyed purely
off `SiteProfile.output_layout.per_language_folders`. This replaces
independently hand-rolled implementations that previously existed across
the quality/audit script family and (for the pattern-substitution logic)
mirrors what `TranslationEngine._get_output_path()` already did correctly,
extracted here so it can be imported without constructing a full
`TranslationEngine`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

# Canonical superset of known language codes -- used (unioned with a site's
# own target_langs) to recognize translated filenames even for codes not
# configured as a target language on every site. This is the single source
# of truth other modules should import instead of hand-copying.
ALL_LANGUAGE_CODES = frozenset(
    [
        "af", "ar", "az", "bg", "ca", "cs", "da", "de", "el", "es", "et",
        "fa", "fi", "fr", "ga", "he", "hi", "hr", "hu", "id", "it", "ja",
        "ko", "lt", "lv", "ms", "nb", "nl", "no", "pl", "pt", "ro", "ru",
        "sk", "sl", "sr", "sv", "th", "tr", "uk", "vi", "zh",
    ]
)


def is_translated_filename(
    filename: str, target_langs: list[str], source_lang: str = "en"
) -> tuple[bool, str | None]:
    """
    Check if filename appears to be a translated file based on language code pattern.

    Detects filenames matching pattern: {name}.{lang}.(md|markdown)
    Examples:
        - index.es.md -> (True, 'es')
        - index.ES.MD -> (True, 'es')  # case-insensitive
        - tutorial.fr.markdown -> (True, 'fr')
        - index.md -> (False, None)  # source file
        - index.es.da.md -> (True, 'da')  # matches last language code

    Whitelist-based deliberately: a bare "any 2-3 letter suffix" regex (the
    approach found duplicated ad hoc elsewhere) would misclassify stray
    files like `index.bak.md` as a translation. Only codes in
    ALL_LANGUAGE_CODES or the caller's own target_langs count.
    """
    all_lang_codes = ALL_LANGUAGE_CODES | set(target_langs)
    all_lang_codes = all_lang_codes - {source_lang}

    sorted_langs = sorted(all_lang_codes, key=len, reverse=True)
    escaped_langs = [re.escape(lang) for lang in sorted_langs]
    lang_pattern = "|".join(escaped_langs)
    pattern = rf"\.({lang_pattern})\.(md|markdown)$"

    compiled_pattern = re.compile(pattern, re.IGNORECASE)
    match = compiled_pattern.search(filename)

    if match:
        detected_lang = match.group(1)
        detected_lang_lower = detected_lang.lower()
        for lang in sorted_langs:
            if lang.lower() == detected_lang_lower:
                return (True, lang)
        return (True, detected_lang)

    return (False, None)


def _get_output_layout(site_profile: Any) -> tuple[bool, str | None]:
    """Extract (per_language_folders, pattern) from a SiteProfile or dict."""
    output_layout = getattr(site_profile, "output_layout", None)
    per_language_folders = False
    pattern = None
    if output_layout:
        per_language_folders = (
            getattr(output_layout, "per_language_folders", False)
            if hasattr(output_layout, "per_language_folders")
            else output_layout.get("per_language_folders", False)
        )
        pattern = (
            getattr(output_layout, "pattern", None)
            if hasattr(output_layout, "pattern")
            else output_layout.get("pattern", None)
        )
    return per_language_folders, pattern


def resolve_translated_path(
    site_profile: Any, source_path: Path, target_lang: str
) -> Path:
    """
    Compute the expected translated file path for source_path in target_lang.

    Mirrors the per_language_folders/pattern branch of
    TranslationEngine._get_output_path() -- the CLI-override and
    output_dir-fallback wrapper behavior are caller-specific concerns and
    stay in engine.py, not here.
    """
    per_language_folders, pattern = _get_output_layout(site_profile)
    source_lang = getattr(site_profile, "default_source_lang", "en")

    if per_language_folders:
        source_str = str(source_path)
        for sep in ("/", "\\"):
            source_folder = f"{sep}{source_lang}{sep}"
            target_folder = f"{sep}{target_lang}{sep}"
            if source_folder in source_str:
                return Path(source_str.replace(source_folder, target_folder, 1))
        for sep in ("/", "\\"):
            if source_str.endswith(f"{sep}{source_lang}"):
                return Path(source_str[: -len(source_lang)] + target_lang)
        # Layout declares per-language-folders but the source path doesn't
        # contain a source-lang path segment -- matches the original
        # engine.py behavior of falling through to the generic fallback
        # below rather than trying the file-based pattern branch.

    elif pattern:
        filename_stem = source_path.stem
        filename_ext = source_path.suffix
        # Supply every placeholder name observed across the real registry
        # (`{filename}.{lang}{ext}` and `{path_stem}.{lang}.md`) so any of
        # them can be used without a KeyError -- confirmed during this
        # extraction that the prior engine.py implementation only ever
        # supplied `filename`, which would raise KeyError for
        # www.aspose.net.yaml's `{path_stem}.{lang}.md` pattern the moment
        # its file-based branch actually ran.
        output_filename = pattern.format(
            filename=filename_stem,
            path_stem=filename_stem,
            lang=target_lang,
            ext=filename_ext,
            path=str(source_path.name),
        )
        return source_path.parent / output_filename

    # Absolute last resort: no usable layout info at all.
    return source_path.parent / target_lang / source_path.name


def resolve_source_root(site_profile: Any, content_root: Path) -> Path:
    """
    The root a source file's path should be made relative to, for computing
    a stable `rel` (e.g. for family/platform-depth checks or JSONL output).

    per_language_folders=True: content_root/{default_source_lang} (matches
    discover_source_files' own walk root). per_language_folders=False:
    content_root itself (there is no source-language subdirectory).
    """
    per_language_folders, _ = _get_output_layout(site_profile)
    if per_language_folders:
        source_lang = getattr(site_profile, "default_source_lang", "en")
        return content_root / source_lang
    return content_root


def discover_source_files(site_profile: Any, content_root: Path) -> list[Path]:
    """
    Enumerate this site's source-language (default_source_lang) files.

    For per_language_folders=True sites, walks content_root/{source_lang}.
    For per_language_folders=False (file-suffix) sites, walks content_root
    directly and filters out files that are themselves translations.
    """
    per_language_folders, _ = _get_output_layout(site_profile)
    source_lang = getattr(site_profile, "default_source_lang", "en")
    target_langs = list(getattr(site_profile, "target_langs", None) or [])

    if per_language_folders:
        source_root = content_root / source_lang
        if not source_root.exists():
            return []
        return sorted(source_root.rglob("*.md"))

    if not content_root.exists():
        return []
    return [
        f
        for f in sorted(content_root.rglob("*.md"))
        if not is_translated_filename(f.name, target_langs, source_lang)[0]
    ]


def iter_locale_pairs(
    site_profile: Any, content_root: Path
) -> Iterator[tuple[Path, str, Path]]:
    """
    Yield (source_path, locale, expected_translated_path) for every source
    file x every configured target language. The single generic replacement
    for hand-rolled "find translation pairs" logic, regardless of layout.
    """
    target_langs = list(getattr(site_profile, "target_langs", None) or [])
    for source_path in discover_source_files(site_profile, content_root):
        for locale in target_langs:
            yield (
                source_path,
                locale,
                resolve_translated_path(site_profile, source_path, locale),
            )


def iter_bundle_family_platform_index(content_root: Path) -> Iterator[Path]:
    """
    Yield family/platform-level `_index.md` pages: `{family}/{platform}/_index.md`,
    directly under content_root.

    Generalizes the family/platform traversal shape confirmed correct
    against real disk structure (audit_blog_bundle.py's investigation: 11
    families, 24 family/platform index pages). Layout-agnostic: pass
    `content_root` directly for file-suffix sites, or `content_root /
    default_source_lang` for per_language_folders sites, to get the
    equivalent shape in either case.
    """
    if not content_root.exists():
        return
    yield from content_root.glob("*/*/_index.md")
