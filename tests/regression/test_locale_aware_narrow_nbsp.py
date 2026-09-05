"""TC-APT-077: U+202F NARROW NO-BREAK SPACE normalization must be locale-aware.

Measured on words-document-net's 5 regenerated locales (0 in source in every
case): fr 21 (legitimate French typography before ; : ! ?), nl 2, fa 1
(injected -- the model plausibly over-applies its French-typography habit
when producing other languages). A source-conditional-only strip (the same
test every other injected invisible in this module uses) cannot tell those
apart, because the source is English/ASCII and never legitimately uses this
character either way -- only target_lang can. Recorded and deliberately NOT
fixed blind in data/summaries/review-words-doc-r3-nl-20260905.json: "a
source-conditional strip has no locale awareness and would delete 21 correct
French narrow spaces to remove 3 injected ones elsewhere."
"""

from src.translation_engine.text_fidelity import normalize_injected_invisibles

NNBSP = " "


def test_french_keeps_its_legitimate_narrow_space_before_punctuation():
    translated = f"Bonjour{NNBSP}: comment allez-vous{NNBSP}?"
    assert normalize_injected_invisibles("Hello: how are you?", translated, "fr") == translated


def test_dutch_strips_an_injected_narrow_space():
    translated = f"Hallo{NNBSP}: hoe gaat het{NNBSP}?"
    result = normalize_injected_invisibles("Hello: how are you?", translated, "nl")
    assert NNBSP not in result
    assert result == "Hallo: hoe gaat het?"


def test_farsi_strips_an_injected_narrow_space():
    translated = f"salaam{NNBSP}!"
    result = normalize_injected_invisibles("hello!", translated, "fa")
    assert NNBSP not in result


def test_missing_target_lang_defaults_to_the_safe_strip_behaviour():
    """A caller that cannot supply target_lang (the legacy non-AST path) must not
    accidentally start preserving the character for every locale."""
    translated = f"Hallo{NNBSP}wereld"
    assert NNBSP not in normalize_injected_invisibles("Hello world", translated, None)
    assert NNBSP not in normalize_injected_invisibles("Hello world", translated)


def test_a_character_the_source_itself_uses_still_survives_regardless_of_locale():
    """The existing fidelity rule (source-conditional) takes priority: this is not
    a blanket "always strip for non-fr" rule, it only fires on injection."""
    text = f"word{NNBSP}word"
    assert normalize_injected_invisibles(text, text, "de") == text


def test_other_injected_invisibles_are_unaffected_by_locale():
    """Regression guard: the new per-character locale table must not weaken the
    existing unconditional invisibles (soft hyphen, non-breaking hyphen, etc.)."""
    SHY = "­"
    translated = f"depen{SHY}dent"
    assert normalize_injected_invisibles("dependent", translated, "fr") == "dependent"
