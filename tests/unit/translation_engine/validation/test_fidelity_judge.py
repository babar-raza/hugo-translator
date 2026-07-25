"""Tests for the LLM meaning-fidelity judge (HT-QUALITY-GATES-001 Part 22,
plan 5.4 item 3).

Mocking pattern mirrors tests/unit/test_correction_pass.py's
TestAttemptCorrection -- fidelity_judge.judge_fidelity() uses the exact same
lazy-import-then-construct-provider idiom as correction.py's
attempt_correction(), so patches target the same two symbols.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.translation_engine.validation.fidelity_judge import (
    FidelityVerdict,
    _aligned_fidelity_chunks,
    _parse_response,
    _replace_fenced_code,
    judge_fidelity,
)


class TestParseResponse:
    def test_clean_json(self):
        score, issues, parsed = _parse_response('{"score": 8, "issues": []}')
        assert score == 0.8
        assert issues == []
        assert parsed is True

    def test_json_with_issues(self):
        score, issues, parsed = _parse_response(
            '{"score": 2, "issues": ["source says supported, translation says not supported"]}'
        )
        assert score == 0.2
        assert len(issues) == 1
        assert parsed is True

    def test_json_wrapped_in_prose(self):
        """Some LLMs prepend commentary despite instructions -- must still parse."""
        score, issues, parsed = _parse_response(
            'Here is my verdict:\n{"score": 6, "issues": ["minor omission"]}\nDone.'
        )
        assert score == 0.6
        assert parsed is True

    def test_score_clamped_to_range(self):
        score, _, _ = _parse_response('{"score": 15, "issues": []}')
        assert score == 1.0
        score, _, _ = _parse_response('{"score": -3, "issues": []}')
        assert score == 0.0

    def test_malformed_json_falls_back_to_leading_int(self):
        score, issues, parsed = _parse_response("Score: 7 out of 10, looks fine")
        assert score == 0.7
        assert issues == []
        assert parsed is False

    def test_empty_response_returns_none(self):
        score, issues, parsed = _parse_response("")
        assert score is None
        assert parsed is False

    def test_no_number_anywhere_returns_none(self):
        score, issues, parsed = _parse_response("I cannot evaluate this.")
        assert score is None
        assert parsed is False

    def test_issues_non_list_coerced(self):
        """A model returning issues as a string (not array) must not crash."""
        score, issues, parsed = _parse_response('{"score": 3, "issues": "wrong meaning"}')
        assert score == 0.3
        assert issues == ["wrong meaning"]


class TestJudgeFidelity:
    def test_short_complete_document_is_not_asymmetrically_truncated(self):
        source = "SOURCE-START\n" + ("source sentence. " * 400) + "\nSOURCE-TAIL"
        target = "TARGET-START\n" + ("translated sentence. " * 400) + "\nTARGET-TAIL"

        chunks = _aligned_fidelity_chunks(source, target)

        assert chunks == [(source, target)]
        assert "SOURCE-TAIL" in chunks[0][0]
        assert "TARGET-TAIL" in chunks[0][1]

    def test_fenced_code_payload_is_replaced_with_aligned_markers(self):
        text = "Before\n```rust\nlet candidate = secret();\n```\nAfter"

        prepared = _replace_fenced_code(text)

        assert prepared == "Before\n<PRESERVED_CODE_BLOCK_1>\nAfter"
        assert "candidate" not in prepared

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_long_document_is_fully_judged_in_aligned_chunks(
        self, mock_registry_cls, mock_backend_cls
    ):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry
        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.side_effect = [
            ('{"score": 9, "issues": []}', 100, 20),
            ('{"score": 4, "issues": ["late semantic reversal"]}', 100, 20),
        ]
        mock_backend_cls.return_value = mock_backend
        source = "\n".join(
            [
                "# One\n" + ("source one. " * 800),
                "# Two\n" + ("source two. " * 800),
                "# Three\n" + ("source three. " * 800),
            ]
        )
        target = "\n".join(
            [
                "# Eins\n" + ("target one. " * 800),
                "# Zwei\n" + ("target two. " * 800),
                "# Drei\n" + ("target three. " * 800),
            ]
        )

        verdict = judge_fidelity(source, target, "en", "de")

        assert verdict.score == 0.4
        assert verdict.verdict == "fail"
        assert mock_backend._provider.generate.call_count == 2
        second_prompt = mock_backend._provider.generate.call_args_list[1].args[1]
        assert "# Three" in second_prompt
        assert "# Drei" in second_prompt

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_high_fidelity_verdict(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = (
            '{"score": 9, "issues": []}', 100, 20,
        )
        mock_backend_cls.return_value = mock_backend

        verdict = judge_fidelity(
            "The Load method returns the collection.",
            "La méthode Load renvoie la collection.",
            "en", "fr",
        )
        assert isinstance(verdict, FidelityVerdict)
        assert verdict.score == 0.9
        assert verdict.verdict == "pass"
        assert verdict.issues == []
        mock_backend.load.assert_called_once()

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_low_fidelity_verdict_fail(self, mock_registry_cls, mock_backend_cls):
        """Reproduces the cataloged 'core'->'Korea' homonym-mistranslation
        shape -- fluent, on-topic, but wrong meaning; embeddings alone
        wouldn't catch this, which is the whole reason this judge exists."""
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = (
            '{"score": 1, "issues": ["\'core\' mistranslated as the country '
            '\'Korea\' instead of the software/hardware sense"]}',
            100, 25,
        )
        mock_backend_cls.return_value = mock_backend

        verdict = judge_fidelity(
            "Set the number of cores used for rendering.",
            "Setați numărul de Coreea utilizate pentru randare.",
            "en", "ro",
        )
        assert verdict.verdict == "fail"
        assert verdict.score == 0.1
        assert len(verdict.issues) == 1

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_mid_score_is_warn(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = ('{"score": 6, "issues": ["awkward phrasing"]}', 10, 5)
        mock_backend_cls.return_value = mock_backend

        verdict = judge_fidelity("Hello world", "Bonjour monde", "en", "fr")
        assert verdict.verdict == "warn"

    @patch("src.model_runtime.registry.ModelRegistry")
    def test_unknown_model_fails_open(self, mock_registry_cls):
        mock_registry = MagicMock()
        mock_registry.get_model.side_effect = KeyError("not found")
        mock_registry_cls.return_value = mock_registry

        verdict = judge_fidelity("src", "tgt", "en", "de", model_id="nonexistent")
        assert verdict is None

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_provider_none_fails_open(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = None
        mock_backend_cls.return_value = mock_backend

        verdict = judge_fidelity("src", "tgt", "en", "it")
        assert verdict is None

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_generate_raises_fails_open(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.side_effect = RuntimeError("API timeout")
        mock_backend_cls.return_value = mock_backend

        verdict = judge_fidelity("src", "tgt", "en", "ja")
        assert verdict is None

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_unparseable_response_fails_open(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = ("I refuse to answer.", 5, 5)
        mock_backend_cls.return_value = mock_backend

        verdict = judge_fidelity("src", "tgt", "en", "ko")
        assert verdict is None

    def test_empty_source_or_translation_fails_open_without_llm_call(self):
        assert judge_fidelity("", "tgt", "en", "fr") is None
        assert judge_fidelity("src", "", "en", "fr") is None

    def test_import_error_fails_open(self):
        with patch.dict("sys.modules", {"src.model_runtime.registry": None}):
            verdict = judge_fidelity("src", "tgt", "en", "de")
            assert verdict is None

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_live_canary_replay_known_bad_columninfo_he(self, mock_registry_cls, mock_backend_cls):
        """Golden-corpus-style replay of a REAL professionalize_llm response,
        captured live 2026-07-23 against the exact file the user flagged
        directly this session (reference.aspose.org/he/pdf/net/ColumnInfo.md
        vs its EN source) -- HT-QUALITY-GATES-001 Part 22/Part 6 item 3's
        canary requirement before trusting this gate. The live judge scored
        this severely mixed-Hebrew/Spanish, mistranslated file 0/10 and named
        specific, human-verifiable issues (including that literal 'FOSS' was
        mistranslated as the Hebrew word for 'fox', a detail not manually
        flagged before running the judge). This test pins that exact real
        response so the parsing path is regression-tested against real judge
        output shape forever, without needing live network access in CI."""
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = (
            '{"score": 0, "issues": ["\'ColumnInfo\' described as \'type of '
            'fox\' instead of class", "Incorrect verb \'supports\' used '
            'instead of \'stores\'", "Mixed Hebrew/Spanish text, not '
            'faithful", "Property descriptions mistranslated (widths, '
            'spacing, count)"]}',
            180, 60,
        )
        mock_backend_cls.return_value = mock_backend

        verdict = judge_fidelity(
            "ColumnInfo stores table layout details, exposing ColumnWidths, "
            "ColumnSpacing, and ColumnCount properties for precise column sizing.",
            "[מגוון] תומך בפרטים של טבלה, expuesto ColumnWidths, ColumnSpacing "
            "ו las propiedades ColumnCount para el tamaño de columna preciso.",
            "en", "he",
        )
        assert verdict.score == 0.0
        assert verdict.verdict == "fail"
        assert len(verdict.issues) == 4
        assert any("fox" in i for i in verdict.issues)

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_live_canary_replay_known_good_columninfo_de(self, mock_registry_cls, mock_backend_cls):
        """Sibling to the known-bad replay above -- same live canary run,
        same real file pair's German translation, which the judge correctly
        scored 8/10 (pass) while still catching the one genuine, minor
        completeness gap (an omitted sentence) rather than either
        rubber-stamping or false-flagging a good-but-imperfect translation."""
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = (
            '{"score": 8, "issues": ["Omitted sentence about ColumnInfo '
            'storing table layout details and purpose"]}',
            180, 40,
        )
        mock_backend_cls.return_value = mock_backend

        verdict = judge_fidelity(
            "ColumnInfo stores table layout details, exposing ColumnWidths, "
            "ColumnSpacing, and ColumnCount properties for precise column sizing.",
            "`ColumnInfo` ist eine Klasse in Aspose.PDF FOSS für .NET. "
            "Eigenschaften: `ColumnCount`, `ColumnSpacing`, `ColumnWidths`.",
            "en", "de",
        )
        assert verdict.score == 0.8
        assert verdict.verdict == "pass"
        assert len(verdict.issues) == 1

    @patch("src.model_runtime.llm_backend.LLMModelBackend")
    @patch("src.model_runtime.registry.ModelRegistry")
    def test_custom_thresholds_respected(self, mock_registry_cls, mock_backend_cls):
        mock_registry = MagicMock()
        mock_registry.get_model.return_value = MagicMock()
        mock_registry_cls.return_value = mock_registry

        mock_backend = MagicMock()
        mock_backend._provider = MagicMock()
        mock_backend._provider.generate.return_value = ('{"score": 7, "issues": []}', 10, 5)
        mock_backend_cls.return_value = mock_backend

        # score 0.7 is normally "pass" (default warn_threshold=0.7 means <0.7
        # warns), but with a stricter warn_threshold of 0.8 it should warn.
        verdict = judge_fidelity(
            "src", "tgt", "en", "fr", warn_threshold=0.8, fail_threshold=0.5,
        )
        assert verdict.verdict == "warn"
