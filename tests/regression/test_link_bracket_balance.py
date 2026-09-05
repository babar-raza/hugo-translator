"""TC-APT-084: never hand the model an unbalanced link bracket.

The tail-only link preserve_pattern masked "](url)" but left the opening "[",
so the model received "[Anchor{PLACEHOLDER_0}" and closed the bracket itself.

Measured on introducing-cells-foss-go, which is what turned the reviewer's
inference into a verified mechanism -- two distinct sites, both list items whose
whole content is a link:

  L277 (brand label)   de, el, id, he ->  "...](https://blog.aspose.com/)]"
  L272 (API Reference) pl, pt, ro     ->  "[API Reference{](url)]"

The orphan "{" in the second shape is the proof: it is a BROKEN placeholder
token, which only happens if the model was editing around a raw "[" next to a
placeholder. Bracket balance vs source is now part of the mechanical pre-check
too, because link COUNT cannot see a stray "]" (a lone bracket forms no link).
"""

from pathlib import Path

import pytest

from src.translation_engine.extractor.placeholder_manager import PlaceholderManager
from src.utils.config_loader import ConfigService


@pytest.fixture(scope="module")
def patterns():
    return list(ConfigService(Path("config")).get_site_profile("blog.aspose.org").body.preserve_patterns)


def _masked(patterns, text):
    return PlaceholderManager().protect(text, patterns)


def test_the_model_never_sees_a_raw_opening_bracket_of_a_link(patterns):
    masked, _ = _masked(patterns, "[API Reference](https://reference.aspose.org/cells/go/)")

    assert "[" not in masked
    assert "]" not in masked


def test_the_frame_is_balanced_and_the_anchor_stays_translatable(patterns):
    masked, mapping = _masked(patterns, "[API Reference](https://example.com/)")

    assert masked.count("[") == masked.count("]") == 0
    assert "API Reference" in masked, "anchor text must remain translatable"
    assert "[" in mapping.values()


def test_it_round_trips_byte_identical(patterns):
    for text in (
        "[API Reference](https://reference.aspose.org/cells/go/)",
        "See the [docs](https://example.com/) and the [KB](https://kb.example.com/).",
        "Install it via NuGet, or build it from source.",
    ):
        manager = PlaceholderManager()
        masked, mapping = manager.protect(text, patterns)
        assert manager.restore(masked, mapping) == text


def test_brackets_that_do_not_open_a_link_are_untouched(patterns):
    """Lookahead-scoped: prose and code brackets must not be masked."""
    text = "Use arr[0] and see note [1] below."

    masked, _ = _masked(patterns, text)

    assert "arr[0]" in masked
    assert "[1]" in masked


def test_a_reference_style_bracket_is_untouched(patterns):
    text = "As described in [the spec] elsewhere."

    masked, _ = _masked(patterns, text)

    assert "[the spec]" in masked
