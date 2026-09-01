"""
HT-QUALITY-GATES-001 RC2: PlaceholderManager.restore() brace-stripped fallback.

Root cause confirmed DIRECTLY against the real nllb_200_1.3b model (not
theorized): protecting "with `.mtl`" as "with {PLACEHOLDER_0}" and
translating en->fi produced raw model output
'OBJ (PLACEHOLDER_0):n kanssa), STL:n (binääri ja ASCII) ...' — the braces
are gone entirely, and a Finnish case suffix (":n") is glued directly onto
the bare token. None of the pre-existing restore() passes (all brace-
anchored) could see this shape, so it shipped into production untouched —
confirmed present in a real retranslated file (products.aspose.org fi/3d/java
FAQ answer field, from this session's ground-truth verification pass).

This is the exact case pinned below, not a synthetic approximation.
"""
from src.translation_engine.extractor.placeholder_manager import PlaceholderManager


class TestBareBraceWrappedCorrectValue:
    """Found 2026-07-22 in real reference.aspose.org output (es/pdf/net/
    ColumnInfo.md, he/pdf/net/ColumnInfo.md) from the cross_locale_dup
    remediation campaign: description/summary shipped as
    "`{ColumnInfo}` clase con 3 propiedades" instead of "`ColumnInfo`
    clase con 3 propiedades". Root cause: reference.aspose.org's frontmatter
    preserve_patterns have no backtick-specific rule (backticks are only
    protected via the AST-level `codespan` preserve_block, which doesn't
    apply to frontmatter strings) -- only the bare PascalCase pattern
    matches "ColumnInfo" without the surrounding backticks, so the
    placeholder ends up sitting directly between literal backtick and brace
    characters: "`{PLACEHOLDER_0}` class...". The model correctly guessed
    the identifier but kept the literal `{`/`}` around it instead of the
    exact "PLACEHOLDER_0" token, and none of the existing digit-anchored
    passes match (no digit remains), while the close-match fallback's naive
    substring check treated "ColumnInfo" as already present (true, but
    still brace-wrapped) and skipped it."""

    def test_real_confirmed_repro_columninfo(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "ColumnInfo"}
        raw_model_output = "`{ColumnInfo}` clase con 3 propiedades"

        restored = pm.restore(raw_model_output, placeholder_map)

        assert restored == "`ColumnInfo` clase con 3 propiedades"

    def test_whitespace_inside_braces_still_stripped(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "ColumnInfo"}
        raw = "`{ ColumnInfo }` clase con 3 propiedades"

        restored = pm.restore(raw, placeholder_map)

        assert restored == "`ColumnInfo` clase con 3 propiedades"

    def test_does_not_touch_unrelated_braced_text(self):
        """A brace pair NOT matching any placeholder's original value must
        be left alone -- this pass is a targeted, exact-value match, not a
        blanket brace-stripper."""
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "ColumnInfo"}
        raw = "See {SomeOtherClass} for details. `ColumnInfo` clase con 3 propiedades"

        restored = pm.restore(raw, placeholder_map)

        assert "{SomeOtherClass}" in restored
        assert restored.count("ColumnInfo") == 1


class TestFuzzyVariantBraceStripOrderingGap:
    """HT-QUALITY-GATES-001 Part 21: the exact-value brace-strip pass and the
    fuzzy-variant substitution pass ran in an order that left a gap -- if the
    model's guess is a close VARIANT rather than an exact match (e.g.
    "{ColumnInfos}" instead of "{ColumnInfo}"), the exact-match brace-strip
    pass (which ran first) can't see it (not an exact value match), and the
    fuzzy-variant pass (which ran after) only swaps the inner word via
    substring replace, leaving the surrounding braces untouched:
    "{ColumnInfos}" -> "{ColumnInfo}", braces intact, still a leaked-looking
    token. Fixed by re-running the brace-strip pass a final time after the
    fuzzy-variant substitution."""

    def test_close_variant_inside_braces_loses_both_typo_and_braces(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "ColumnInfo"}
        raw = "`{ColumnInfos}` clase con 3 propiedades"

        restored = pm.restore(raw, placeholder_map)

        assert restored == "`ColumnInfo` clase con 3 propiedades"
        assert "{" not in restored and "}" not in restored

    def test_close_variant_without_surrounding_backticks(self):
        """OutlineElement/OutlineElements (ratio ~0.97) is a genuine close-typo
        variant, unlike PropertyCollection/PropertiesCollection (ratio ~0.89,
        below the intentional 0.92 cutoff -- see the comment on that cutoff
        just above in the source) which the pipeline deliberately does NOT
        auto-correct since singular/plural could be a real, non-typo
        difference."""
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "OutlineElement"}
        raw = "See {OutlineElements} for details."

        restored = pm.restore(raw, placeholder_map)

        assert restored == "See OutlineElement for details."


