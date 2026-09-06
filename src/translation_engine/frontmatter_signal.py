"""Single source for the frontmatter language-signal thresholds (TC-APT-090).

The same rule is enforced in two layers: the engine's FrontmatterLanguageCheck
and the write-time verification in ``src/verification/checks/language_check.py``.
Those layers already say so in their own comments -- language_check.py carried a
copy of engine.py's 6-character floor with a note explaining it was copied --
and a fix applied to one of them left the other rejecting the same cells for the
same reason. That cost two full retrigger cycles.

This module exists so the thresholds cannot drift apart again. It is a leaf: it
imports nothing from the engine, so the verification layer can use it without
pulling in model loading. Same pattern as ``governed_terms.py`` (TC-APT-079),
which ended the same duplication for governed terminology across four
inventories.

Calibrated on the shipped corpus, 19 locales and 68 samples per length:
langdetect accuracy on a signal residue is 66.2% at 6 alphabetic characters,
88.2% at 20, 91.2% at 25-30, 98.5% at 40 and 100% at 70. Its confidence does not
fall when it is wrong -- 87-91% of wrong answers exceed a 0.80 threshold and the
median confidence when wrong is 1.000 -- so no confidence cut helps and length
is the only usable lever.
"""

from __future__ import annotations

import difflib

#: Minimum alphabetic characters of signal residue before a language verdict is
#: allowed. Below this the residue is page scaffolding rather than prose: on
#: introducing-cells-foss-rust the ENGLISH SOURCE seoTitle strips to
#: "for - Open-Source Excel Crate for" and reads en 0.70 / ro 0.30, which is why
#: cs, id, it, hi and ru were all rejected there as Romanian while genuine
#: Romanian passed. The verdict tracked the page, not the translation.
MIN_FRONTMATTER_SIGNAL_ALPHA = 40

#: Below the floor the guard still has a job -- catching a field that was never
#: translated -- but it must do it without naming a language. An untranslated
#: field's residue IS the source residue, so compare them directly.
#:
#: Exact identity, chosen from the 5,753 shipped pairs this rule actually judges
#: (median similarity 0.308, p95 0.741). False rejections of correct cells by
#: threshold: 0.90 -> 76 (1.32%), 0.95 -> 43, 0.98 -> 25, 1.00 -> 25. The curve
#: flattens at 0.98 because 25 correct cells have a residue byte-identical to the
#: source -- legitimate kept terms. Nothing below 1.0 buys accuracy, so take the
#: only value whose premise is literally true: reject when the text is unchanged.
FRONTMATTER_UNTRANSLATED_SIMILARITY = 1.0


def residue_similarity(source_residue: str, translated_residue: str) -> float:
    """Similarity of two signal residues, 1.0 meaning identical.

    Both layers must score identity the same way, or one will reject what the
    other accepts.
    """
    return difflib.SequenceMatcher(
        None, (source_residue or "").strip(), (translated_residue or "").strip()
    ).ratio()


def is_untranslated(source_residue: str, translated_residue: str) -> bool:
    """True when the residue is unchanged from the source, i.e. not translated.

    Empty residues never count: there is nothing to compare, and a verdict with
    no evidence is what this whole taskcard exists to remove.
    """
    if not (source_residue or "").strip() or not (translated_residue or "").strip():
        return False
    return residue_similarity(source_residue, translated_residue) >= (
        FRONTMATTER_UNTRANSLATED_SIMILARITY
    )
