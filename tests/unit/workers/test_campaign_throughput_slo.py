from scripts.campaign.throughput_slo import ThroughputPolicy, evaluate_throughput


def test_throughput_slo_passes_when_rate_eta_and_call_budget_pass():
    result = evaluate_throughput(
        accepted=120,
        remaining=100,
        elapsed_seconds=3600,
        provider_calls=240,
        policy=ThroughputPolicy(
            target_outputs_per_hour=100,
            max_eta_minutes=120,
            max_provider_calls_per_hour=300,
            min_rate_per_hour=50,
        ),
    )
    assert result["passed"] is True
    assert result["reasons"] == []
    assert result["eta_minutes"] == 50.0


def test_throughput_slo_flags_collapse_and_provider_budget():
    result = evaluate_throughput(
        accepted=1,
        remaining=1000,
        elapsed_seconds=3600,
        provider_calls=5000,
        policy=ThroughputPolicy(
            target_outputs_per_hour=100,
            max_eta_minutes=120,
            max_provider_calls_per_hour=3000,
            min_rate_per_hour=10,
        ),
    )
    assert result["passed"] is False
    assert result["collapse"] is True
    assert "below_target_rate" in result["reasons"]
    assert "provider_call_budget_exceeded" in result["reasons"]


def test_zero_elapsed_is_explicitly_non_passing():
    result = evaluate_throughput(accepted=10, remaining=10, elapsed_seconds=0)
    assert result["accepted_outputs_per_hour"] == 0.0
    assert result["passed"] is False
    assert result["eta_minutes"] is None
