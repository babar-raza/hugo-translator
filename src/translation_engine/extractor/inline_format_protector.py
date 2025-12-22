"""
Inline format protection for preserving markdown formatting during translation.

Protects bold, italic, links, and inline code during segment extraction.

Robust placeholder strategy:
- Uses simple single-token placeholders (⟦TOKEN⟧) that MT models preserve
- Only protects what MUST NOT be translated (URLs, code content)
- Lets translatable content (link text, alt text) flow through naturally
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


@dataclass
class ProtectedInlineSegment:
    """A segment with inline formatting protected via placeholders."""

    original: str
    protected: str
    placeholder_map: Dict[str, str] = field(default_factory=dict)
    url_map: Dict[str, str] = field(default_factory=dict)


class InlineFormatProtector:
    """
    Protects inline markdown formatting during segment extraction.

    Strategy (Robust V2):
    - Uses simple single-token placeholders that survive MT model processing
    - Format: ⟦TYPE_NNNN⟧ using Unicode brackets that are rarely modified
    - Alternative format: XIFPX_TYPE_NNNN_XIFPX for pure ASCII environments

    Handles:
    - Bold: **text** or __text__
    - Italic: *text* or _text_ (single asterisk/underscore)
    - Bold-italic: ***text***
    - Inline code: `code` - content protected as single token
    - Links: [text](url) - URL protected, text translatable
    - Images: ![alt](src) - src protected, alt translatable
    """

    # Use Unicode mathematical brackets - these are single characters
    # that MT models typically preserve as they appear technical
    TOKEN_START = "⟦"
    TOKEN_END = "⟧"

    # Fallback ASCII pattern for environments without Unicode support
    ASCII_TOKEN_START = "XIFPX"
    ASCII_TOKEN_END = "XIFPX"

    def __init__(self, use_unicode: bool = True):
        """Initialize the protector.

        Args:
            use_unicode: If True, use Unicode brackets. If False, use ASCII markers.
        """
        self._counter = 0
        self._url_map: Dict[str, str] = {}
        self._code_map: Dict[str, str] = {}
        self._use_unicode = use_unicode

        if use_unicode:
            self._token_start = self.TOKEN_START
            self._token_end = self.TOKEN_END
        else:
            self._token_start = self.ASCII_TOKEN_START
            self._token_end = self.ASCII_TOKEN_END

    def _make_token(self, token_type: str) -> str:
        """Generate a unique token placeholder.

        Args:
            token_type: Type prefix (URL, IMG, CODE, etc.)

        Returns:
            Token like ⟦URL0001⟧ or XIFPXURL0001XIFPX
        """
        token_id = f"{token_type}{self._counter:04d}"
        self._counter += 1
        if self._use_unicode:
            return f"{self._token_start}{token_id}{self._token_end}"
        else:
            return f"{self._token_start}{token_id}{self._token_end}"

    def _get_token_pattern(self, token_type: str = None) -> re.Pattern:
        """Get regex pattern to match tokens.

        Args:
            token_type: Optional type to match (URL, IMG, CODE). If None, matches all.

        Returns:
            Compiled regex pattern
        """
        if self._use_unicode:
            start = re.escape(self.TOKEN_START)
            end = re.escape(self.TOKEN_END)
        else:
            start = re.escape(self.ASCII_TOKEN_START)
            end = re.escape(self.ASCII_TOKEN_END)

        if token_type:
            return re.compile(f"{start}({token_type}\\d{{4}}){end}")
        else:
            return re.compile(f"{start}([A-Z]+\\d{{4}}){end}")

    def protect(self, text: str) -> ProtectedInlineSegment:
        """
        Replace inline formatting markers with simple placeholders.

        Strategy:
        - URLs in links/images: Replace entire URL with single token
        - Inline code content: Replace entire code with single token
        - Bold/italic markers: Preserve as-is (they don't need protection)

        Args:
            text: Original text with markdown formatting

        Returns:
            ProtectedInlineSegment with placeholders and restoration maps
        """
        self._url_map = {}
        self._code_map = {}
        protected = text

        # 1. Protect image sources (before links - similar syntax)
        protected = self._protect_images_v2(protected)

        # 2. Link handling: Do NOT protect link URLs - let MT handle markdown directly
        # MT models are trained on markdown and preserve [text](url) structure well
        # Placeholder corruption was causing link syntax failures
        # protected = self._protect_links_v2(protected)  # DISABLED

        # 3. Protect inline code content
        protected = self._protect_inline_code_v2(protected)

        # NOTE: Bold/italic markers (**text**, *text*) don't need protection
        # They are simple characters that MT models typically preserve

        return ProtectedInlineSegment(
            original=text,
            protected=protected,
            placeholder_map={},
            url_map=dict(self._url_map)
        )

    def restore(self, segment: ProtectedInlineSegment, translated: str) -> str:
        """
        Restore original content from placeholders.

        Uses fuzzy matching to handle minor token corruption.

        Args:
            segment: Original protection data
            translated: Translated text with placeholders

        Returns:
            Translated text with original content restored
        """
        result = translated

        # Restore URLs and image sources
        result = self._restore_urls_v2(result, segment.url_map)

        # Restore inline code
        result = self._restore_code_v2(result)

        return result

    # === LINK PROTECTION ===

    def _protect_links(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Protect markdown links [text](url) or [text](url "title").

        URLs are stored separately and replaced with hashes to ensure
        they are never modified by the translation model.
        """
        placeholder_map = {}

        # Pattern matches [text](url) or [text](url "title")
        pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

        def replace_link(match: re.Match) -> str:
            link_text = match.group(1)
            url = match.group(2)

            # Generate unique hash for URL
            url_hash = f"U{self._counter:04d}"
            self._counter += 1
            self._url_map[url_hash] = url

            # Replace with placeholders - URL becomes a hash reference
            placeholder = f"{self.LINK_TEXT_START}{link_text}{self.LINK_TEXT_END}{self.LINK_URL_PH % url_hash}"
            return placeholder

        result = pattern.sub(replace_link, text)
        return result, placeholder_map

    def _restore_links(self, text: str, url_map: Dict[str, str]) -> str:
        """
        Restore markdown links from placeholders with robust corruption handling.

        MT models often corrupt placeholders in various ways:
        - Case changes: IFP -> IFp, ifp
        - Letter substitution: IFP -> IFF, FAN, ICS, JWW
        - Spaces inserted: {{ {IFP_LU}} or { {IFF_LU}}
        - Missing braces: {FAN_LU_U0000}}
        """
        result = text

        # Pattern 1: Standard case-insensitive match
        pattern_standard = re.compile(
            r'\{\{IFP_LT\}\}(.+?)\{\{IFP_LTE\}\}\{\{IFP_LU_([A-Za-z0-9]+)\}\}',
            re.IGNORECASE
        )

        # Pattern 2: Handle common letter corruptions (IFP -> IFF, IFp, etc.)
        # Allow any 2-3 letter prefix followed by _LU_
        pattern_corrupted_url = re.compile(
            r'\{\{IFP_LT\}\}(.+?)\{\{IF[Pp]_LTE\}\}\s*\{+\s*\{?\s*[A-Za-z]{2,4}_LU_([A-Za-z0-9]+)\}+',
            re.IGNORECASE
        )

        # Pattern 3: Handle severely corrupted URL placeholders with spaces
        # Match {{IFP_LT}}text{{IFP_LTE}} followed by corrupted URL placeholder
        pattern_severe_corruption = re.compile(
            r'\{\{IFP_LT\}\}(.+?)\{\{IF[Pp]_LTE\}\}\s*\{+\s*\{?\s*[A-Za-z]{2,4}_LU_([A-Za-z0-9]+)\s*\}+',
            re.IGNORECASE
        )

        def restore_link(match: re.Match) -> str:
            link_text = match.group(1)
            url_hash = match.group(2).upper()  # Normalize to uppercase for lookup
            url = url_map.get(url_hash, self._url_map.get(url_hash, '#'))
            return f"[{link_text}]({url})"

        # Apply patterns in order of specificity
        result = pattern_standard.sub(restore_link, result)
        result = pattern_corrupted_url.sub(restore_link, result)
        result = pattern_severe_corruption.sub(restore_link, result)

        # Pattern 4: Clean up orphaned link text markers (when URL placeholder was completely mangled)
        # Match {{IFP_LT}}text{{IFP_LTE}} followed by something that looks like a corrupted URL placeholder
        orphan_pattern = re.compile(
            r'\{\{IFP_LT\}\}([^{]+?)\{\{IF[Pp]_LTE\}\}\s*\{+[^}]*_LU_([A-Za-z0-9]+)[^}]*\}+',
            re.IGNORECASE
        )
        result = orphan_pattern.sub(restore_link, result)

        return result

    # === IMAGE PROTECTION ===

    def _protect_images(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Protect markdown images ![alt](src)."""
        placeholder_map = {}

        pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

        def replace_image(match: re.Match) -> str:
            alt = match.group(1)
            src = match.group(2)

            src_hash = f"I{self._counter:04d}"
            self._counter += 1
            self._url_map[src_hash] = src

            placeholder = f"{self.IMG_ALT_START}{alt}{self.IMG_ALT_END}{self.IMG_SRC_PH % src_hash}"
            return placeholder

        result = pattern.sub(replace_image, text)
        return result, placeholder_map

    def _restore_images(self, text: str, url_map: Dict[str, str]) -> str:
        """
        Restore markdown images from placeholders with robust corruption handling.

        Similar to links, MT models can corrupt image placeholders.
        """
        result = text

        # Pattern 1: Standard case-insensitive match
        pattern_standard = re.compile(
            r'\{\{IFP_IA\}\}(.*?)\{\{IFP_IAE\}\}\{\{IFP_IS_([A-Za-z0-9]+)\}\}',
            re.IGNORECASE
        )

        # Pattern 2: Handle common letter corruptions
        pattern_corrupted_src = re.compile(
            r'\{\{IFP_IA\}\}(.*?)\{\{IF[Pp]_IAE\}\}\s*\{+\s*\{?\s*[A-Za-z]{2,4}_IS_([A-Za-z0-9]+)\}+',
            re.IGNORECASE
        )

        # Pattern 3: Handle severely corrupted src placeholders with spaces
        pattern_severe_corruption = re.compile(
            r'\{\{IFP_IA\}\}(.*?)\{\{IF[Pp]_IAE\}\}\s*\{+\s*\{?\s*[A-Za-z]{2,4}_IS_([A-Za-z0-9]+)\s*\}+',
            re.IGNORECASE
        )

        def restore_image(match: re.Match) -> str:
            alt = match.group(1)
            src_hash = match.group(2).upper()  # Normalize to uppercase for lookup
            src = url_map.get(src_hash, self._url_map.get(src_hash, ''))
            return f"![{alt}]({src})"

        # Apply patterns in order of specificity
        result = pattern_standard.sub(restore_image, result)
        result = pattern_corrupted_src.sub(restore_image, result)
        result = pattern_severe_corruption.sub(restore_image, result)

        # Pattern 4: Clean up orphaned image alt markers
        orphan_pattern = re.compile(
            r'\{\{IFP_IA\}\}([^{]*?)\{\{IF[Pp]_IAE\}\}\s*\{+[^}]*_IS_([A-Za-z0-9]+)[^}]*\}+',
            re.IGNORECASE
        )
        result = orphan_pattern.sub(restore_image, result)

        return result

    # === INLINE CODE PROTECTION ===

    def _protect_inline_code(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Protect inline code `code`."""
        placeholder_map = {}

        # Match single backtick inline code (not code blocks)
        pattern = re.compile(r'`([^`]+)`')

        def replace_code(match: re.Match) -> str:
            code = match.group(1)
            return f"{self.CODE_START}{code}{self.CODE_END}"

        result = pattern.sub(replace_code, text)
        return result, placeholder_map

    def _restore_inline_code(self, text: str) -> str:
        """
        Restore inline code markers from placeholders with robust corruption handling.

        MT models can corrupt code placeholders:
        - Case changes: IFP_CS -> IFp_CS, ifp_cs
        - Letter substitution: IFP -> IFF, ICS, JWW
        - Spaces inserted: {{ IFP_CS}}
        - Underscore -> dash: IFP_CS -> IFP-CS
        """
        result = text

        # Pattern 1: Standard case-insensitive match
        result = re.sub(r'\{\{IFP_CS\}\}', '`', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{IFP_CE\}\}', '`', result, flags=re.IGNORECASE)

        # Pattern 2: Handle spaces inside braces
        result = re.sub(r'\{\{\s*IFP_CS\s*\}\}', '`', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{\s*IFP_CE\s*\}\}', '`', result, flags=re.IGNORECASE)

        # Pattern 3: Handle dash instead of underscore
        result = re.sub(r'\{\{\s*IFP-CS\s*\}\}', '`', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{\s*IFP-CE\s*\}\}', '`', result, flags=re.IGNORECASE)

        # Pattern 4: Handle common letter corruptions (IFP -> IFF, ICS, JWW, etc.)
        # Match any 2-4 letter prefix followed by _CS or _CE or -CS or -CE
        result = re.sub(r'\{+\s*\{?\s*[A-Za-z]{2,4}[-_]CS\s*\}+', '`', result, flags=re.IGNORECASE)
        result = re.sub(r'\{+\s*\{?\s*[A-Za-z]{2,4}[-_]CE\s*\}+', '`', result, flags=re.IGNORECASE)

        return result

    # === BOLD-ITALIC PROTECTION ===

    def _protect_bold_italic(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Protect bold-italic ***text***."""
        placeholder_map = {}

        pattern = re.compile(r'\*\*\*(.+?)\*\*\*', re.DOTALL)

        def replace_bold_italic(match: re.Match) -> str:
            content = match.group(1)
            # Use combined markers
            return f"{self.STRONG_START}{self.EM_START}{content}{self.EM_END}{self.STRONG_END}"

        result = pattern.sub(replace_bold_italic, text)
        return result, placeholder_map

    def _restore_bold_italic(self, text: str) -> str:
        """Restore bold-italic markers (handled by bold/italic restore)."""
        # Bold-italic is restored by the combination of bold and italic restore
        return text

    # === BOLD PROTECTION ===

    def _protect_bold(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Protect bold **text** or __text__."""
        placeholder_map = {}

        # Match **text** (asterisk bold)
        pattern_asterisk = re.compile(r'\*\*(.+?)\*\*', re.DOTALL)
        result = pattern_asterisk.sub(
            lambda m: f"{self.STRONG_START}{m.group(1)}{self.STRONG_END}",
            text
        )

        # Match __text__ (underscore bold)
        pattern_underscore = re.compile(r'__(.+?)__', re.DOTALL)
        result = pattern_underscore.sub(
            lambda m: f"{self.STRONG_START}{m.group(1)}{self.STRONG_END}",
            result
        )

        return result, placeholder_map

    def _restore_bold(self, text: str) -> str:
        """
        Restore bold markers from placeholders with robust corruption handling.

        Handles common MT model corruptions for bold markers.
        """
        result = text

        # Pattern 1: Standard case-insensitive match
        result = re.sub(r'\{\{IFP_SS\}\}', '**', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{IFP_SE\}\}', '**', result, flags=re.IGNORECASE)

        # Pattern 2: Handle spaces inside braces
        result = re.sub(r'\{\{\s*IFP_SS\s*\}\}', '**', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{\s*IFP_SE\s*\}\}', '**', result, flags=re.IGNORECASE)

        # Pattern 3: Handle dash instead of underscore
        result = re.sub(r'\{\{\s*IFP-SS\s*\}\}', '**', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{\s*IFP-SE\s*\}\}', '**', result, flags=re.IGNORECASE)

        # Pattern 4: Handle common letter corruptions
        result = re.sub(r'\{+\s*\{?\s*[A-Za-z]{2,4}[-_]SS\s*\}+', '**', result, flags=re.IGNORECASE)
        result = re.sub(r'\{+\s*\{?\s*[A-Za-z]{2,4}[-_]SE\s*\}+', '**', result, flags=re.IGNORECASE)

        return result

    # === ITALIC PROTECTION ===

    def _protect_italic(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Protect italic *text* (single asterisk only).

        Note: Underscore italic (_text_) is skipped to avoid matching
        words_with_underscores which are common in code.
        """
        placeholder_map = {}

        # Match *text* but not **text** (already handled)
        # Use negative lookbehind/lookahead for asterisk
        pattern = re.compile(r'(?<!\*)\*([^\*]+?)\*(?!\*)')

        result = pattern.sub(
            lambda m: f"{self.EM_START}{m.group(1)}{self.EM_END}",
            text
        )

        return result, placeholder_map

    def _restore_italic(self, text: str) -> str:
        """
        Restore italic markers from placeholders with robust corruption handling.

        Handles common MT model corruptions for italic markers.
        """
        result = text

        # Pattern 1: Standard case-insensitive match
        result = re.sub(r'\{\{IFP_ES\}\}', '*', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{IFP_EE\}\}', '*', result, flags=re.IGNORECASE)

        # Pattern 2: Handle spaces inside braces
        result = re.sub(r'\{\{\s*IFP_ES\s*\}\}', '*', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{\s*IFP_EE\s*\}\}', '*', result, flags=re.IGNORECASE)

        # Pattern 3: Handle dash instead of underscore
        result = re.sub(r'\{\{\s*IFP-ES\s*\}\}', '*', result, flags=re.IGNORECASE)
        result = re.sub(r'\{\{\s*IFP-EE\s*\}\}', '*', result, flags=re.IGNORECASE)

        # Pattern 4: Handle common letter corruptions
        result = re.sub(r'\{+\s*\{?\s*[A-Za-z]{2,4}[-_]ES\s*\}+', '*', result, flags=re.IGNORECASE)
        result = re.sub(r'\{+\s*\{?\s*[A-Za-z]{2,4}[-_]EE\s*\}+', '*', result, flags=re.IGNORECASE)

        return result

    # === UTILITY METHODS ===

    def has_inline_formatting(self, text: str) -> bool:
        """
        Check if text contains inline markdown formatting.

        Args:
            text: Text to check

        Returns:
            True if inline formatting detected
        """
        patterns = [
            r'\*\*.+?\*\*',  # Bold asterisk
            r'__.+?__',      # Bold underscore
            r'(?<!\*)\*[^\*]+?\*(?!\*)',  # Italic
            r'`.+?`',        # Inline code
            r'\[.+?\]\(.+?\)',  # Links
            r'!\[.*?\]\(.+?\)',  # Images
        ]

        for pattern in patterns:
            if re.search(pattern, text):
                return True
        return False

    def reset(self):
        """Reset internal state for new document."""
        self._counter = 0
        self._url_map = {}
        self._code_map = {}

    # === V2 ROBUST PROTECTION METHODS ===
    # These use simple single-token placeholders that survive MT processing

    def _protect_links_v2(self, text: str) -> str:
        """
        Protect link URLs with simple token placeholders.

        Strategy: [text](url) -> [text](⟦URL0001⟧)
        The link text is translatable, only the URL is protected.
        """
        # Use negative lookbehind to NOT match images (which start with !)
        pattern = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)]+)\)')

        def replace_link(match: re.Match) -> str:
            link_text = match.group(1)
            url = match.group(2)

            token = self._make_token("URL")
            self._url_map[token] = url

            return f"[{link_text}]({token})"

        return pattern.sub(replace_link, text)

    def _protect_images_v2(self, text: str) -> str:
        """
        Protect image sources with simple token placeholders.

        Strategy: ![alt](src) -> ![alt](⟦IMG0001⟧)
        The alt text is translatable, only the source is protected.
        """
        pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

        def replace_image(match: re.Match) -> str:
            alt = match.group(1)
            src = match.group(2)

            token = self._make_token("IMG")
            self._url_map[token] = src

            return f"![{alt}]({token})"

        return pattern.sub(replace_image, text)

    def _protect_inline_code_v2(self, text: str) -> str:
        """
        Protect inline code content with simple token placeholders.

        Strategy: `code` -> `⟦CODE0001⟧`
        The code content is protected to prevent corruption.
        """
        pattern = re.compile(r'`([^`]+)`')

        def replace_code(match: re.Match) -> str:
            code = match.group(1)

            token = self._make_token("CODE")
            self._code_map[token] = code

            return f"`{token}`"

        return pattern.sub(replace_code, text)

    def _restore_urls_v2(self, text: str, url_map: Dict[str, str]) -> str:
        """
        Restore URLs from token placeholders with fuzzy matching.

        Handles minor corruption of tokens by MT models.
        """
        result = text

        # Build combined map from both sources
        combined_map = {**self._url_map, **url_map}

        for token, url in combined_map.items():
            # Extract the token ID (e.g., "URL0001" from "⟦URL0001⟧")
            if self._use_unicode:
                token_id = token.strip(self.TOKEN_START + self.TOKEN_END)
            else:
                token_id = token.replace(self.ASCII_TOKEN_START, "").replace(self.ASCII_TOKEN_END, "")

            # Try exact match first
            result = result.replace(token, url)

            # Try fuzzy match patterns for common corruptions
            # Pattern: Allow spaces, case changes, minor character variations
            fuzzy_patterns = [
                # Exact token ID with different brackets
                re.compile(rf'[⟦\[\(\{{<]+\s*{re.escape(token_id)}\s*[⟧\]\)\}}>]+', re.IGNORECASE),
                # Token ID with spaces
                re.compile(rf'⟦\s*{re.escape(token_id)}\s*⟧', re.IGNORECASE),
                # ASCII version with spaces
                re.compile(rf'XIFPX\s*{re.escape(token_id)}\s*XIFPX', re.IGNORECASE),
                # Just the token ID if brackets were completely removed
                re.compile(rf'\b{re.escape(token_id)}\b'),
            ]

            for pattern in fuzzy_patterns:
                result = pattern.sub(url, result)

        return result

    def _restore_code_v2(self, text: str) -> str:
        """
        Restore inline code content from token placeholders with fuzzy matching.
        """
        result = text

        for token, code in self._code_map.items():
            # Extract the token ID
            if self._use_unicode:
                token_id = token.strip(self.TOKEN_START + self.TOKEN_END)
            else:
                token_id = token.replace(self.ASCII_TOKEN_START, "").replace(self.ASCII_TOKEN_END, "")

            # Try exact match first
            result = result.replace(token, code)

            # Try fuzzy match patterns
            fuzzy_patterns = [
                re.compile(rf'`[⟦\[\(\{{<]+\s*{re.escape(token_id)}\s*[⟧\]\)\}}>]+`'),
                re.compile(rf'`⟦\s*{re.escape(token_id)}\s*⟧`'),
                re.compile(rf'`XIFPX\s*{re.escape(token_id)}\s*XIFPX`'),
            ]

            for pattern in fuzzy_patterns:
                result = pattern.sub(f"`{code}`", result)

        return result
