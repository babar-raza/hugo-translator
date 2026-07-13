"""
FileReconstructor — in-place unit-level file reconstruction.

Given an existing translated file and a dict of {unit_idx: new_translation},
re-parses the file, substitutes only the specified units, and renders the
result back to markdown. All other units remain verbatim from the original
translated content.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .parser import HugoParser
from .reconstructor import ASTRenderer, YAMLFormatter
from .extractor import TextUnitExtractor

logger = logging.getLogger(__name__)


class FileReconstructor:
    """
    Rebuilds a translated file with surgical per-unit substitutions.

    Usage::

        rec = FileReconstructor(site_profile=profile)
        new_content = rec.reconstruct(
            original_tr_content=tr_file.read_text(encoding="utf-8"),
            en_content=en_file.read_text(encoding="utf-8"),
            unit_replacements={3: "Neue Übersetzung", 7: "Andere Übersetzung"},
            site_id="reference.aspose.org",
            locale="de",
        )

    ``unit_replacements`` maps the 0-based index of a unit in the translated
    file's TextUnit list to the new translated string for that unit.

    Units not listed in ``unit_replacements`` keep their existing translated
    content verbatim (identity translation: translated_text = source_text).
    """

    def __init__(self, site_profile: Any | None = None) -> None:
        self._site_profile = site_profile

    def reconstruct(
        self,
        original_tr_content: str,
        en_content: str,
        unit_replacements: dict[int, str],
        site_id: str,
        locale: str,
    ) -> str:
        """
        Rebuild *original_tr_content* replacing only the indexed units.

        Args:
            original_tr_content: Current translated file content (may have bad units).
            en_content: English source file content (used for passthrough field values).
            unit_replacements: ``{unit_idx: new_translation}`` — only these change.
            site_id: Site identifier (e.g. "reference.aspose.org").
            locale: Target locale (e.g. "uk").

        Returns:
            Reconstructed file content as a string.

        Raises:
            ValueError: If the file cannot be parsed or reconstruction fails.
        """
        parser = HugoParser()

        # Parse the translated file (the one we want to patch)
        tr_doc = parser.parse_string(original_tr_content)

        # Parse the EN source (for passthrough field values)
        en_doc = parser.parse_string(en_content)

        # Extract units from the TRANSLATED document.
        # source_text here == the already-translated content for each unit.
        profile = self._site_profile
        preserve_patterns = (
            profile.body.preserve_patterns if profile and hasattr(profile, "body") else None
        )
        extractor = TextUnitExtractor(
            segmentation_strategy="sentence_only",
            terminology_file=None,
            mt_model=None,
            preserve_patterns=preserve_patterns,
            site_profile=profile,
        )
        plan = extractor.extract_from_ast(tr_doc.ast, tr_doc.frontmatter)
        tr_units = plan.units

        # Mark every unit as "keep as-is": translated_text = source_text
        for unit in tr_units:
            unit.translated_text = unit.source_text

        # Apply replacements for bad units
        for unit_idx, new_text in unit_replacements.items():
            if 0 <= unit_idx < len(tr_units):
                tr_units[unit_idx].translated_text = new_text
            else:
                logger.warning(
                    "FileReconstructor: unit_idx %d out of range (len=%d); skipping",
                    unit_idx,
                    len(tr_units),
                )

        # For passthrough frontmatter fields: force translated_text = EN source value
        if en_doc.frontmatter and tr_doc.frontmatter:
            self._apply_passthrough_from_en(tr_units, en_doc.frontmatter)

        # Render: apply translated units back to the TR AST
        renderer = ASTRenderer()
        renderer.apply_translations(tr_doc.ast, tr_units, frontmatter=tr_doc.frontmatter)

        # Reconstruct frontmatter YAML from the (now-updated) tr_doc.frontmatter dict
        yaml_formatter = YAMLFormatter()
        frontmatter_yaml = yaml_formatter.format_frontmatter(tr_doc.frontmatter)

        # Render body
        translated_body = renderer.render_to_markdown(tr_doc.ast)

        return f"{frontmatter_yaml}\n{translated_body}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_passthrough_from_en(
        self,
        tr_units: list,
        en_frontmatter: dict[str, Any],
    ) -> None:
        """For passthrough frontmatter units, force translated_text = EN value."""
        for unit in tr_units:
            node_addr = getattr(unit, "node_addr", None) or ""
            if not node_addr.startswith("frontmatter."):
                continue
            if not unit.do_not_translate:
                continue
            # "frontmatter.title" → "title"; "frontmatter.keywords[0]" → "keywords"
            field_part = node_addr[len("frontmatter."):]
            field_name = field_part.split("[")[0].split(".")[0]
            en_val = en_frontmatter.get(field_name)
            if isinstance(en_val, str):
                unit.translated_text = en_val
