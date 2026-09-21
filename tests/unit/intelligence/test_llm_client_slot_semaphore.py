"""TC-APT-094: src/intelligence/llm_client.py must also acquire the
cross-process LLM slot semaphore.

This client is pointed at the same shared `professionalize_llm` endpoint by
the TM improvement worker (config/global.yaml `tm_improvement.llm`),
independently of the K-launcher fleet -- without this, its calls evade the
fleet-wide cap on in-flight API calls that TC-APT-094 exists to enforce.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.intelligence.llm_client import LLMClient, LLMConfig


def _make_client(mock_provider: MagicMock) -> LLMClient:
    with patch(
        "src.model_runtime.llm_providers.create_provider", return_value=mock_provider
    ):
        client = LLMClient(LLMConfig(provider="openai_compatible", model="recommended"))
    assert client.is_available()
    return client


class TestCallLlmAcquiresSlot:
    def test_generate_call_holds_exactly_one_slot_and_releases_it_after(
        self, tmp_path, monkeypatch
    ):
        slots_path = tmp_path / "llm_slots.json"
        monkeypatch.setenv("HT_LLM_SLOTS_PATH", str(slots_path))

        seen: dict[str, object] = {}

        def _generate(system_prompt, user_text):
            seen["slots_during_call"] = json.loads(
                slots_path.read_text(encoding="utf-8")
            )["slots"]
            return "adapted", 10, 5

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = _generate
        client = _make_client(mock_provider)

        result = client._call_llm("prompt")

        assert result == "adapted"
        assert len(seen["slots_during_call"]) == 1
        assert json.loads(slots_path.read_text(encoding="utf-8"))["slots"] == {}

    def test_releases_the_slot_even_when_generate_raises(self, tmp_path, monkeypatch):
        slots_path = tmp_path / "llm_slots.json"
        monkeypatch.setenv("HT_LLM_SLOTS_PATH", str(slots_path))

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = RuntimeError("provider failure")
        client = _make_client(mock_provider)

        try:
            client._call_llm("prompt")
        except RuntimeError:
            pass

        assert json.loads(slots_path.read_text(encoding="utf-8"))["slots"] == {}
