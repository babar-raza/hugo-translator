"""
CU-02 (TC-APT-105/TC-APT-106 hardening): PlaceholderManager.restore() must
fail loudly on a placeholder map that has been merged/nested from two
independently-produced maps, rather than silently producing an
iteration-order-dependent, potentially duplicated/collided result.

TC-APT-106 (commit b7ba0813) and TC-APT-105 both root-caused to the same
underlying shape: two independent mechanisms each thinking they own
resolving "this content", keyed differently, colliding. PlaceholderManager
itself has never actually hit this bug (every real call site scopes
protect()/restore() to one unit's own map), but its counter-reset-on-every-
protect() design (`self.counter = 0` in `protect()`) means a future call
site that merges two maps before a single restore() would reproduce the
exact same class of bug immediately and silently. This test file pins:
(1) today's real, safe usage pattern is completely unaffected by the new
guard, and (2) the guard actually fires on a deliberately-constructed
merged/nested map.
"""
import pytest

from src.translation_engine.extractor.placeholder_manager import (
    PlaceholderManager,
    PlaceholderMapIntegrityError,
)


class TestExistingSafeUsageUnaffected:
    """Every real call site in this codebase scopes one protect() call's
    map to one restore() call -- this must keep working byte-for-byte."""

    def test_single_protect_restore_roundtrip_unaffected(self):
        manager = PlaceholderManager()
        protected, placeholder_map = manager.protect(
            "Write `string` and `int` values.", [r"`[^`]+`"]
        )
        assert protected == "Write {PLACEHOLDER_0} and {PLACEHOLDER_1} values."

        restored = manager.restore(protected, placeholder_map)

        assert restored == "Write `string` and `int` values."

    def test_multiple_distinct_placeholders_roundtrip_unaffected(self):
        manager = PlaceholderManager()
        protected, placeholder_map = manager.protect(
            "See [Installation](../installation/) and [API Reference](https://x/y).",
            [r"\[[^\]]+\]\([^)]+\)"],
        )
        restored = manager.restore(protected, placeholder_map)

        assert restored == (
            "See [Installation](../installation/) and [API Reference](https://x/y)."
        )

    def test_empty_map_is_a_no_op(self):
        manager = PlaceholderManager()
        assert manager.restore("plain text, no placeholders", {}) == "plain text, no placeholders"

    def test_single_entry_map_never_triggers_the_guard(self):
        """A map with exactly one entry can never contain "another key" by
        definition -- the guard must short-circuit cheaply, not scan."""
        manager = PlaceholderManager()
        # Deliberately construct a single-entry map whose value looks
        # placeholder-shaped (but there IS no other key to collide with).
        placeholder_map = {"{PLACEHOLDER_0}": "some {PLACEHOLDER_99}-shaped text"}
        assert manager.restore("{PLACEHOLDER_0}", placeholder_map) == (
            "some {PLACEHOLDER_99}-shaped text"
        )


class TestNestedMapGuardFires:
    """Deliberately-malformed maps, of the shape a future merge-before-
    restore bug would produce, must raise instead of silently mis-
    substituting."""

    def test_stored_value_containing_another_key_raises(self):
        manager = PlaceholderManager()
        malformed_map = {
            "{PLACEHOLDER_0}": "**[{PLACEHOLDER_1}](https://reference.aspose.org/cells/go/)**",
            "{PLACEHOLDER_1}": "API Reference",
        }

        with pytest.raises(PlaceholderMapIntegrityError) as exc_info:
            manager.restore("{PLACEHOLDER_0}", malformed_map)
        assert "{PLACEHOLDER_0}" in str(exc_info.value)
        assert "{PLACEHOLDER_1}" in str(exc_info.value)

    def test_guard_fires_regardless_of_which_key_is_checked_first(self):
        """The nesting can appear on either side -- the guard must not
        depend on dict iteration order to detect it."""
        manager = PlaceholderManager()
        malformed_map = {
            "{PLACEHOLDER_1}": "API Reference",
            "{PLACEHOLDER_0}": "**[{PLACEHOLDER_1}](https://reference.aspose.org/cells/go/)**",
        }

        with pytest.raises(PlaceholderMapIntegrityError):
            manager.restore("irrelevant", malformed_map)

    def test_three_entry_map_with_one_nested_pair_raises(self):
        manager = PlaceholderManager()
        malformed_map = {
            "{PLACEHOLDER_0}": "unrelated protected value",
            "{PLACEHOLDER_1}": "wrapper around {PLACEHOLDER_2}",
            "{PLACEHOLDER_2}": "inner value",
        }

        with pytest.raises(PlaceholderMapIntegrityError):
            manager.restore("irrelevant", malformed_map)


