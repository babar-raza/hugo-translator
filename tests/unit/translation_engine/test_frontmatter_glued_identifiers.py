"""TC-APT-112 (2026-09-11): GluedIdentifierValidator (TC-APT-110/17073573)
never evaluates frontmatter field text.

Root cause: every production caller of ValidationSuite.validate_aggregated()
(engine.py's candidate-byte acceptance path, file_pipeline.py's two call
sites) builds source_body/translated_body with the frontmatter delimiters
stripped out entirely -- the same separation _check_frontmatter_language
already relies on for its own, independent frontmatter-only pass. The main
validator suite (including GluedIdentifierValidator) therefore structurally
never sees frontmatter text, so a glued technical identifier confined to
the `description` field slips through no matter how correct the gate
itself is.

Confirmed live: wave-cellsrust-quickstart-glueretrigger-20260911r3 --
launched specifically to prove GluedIdentifierValidator (commit 17073573)
closes the class -- still shipped cs and hu glued in the description field
(pt came out clean that run). Strings below are quoted directly from that
run's real committed-candidate files, not paraphrased.
"""

from unittest.mock import Mock

from src.translation_engine.engine import TranslationEngine

_SOURCE = (
    "---\n"
    "title: test\n"
    "description: >-\n"
    "    Create your first Excel XLSX workbook in Rust with Aspose.Cells FOSS: "
    "typed cell values, a formula with a cached result, saving with "
    "Workbook.save and reloading with Workbook.load_xlsx.\n"
    "---\n"
    "body\n"
)


class _DummyConfigService:
    def get_config(self):
        return {
            "adaptive_batching": {"enabled": False},
            "language_detection": {"provider": "none"},
            "autonomous_recovery": {"oom_retry": {"enabled": False}},
        }


def _make_engine() -> TranslationEngine:
    return TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=False,
        enable_telemetry=False,
    )


def _translated(description: str) -> str:
    return f"---\ntitle: test\ndescription: >-\n    {description}\n---\ntelo\n"


class TestRealReproFromR3:
    def test_cs_glue_is_caught(self):
        translated = _translated(
            "uložení pomocíWorkbook.save a načtení pomocíWorkbook.load_xlsx."
        )

        issues = _make_engine()._check_frontmatter_glued_identifiers(translated, _SOURCE)

        assert len(issues) == 2
        assert all(issue.validator == "GluedIdentifierValidator" for issue in issues)
        assert all(issue.location == "frontmatter.description" for issue in issues)

    def test_hu_glue_is_caught(self):
        translated = _translated(
            "mentés aWorkbook.save-el, és újratöltés aWorkbook.load_xlsx-szal."
        )

        issues = _make_engine()._check_frontmatter_glued_identifiers(translated, _SOURCE)

        assert len(issues) == 2

    def test_pt_clean_generation_has_no_issues(self):
        translated = _translated(
            "salvando com Workbook.save e recarregando com Workbook.load_xlsx."
        )

        issues = _make_engine()._check_frontmatter_glued_identifiers(translated, _SOURCE)

        assert issues == []


class TestDoesNotRegressLegitimateCases:
    def test_hu_hyphen_suffix_is_legal(self):
        translated = _translated(
            "mentés a Workbook.save-el, és újratöltés a Workbook.load_xlsx-szal."
        )

        issues = _make_engine()._check_frontmatter_glued_identifiers(translated, _SOURCE)

        assert issues == []

    def test_cjk_no_space_convention_is_legal(self):
        translated = _translated("使用Workbook.save保存")

        issues = _make_engine()._check_frontmatter_glued_identifiers(translated, _SOURCE)

        assert issues == []

    def test_no_source_content_returns_no_issues(self):
        translated = _translated("uložení pomocíWorkbook.save.")

        issues = _make_engine()._check_frontmatter_glued_identifiers(translated, "")

        assert issues == []

    def test_no_frontmatter_returns_no_issues(self):
        issues = _make_engine()._check_frontmatter_glued_identifiers("plain body, no frontmatter", _SOURCE)

        assert issues == []
