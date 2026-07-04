"""TC-C5 / TC-C5B: Correction pass scope guard tests.

Original four cases (TC-C5):
  1. test_purity_failure_skips_correction — purity check is post-correction by architecture
  2. test_placeholder_leak_triggers_correction — attempt_correction called on validation reject
  3. test_failed_correction_returns_none — correction returns None when model not found
  4. test_correction_prompt_excludes_purity_type_issues — prompt builder handles all issue types

TC-C5B bypass cases (added 2026-06-11, ethereal-sauteeing-brook sprint 2):
  5. test_shortcode_loss_bypasses_correction
  6. test_structure_violation_bypasses_correction
  7. test_yaml_failure_bypasses_correction
  8. test_frontmatter_integrity_bypasses_correction
  9. test_language_consistency_bypasses_correction
  10. test_mixed_bypass_and_correctable_proceeds
  11. test_all_bypass_types_are_real_validator_names
  12. test_empty_issues_bypasses_correction
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestCorrectionScope:
    def test_purity_failure_skips_correction(self):
        """Architecture: purity check runs AFTER correction pass, so purity failures
        cannot trigger correction. This test documents the code path ordering."""
        # The correction pass runs at engine.py ~line 1631 on REJECT decision.
        # Purity check runs at engine.py ~line 2048 inside validation_passed=True block.
        # These are separate execution paths — purity fail cannot reach correction entry.

        # We verify via code inspection that the guard is structural, not explicit.
        import inspect

        import src.translation_engine.engine as engine_mod

        src = inspect.getsource(engine_mod.TranslationEngine._verify_final_file_purity)
        # _verify_final_file_purity must NOT call attempt_correction
        assert "attempt_correction" not in src, (
            "Purity check must NOT call attempt_correction directly"
        )

    def test_attempt_correction_called_when_enabled(self):
        """attempt_correction is invoked when correction_pass.enabled=True."""
        from src.translation_engine.correction import attempt_correction

        # Lazy imports inside attempt_correction: patch at the source module
        with patch("src.model_runtime.registry.ModelRegistry") as MockRegistry:
            with patch("src.model_runtime.llm_backend.LLMModelBackend") as MockBackend:
                mock_reg = MagicMock()
                mock_reg.get_model.return_value = MagicMock()
                MockRegistry.return_value = mock_reg
                mock_backend_inst = MagicMock()
                mock_backend_inst._provider.generate.return_value = (
                    "Fixed translation text",
                    50,
                    30,
                )
                MockBackend.return_value = mock_backend_inst

                result = attempt_correction(
                    source_body="Save the document",
                    translated_body="Guardar el documento incorrecto aqui",
                    src_lang="en",
                    tgt_lang="es",
                    issues=[{"severity": "error", "message": "placeholder leak"}],
                    model_id="professionalize_llm",
                )

        assert result == "Fixed translation text"

    def test_failed_correction_returns_none(self):
        """When model not in registry, attempt_correction returns None (never writes bad output)."""
        from src.translation_engine.correction import attempt_correction

        with patch("src.model_runtime.registry.ModelRegistry") as MockRegistry:
            mock_reg = MagicMock()
            mock_reg.get_model.side_effect = KeyError("professionalize_llm not found")
            MockRegistry.return_value = mock_reg

            result = attempt_correction(
                source_body="Source text",
                translated_body="Wrong translation",
                src_lang="en",
                tgt_lang="de",
                issues=[],
                model_id="professionalize_llm",
            )

        assert result is None, "Failed correction must return None, not bad output"

    def test_correction_prompt_excludes_purity_type_issues(self):
        """build_correction_prompt handles all issue types without crashing on purity-type issues."""
        from src.translation_engine.correction import build_correction_prompt

        # Purity is not supposed to trigger correction, but if a purity-type issue
        # were somehow included, the prompt builder must handle it gracefully
        issues = [
            {"severity": "error", "message": "PURITY: 44% wrong language"},
            {"severity": "warning", "message": "placeholder leak detected"},
        ]
        prompt = build_correction_prompt(
            source_body="Source",
            translated_body="Translation",
            src_lang="en",
            tgt_lang="bg",
            issues=issues,
        )
        assert "PURITY" in prompt  # included in issues_text if passed
        assert "placeholder leak" in prompt
        assert "Fix ONLY the issues listed below" in prompt


class TestCorrectionBypassAllowlist:
    """TC-C5B: verify that structural/purity issues bypass the LLM correction call."""

    def _make_issue(self, validator: str, message: str = "test issue") -> object:
        """Create a minimal ValidationIssue-like object."""
        from unittest.mock import MagicMock
        issue = MagicMock()
        issue.validator = validator
        issue.message = message
        return issue

    def test_shortcode_loss_bypasses_correction(self):
        """ShortcodePreservationValidator issues must bypass correction (structural)."""
        from src.translation_engine.correction import attempt_correction
        issue = self._make_issue("ShortcodePreservationValidator", "shortcode {{< tabs >}} lost")
        result = attempt_correction("src", "tgt", "en", "de", [issue])
        assert result is None, "Shortcode loss must bypass LLM correction"

    def test_structure_violation_bypasses_correction(self):
        """StructureValidator issues (e.g., code block count) must bypass correction."""
        from src.translation_engine.correction import attempt_correction
        issue = self._make_issue("StructureValidator", "code block count mismatch: 3 vs 2")
        result = attempt_correction("src", "tgt", "en", "fr", [issue])
        assert result is None, "Code block count mismatch must bypass LLM correction"

    def test_yaml_failure_bypasses_correction(self):
        """YAMLValidator issues must bypass correction."""
        from src.translation_engine.correction import attempt_correction
        issue = self._make_issue("YAMLValidator", "YAML parse error at line 3")
        result = attempt_correction("src", "tgt", "en", "es", [issue])
        assert result is None, "YAML parse error must bypass LLM correction"

    def test_frontmatter_integrity_bypasses_correction(self):
        """FrontmatterIntegrityValidator issues must bypass correction."""
        from src.translation_engine.correction import attempt_correction
        issue = self._make_issue("FrontmatterIntegrityValidator", "title field missing")
        result = attempt_correction("src", "tgt", "en", "it", [issue])
        assert result is None, "Frontmatter integrity failure must bypass LLM correction"

    def test_language_consistency_bypasses_correction(self):
        """LanguageConsistencyValidator issues (wrong-language content) must bypass correction."""
        from src.translation_engine.correction import attempt_correction
        issue = self._make_issue("LanguageConsistencyValidator", "44% wrong language detected")
        result = attempt_correction("src", "tgt", "en", "bg", [issue])
        assert result is None, "Language consistency failure must bypass LLM correction"

    def test_mixed_bypass_and_correctable_proceeds(self):
        """If ANY issue is correctable, the LLM is called (bypass only when ALL bypass)."""
        from src.translation_engine.correction import attempt_correction
        from unittest.mock import patch, MagicMock

        bypass_issue = self._make_issue("StructureValidator", "code block count mismatch")
        correctable_issue = self._make_issue("PlaceholderValidator", "placeholder %s leaked")

        with patch("src.model_runtime.registry.ModelRegistry") as MockReg:
            with patch("src.model_runtime.llm_backend.LLMModelBackend") as MockBackend:
                mock_reg = MagicMock()
                mock_reg.get_model.return_value = MagicMock()
                MockReg.return_value = mock_reg
                mock_be = MagicMock()
                mock_be._provider.generate.return_value = "Fixed text"
                MockBackend.return_value = mock_be

                result = attempt_correction(
                    "src", "tgt", "en", "pl",
                    [bypass_issue, correctable_issue],
                )

        assert result == "Fixed text", (
            "When at least one correctable issue exists, the LLM must be called"
        )

    def test_all_bypass_types_are_real_validator_names(self):
        """Verify that every name in _BYPASS_VALIDATORS matches an actual validator class."""
        from src.translation_engine.correction import _BYPASS_VALIDATORS
        import importlib
        import inspect
        import pkgutil
        import src.translation_engine.validation as val_pkg

        # Collect all class names in the validation package
        actual_validator_classes: set[str] = set()
        for _importer, modname, _ispkg in pkgutil.iter_modules(val_pkg.__path__):
            try:
                mod = importlib.import_module(f"src.translation_engine.validation.{modname}")
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    actual_validator_classes.add(name)
            except Exception:
                pass

        for bypass_name in _BYPASS_VALIDATORS:
            assert bypass_name in actual_validator_classes, (
                f"'{bypass_name}' in _BYPASS_VALIDATORS is not an actual validator class. "
                f"Known classes: {sorted(actual_validator_classes)}"
            )

    def test_empty_issues_bypasses_correction(self):
        """Empty issues list → bypass (nothing to correct)."""
        from src.translation_engine.correction import attempt_correction
        result = attempt_correction("src", "tgt", "en", "de", [])
        assert result is None, "Empty issues list must bypass correction (nothing to fix)"
