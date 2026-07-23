"""
Integration tests for write gate 38 (HT-QUALITY-GATES-001 Phase 8, Tier A
#14): prose-before-code-block deletion -- a dropped lead-in paragraph
immediately before a fenced code block, distinct from Gates 34/35's
trailing-SECTION loss and Gate 19/26's fence-count checks.

Ships "warn" per this registry's established rollout convention (see Gate
28/29's history in write_gate.py).
"""
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


def _make_gate() -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    return WriteGateEvaluator(
        detector=None, similarity_tracker=None, config=config, force_accept=True,
    )


_EN_WITH_LEAD_IN = """---
title: Sample
---
Here is how you call the method, note the exact syntax below:

```python
print(hello)
```

More text after.
"""


class TestGateProseBeforeCodeDropped:
    def test_dropped_lead_in_is_flagged(self):
        tr = """---
title: Sample
---

```python
print(hello)
```

Mas texto despues.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_prose_before_code_dropped(_EN_WITH_LEAD_IN, tr, Path("test.md"), result)

        assert result.passed is False
        assert "block #1" in result.error

    def test_preserved_lead_in_is_silent(self):
        tr = """---
title: Sample
---
Aqui esta como llamar al metodo, note la sintaxis exacta abajo:

```python
print(hello)
```

Mas texto despues.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_prose_before_code_dropped(_EN_WITH_LEAD_IN, tr, Path("test.md"), result)

        assert result.passed is True

    def test_fence_at_document_start_has_no_lead_in_to_lose(self):
        en = """---
title: Sample
---
```python
print(hello)
```

Text after.
"""
        tr = """---
title: Sample
---
```python
print(hello)
```

Texto despues.
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_prose_before_code_dropped(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_fence_count_mismatch_is_not_this_gates_job(self):
        """A dropped fence entirely is Gate 19/26's job -- this gate must
        not also fire (or crash) when counts don't align 1:1."""
        en = """---
title: Sample
---
Intro text before first block:

```python
one()
```

More intro before second block:

```python
two()
```
"""
        tr = """---
title: Sample
---
Solo un bloque aqui:

```python
one()
```
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_prose_before_code_dropped(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_no_fences_at_all_is_a_silent_no_op(self):
        en = "---\ntitle: Sample\n---\nJust prose, no code anywhere.\n"
        tr = "---\ntitle: Sample\n---\nSolo prosa, sin codigo.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_prose_before_code_dropped(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_second_of_two_blocks_loses_its_lead_in(self):
        en = """---
title: Sample
---
First intro:

```python
one()
```

Second intro with real explanatory content here:

```python
two()
```
"""
        tr = """---
title: Sample
---
Primera introduccion:

```python
one()
```

```python
two()
```
"""
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_prose_before_code_dropped(en, tr, Path("test.md"), result)

        assert result.passed is False
        assert "block #2" in result.error
