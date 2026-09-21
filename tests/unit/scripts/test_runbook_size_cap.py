"""TC-APT-082: the runbook carries a hard size cap (~40KB, plan §0.9 revision 16).

A failing test here is the "mandatory compaction step" trigger the plan calls
for: archive the oldest §L entries to project/loop-prompt-archive.md (never
touch the numbered rule sections) until this passes again.
"""

from pathlib import Path

RUNBOOK_PATH = Path(__file__).parent.parent.parent.parent / "project" / "loop-prompt.md"
HARD_CAP_BYTES = 40_000


def test_the_runbook_is_under_its_hard_size_cap():
    size = len(RUNBOOK_PATH.read_bytes())
    assert size <= HARD_CAP_BYTES, (
        f"project/loop-prompt.md is {size} bytes, over the {HARD_CAP_BYTES}-byte cap "
        "(plan §0.9/TC-APT-082). Archive the oldest §L field-note entries to "
        "project/loop-prompt-archive.md -- never edit the numbered rule sections."
    )
