"""TC-HLN-006-c: unit_heal.py's write-gate check must not silently reject
every fix via a broken import.

Root cause: _run_write_gates() imported `WriteGate` from
src.translation_engine.write_gate, which has never existed there (the real
class is `WriteGateEvaluator`) -- this raised ImportError inside the
function's own broad `except Exception`, logged as "Gate evaluation error",
and was counted identically to a genuine gate rejection ("Write gate
failed"). Result: since unit_heal.py was written (commit d55b42c), every
single fix attempt across every prior run was silently discarded --
"units_fixed" in the summary counted unit-level validation passes, but zero
files were ever actually written (confirmed: a full 62,112-file run reported
393 units_fixed / 123 gates_failed / 0 write_errors, yet the done-file had
zero entries and there was not one "Done in ...units fixed" success log line
anywhere in the run).
"""

from pathlib import Path

from scripts.quality.unit_heal import _run_write_gates

_EN_MD = """---
title: "Sample"
description: "Sample class"
---

Some prose about a sample class.
"""

_TR_MD = """---
title: "Sample"
description: "Sample class"
---

Deyalar hakkında bazı metin burada.
"""


class TestRunWriteGatesDoesNotCrashOnImport:
    def test_gate_check_runs_without_import_error(self, tmp_path):
        """The concrete regression: this must not silently return False due
        to an ImportError inside the try/except -- it must actually
        evaluate the gates."""
        output_path = tmp_path / "sample.md"
        passed = _run_write_gates(
            source_content=_EN_MD,
            translated_content=_TR_MD,
            output_path=output_path,
            locale="tr",
            site_id="reference.aspose.org",
        )
        # A clean, well-formed translation with no structural issues must
        # pass -- proving the evaluator actually ran (a broken import would
        # always return False here regardless of content quality).
        assert passed is True

    def test_structurally_broken_content_is_still_correctly_rejected(self, tmp_path):
        """Negative control: gates must still genuinely reject bad content,
        not rubber-stamp everything now that the import works. Uses a
        dropped code block -- a real, reliably gate-checked structural
        defect (code block count mismatch)."""
        en_with_code = """---
title: "Sample"
description: "Sample class"
---

Some prose about a sample class.

```python
print("hello")
```
"""
        output_path = tmp_path / "sample.md"
        passed = _run_write_gates(
            source_content=en_with_code,
            translated_content=_TR_MD,  # no code block at all
            output_path=output_path,
            locale="tr",
            site_id="reference.aspose.org",
        )
        assert passed is False
