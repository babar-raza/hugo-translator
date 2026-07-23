"""HT-QUALITY-GATES-001 Phase 8 (F4): tests for merge_audit_queues.py's
auto-discovery now including unit_heal_queue.jsonl (build_unit_heal_queue.py's
output) as a 5th tier -- previously a disconnected pipeline whose real
per-unit indices never reached master_heal_queue.jsonl (root cause RC2).
"""
from __future__ import annotations

import json

from scripts.quality.merge_audit_queues import merge


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_merge_includes_unit_heal_queue_entries_with_real_indices(tmp_path):
    t1 = tmp_path / "audit_structural.jsonl"
    _write_jsonl(t1, [
        {
            "file_path": "content/es/foo.md",
            "en_path": "content/en/foo.md",
            "locale": "es",
            "site_id": "reference.aspose.org",
            "issues": [{"type": "empty_body", "detail": "", "unit_indices": [], "priority": 1}],
            "max_priority": 1,
        },
    ])
    unit_queue = tmp_path / "unit_heal_queue.jsonl"
    _write_jsonl(unit_queue, [
        {
            "file_path": "content/es/foo.md",
            "en_path": "content/en/foo.md",
            "locale": "es",
            "site_id": "reference.aspose.org",
            "issues": [{"type": "mojibake_detector", "unit_indices": [3, 7], "priority": 1}],
            "max_priority": 1,
        },
    ])

    output = tmp_path / "master_heal_queue.jsonl"
    merge([t1, unit_queue], output)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    issue_types = {iss["type"]: iss for iss in record["issues"]}
    assert "empty_body" in issue_types
    assert "mojibake_detector" in issue_types
    # The real per-unit indices from build_unit_heal_queue.py's scorer pass
    # must survive the merge unchanged.
    assert issue_types["mojibake_detector"]["unit_indices"] == [3, 7]
    assert issue_types["empty_body"]["unit_indices"] == []


def test_merge_deduplicates_same_issue_type_across_tiers(tmp_path):
    t1 = tmp_path / "audit_structural.jsonl"
    _write_jsonl(t1, [
        {
            "file_path": "content/es/foo.md", "en_path": "content/en/foo.md",
            "locale": "es", "site_id": "reference.aspose.org",
            "issues": [{"type": "empty_body", "detail": "", "unit_indices": [], "priority": 1}],
            "max_priority": 1,
        },
    ])
    t2 = tmp_path / "audit_linguistic.jsonl"
    _write_jsonl(t2, [
        {
            "file_path": "content/es/foo.md", "en_path": "content/en/foo.md",
            "locale": "es", "site_id": "reference.aspose.org",
            "issues": [{"type": "empty_body", "detail": "dup", "unit_indices": [], "priority": 1}],
            "max_priority": 1,
        },
    ])
    output = tmp_path / "master_heal_queue.jsonl"
    merge([t1, t2], output)
    record = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert len(record["issues"]) == 1  # not duplicated across tiers