class TestProtectNeverProducesNestedPlaceholders:
    """VA-06 (TC-APT-105 audit): root cause of the only live
    PlaceholderMapIntegrityError this guard has actually caught --
    content/docs.aspose.org/en/cells/go/getting-started/license.md's "See
    the full license text in the [GitHub repository](url)" sentence.
    protect() applies multiple patterns sequentially on the same mutating
    text: an earlier pattern (e.g. a bare PascalCase identifier like
    "GitHub") can be fully inside the span a LATER pattern also matches
    (e.g. the enclosing markdown link). Before this fix, the later
    placeholder's stored value was the raw regex match -- including the
    earlier pattern's already-substituted token literally -- so
    restore() would later hit PlaceholderMapIntegrityError. protect()
    itself must never produce such a map: a later, larger match unpacks
    and supersedes any placeholder token it subsumes.
    """

    def test_identifier_inside_later_link_match_is_unpacked_not_nested(self):
        """Exact live shape: identifier pattern runs first (matches
        "GitHub" alone), then a link pattern's match subsumes that
        placeholder token inside a larger "[GitHub repository](url)" span."""
        manager = PlaceholderManager()
        text = (
            'See the full license text in the [GitHub repository]'
            '(https://github.com/aspose-cells-foss/Aspose.Cells-FOSS-for-Go/'
            "blob/main/LICENSE) for the complete terms."
        )
        protected, placeholder_map = manager.protect(
            text,
            [
                r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+\b",  # PascalCase compound (e.g. GitHub)
                r"\[([^\]]+)\]\(([^)]+)\)",  # markdown link
            ],
        )

        # No stored value may contain another key from this same map.
        for key, value in placeholder_map.items():
            for other_key in placeholder_map:
                if other_key != key:
                    assert other_key not in value, (
                        f"{key}'s value {value!r} still contains {other_key} -- "
                        "protect() produced a nested placeholder"
                    )

        # restore() must not raise, and must recover the exact original text.
        restored = manager.restore(protected, placeholder_map)
        assert restored == text

    def test_earlier_subsumed_placeholder_is_removed_from_the_map(self):
        """The earlier, now fully-covered placeholder must not survive as an
        orphaned, unused entry -- the later match's stored value already
        carries its original text back out."""
        manager = PlaceholderManager()
        text = "The [GitHub repository](https://example.com/repo) has the source."
        _protected, placeholder_map = manager.protect(
            text,
            [
                r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+\b",
                r"\[([^\]]+)\]\(([^)]+)\)",
            ],
        )

        assert len(placeholder_map) == 1
        (sole_value,) = placeholder_map.values()
        assert sole_value == "[GitHub repository](https://example.com/repo)"

    def test_two_independent_identifiers_outside_any_link_stay_distinct(self):
        """Sanity check the fix doesn't over-collapse: two identifier
        matches that are NOT subsumed by any later match must remain two
        separate, independently-restorable placeholders."""
        manager = PlaceholderManager()
        text = "TypeScript and JavaScript are both supported."
        protected, placeholder_map = manager.protect(
            text, [r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+\b"]
        )

        assert len(placeholder_map) == 2
        restored = manager.restore(protected, placeholder_map)
        assert restored == text
