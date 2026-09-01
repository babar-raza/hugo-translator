"""Tests for audit_translation_quality.py's meaning-fidelity scoring
(HT-QUALITY-GATES-001 Part 22, plan 5.4 item 4 -- the sampled/periodic-audit
tier, sibling to write_gate.py's Gate 36 synchronous high-risk tier).
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "audit_translation_quality.py"

_spec = importlib.util.spec_from_file_location("audit_translation_quality", _SCRIPT_PATH)
_audit = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("audit_translation_quality", _audit)
_spec.loader.exec_module(_audit)

from src.translation_engine.validation.fidelity_judge import FidelityVerdict  # noqa: E402


class TestScoreMeaningFidelity:
    def test_disabled_when_model_id_none(self):
        score, issues = _audit.score_meaning_fidelity("src", "tgt", "de", None)
        assert score is None
        assert issues == []

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_delegates_to_judge_fidelity(self, mock_judge):
        mock_judge.return_value = FidelityVerdict(
            score=0.3, verdict="fail", issues=["homonym mistranslation"],
            model="professionalize_llm", raw_response="{}",
        )
        source = "---\ntitle: X\n---\n" + ("This is real prose content. " * 5)
        translated = "---\ntitle: X\n---\n" + ("Dies ist echter Prosa-Inhalt. " * 5)

        score, issues = _audit.score_meaning_fidelity(source, translated, "de", "professionalize_llm")

        assert score == 0.3
        assert issues == ["homonym mistranslation"]
        mock_judge.assert_called_once()

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_short_body_skips_without_calling_judge(self, mock_judge):
        score, issues = _audit.score_meaning_fidelity(
            "---\ntitle: X\n---\nHi.\n", "---\ntitle: X\n---\nHallo.\n",
            "de", "professionalize_llm",
        )
        assert score is None
        mock_judge.assert_not_called()

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_judge_returns_none_propagates_as_none(self, mock_judge):
        mock_judge.return_value = None
        source = "---\ntitle: X\n---\n" + ("Real prose content here. " * 5)
        translated = "---\ntitle: X\n---\n" + ("Contenu réel ici. " * 5)

        score, issues = _audit.score_meaning_fidelity(source, translated, "fr", "professionalize_llm")

        assert score is None
        assert issues == []


class TestScorePairFidelityWiring:
    def test_score_pair_populates_fidelity_fields_when_enabled(self, tmp_path):
        src_file = tmp_path / "source.md"
        tgt_file = tmp_path / "source.de.md"
        body = "This is real prose content that is long enough to score. " * 3
        src_file.write_text(f"---\ntitle: X\n---\n{body}\n", encoding="utf-8")
        tgt_file.write_text(f"---\ntitle: X\n---\n{body}\n", encoding="utf-8")

        pair = _audit.SamplePair(
            source_path=src_file, translated_path=tgt_file,
            lang="de", site="site", content_type="other",
        )

        with patch(
            "src.translation_engine.validation.fidelity_judge.judge_fidelity"
        ) as mock_judge:
            mock_judge.return_value = FidelityVerdict(
                score=0.85, verdict="pass", issues=[], model="professionalize_llm",
                raw_response="{}",
            )
            scores = _audit.score_pair(
                pair=pair, terminology_config={}, fasttext_detector=None,
                llm_provider=None, threshold=0.70,
                fidelity_model_id="professionalize_llm",
            )

        assert scores.fidelity_llm == 0.85
        assert scores.fidelity_issues == []

    def test_score_pair_leaves_fidelity_none_when_disabled(self, tmp_path):
        src_file = tmp_path / "source.md"
        tgt_file = tmp_path / "source.de.md"
        src_file.write_text("---\ntitle: X\n---\nbody\n", encoding="utf-8")
        tgt_file.write_text("---\ntitle: X\n---\nkörper\n", encoding="utf-8")

        pair = _audit.SamplePair(
            source_path=src_file, translated_path=tgt_file,
            lang="de", site="site", content_type="other",
        )
        scores = _audit.score_pair(
            pair=pair, terminology_config={}, fasttext_detector=None,
            llm_provider=None, threshold=0.70, fidelity_model_id=None,
        )
        assert scores.fidelity_llm is None
        assert scores.fidelity_issues == []
