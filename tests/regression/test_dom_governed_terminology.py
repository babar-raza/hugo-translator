"""TC-APT-050: "Document Object Model" is governed terminology for this portfolio.

All six FrontmatterLanguageCheck failures on words-document-net shared one
signature -- field=seoTitle, detected_lang=ca, letter_count 55-56, across
cs/el/es/hi. `el` is Greek and `hi` is Devanagari, so a Latin-script detection at
all proved the field stayed English, and untranslated English reproducibly
detects as `ca` at ~1.000.

The decision rests on the portfolio's own published output, not on convenience:
three tracked, genuinely localized pages keep the term verbatim in English --
content/docs.aspose.org/ar/note/python/developer-guide/note-document.md (35% of
its letters are Arabic script), content/kb.aspose.org/nl/note/python/
how-to-traverse-dom-onenote-python.md and content/reference.aspose.org/de/note/
python/enums.md -- against zero counter-examples across 3771 tracked localized
files.

Adding a governed term to the frontmatter signal inventory looks, from the
outside, identical to silencing a gate. The test that separates the two is
test_ordinary_prose_residue_is_still_judged: the >= 6 signal_alpha floor is
untouched, and any field whose residue is real prose is still judged and still
fails when left untranslated. If that property ever breaks, this change stopped
being a fix.
"""

from pathlib import Path

import langdetect
import pytest

from src.translation_engine.engine import (
    _FRONTMATTER_TECHNICAL_SIGNAL_RE,
    _frontmatter_language_signal_text,
)
from src.translation_engine.extractor.placeholder_manager import PlaceholderManager
from src.utils.config_loader import ConfigService

BLOG_PATTERNS = ConfigService(Path("config")).get_site_profile("blog.aspose.org").body.preserve_patterns

# The exact fields off words-document-net, by which the six failures were recorded.
SEO_TITLE = "Aspose.Words FOSS for .NET — Document Object Model & DocumentBuilder"
TITLE = "Inside the Aspose.Words FOSS for .NET Document Object Model"


def _signal_alpha(text: str) -> int:
    return sum(character.isalpha() for character in _frontmatter_language_signal_text(text))


def test_the_governed_term_is_not_counted_as_prose_evidence():
    assert "Document Object Model" not in _frontmatter_language_signal_text(SEO_TITLE)


def test_the_seotitle_that_failed_six_times_is_no_longer_judged():
    """Residue is 'for &' -- three alphabetic characters, below the existing floor."""
    assert _signal_alpha(SEO_TITLE) < 6


@pytest.mark.parametrize(
    "text",
    [
        TITLE,  # residue 'Inside the for' -- 12 chars of real prose
        "There are no usage restrictions and no runtime fees for the Document Object Model",
        "Learn how to read and edit a document in memory",
    ],
)
def test_ordinary_prose_residue_is_still_judged(text):
    """The property that must never regress -- see the module docstring."""
    assert _signal_alpha(text) >= 6


def test_an_untranslated_prose_field_still_reads_as_english():
    """Judged is not enough; the verdict must still be the rejecting one."""
    signal = _frontmatter_language_signal_text(TITLE)
    top = langdetect.detect_langs(signal)[0]

    assert top.lang == "en"
    assert top.prob > 0.9


def test_the_signal_floor_itself_was_not_lowered():
    source = Path("src/translation_engine/engine.py").read_text(encoding="utf-8")

    assert "signal_alpha_count >= 6" in source


def test_the_term_masks_as_one_span_and_round_trips():
    manager = PlaceholderManager()

    masked, mapping = manager.protect(SEO_TITLE, BLOG_PATTERNS)

    assert "Document Object Model" in mapping.values()
    assert manager.restore(masked, mapping) == SEO_TITLE


def test_masking_the_term_does_not_starve_body_prose():
    """Protection must not leave the model a field of placeholders.

    This is the failure mode that made the earlier over-protection hypothesis
    worth testing at all, so it is pinned rather than assumed.
    """
    manager = PlaceholderManager()
    body = "The Document Object Model lets you read and edit a document in memory."

    masked, mapping = manager.protect(body, BLOG_PATTERNS)
    residue = masked
    for key in mapping:
        residue = residue.replace(key, " ")

    assert len([w for w in residue.split() if any(c.isalpha() for c in w)]) >= 8


def test_the_new_pattern_cannot_nest_inside_an_earlier_one():
    """The profile's own ordering rule: no pattern may match inside a claimed span.

    restore() makes a single sequential pass, so a nested placeholder would not
    unwind -- the brace-leak root cause the profile comments cite.
    """
    manager = PlaceholderManager()

    _masked, mapping = manager.protect(SEO_TITLE, BLOG_PATTERNS)

    assert not any(key in value for key in mapping for value in mapping.values())


def test_the_lowercase_phrase_is_not_governed():
    """Only the capitalized term of art is protected; prose usage stays translatable."""
    prose = "Aspose.Words provides a document object model"

    assert "document object model" in _frontmatter_language_signal_text(prose)
    assert not _FRONTMATTER_TECHNICAL_SIGNAL_RE.search("document object model")
