"""
TC-APT-110 (2026-09-11): PlaceholderManager.restore() glued-word fix.

Root cause: the LLM can drop the whitespace immediately before/after a
placeholder token during generation while leaving the braces themselves
intact (a distinct failure mode from the already-fixed RC2 brace-stripped
bug, which is about the braces disappearing, not the space). Naive
restore() then glues the restored value directly onto adjacent prose --
e.g. en "with {PLACEHOLDER_0}" -> pt "com{PLACEHOLDER_0}" -> restored
"comWorkbook.save", a reader-facing garbled non-word.

Confirmed directly (not synthetic) on cells/rust/getting-started/
quickstart.md's frontmatter `description` field: 8/25 locales in
wave-cellsrust-quickstart-fixretrigger-20260911 (ar, cs, es, fa, hu, nl,
pt, uk) shipped this defect, caught by a 5-agent parallel rubric review
(config/review_rubric.yaml RB-004) before commit -- see
data/campaigns/heal_queue.jsonl tickets
`auto-wave-cellsrust-quickstart-fixretrigger-20260911-*-quickstart`. Never
seen in body markdown across any of the 25 locales on the same page,
because body identifiers are backtick-delimited (the backtick, not a
space, sits at the placeholder boundary there) -- only the frontmatter
`description` field carries the bare identifier with no delimiter, so a
lost space had nothing else to absorb it. The exact strings below are
quoted directly from the real review findings, not paraphrased.
"""
from src.translation_engine.extractor.placeholder_manager import PlaceholderManager


class TestGluedWordRealRepros:
    """Each case is the literal (minus surrounding sentence trimming)
    shape a review agent quoted from the actual committed-candidate file,
    reconstructed as the pre-restore raw model output PlaceholderManager
    would have received (braces intact, boundary space missing)."""

    def test_pt_single_sided_glue_both_identifiers(self):
        pm = PlaceholderManager()
        placeholder_map = {
            "{PLACEHOLDER_0}": "Workbook.save",
            "{PLACEHOLDER_1}": "Workbook.load_xlsx",
        }
        raw = "salvando com{PLACEHOLDER_0} e recarregando com{PLACEHOLDER_1}."

        restored = pm.restore(raw, placeholder_map)

        assert restored == "salvando com Workbook.save e recarregando com Workbook.load_xlsx."

    def test_hu_double_sided_glue(self):
        """hu was the worst-observed case: glued on BOTH sides of BOTH
        identifiers (article/preposition before, suffix after, zero
        separator anywhere)."""
        pm = PlaceholderManager()
        placeholder_map = {
            "{PLACEHOLDER_0}": "Workbook.save",
            "{PLACEHOLDER_1}": "Workbook.load_xlsx",
        }
        raw = (
            "mentés a{PLACEHOLDER_0}használatával, "
            "és újratöltés a{PLACEHOLDER_1}segítségével."
        )

        restored = pm.restore(raw, placeholder_map)

        assert "aWorkbook" not in restored
        assert "savehaszn" not in restored
        assert "a Workbook.save használatával" in restored
        assert "a Workbook.load_xlsx segítségével" in restored

    def test_ar_multiple_glued_tokens_in_one_sentence(self):
        """ar had 4 separate glue points in the same description sentence,
        each between an Arabic word and a Latin-script protected value."""
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "Workbook", "{PLACEHOLDER_1}": "Rust"}
        raw = "مصنف{PLACEHOLDER_0}Excel لك في{PLACEHOLDER_1}باستخدام"

        restored = pm.restore(raw, placeholder_map)

        assert "مصنفWorkbook" not in restored
        assert "فيRust" not in restored


class TestGluedWordFixDoesNotRegressLegitimateNoSpace:
    """The fix must stay narrowly scoped: punctuation boundaries and
    no-space-convention scripts (CJK/Thai/etc.) must be completely
    unaffected -- see the already-passing brace-stripped-restore suite for
    the documented Finnish case-suffix example this must not break."""

    def test_finnish_colon_suffix_unaffected(self):
        """Real confirmed case from test_placeholder_manager_brace_stripped.py:
        a colon-attached Finnish case suffix is legitimate and must not
        gain a synthetic space (colon is not alnum, so the new pass never
        fires here)."""
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "`.mtl`"}
        raw = "OBJ (PLACEHOLDER_0):n kanssa)"

        restored = pm.restore(raw, placeholder_map)

        assert restored == "OBJ (`.mtl`):n kanssa)"

    def test_cjk_no_synthetic_space_inserted(self):
        """zh/ja/ko/th all correctly kept native no-space-around-Latin-term
        conventions on the SAME real page/run this bug was found on --
        the fix must not start breaking what was already correct."""
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "Workbook.save"}
        raw = "使用{PLACEHOLDER_0}保存"

        restored = pm.restore(raw, placeholder_map)

        assert restored == "使用Workbook.save保存"

    def test_punctuation_boundary_unaffected(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "ColumnInfo"}
        raw = "See ({PLACEHOLDER_0}) for details."

        restored = pm.restore(raw, placeholder_map)

        assert restored == "See (ColumnInfo) for details."

    def test_already_spaced_text_unaffected(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "Workbook.save"}
        raw = "saving with {PLACEHOLDER_0} correctly."

        restored = pm.restore(raw, placeholder_map)

        assert restored == "saving with Workbook.save correctly."


class TestGluedWordOtherRestorePasses:
    """TC-APT-110 follow-up (r2 reverification): the model can drop the
    boundary space around ANY token shape the later fallback passes handle,
    not just the intact braced form -- each pass needs the same boundary
    logic."""

    def test_bare_token_glued_gains_space(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "Workbook.save"}
        raw = "uložení pomocíPLACEHOLDER_0 správně."

        restored = pm.restore(raw, placeholder_map)

        assert "pomocíWorkbook" not in restored
        assert "pomocí Workbook.save" in restored

    def test_bare_token_finnish_colon_suffix_still_unaffected(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "`.mtl`"}
        raw = "OBJ (PLACEHOLDER_0):n kanssa)"

        restored = pm.restore(raw, placeholder_map)

        assert restored == "OBJ (`.mtl`):n kanssa)"

    def test_fuzzy_token_glued_gains_space(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_1}": "Workbook.load_xlsx"}
        raw = "načtení pomocí{ PLACHOLDER _1 }znovu."

        restored = pm.restore(raw, placeholder_map)

        assert "pomocíWorkbook" not in restored
        assert "xlsxznovu" not in restored
        assert "pomocí Workbook.load_xlsx znovu" in restored

    def test_brace_wrapped_guessed_value_glued_gains_space(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "Workbook.save"}
        raw = "uložení pomocí{Workbook.save}správně."

        restored = pm.restore(raw, placeholder_map)

        assert "pomocíWorkbook" not in restored
        assert "pomocí Workbook.save správně" in restored

    def test_brace_wrapped_guessed_value_spaced_unaffected(self):
        pm = PlaceholderManager()
        placeholder_map = {"{PLACEHOLDER_0}": "ColumnInfo"}
        raw = "`{ColumnInfo}` clase principal."

        restored = pm.restore(raw, placeholder_map)

        assert restored == "`ColumnInfo` clase principal."