class TestBraceStrippedRestore:
    def test_real_confirmed_repro_fi_3d_java(self):
        """The literal input/output pair confirmed by running the real
        model, from this session's Phase A4 investigation."""
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "`.mtl`"}
        raw_model_output = (
            "OBJ (PLACEHOLDER_0):n kanssa), STL:n (binääri ja ASCII) glTF 2.0: n, "
            "GLB:nen (bynääripäin glFT) ja FBX:nin (vain tuonti)."
        )

        restored = pm.restore(raw_model_output, placeholder_map)

        assert "PLACEHOLDER_0" not in restored
        assert "`.mtl`" in restored

    def test_bare_token_with_no_adjacent_text(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "`Aspose.Cells.Cell`"}
        raw = "See the PLACEHOLDER_0 class for details."

        restored = pm.restore(raw, placeholder_map)

        assert restored == "See the `Aspose.Cells.Cell` class for details."

    def test_multiple_bare_tokens_each_restored_independently(self):
        pm = PlaceholderManager()
        placeholder_map = {
            "{PLACEHOLDER_0}": "`.mtl`",
            "{PLACEHOLDER_1}": "`.obj`",
        }
        raw = "Supports PLACEHOLDER_0 and PLACEHOLDER_1 formats."

        restored = pm.restore(raw, placeholder_map)

        assert restored == "Supports `.mtl` and `.obj` formats."

    def test_well_formed_braced_token_still_restored_normally(self):
        """The common, non-corrupted case must keep working unchanged."""
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "`.mtl`"}
        raw = "Supports {PLACEHOLDER_0} format."

        restored = pm.restore(raw, placeholder_map)

        assert restored == "Supports `.mtl` format."

    def test_unknown_bare_number_left_untouched(self):
        """A hallucinated placeholder number with no matching map entry
        can't be restored (nothing to restore it to) -- left as-is so the
        downstream leak-check can still flag it, rather than silently
        swallowed."""
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "`.mtl`"}
        raw = "Mentions PLACEHOLDER_99 for some reason."

        restored = pm.restore(raw, placeholder_map)

        assert "PLACEHOLDER_99" in restored

    def test_extract_placeholders_is_brace_agnostic(self):
        pm = PlaceholderManager()
        assert pm.extract_placeholders("bare PLACEHOLDER_0 here") == ["PLACEHOLDER_0"]
        assert pm.extract_placeholders("braced {PLACEHOLDER_0} here") == ["{PLACEHOLDER_0}"]
        assert pm.extract_placeholders("no placeholders here") == []


class TestFindMissingProtectedValues:
    """
    HT-QUALITY-GATES-001 Part 20: detect when the MT model drops a protected
    span entirely (not corrupting its shape, which restore()'s fuzzy pass
    already recovers -- confirmed real cases above all restore fine). This is
    the residual, more severe failure mode: no trace of the placeholder
    survives at all, replaced by unrelated hallucinated fluent prose.

    The 12-placeholder case below is the exact real `cells/net` content_left
    segment reproduced directly against the real nllb_200_1.3b model this
    session: 3 of 12 protected values (`DateTime`, `Cell.PutValue(value)`,
    `Workbook.Worksheets`) never appeared anywhere in the restored hr output.
    """

    def test_real_confirmed_repro_cells_net_dropped_values(self):
        pm = PlaceholderManager()
        placeholder_map = {
            "{PLACEHOLDER_0}": "`Workbook(fileName)`",
            "{PLACEHOLDER_1}": "`Save(fileName)`",
            "{PLACEHOLDER_2}": "`string`",
            "{PLACEHOLDER_3}": "`int`",
            "{PLACEHOLDER_4}": "`bool`",
            "{PLACEHOLDER_5}": "`decimal`",
            "{PLACEHOLDER_6}": "`DateTime`",
            "{PLACEHOLDER_7}": "`Cell.PutValue(value)`",
            "{PLACEHOLDER_8}": "`Cell.StringValue`",
            "{PLACEHOLDER_9}": "`Cell.Value`",
            "{PLACEHOLDER_10}": "`Cell.Formula`",
            "{PLACEHOLDER_11}": "`Workbook.Worksheets`",
        }
        raw_hr_output = (
            "- **XLSX čitati/pisati:** Otvoriti i pohraniti radne sveske s punom "
            "vjernošću za povratak uz pomoć {PLACEHOLDER_0} i { PLAceHolder_1}. "
            "- * Vrijednosti u stanicama: ** Napisati vrijednosti {placeholdera_2}, "
            "{placeholdera_3} , {plejeholdera _4},, {pljesholdere_5} te {platni "
            "listovi po imenu ili indeksu. } - ***Prihod ćelije:*** Pročitajte "
            "vrednosti sa {PLESHOLEDER_8} a {BLESHODLER__9}.- **Formule: **** "
            "Skladi nizove putem formule {PPLESHALEDERA_10}  procijenjene Excelom "
            "na otvorenim radnim listovima. - Navigacija kroz listu: pristup "
            "prema nazivu ili indeksu preko aplikacije "
            "{PUČNASTE NA SLOVENOM STANKU} .11"
        )
        restored = pm.restore(raw_hr_output, placeholder_map)

        missing = pm.find_missing_protected_values(restored, placeholder_map)

        assert set(missing) == {
            "`DateTime`",
            "`Cell.PutValue(value)`",
            "`Workbook.Worksheets`",
        }

    def test_all_values_present_returns_empty(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "`.mtl`", "{PLACEHOLDER_1}": "`.obj`"}
        restored = "Supports `.mtl` and `.obj` formats."

        assert pm.find_missing_protected_values(restored, placeholder_map) == []

    def test_empty_map_returns_empty(self):
        pm = PlaceholderManager()
        assert pm.find_missing_protected_values("anything", {}) == []
