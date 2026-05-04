"""Asset synchronization for Hugo page bundles across language folders.

Copies non-Markdown assets (images, PDFs, etc.) from the source language
folder to each target language folder, preserving the relative page-bundle
structure.  Only operates on ``per_language_folders: true`` sites.

Disabled by default; enable via ``asset_sync.enabled: true`` in global.yaml.

Source: Pattern from GitLab project 579 (product-pages-translator-agent).
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Default extensions to sync (configurable via global.yaml)
DEFAULT_ASSET_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp",
    ".pdf", ".zip", ".ico", ".bmp", ".tiff",
})


def sync_assets(
    source_dir: Path,
    target_dir: Path,
    extensions: frozenset[str] | set[str] | list[str] | None = None,
    skip_if_exists: bool = True,
) -> int:
    """Copy non-Markdown asset files from *source_dir* to *target_dir*.

    Walks *source_dir* recursively.  For each file whose suffix is in
    *extensions*, copies it to the corresponding relative path under
    *target_dir*.

    Args:
        source_dir: Root of the source language folder (e.g., ``content/en``).
        target_dir: Root of the target language folder (e.g., ``content/es``).
        extensions: Set of lowercase file extensions to sync.
            Defaults to :data:`DEFAULT_ASSET_EXTENSIONS`.
        skip_if_exists: When True, skip copying if the target file already
            exists and has the same size as the source.

    Returns:
        Number of files actually copied.
    """
    if extensions is None:
        extensions = DEFAULT_ASSET_EXTENSIONS
    else:
        extensions = frozenset(ext.lower() for ext in extensions)

    if not source_dir.is_dir():
        logger.debug("Asset sync skipped: source_dir %s does not exist", source_dir)
        return 0

    copied = 0
    for src_file in source_dir.rglob("*"):
        if not src_file.is_file():
            continue
        if src_file.suffix.lower() not in extensions:
            continue

        rel = src_file.relative_to(source_dir)
        dst_file = target_dir / rel

        if skip_if_exists and dst_file.exists():
            try:
                if dst_file.stat().st_size == src_file.stat().st_size:
                    continue
            except OSError:
                pass  # stat failed — copy anyway

        try:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied += 1
        except OSError as exc:
            logger.warning("Asset sync failed: %s -> %s: %s", src_file, dst_file, exc)

    if copied:
        logger.info(
            "Asset sync: copied %d files from %s to %s",
            copied, source_dir, target_dir,
        )

    return copied
