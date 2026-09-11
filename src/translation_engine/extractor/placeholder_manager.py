"""
Placeholder management for protecting non-translatable content.
"""

import difflib
import re


class PlaceholderMapIntegrityError(RuntimeError):
    """Raised when a placeholder map is not safe to restore().

    CU-02 (TC-APT-105/TC-APT-106 hardening): every `protect()`/`restore()`
    pair must be scoped to one unit's own map -- maps must never be merged
    or nested before a single `restore()` call. `restore()`'s substitution
    is a sequential, non-atomic loop over `dict.items()`; if a stored
    "original" value itself contains another placeholder token from the
    same map, the outcome would silently depend on dict iteration order
    instead of being well-defined. This is exactly the collision shape
    behind the already-fixed TC-APT-106 (AST-reuse map keyed by re-derived
    text) and TC-APT-105 (a container's combined translation duplicating a
    protected leaf) bugs -- this exception exists so a future caller that
    accidentally merges two independently-produced maps fails loudly in
    tests, instead of shipping a silent duplicate/collision.
    """


# TC-APT-110 (2026-09-11): scripts that conventionally write with NO space
# between adjacent words/foreign terms -- inserting a synthetic space for
# these would itself be wrong, so the glued-word fix below never fires when
# either boundary character falls in one of these ranges. Confirmed by the
# real defect's own distribution: it only ever appeared in space-delimited
# scripts (ar cs es fa hu nl pt uk); ja/ko/zh/th candidates on the same page,
# same run, kept correct spacing around the identical Latin identifiers.
_NO_SPACE_SCRIPT_RANGES = (
    (0x3040, 0x30FF),  # Hiragana, Katakana
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x1100, 0x11FF),  # Hangul Jamo
    (0xAC00, 0xD7A3),  # Hangul Syllables
    (0x0E00, 0x0E7F),  # Thai
    (0x0E80, 0x0EFF),  # Lao
    (0x1000, 0x109F),  # Myanmar
    (0x1780, 0x17FF),  # Khmer
)


def _is_no_space_script_char(ch: str) -> bool:
    codepoint = ord(ch)
    return any(lo <= codepoint <= hi for lo, hi in _NO_SPACE_SCRIPT_RANGES)


def _needs_space_boundary(context_char: str, value_char: str) -> bool:
    """True if a placeholder's restored value would butt directly against
    `context_char` with zero separator, in a script where that is never a
    legitimate construction (see `_NO_SPACE_SCRIPT_RANGES`).

    Deliberately restricted to letter/digit-against-letter/digit: a
    placeholder boundary against punctuation (parens, colons, quotes) is
    common and legitimate (e.g. the documented Finnish case-suffix
    "PLACEHOLDER_0:n" -- the colon is not alnum, so this returns False and
    that behavior is unchanged).
    """
    if not context_char or not value_char:
        return False
    if not (context_char.isalnum() and value_char.isalnum()):
        return False
    if _is_no_space_script_char(context_char) or _is_no_space_script_char(value_char):
        return False
    return True


