from concurrent.futures import ThreadPoolExecutor

import pytest

from src.model_runtime.campaign_llm_policy import (
    DeferredLLMCall,
    accounted_generate,
    campaign_llm_scope,
    llm_category,
)


@pytest.mark.parametrize("mode", ["immediate", "deferred"])
@pytest.mark.parametrize("category", ["identity", "primary", "retry", "repair", "validation"])
def test_category_policy_and_accounting(mode, category):
    events, calls = [], []

    def generate():
        calls.append(1)
        return "candidate secret", 5, 2

    with campaign_llm_scope(mode, category, events.append, campaign_id="fixture"):
        if mode == "deferred" and category != "validation":
            with pytest.raises(DeferredLLMCall):
                accounted_generate("professionalize_llm", generate)
            assert calls == []
            assert [e["outcome"] for e in events] == ["deferred"]
        else:
            assert accounted_generate("professionalize_llm", generate)[0] == "candidate secret"
            assert calls == [1]
            assert [e["outcome"] for e in events] == ["started", "completed"]
    assert "candidate secret" not in str(events)
    assert all(e["category"] == category for e in events)


def test_failure_is_recorded_and_scope_is_restored():
    events = []

    def fail():
        raise TimeoutError("provider secret")

    with campaign_llm_scope("immediate", "retry", events.append):
        with pytest.raises(TimeoutError):
            accounted_generate("model", fail)
    assert events[-1]["error_class"] == "TimeoutError"
    assert "provider secret" not in str(events)
    assert accounted_generate("model", lambda: ("ok", 1, 1))[0] == "ok"


def test_nested_validation_allowed_and_threads_are_isolated():
    @llm_category("validation")
    def validate():
        return accounted_generate("model", lambda: ("ok", 1, 1))

    def run(mode):
        events = []
        with campaign_llm_scope(mode, "primary", events.append):
            assert validate()[0] == "ok"
        return events

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, ["immediate", "deferred"]))
    assert [rows[0]["mode"] for rows in results] == ["immediate", "deferred"]
    assert all(row["category"] == "validation" for rows in results for row in rows)
