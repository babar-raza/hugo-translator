# Model Parameterization in Tests (BM-05)

This document explains how to write tests that work with any translation model, avoiding hardcoded model names.

## Problem

Previously, tests hardcoded `"m2m100_418m"` throughout the codebase, making tests inflexible and preventing testing with different models.

## Solution

Use pytest fixtures that provide model IDs dynamically, allowing tests to be parameterized at runtime.

## Pytest Fixtures

### Available Fixtures

1. **`test_model`** - Single model for testing (default: `m2m100_418m`)
   - Scope: session
   - Can be overridden via CLI: `pytest --test-model=opus_en_fr`

2. **`test_models`** - List of models for parameterized testing
   - Scope: session
   - Defaults to all models from registry
   - Can be overridden: `pytest --test-models=m2m100_418m,opus_en_fr`

3. **`available_models`** - All models from registry
   - Scope: session
   - Loaded from `config/model_registry.yaml`

4. **`small_test_models`** - Subset of fast models (≤418M params)
   - Scope: session
   - Useful for quick CI testing

## Usage Examples

### Single Model Test

**Before (hardcoded)**:
```python
def test_translation():
    runner = TranslationRunner(model_id="m2m100_418m")
    result = runner.translate("Hello world")
    assert result is not None
```

**After (parameterized)**:
```python
def test_translation(test_model):
    runner = TranslationRunner(model_id=test_model)
    result = runner.translate("Hello world")
    assert result is not None
```

### Parameterized Test (Multiple Models)

```python
import pytest

@pytest.mark.parametrize("model_id", pytest.lazy_fixture("small_test_models"))
def test_all_models(model_id):
    runner = TranslationRunner(model_id=model_id)
    result = runner.translate("Test")
    assert result is not None
```

### Using Specific Models in CI

```python
@pytest.mark.parametrize("model_id", ["m2m100_418m", "opus_en_fr"])
def test_core_models(model_id):
    # Test only these two models regardless of registry
    assert model_available(model_id)
```

## Running Tests

### Default Behavior

```bash
# Uses m2m100_418m (default)
pytest tests/unit/test_translation.py
```

### Override Model

```bash
# Test with a different model
pytest --test-model=opus_en_fr tests/unit/
```

### Test Multiple Models

```bash
# Test all small models
pytest --test-models=m2m100_418m,opus_en_fr,opus_en_de tests/integration/
```

### Test All Registry Models

```bash
# Defaults to all models in registry (slow!)
pytest tests/integration/test_benchmarking.py
```

## Benefits

1. **Flexibility**: Tests work with any model in the registry
2. **CI Optimization**: Use small models for fast CI, large models for nightly tests
3. **Model Discovery**: Automatically test newly discovered models
4. **No Hardcoding**: Eliminates `"m2m100_418m"` scattered throughout tests

## Migration Guide

### Step 1: Add fixture parameter

```python
# Before
def test_something():
    model_id = "m2m100_418m"

# After
def test_something(test_model):
    model_id = test_model
```

### Step 2: Run tests to verify

```bash
pytest tests/unit/test_something.py
```

### Step 3: Test with different model

```bash
pytest --test-model=opus_en_fr tests/unit/test_something.py
```

## See Also

- `tests/conftest.py` - Fixture definitions
- `tests/integration/test_cpu_benchmarking.py` - Example usage
- `config/model_registry.yaml` - Available models
