import json

import pytest

from scripts.campaign.launch_parallel_campaign_shards import TerminalLedgerTail


def test_tail_waits_for_complete_row_and_reads_each_row_once(tmp_path):
    path = tmp_path / "receipts.jsonl"
    tail = TerminalLedgerTail(path)
    assert tail.poll() == []
    path.write_bytes(b'{"accepted":')
    assert tail.poll() == []
    with path.open("ab") as stream:
        stream.write(b'1}\n')
    assert tail.poll() == [{"accepted": 1}]
    assert tail.poll() == []
    with path.open("ab") as stream:
        stream.write(json.dumps({"accepted": 2}).encode() + b"\n")
    assert tail.poll() == [{"accepted": 2}]
    assert tail.count == 2


def test_tail_refuses_truncation(tmp_path):
    path = tmp_path / "receipts.jsonl"
    path.write_bytes(b'{}\n')
    tail = TerminalLedgerTail(path)
    tail.poll()
    path.write_bytes(b'')
    with pytest.raises(RuntimeError, match="truncated"):
        tail.poll()


def test_tail_rejects_corrupt_complete_row(tmp_path):
    path = tmp_path / "receipts.jsonl"
    path.write_bytes(b'{invalid}\n')
    with pytest.raises(ValueError):
        TerminalLedgerTail(path).poll()
