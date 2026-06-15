"""Tests for TC-AGT-12: Professionalize-powered blocker classifier."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.observability.blocker_classifier import (
    BlockerCategory,
    _parse_classifications,
    build_classifier_prompt,
    classify_blockers,
    collect_blockers,
)
from src.workers.continuation_state import add_blocker, start_run


SAMPLE_BLOCKERS = [
    {
        "source": "continuation_state",
        "blocker_id": "BLK-001",
        "type": "external_dependency",
        "description": "LLM endpoint unreachable",
    },
    {
        "source": "quarantine",
        "blocker_id": "overview.md",
        "type": "quarantined_file",
        "description": "File quarantined after 3 retries",
        "tgt_lang": "ar",
    },
]


@pytest.fixture()
def state_file(tmp_path):
    return tmp_path / "continuation_state.json"


@pytest.fixture()
def quarantine_file(tmp_path):
    return tmp_path / "quarantine.jsonl"


class TestBuildPrompt:
    def test_prompt_contains_blockers(self):
        prompt = build_classifier_prompt(SAMPLE_BLOCKERS)
        assert "BLK-001" in prompt
        assert "LLM endpoint unreachable" in prompt
        assert "overview.md" in prompt

    def test_prompt_contains_context(self):
        prompt = build_classifier_prompt(SAMPLE_BLOCKERS, {"site_id": "docs.aspose.net"})
        assert "docs.aspose.net" in prompt

    def test_prompt_has_categories(self):
        prompt = build_classifier_prompt(SAMPLE_BLOCKERS)
        assert "CONFIG_ERROR" in prompt
        assert "DATA_QUALITY" in prompt
        assert "MODEL_LIMITATION" in prompt


class TestParseClassifications:
    def test_parse_valid_array(self):
        response = (
            '[{"blocker_id": "BLK-001", "category": "EXTERNAL_DEPENDENCY", "confidence": 0.9}]'
        )
        result = _parse_classifications(response)
        assert len(result) == 1
        assert result[0]["category"] == "EXTERNAL_DEPENDENCY"

    def test_parse_empty_array(self):
        result = _parse_classifications("[]")
        assert result == []

    def test_parse_invalid_category_normalized(self):
        response = '[{"blocker_id": "BLK-001", "category": "INVALID_CAT"}]'
        result = _parse_classifications(response)
        assert result[0]["category"] == "UNKNOWN"

    def test_parse_valid_category_preserved(self):
        for cat in BlockerCategory:
            response = f'[{{"blocker_id": "x", "category": "{cat.value}"}}]'
            result = _parse_classifications(response)
            assert result[0]["category"] == cat.value

    def test_parse_embedded_in_text(self):
        response = (
            'Here are the results:\n[{"blocker_id": "BLK-001", "category": "CONFIG_ERROR"}]\nDone.'
        )
        result = _parse_classifications(response)
        assert len(result) == 1
        assert result[0]["category"] == "CONFIG_ERROR"

    def test_parse_invalid_json(self):
        result = _parse_classifications("not parseable")
        assert len(result) == 1
        assert result[0]["blocker_id"] == "RAW"

    def test_parse_empty(self):
        result = _parse_classifications("")
        assert result == []


class TestCollectBlockers:
    def test_collect_from_continuation_state(self, state_file, quarantine_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        add_blocker("BLK-001", "test blocker", blocker_type="config", state_file=state_file)
        blockers = collect_blockers(
            continuation_state_file=state_file,
            quarantine_file=quarantine_file,
        )
        assert len(blockers) == 1
        assert blockers[0]["blocker_id"] == "BLK-001"
        assert blockers[0]["source"] == "continuation_state"

    def test_collect_from_quarantine(self, state_file, quarantine_file):
        quarantine_file.write_text(
            json.dumps(
                {
                    "output_path": "/path/to/file.md",
                    "tgt_lang": "ar",
                    "retry_count": 3,
                    "quarantined_at": "2026-06-13T12:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        blockers = collect_blockers(
            continuation_state_file=state_file,
            quarantine_file=quarantine_file,
        )
        assert len(blockers) == 1
        assert blockers[0]["source"] == "quarantine"
        assert blockers[0]["tgt_lang"] == "ar"

    def test_collect_empty(self, state_file, quarantine_file):
        blockers = collect_blockers(
            continuation_state_file=state_file,
            quarantine_file=quarantine_file,
        )
        assert blockers == []

    def test_collect_combined(self, state_file, quarantine_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        add_blocker("BLK-001", "test", state_file=state_file)
        quarantine_file.write_text(
            json.dumps({"output_path": "/path/f.md", "tgt_lang": "fr", "retry_count": 3}) + "\n",
            encoding="utf-8",
        )
        blockers = collect_blockers(
            continuation_state_file=state_file,
            quarantine_file=quarantine_file,
        )
        assert len(blockers) == 2


class TestClassifyBlockers:
    def test_disabled_returns_empty(self):
        result = classify_blockers(
            SAMPLE_BLOCKERS,
            classifier_config={"enabled": False},
        )
        assert result["classifications"] == []
        assert result["llm_called"] is False

    def test_no_blockers(self, tmp_path):
        result = classify_blockers(
            [],
            classifier_config={"enabled": True},
            output_dir=tmp_path,
        )
        assert result["classifications"] == []

    def test_dry_run_writes_file(self, tmp_path):
        result = classify_blockers(
            SAMPLE_BLOCKERS,
            classifier_config={"enabled": True, "dry_run": True},
            output_dir=tmp_path,
        )
        assert result["dry_run"] is True
        assert result["llm_called"] is False
        assert result["classifications"][0]["blocker_id"] == "DRY_RUN"
        assert result["output_path"]

        out_path = Path(result["output_path"])
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["blockers_count"] == 2

    def test_dry_run_prompt_populated(self, tmp_path):
        result = classify_blockers(
            SAMPLE_BLOCKERS,
            classifier_config={"enabled": True, "dry_run": True},
            output_dir=tmp_path,
        )
        assert "BLK-001" in result["prompt"]

    @patch("src.observability.blocker_classifier._call_llm")
    def test_live_mode_calls_llm(self, mock_call_llm, tmp_path):
        mock_call_llm.return_value = '[{"blocker_id": "BLK-001", "category": "EXTERNAL_DEPENDENCY", "confidence": 0.95, "reasoning": "LLM endpoint down", "recommendation": "Check network"}]'
        result = classify_blockers(
            SAMPLE_BLOCKERS,
            classifier_config={"enabled": True, "dry_run": False},
            output_dir=tmp_path,
        )
        assert result["llm_called"] is True
        assert len(result["classifications"]) == 1
        assert result["classifications"][0]["category"] == "EXTERNAL_DEPENDENCY"

    @patch("src.observability.blocker_classifier._call_llm")
    def test_live_mode_llm_failure(self, mock_call_llm, tmp_path):
        mock_call_llm.return_value = None
        result = classify_blockers(
            SAMPLE_BLOCKERS,
            classifier_config={"enabled": True, "dry_run": False},
            output_dir=tmp_path,
        )
        assert result["llm_called"] is False
        assert any(c["blocker_id"] == "LLM_UNAVAILABLE" for c in result["classifications"])

    def test_default_config_disabled(self):
        result = classify_blockers(SAMPLE_BLOCKERS)
        assert result["classifications"] == []

    def test_with_context(self, tmp_path):
        result = classify_blockers(
            SAMPLE_BLOCKERS,
            classifier_config={"enabled": True, "dry_run": True},
            context={"site_id": "docs.aspose.net", "recent_failures": 3},
            output_dir=tmp_path,
        )
        assert "docs.aspose.net" in result["prompt"]
