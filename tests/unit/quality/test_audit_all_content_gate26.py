"""Audit Gate 26 must report the same strict parity defects as production."""
from __future__ import annotations

from pathlib import Path

from scripts.quality import audit_all_content as aac


def _fenced(blocks: int, drop_last: bool = False) -> str:
    lines: list[str] = []
    for index in range(blocks):
        lines.extend(("```python", f"value_{index} = 1"))
        if not (drop_last and index == blocks - 1):
            lines.append("```")
    return "\n".join(lines) + "\n"


def _registry_findings(source: str, target: str) -> list[str]:
    findings: list[str] = []
    aac._run_registry_gates(source, target, "vi", Path("fake/vi/test.md"), lambda issue, _detail: findings.append(issue))
    return findings


def test_two_fence_loss_is_no_longer_suppressed_by_legacy_tolerance():
    source = _fenced(4)
    target = _fenced(3)  # src=8, tgt=6: exact post-closure pilot shape
    issue, detail = aac.check_code_fence_dropped(source, target)
    assert issue is True
    assert "Gate 26" in detail
    assert _registry_findings(source, target).count("code_fence_dropped") == 1


def test_new_reopened_fence_is_reported_under_established_audit_name():
    source = _fenced(1)
    target = "```python\nvalue = 1\n```python\nmore = 2\n```\n```\n"
    issue, detail = aac.check_code_fence_dropped(source, target)
    assert issue is True
    assert "reopened" in detail
    assert _registry_findings(source, target) == ["code_fence_dropped"]


def test_matching_fences_have_no_gate26_audit_finding():
    source = _fenced(2)
    issue, detail = aac.check_code_fence_dropped(source, source)
    assert (issue, detail) == (False, "")
    assert "code_fence_dropped" not in _registry_findings(source, source)
