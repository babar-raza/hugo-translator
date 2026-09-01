"""
Placeholder management for protecting non-translatable content.
"""
import difflib
import re


class PlaceholderManager:
    """Manages placeholder replacement and restoration for protected content."""

    def __init__(self):
        """Initialize placeholder manager."""
        self.placeholder_map: dict[str, str] = {}
        self.counter = 0

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
        protected_text = text

        for pattern in patterns:
            protected_text = self._apply_pattern(protected_text, pattern)

        return protected_text, dict(self.placeholder_map)

    def _apply_pattern(self, text: str, pattern: str) -> str:
        """Apply a single protection pattern."""

        def replace_match(match: re.Match) -> str:
            placeholder = f"{{PLACEHOLDER_{self.counter}}}"
            self.placeholder_map[placeholder] = match.group(0)
            self.counter += 1
            return placeholder

        try:
            return re.sub(pattern, replace_match, text)
        except re.error:
            # If pattern is invalid, return text unchanged
            return text

    def restore(self, text: str, placeholder_map: dict[str, str]) -> str:
        """
        Restore placeholders to original content.

        Args:
            text: Text with placeholders
            placeholder_map: Mapping of placeholders to original content

        Returns:
            Text with placeholders restored
        """
        restored = text

        # Exact replacements first
        for placeholder, original in placeholder_map.items():
            restored = restored.replace(placeholder, original)

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
            restored = re.sub(r'\{[A-Z][A-Z_]*[A-Z]\}+', '', restored)

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
                text = re.sub(
                    r"\{\s*" + re.escape(original) + r"\s*\}", original, text
                )
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
