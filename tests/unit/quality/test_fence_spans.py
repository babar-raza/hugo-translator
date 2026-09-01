"""Regression net for the shared Markdown code-region primitive (TC-DCF-011)."""
from __future__ import annotations

import pytest

from scripts.quality import fence_spans as quality_fence_spans
from src.translation_engine import fence_spans as engine_fence_spans
from tests.unit.quality.fence_span_cases import CODE_REGION_CASES


@pytest.mark.parametrize("case", CODE_REGION_CASES, ids=lambda case: case.name)
def test_all_public_consumers_agree_on_code_region_mask(case):
    """The scripts re-export and canonical engine API must remain identical."""
    assert engine_fence_spans.fenced_line_mask(case.body) == case.expected_mask
    assert quality_fence_spans.fenced_line_mask(case.body) == case.expected_mask
