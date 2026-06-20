"""Basic tests for scripts/ops/audit_sheet_reconciliation.py.

TC-10: Verify the script is importable and classify_row() correctly
categorises all documented audit categories.
"""

from __future__ import annotations

import importlib


def test_importable():
    """Script imports without error."""
    mod = importlib.import_module("scripts.ops.audit_sheet_reconciliation")
    assert hasattr(mod, "classify_row")
    assert hasattr(mod, "load_posted_sidecars")
    assert hasattr(mod, "build_report")


def _sidecar(
    *,
    response_code=200,
    website="aspose.net",
    product="Aspose.Words",
    items_discovered=5,
    confidence="high",
    fallback_used=False,
) -> dict:
    return {
        "posted_payload": {
            "website": website,
            "product": product,
            "items_discovered": items_discovered,
        },
        "scope": {
            "reporting_confidence": confidence,
            "fallback_used": fallback_used,
        },
        "posting": {
            "response_code": response_code,
        },
    }


def test_classify_clean():
    from scripts.ops.audit_sheet_reconciliation import classify_row

    assert classify_row(_sidecar()) == "CLEAN"


def test_classify_response_code_anomaly():
    from scripts.ops.audit_sheet_reconciliation import classify_row

    assert classify_row(_sidecar(response_code=500)) == "RESPONSE_CODE_ANOMALY"
    assert classify_row(_sidecar(response_code=0)) == "RESPONSE_CODE_ANOMALY"


def test_classify_broken_tm_scope():
    from scripts.ops.audit_sheet_reconciliation import classify_row

    assert classify_row(_sidecar(website="tm_improvement")) == "BROKEN_TM_SCOPE"
    assert classify_row(_sidecar(product="Aspose.Tm_improvement")) == "BROKEN_TM_SCOPE"


def test_classify_zero_item():
    from scripts.ops.audit_sheet_reconciliation import classify_row

    assert classify_row(_sidecar(items_discovered=0)) == "ZERO_ITEM"


def test_classify_low_confidence():
    from scripts.ops.audit_sheet_reconciliation import classify_row

    assert classify_row(_sidecar(confidence="low")) == "LOW_CONFIDENCE"
