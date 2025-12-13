# INF-03 Quick Reference Guide

## New Imports

```python
from src.translation_engine.models import (
    ValidationDecision,      # NEW: Enum for decision outcomes
    TranslationStats,        # Extended with validation metrics
    TranslationResult,       # Extended with decision fields
)
```

## ValidationDecision Enum

```python
ValidationDecision.ACCEPT  # 0 - Translation acceptable
ValidationDecision.RETRY   # 1 - Translation has issues, retry recommended
ValidationDecision.REJECT  # 2 - Translation has critical errors
```

## TranslationStats - New Fields

```python
stats = TranslationStats(
    # Existing fields (unchanged)...

    # NEW: Validation state
    validation_passed=True,           # bool - Did validation pass?
    validation_failed=False,          # bool - Did validation fail?
    validation_retried=2,             # int - Number of retry attempts
    validation_decision="ACCEPT",     # str - "ACCEPT", "RETRY", or "REJECT"

    # NEW: Issue counts
    validation_errors=0,              # int - Number of errors
    validation_warnings=2,            # int - Number of warnings
    validation_info=5,                # int - Number of info messages

    # NEW: Performance metrics
    validation_duration_ms=150.0,     # float - Time spent validating (ms)
    retry_duration_ms=200.0,          # float - Time spent on retries (ms)
)
```

## TranslationResult - New Fields

```python
result = TranslationResult(
    # Existing fields (unchanged)...

    # NEW: Decision tracking
    validation_decision=ValidationDecision.ACCEPT,  # Optional[ValidationDecision]
    decision_reason="Quality excellent",            # Optional[str]
    retry_attempts=2,                               # int
    retry_history=[                                 # List[Dict[str, Any]]
        {
            "attempt": 1,
            "timestamp": "2024-01-01T12:00:00",
            "errors": 3,
            "decision": "RETRY",
            "reason": "Placeholder issues"
        },
        {
            "attempt": 2,
            "errors": 0,
            "decision": "ACCEPT",
            "reason": "All issues resolved"
        }
    ],
)
```

## Usage Examples

### Example 1: First-attempt acceptance
```python
stats = TranslationStats(
    total_segments=100,
    tm_hits=75,
    validation_passed=True,
    validation_decision="ACCEPT",
    validation_errors=0,
    validation_duration_ms=150.0,
)

result = TranslationResult(
    success=True,
    file_path=Path("post.md"),
    stats=stats,
    validation_decision=ValidationDecision.ACCEPT,
    decision_reason="No issues detected",
    retry_attempts=0,
)
```

### Example 2: Retry then accept
```python
stats = TranslationStats(
    validation_passed=True,
    validation_retried=1,
    validation_decision="ACCEPT",
    validation_errors=0,
    validation_warnings=1,
    retry_duration_ms=180.0,
)

result = TranslationResult(
    success=True,
    file_path=Path("guide.md"),
    stats=stats,
    validation_decision=ValidationDecision.ACCEPT,
    decision_reason="Accepted after retry",
    retry_attempts=1,
    retry_history=[
        {"attempt": 1, "errors": 2, "decision": "RETRY"},
        {"attempt": 2, "errors": 0, "decision": "ACCEPT"}
    ],
)
```

### Example 3: Rejection after retries
```python
stats = TranslationStats(
    validation_failed=True,
    validation_retried=2,
    validation_decision="REJECT",
    validation_errors=5,
    retry_duration_ms=400.0,
)

result = TranslationResult(
    success=False,
    file_path=Path("article.md"),
    stats=stats,
    validation_decision=ValidationDecision.REJECT,
    decision_reason="Critical errors persist after max retries",
    retry_attempts=2,
)
```

### Example 4: Directory aggregation
```python
dir_result = DirectoryResult(
    success=True,
    directory=Path("content/"),
    file_results=[result1, result2, result3],
)

# Aggregate stats automatically includes validation metrics
agg = dir_result.aggregate_stats
print(f"Total errors: {agg.validation_errors}")
print(f"Total warnings: {agg.validation_warnings}")
print(f"Total validation time: {agg.validation_duration_ms}ms")
print(f"Total retry time: {agg.retry_duration_ms}ms")
```

## Backward Compatibility

All existing code continues to work without modification:

```python
# Old-style creation (still works)
stats = TranslationStats(
    total_segments=100,
    tm_hits=75,
)
# New fields auto-default to False/0/""

result = TranslationResult(
    success=True,
    file_path=Path("test.md"),
)
# New fields auto-default to None/0/[]
```

## Integration with Future Components

### For ValidationDecisionEngine (DEC-01)
```python
# Engine will populate these fields:
result.validation_decision = decision_result.decision
result.decision_reason = decision_result.reason
result.stats.validation_decision = decision_result.decision.name
```

### For Retry Logic (INT-01)
```python
# Retry loop will populate:
result.retry_attempts = current_attempt
result.retry_history.append({
    "attempt": current_attempt,
    "errors": validation_result.error_count,
    "decision": decision.decision.name,
})
result.stats.validation_retried = current_attempt
result.stats.retry_duration_ms = total_retry_time
```

### For Telemetry (TEL-04)
```python
# Telemetry will read:
telemetry.record_validation_metrics(
    duration=stats.validation_duration_ms,
    errors=stats.validation_errors,
    warnings=stats.validation_warnings,
    decision=stats.validation_decision,
    retry_count=stats.validation_retried,
)
```

## Field Defaults Reference

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `validation_passed` | bool | False | Set to True when validation succeeds |
| `validation_failed` | bool | False | Set to True when validation fails |
| `validation_retried` | int | 0 | Increment on each retry |
| `validation_decision` | str | "" | "ACCEPT", "RETRY", or "REJECT" |
| `validation_errors` | int | 0 | Count of error-level issues |
| `validation_warnings` | int | 0 | Count of warning-level issues |
| `validation_info` | int | 0 | Count of info-level issues |
| `validation_duration_ms` | float | 0.0 | Time spent in validation |
| `retry_duration_ms` | float | 0.0 | Total time spent on retries |
| `validation_decision` | Optional[ValidationDecision] | None | Enum decision value |
| `decision_reason` | Optional[str] | None | Human-readable explanation |
| `retry_attempts` | int | 0 | Number of retries performed |
| `retry_history` | List[Dict] | [] | Detailed retry history |

## Testing

Run tests with:
```bash
pytest tests/unit/test_models.py -v
```

Test coverage includes:
- ValidationDecision enum (values, ordering)
- TranslationStats validation fields (defaults, populated)
- TranslationResult decision fields (defaults, populated)
- DirectoryResult aggregation (validation metrics)
- Backward compatibility (old-style creation)
- Edge cases (None vs empty, mixed states)
- Serialization (dict conversion, enum handling)
