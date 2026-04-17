"""
TextUnit data models for AST-based translation AST-based translation.

This module defines the core data structures for node-addressed translation,
enabling 100% structure preservation by decoupling translation from formatting.
"""
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TextUnitKind(str, Enum):
    """
    Type of text unit in the AST.

    Determines where the translatable text lives in the document structure.
    Different kinds may have different translation rules or priorities.
    """

    TEXT = "text"
    """Plain text node (most common)."""

    HEADING_TEXT = "heading_text"
    """Text content within a heading."""

    LINK_TEXT = "link_text"
    """Link text (NOT the URL - URLs are never translated)."""

    IMAGE_ALT = "image_alt"
    """Image alt text (src attribute is never translated)."""

    TABLE_CELL_TEXT = "table_cell_text"
    """Text content within a table cell."""

    CODE_SPAN = "code_span"
    """Inline code content (typically do_not_translate=True)."""

    BLOCKQUOTE_TEXT = "blockquote_text"
    """Text content within a blockquote."""

    LIST_ITEM_TEXT = "list_item_text"
    """Text content within a list item."""


@dataclass
class TextUnit:
    """
    A translatable text unit with stable node addressing.

    Represents a single piece of translatable text extracted from the AST.
    The node_addr field provides deterministic mapping back to the AST node
    after translation, eliminating the need for fuzzy matching or alignment.

    Key Innovation: Translation operates on TextUnits, not on flat strings.
    After translation, TextUnits are applied back to AST nodes by address,
    guaranteeing 100% structure preservation regardless of MT model behavior.

    Example:
        >>> unit = TextUnit(
        ...     unit_id="abc123",
        ...     node_addr="para[2].strong[0].text[1]",
        ...     kind=TextUnitKind.TEXT,
        ...     source_text="Hello World",
        ...     prefix_ws="",
        ...     suffix_ws=" ",
        ...     do_not_translate=False
        ... )
        >>> # After translation:
        >>> unit.translated_text = "Hola Mundo"
        >>> # Apply to AST: ast.get_node(unit.node_addr).content = unit.translated_text
    """

    unit_id: str
    """Unique identifier for this text unit (hash of node_addr + content)."""

    node_addr: str
    """
    Stable node address in the AST (e.g., "para[2].strong[0].text[1]").

    This address is deterministic and unchanging for a given AST structure.
    After translation, use this address to apply the translation back to
    the exact same node, eliminating alignment/search problems.
    """

    kind: TextUnitKind
    """Type of text unit (determines context and translation rules)."""

    source_text: str
    """
    The exact text to translate.

    Whitespace is stripped and stored separately in prefix_ws/suffix_ws
    to ensure whitespace preservation during translation.
    """

    prefix_ws: str = ""
    """Leading whitespace (captured during extraction, reattached after translation)."""

    suffix_ws: str = ""
    """Trailing whitespace (captured during extraction, reattached after translation)."""

    do_not_translate: bool = False
    """
    If True, this unit should be copied as-is without translation.

    Set to True for:
    - Code blocks and inline code
    - URLs (in links and images)
    - Product names (detected via terminology dictionary or NER)
    - Technical identifiers (API names, class names, etc.)

    When True, translation step copies source_text to translated_text unchanged.
    """

    translated_text: str | None = None
    """
    Translated text (populated after translation).

    For do_not_translate=True units, this is set to source_text (copy as-is).
    For translatable units, this is populated by the MT model.
    """

    metadata: dict[str, Any] = field(default_factory=dict)
    """
    Optional metadata for context or debugging.

    May contain:
    - parent_node_type: Type of parent AST node
    - depth: Nesting depth in AST
    - surrounding_context: Text before/after for context
    - terminology_matches: Product names detected in this unit
    """

    def __post_init__(self):
        """Validate required fields after initialization."""
        if not self.unit_id:
            raise ValueError("unit_id cannot be empty")
        if not self.node_addr:
            raise ValueError("node_addr cannot be empty")
        # source_text can be empty for whitespace-only nodes

    @classmethod
    def create_id(cls, node_addr: str, source_text: str, kind: TextUnitKind) -> str:
        """
        Generate a stable unit ID from node address and content.

        Uses SHA-256 hash to create a unique identifier based on:
        - Node address (stable for a given AST structure)
        - Source text content
        - Unit kind

        This ensures the same content at the same location produces
        the same unit_id, enabling TM lookups and caching.

        Args:
            node_addr: Stable node address (e.g., "para[2].text[0]")
            source_text: Source text content
            kind: Type of text unit

        Returns:
            16-character hex hash (first 16 chars of SHA-256)

        Example:
            >>> TextUnit.create_id("p1.t1", "Hello", TextUnitKind.TEXT)
            'a1b2c3d4e5f60718'
        """
        content = f"{node_addr}:{kind}:{source_text}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary for JSON/YAML storage.

        Returns:
            Dictionary with all fields, suitable for JSON serialization

        Example:
            >>> unit = TextUnit(unit_id="abc", node_addr="p1.t1",
            ...                 kind=TextUnitKind.TEXT, source_text="Hello")
            >>> data = unit.to_dict()
            >>> assert data['unit_id'] == 'abc'
            >>> assert data['kind'] == 'text'
        """
        return {
            'unit_id': self.unit_id,
            'node_addr': self.node_addr,
            'kind': self.kind.value,  # Serialize enum to string
            'source_text': self.source_text,
            'prefix_ws': self.prefix_ws,
            'suffix_ws': self.suffix_ws,
            'do_not_translate': self.do_not_translate,
            'translated_text': self.translated_text,
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextUnit":
        """
        Deserialize from dictionary.

        Args:
            data: Dictionary with TextUnit fields

        Returns:
            TextUnit instance

        Raises:
            ValueError: If required fields are missing or invalid
            KeyError: If required fields are not present in data

        Example:
            >>> data = {
            ...     'unit_id': 'abc',
            ...     'node_addr': 'p1.t1',
            ...     'kind': 'text',
            ...     'source_text': 'Hello'
            ... }
            >>> unit = TextUnit.from_dict(data)
            >>> assert unit.source_text == 'Hello'
        """
        # Required fields
        unit_id = data['unit_id']
        node_addr = data['node_addr']
        kind = TextUnitKind(data['kind'])  # Convert string to enum
        source_text = data['source_text']

        # Optional fields with defaults
        prefix_ws = data.get('prefix_ws', '')
        suffix_ws = data.get('suffix_ws', '')
        do_not_translate = data.get('do_not_translate', False)
        translated_text = data.get('translated_text')
        metadata = data.get('metadata', {})

        return cls(
            unit_id=unit_id,
            node_addr=node_addr,
            kind=kind,
            source_text=source_text,
            prefix_ws=prefix_ws,
            suffix_ws=suffix_ws,
            do_not_translate=do_not_translate,
            translated_text=translated_text,
            metadata=metadata,
        )

    def get_final_text(self) -> str:
        """
        Get final text with whitespace reattached.

        Returns translated_text (if available) or source_text,
        with prefix_ws and suffix_ws reattached.

        Returns:
            Final text ready for insertion into AST

        Example:
            >>> unit = TextUnit(unit_id="a", node_addr="p1.t1",
            ...                 kind=TextUnitKind.TEXT, source_text="Hello",
            ...                 prefix_ws="  ", suffix_ws=" ")
            >>> unit.translated_text = "Hola"
            >>> unit.get_final_text()
            '  Hola '
        """
        text = self.translated_text if self.translated_text is not None else self.source_text
        return f"{self.prefix_ws}{text}{self.suffix_ws}"


@dataclass
class BodyTranslationPlan:
    """
    Complete translation plan for a document body.

    Encapsulates the entire translation workflow for the markdown body:
    1. Original AST (preserved for reconstruction)
    2. Extracted TextUnits (sent for translation)
    3. AST fingerprint (for sanity checking)

    The AST is kept as the single source of truth for document structure.
    TextUnits are extracted from the AST, translated, then applied back
    to the AST by node addresses before final rendering.

    Example Workflow:
        >>> # 1. Create plan from parsed document
        >>> plan = BodyTranslationPlan(
        ...     ast=parsed_doc.ast,
        ...     units=[unit1, unit2, unit3],
        ...     ast_fingerprint=compute_fingerprint(parsed_doc.ast)
        ... )
        >>>
        >>> # 2. Translate units
        >>> for unit in plan.units:
        ...     if not unit.do_not_translate:
        ...         unit.translated_text = mt_model.translate(unit.source_text)
        ...     else:
        ...         unit.translated_text = unit.source_text
        >>>
        >>> # 3. Apply translations to AST
        >>> for unit in plan.units:
        ...     node = plan.ast.get_node_by_addr(unit.node_addr)
        ...     node.content = unit.get_final_text()
        >>>
        >>> # 4. Render AST to markdown
        >>> output = render_ast_to_markdown(plan.ast)
    """

    ast: Any
    """
    The original AST (preserved for reconstruction).

    Type is Any to avoid circular dependency with ast_nodes module.
    In practice, this is List[ASTNode] from the parser.
    """

    units: list[TextUnit]
    """All translatable text units extracted from the AST."""

    ast_fingerprint: str
    """
    Hash of AST structure for sanity checking.

    Used to detect if the AST was modified between extraction and reconstruction.
    If fingerprint changes, reconstruction should fail-fast to prevent corruption.

    Computed by hashing the AST structure (node types and hierarchy),
    NOT the text content (since content changes during translation).
    """

    metadata: dict[str, Any] = field(default_factory=dict)
    """
    Optional metadata for the translation plan.

    May contain:
    - source_lang: Source language code
    - target_lang: Target language code
    - extraction_timestamp: When units were extracted
    - extraction_strategy: Which strategy was used (full-sentence vs leaf-level)
    - stats: Extraction statistics (total units, translatable units, etc.)
    """

    def __post_init__(self):
        """Validate required fields after initialization."""
        if self.ast is None:
            raise ValueError("ast cannot be None")
        if not isinstance(self.units, list):
            raise ValueError("units must be a list")
        if not self.ast_fingerprint:
            raise ValueError("ast_fingerprint cannot be empty")

    def get_translatable_units(self) -> list[TextUnit]:
        """
        Get only units that need translation (do_not_translate=False).

        Returns:
            List of TextUnit instances that should be sent to MT

        Example:
            >>> plan = BodyTranslationPlan(ast=ast, units=[...], ast_fingerprint="abc")
            >>> translatable = plan.get_translatable_units()
            >>> for unit in translatable:
            ...     unit.translated_text = mt_model.translate(unit.source_text)
        """
        return [unit for unit in self.units if not unit.do_not_translate]

    def get_non_translatable_units(self) -> list[TextUnit]:
        """
        Get units that should be copied as-is (do_not_translate=True).

        Returns:
            List of TextUnit instances that should NOT be translated

        Example:
            >>> plan = BodyTranslationPlan(ast=ast, units=[...], ast_fingerprint="abc")
            >>> non_translatable = plan.get_non_translatable_units()
            >>> for unit in non_translatable:
            ...     unit.translated_text = unit.source_text  # Copy as-is
        """
        return [unit for unit in self.units if unit.do_not_translate]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary for JSON/YAML storage.

        Note: AST is NOT serialized (too large, and we have the original file).
        Only units and metadata are serialized.

        Returns:
            Dictionary with serializable fields

        Example:
            >>> plan = BodyTranslationPlan(ast=ast, units=[unit1], ast_fingerprint="abc")
            >>> data = plan.to_dict()
            >>> assert 'units' in data
            >>> assert data['ast_fingerprint'] == 'abc'
        """
        return {
            'units': [unit.to_dict() for unit in self.units],
            'ast_fingerprint': self.ast_fingerprint,
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], ast: Any) -> "BodyTranslationPlan":
        """
        Deserialize from dictionary.

        Note: AST must be provided separately (not serialized).

        Args:
            data: Dictionary with BodyTranslationPlan fields
            ast: The AST object (from original parse)

        Returns:
            BodyTranslationPlan instance

        Example:
            >>> data = {...}  # Serialized plan
            >>> ast = parser.parse_file(path).ast
            >>> plan = BodyTranslationPlan.from_dict(data, ast)
        """
        units = [TextUnit.from_dict(unit_data) for unit_data in data['units']]
        ast_fingerprint = data['ast_fingerprint']
        metadata = data.get('metadata', {})

        return cls(
            ast=ast,
            units=units,
            ast_fingerprint=ast_fingerprint,
            metadata=metadata,
        )