class PlaceholderManager:
    """Manages placeholder replacement and restoration for protected content."""

    def __init__(self):
        """Initialize placeholder manager."""
        self.placeholder_map: dict[str, str] = {}
        self.counter = 0
        # TC-APT-011: token prefix actually in use. Normally the historical
        # "PLACEHOLDER_" so output is byte-identical to previous runs; a nonce is added
        # only when the text itself already contains a placeholder-shaped literal, which
        # would otherwise make masking non-bijective and corrupt the source's own text.
        self.token_prefix = "PLACEHOLDER_"

    def protect(self, text: str, patterns: list[str]) -> tuple[str, dict[str, str]]:
        """
        Replace protected content with placeholders.

        Args:
            text: Original text
            patterns: List of regex patterns to protect

        Returns:
            Tuple of (protected_text, placeholder_map)
        """
        self.placeholder_map = {}
        self.counter = 0
        self.token_prefix = self._collision_free_prefix(text)
        protected_text = text

        for pattern in patterns:
            protected_text = self._apply_pattern(protected_text, pattern)

        return protected_text, dict(self.placeholder_map)

    @staticmethod
    def _collision_free_prefix(text: str) -> str:
        """Token prefix that cannot already occur in ``text`` (TC-APT-011).

        Returns the historical ``PLACEHOLDER_`` unless the text already contains a
        ``{PLACEHOLDER_<digits>}`` literal, in which case a short deterministic nonce is
        appended until no collision remains.  Restoration is driven by the returned map, so
        callers need no change.
        """
        import hashlib
        import re as _re

        base = "PLACEHOLDER_"
        if not _re.search(r"\{" + base + r"\d+\}", text):
            return base
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        for size in (6, 10, 16, 32):
            candidate = f"PH{digest[:size]}_"
            if not _re.search(r"\{" + candidate + r"\d+\}", text):
                return candidate
        return f"PH{digest}_"  # pragma: no cover - astronomically unlikely

    def _apply_pattern(self, text: str, pattern: str) -> str:
        """Apply a single protection pattern."""

        def replace_match(match: re.Match) -> str:
            value = match.group(0)
            # TC-APT-105 audit (VA-06): a later pattern in this protect()
            # call can match a span that already contains an earlier
            # pattern's placeholder token -- e.g. preserve_patterns
            # protects the bare identifier "GitHub" first, then the link
            # pattern protects the whole "[{PLACEHOLDER_0} repository]
            # (url)" as one match. Storing that match verbatim would leave
            # this new placeholder's value containing another placeholder
            # token, which restore() cannot safely unwind (see
            # PlaceholderMapIntegrityError) and which previously surfaced
            # only as that loud, blocking guard. Unpack any such nested
            # token back to its original text before storing -- this new,
            # larger match supersedes the earlier, now fully-covered one,
            # so that entry is removed rather than left orphaned in the map.
            for existing_token, existing_original in list(self.placeholder_map.items()):
                if existing_token in value:
                    value = value.replace(existing_token, existing_original)
                    del self.placeholder_map[existing_token]
            placeholder = f"{{{self.token_prefix}{self.counter}}}"
            self.placeholder_map[placeholder] = value
            self.counter += 1
            return placeholder

        try:
            return re.sub(pattern, replace_match, text)
        except re.error:
            # If pattern is invalid, return text unchanged
            return text

    @staticmethod
    def _check_no_nested_placeholders(placeholder_map: dict[str, str]) -> None:
        """Raise `PlaceholderMapIntegrityError` if any stored value in
        `placeholder_map` contains another key from the SAME map as a
        literal substring -- see that class's docstring for why this is an
        integrity violation, not a coincidence worth tolerating.

        Deliberately scoped to keys within THIS map only (not any
        placeholder-shaped string in general): a legitimately-protected
        value coincidentally looking like `{PLACEHOLDER_0}` text is not this
        bug; a value containing a key that this very map also defines is.
        """
        if len(placeholder_map) < 2:
            return
        for key, value in placeholder_map.items():
            for other_key in placeholder_map:
                if other_key != key and other_key in value:
                    raise PlaceholderMapIntegrityError(
                        f"Placeholder map integrity violation: stored value "
                        f"for {key!r} contains another placeholder token "
                        f"{other_key!r} from the same map. This indicates "
                        "two independently-produced placeholder maps were "
                        "merged or nested before a single restore() call -- "
                        "protect()/restore() pairs must stay scoped to one "
                        "unit's own map (see TC-APT-105/TC-APT-106)."
                    )

    def restore(self, text: str, placeholder_map: dict[str, str]) -> str:
        """
        Restore placeholders to original content.

        Args:
            text: Text with placeholders
            placeholder_map: Mapping of placeholders to original content

        Returns:
            Text with placeholders restored

        Raises:
            PlaceholderMapIntegrityError: if `placeholder_map` is not safe to
                restore (see that class's docstring) -- this never fires for
                a map produced by a single `protect()` call on its own text,
                only for a map a caller has incorrectly merged/nested.
        """
        self._check_no_nested_placeholders(placeholder_map)
        restored = text

        # Exact replacements first
        # TC-APT-110 (2026-09-11): the MT/LLM model can drop the space that
        # preceded/followed a placeholder token during generation (confirmed
        # directly: en "with {PLACEHOLDER_0}" -> pt "com{PLACEHOLDER_0}",
        # braces intact, just the space gone) -- restoring naively then glues
        # the restored value directly onto adjacent prose, e.g.
        # "comWorkbook.save", a reader-facing garbled non-word. Found on
        # cells/rust/getting-started/quickstart.md's frontmatter `description`
        # field, 8/25 locales (ar cs es fa hu nl pt uk), because that field
        # has no backtick delimiter around the protected identifier the way
        # body markdown does -- nothing else was absorbing the lost space.
        # Fixed generally here (not field-specific) via regex substitution so
        # each match's real surrounding context (not the placeholder's
        # position in the object generically) decides whether a space was
        # actually lost, using match.string on the ORIGINAL text so context
        # characters are the model's real output, not a previous iteration's
        # partially-restored string.
        for placeholder, original in placeholder_map.items():

            def _restore_one(match: re.Match, _original: str = original) -> str:
                s = match.string
                start, end = match.span()
                prefix = " " if start > 0 and _needs_space_boundary(s[start - 1], _original[0]) else ""
                suffix = " " if end < len(s) and _needs_space_boundary(s[end], _original[-1]) else ""
                return f"{prefix}{_original}{suffix}"

            restored = re.sub(re.escape(placeholder), _restore_one, restored)

        # HT-QUALITY-GATES-001 RC2: brace-stripped fallback. The MT model can drop
        # the `{`/`}` entirely around a placeholder while translating the
        # surrounding text -- confirmed directly against the real NLLB model, not
        # just theorized: protecting "with `.mtl`" as "with {PLACEHOLDER_0}" and
        # translating to Finnish produced bare "PLACEHOLDER_0" with the braces
        # gone and a Finnish case suffix glued on immediately after
        # ("PLACEHOLDER_0:n"). None of the brace-anchored passes below can see
        # this shape at all, so it was shipping into production untouched.
        # Match the bare digit sequence directly (braces optional) and replace
        # only that span, leaving any adjacent suffix/punctuation the model
        # added in place -- imperfect grammar is an acceptable outcome, a raw
        # leaked placeholder token is not.
        def bare_replace(match: re.Match) -> str:
            key = f"{{PLACEHOLDER_{match.group(1)}}}"
            return placeholder_map.get(key, match.group(0))

        restored = re.sub(r"PLACEHOLDER_(\d+)", bare_replace, restored)

        # Fuzzy replacement: handle translator-modified tokens like {Platch_1} or
        # { PLACHEHOLODER _1 } (NLLB adds spaces and misspells the keyword).
        # Pattern: any {…N…} where N is the digit sequence, with optional trailing
        # whitespace/garbage before the closing brace.
        def fuzzy_replace(match: re.Match) -> str:
            token = match.group(0)
            number = match.group(1)
            key = f"{{PLACEHOLDER_{number}}}"
            return placeholder_map.get(key, token)

        restored = re.sub(r"\{[^{}]*?(\d+)[^{}]*?\}", fuzzy_replace, restored)

        # Inter-pass cleanup: remove corrupted placeholder tokens where M2M100 dropped the
        # digit entirely (e.g. {PLACEHOLDER_1} → {PROLEXHOODERS}}).
        # Pattern: { followed by ALL-CAPS/underscore only (no digit) followed by one or more }
        # This can only be a corrupted placeholder — valid translated content never looks like this.
        if placeholder_map:
            restored = re.sub(r"\{[A-Z][A-Z_]*[A-Z]\}+", "", restored)

        # Bare-brace-wrapped-correct-value cleanup (found 2026-07-22, live in
        # reference.aspose.org's cross_locale_dup remediation output on files
        # like pdf/net/ColumnInfo.md): the MT model can correctly GUESS the
        # protected value and emit it in place of "PLACEHOLDER_N" while still
        # keeping the literal `{`/`}` it saw around the digit token -- e.g.
        # protecting "ColumnInfo" (no backtick pattern for reference.aspose.org
        # frontmatter -- only the bare PascalCase pattern applies, so the
        # backticks around it stay as literal text and the braces end up
        # sitting directly against the identifier) produces
        # "`{PLACEHOLDER_0}` class..." -> "`{ColumnInfo}` clase..." instead of
        # "`{PLACEHOLDER_0}`" -> "`ColumnInfo`". None of the passes above catch
        # this: there's no digit left for the digit-anchored passes to find,
        # and it isn't ALL-CAPS-corrupted. Directly strip a brace pair
        # wrapping an already-correct placeholder value.
        def _strip_wrapping_braces(text: str) -> str:
            for original in placeholder_map.values():
                text = re.sub(r"\{\s*" + re.escape(original) + r"\s*\}", original, text)
            return text

        restored = _strip_wrapping_braces(restored)

        # Third pass: handle cases where NLLB completely replaced the placeholder token
        # with a "guessed" variant of the original (e.g. PropertyCollection →
        # PropertiesCollection). If the original term is absent but a close variant
        # exists in the text, replace the variant with the original.
        #
        # HT-QUALITY-GATES-001 Part 21: the "is original already present" guard used
        # to be a naive substring check (`original not in restored`), which is wrong
        # whenever `original` happens to be a PREFIX of the variant actually present
        # -- e.g. "ColumnInfo" is a substring of "ColumnInfos", so the old guard
        # considered it "already present" and skipped fixing "{ColumnInfos}" at all,
        # braces and typo both left in place. A word-boundary check correctly treats
        # "ColumnInfos" as NOT containing the standalone word "ColumnInfo".
        _PASCAL_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+\b")
        for placeholder, original in placeholder_map.items():
            if not re.match(r"^[A-Z]", original):
                continue
            already_present = re.search(r"\b" + re.escape(original) + r"\b", restored)
            if already_present:
                continue
            # Find all PascalCase-ish words in restored text
            candidates = _PASCAL_RE.findall(restored)
            # cutoff=0.92: strict enough to avoid substituting real translated words
            # that happen to resemble the original (e.g. PropertiesCollection ≈ PropertyCollection)
            matches = difflib.get_close_matches(original, candidates, n=1, cutoff=0.92)
            if matches and matches[0] != original:
                restored = restored.replace(matches[0], original, 1)

        # HT-QUALITY-GATES-001 Part 21: ordering-gap fix. The fuzzy variant pass
        # just above can turn a stray-brace-wrapped variant like "{ColumnInfos}"
        # into "{ColumnInfo}" -- correct word, braces still wrapped -- because
        # the exact-match brace-strip pass runs BEFORE this substitution and only
        # catches an already-exact value; a variant (not exact) is invisible to
        # it. Re-run the same brace-strip as a final pass so braces left behind
        # by a just-corrected variant still get removed.
        restored = _strip_wrapping_braces(restored)

        return restored

    def find_missing_protected_values(
        self, restored_text: str, placeholder_map: dict[str, str]
    ) -> list[str]:
        """
        Return the original protected values that are absent from restored_text.

        HT-QUALITY-GATES-001 Part 20: the MT model sometimes drops a placeholder
        token entirely -- not corrupting its shape (which restore()'s fuzzy pass
        already recovers), but hallucinating unrelated fluent prose in its place.
        No regex can recover text that was never emitted; this only detects it,
        by checking whether each originally-protected value survived restoration.
        Confirmed directly against the real nllb_200_1.3b model: a 12-placeholder
        real segment dropped 3 values (`DateTime`, `Cell.PutValue(value)`,
        `Workbook.Worksheets`) with zero recognizable trace in the output.
        """
        return [value for value in placeholder_map.values() if value not in restored_text]

    def extract_placeholders(self, text: str) -> list[str]:
        """
        Extract all placeholder tokens from text.

        Args:
            text: Text potentially containing placeholders

        Returns:
            List of placeholder tokens found

        HT-QUALITY-GATES-001 RC2: brace-optional — the MT model can strip the
        `{`/`}` entirely (confirmed directly), so a brace-only pattern misses
        exactly the leaked tokens this method exists to catch.
        """
        return re.findall(r"\{?PLACEHOLDER_\d+\}?", text)
