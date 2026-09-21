"""TC-APT-082: write the mission's end-of-iteration state digest.

Plan §0.9/TC-APT-082: "each iteration ends by writing the digest (open
obligations, active clauses, wave_scale, next action, `loop_prompt_version` +
plan revision stamps); orientation reads the digest and re-reads full
documents only when a stamp changed."

Run at the end of a bounded iteration:
    .venv/Scripts/python.exe -m scripts.ops.write_state_digest --next-action "..."

Reads taskcard_status.json (progress truth) and project/loop-prompt.md (for
the live loop_prompt_version line) and writes
.supervisor/state/<mission>/state_digest.json. Never writes translated or
candidate text -- this is a governance summary, not a content artifact.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MISSION_ID = "aspose-org-full-portfolio-translation-20260901"
_STATE_DIR = Path(".supervisor/state") / _MISSION_ID
_TASKCARD_STATUS_PATH = _STATE_DIR / "taskcard_status.json"
_LOOP_PROMPT_PATH = Path("project/loop-prompt.md")
_DIGEST_PATH = _STATE_DIR / "state_digest.json"


def _read_loop_prompt_version(loop_prompt_path: Path) -> str | None:
    if not loop_prompt_path.exists():
        return None
    match = re.search(r"loop_prompt_version:\s*([^\n`]+)", loop_prompt_path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else None


def build_digest(
    *,
    taskcard_status_path: Path = _TASKCARD_STATUS_PATH,
    loop_prompt_path: Path = _LOOP_PROMPT_PATH,
    next_action: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    status = json.loads(taskcard_status_path.read_text(encoding="utf-8"))
    taskcards = status.get("taskcards", {})
    open_obligations = sorted(
        card_id for card_id, card in taskcards.items()
        if isinstance(card, dict) and card.get("status") == "IN_PROGRESS"
    )
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "stamps": {
            "loop_prompt_version": _read_loop_prompt_version(loop_prompt_path),
            "plan_revision": status.get("plan_revision"),
        },
        "open_obligations": open_obligations,
        "active_clauses": {
            "capacity_clause": status.get("capacity_clause"),
            "wave_scale": status.get("wave_scale"),
        },
        "next_action": next_action,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--next-action", default="", help="One-line summary of what the next iteration should do")
    parser.add_argument("--taskcard-status", type=Path, default=_TASKCARD_STATUS_PATH)
    parser.add_argument("--loop-prompt", type=Path, default=_LOOP_PROMPT_PATH)
    parser.add_argument("--out", type=Path, default=_DIGEST_PATH)
    args = parser.parse_args(argv)

    digest = build_digest(
        taskcard_status_path=args.taskcard_status,
        loop_prompt_path=args.loop_prompt,
        next_action=args.next_action,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(digest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
