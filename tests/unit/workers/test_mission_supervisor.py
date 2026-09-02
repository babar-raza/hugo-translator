"""TC-APT-029 acceptance: known taskcard/continuation states drive supervisor_loop.decide().

Mission aspose-org-full-portfolio-translation-20260901.  Each test feeds a known
``taskcard_status.json`` / ``continuation_state.json`` shape through
``mission_supervisor.wake`` and asserts the (unmodified) ``decide()`` verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.workers import continuation_state as cs
from src.workers import mission_supervisor as ms
from src.workers.supervisor_loop import SupervisorDecision
from src.workers.task_queue import TaskStatus, load_all_tasks


def _status(cards: dict[str, dict]) -> dict:
    base = {"mission_id": ms.MISSION_ID, "taskcards": {}}
    for tid, spec in cards.items():
        base["taskcards"][tid] = {
            "status": spec.get("status", "TODO"),
            "gate": spec.get("gate", 0),
            "title": spec.get("title", tid),
            "depends_on": spec.get("depends_on", []),
            "owner": "loop",
            "blocking_reason": spec.get("blocking_reason"),
            "blocker_type": spec.get("blocker_type"),
            "evidence_path": None,
            "commit": None,
            "last_updated": "2026-09-02T00:00:00+00:00",
        }
    return base


@pytest.fixture()
def mission_dir(tmp_path: Path) -> Path:
    d = tmp_path / "mission"
    d.mkdir()
    return d


def _write(mission_dir: Path, status: dict) -> None:
    (mission_dir / ms.STATUS_FILE).write_text(json.dumps(status), encoding="utf-8")


class TestPhaseDetermination:
    def test_phase_a_while_any_phase_a_card_open(self):
        cards = {tid: {"status": "DONE"} for tid in ms.PHASE_A_TASKCARDS}
        cards["TC-APT-012"]["status"] = "IN_PROGRESS"
        assert ms.determine_phase(_status(cards)) == "A"

    def test_phase_b_when_all_phase_a_done(self):
        cards = {tid: {"status": "DONE"} for tid in ms.PHASE_A_TASKCARDS}
        assert ms.determine_phase(_status(cards)) == "B"


class TestDecisions:
    def test_proceed_picks_next_eligible_taskcard_honouring_deps(self, mission_dir):
        _write(
            mission_dir,
            _status(
                {
                    "TC-APT-001": {"status": "DONE", "gate": 0},
                    "TC-APT-002": {"status": "TODO", "gate": 0, "depends_on": ["TC-APT-001"]},
                    "TC-APT-003": {"status": "TODO", "gate": 0, "depends_on": ["TC-APT-002"]},
                    "TC-APT-028": {"status": "TODO", "gate": 1},
                }
            ),
        )
        result = ms.wake(mission_dir, circuit_breaker_dir=None)
        assert result["phase"] == "A"
        assert result["decision"]["decision"] == SupervisorDecision.PROCEED.value
        # 002 (gate 0, deps met) outranks 028 (gate 1); 003's dependency is unmet.
        assert result["decision"]["task_id"] == "TC-APT-002"
        by_id = {t["task_id"]: t for t in load_all_tasks(queue_file=mission_dir / ms.QUEUE_FILE)}
        assert by_id["TC-APT-001"]["status"] == TaskStatus.COMPLETED.value
        assert by_id["TC-APT-002"]["status"] == TaskStatus.IN_PROGRESS.value

    def test_block_on_true_external_taskcard_still_lists_workable_items(self, mission_dir):
        _write(
            mission_dir,
            _status(
                {
                    "TC-APT-004b": {
                        "status": "BLOCKED_TRUE_EXTERNAL",
                        "gate": 1,
                        "blocking_reason": "llm.professionalize.com unreachable beyond fallback",
                        "blocker_type": "provider_outage_beyond_fallback",
                    },
                    "TC-APT-008": {"status": "TODO", "gate": 2},
                }
            ),
        )
        result = ms.wake(mission_dir, circuit_breaker_dir=None)
        assert result["decision"]["decision"] == SupervisorDecision.BLOCK.value
        assert [b["blocker_id"] for b in result["blockers"]] == ["taskcard:TC-APT-004b"]
        assert result["blockers"][0]["type"] == "provider_outage_beyond_fallback"
        # Section 21: a BLOCK never idles the mission -- unaffected items remain workable.
        assert result["workable_pending"] == ["TC-APT-008"]
        state = cs.load_state(state_file=mission_dir / ms.CONTINUATION_FILE)
        assert len(state["blockers"]) == 1

    def test_open_llm_circuit_breaker_is_reported_as_blocker(self, mission_dir, tmp_path):
        cb = tmp_path / "circuit_breaker"
        cb.mkdir()
        (cb / "professionalize_llm.json").write_text(
            json.dumps({"state": "open"}), encoding="utf-8"
        )
        (cb / "m2m100_418m.json").write_text(json.dumps({"state": "closed"}), encoding="utf-8")
        _write(mission_dir, _status({"TC-APT-002": {"status": "TODO"}}))
        result = ms.wake(mission_dir, circuit_breaker_dir=cb)
        assert result["decision"]["decision"] == SupervisorDecision.BLOCK.value
        ids = [b["blocker_id"] for b in result["blockers"]]
        assert ids == ["circuit_breaker:professionalize_llm"]
        assert "m2m100_418m fallback" in result["blockers"][0]["description"]

    def test_half_open_breaker_is_not_a_blocker(self, mission_dir, tmp_path):
        cb = tmp_path / "circuit_breaker"
        cb.mkdir()
        (cb / "professionalize_llm.json").write_text(
            json.dumps({"state": "half_open"}), encoding="utf-8"
        )
        _write(mission_dir, _status({"TC-APT-002": {"status": "TODO"}}))
        result = ms.wake(mission_dir, circuit_breaker_dir=cb)
        assert result["decision"]["decision"] == SupervisorDecision.PROCEED.value

    def test_unreadable_breaker_file_fails_closed_as_blocker(self, mission_dir, tmp_path):
        cb = tmp_path / "circuit_breaker"
        cb.mkdir()
        (cb / "professionalize_llm.json").write_text("{not json", encoding="utf-8")
        _write(mission_dir, _status({"TC-APT-002": {"status": "TODO"}}))
        result = ms.wake(mission_dir, circuit_breaker_dir=cb)
        assert result["decision"]["decision"] == SupervisorDecision.BLOCK.value
        assert result["blockers"][0]["type"] == "circuit_breaker_open"

    def test_circuit_break_after_three_consecutive_failures(self, mission_dir):
        _write(mission_dir, _status({"TC-APT-002": {"status": "TODO"}}))
        sf = mission_dir / ms.CONTINUATION_FILE
        for i in range(3):
            cs.start_run(f"run-{i}", "docs.aspose.org", ["de"], state_file=sf)
            cs.fail_run("same root cause unresolved", state_file=sf)
        result = ms.wake(mission_dir, circuit_breaker_dir=None)
        assert result["decision"]["decision"] == SupervisorDecision.CIRCUIT_BREAK.value
        assert result["snapshot"]["continuation"]["consecutive_failures"] == 3

    def test_resume_when_previous_wake_was_interrupted(self, mission_dir):
        _write(mission_dir, _status({"TC-APT-002": {"status": "TODO"}}))
        sf = mission_dir / ms.CONTINUATION_FILE
        cs.start_run("run-x", "kb.aspose.org", ["ar"], state_file=sf)
        cs.interrupt_run(pending_items=["cell-1", "cell-2"], state_file=sf)
        result = ms.wake(mission_dir, circuit_breaker_dir=None)
        assert result["decision"]["decision"] == SupervisorDecision.RESUME.value
        assert result["snapshot"]["continuation"]["pending_work_count"] == 2

    def test_skip_when_queue_is_empty(self, mission_dir):
        cards = {tid: {"status": "DONE"} for tid in ms.PHASE_A_TASKCARDS}
        _write(mission_dir, _status(cards))
        result = ms.wake(mission_dir, circuit_breaker_dir=None)  # PHASE B, no items supplied
        assert result["phase"] == "B"
        assert result["decision"]["decision"] == SupervisorDecision.SKIP.value

    def test_phase_b_queues_manifest_scoped_items(self, mission_dir):
        cards = {tid: {"status": "DONE"} for tid in ms.PHASE_A_TASKCARDS}
        _write(mission_dir, _status(cards))
        items = [
            {
                "task_id": "cell:docs:foo.md:de",
                "title": "docs foo.md -> de",
                "wave": 0,
                "priority": "P0",
            },
            {
                "task_id": "cell:docs:foo.md:ja",
                "title": "docs foo.md -> ja",
                "wave": 3,
                "priority": "P2",
            },
        ]
        result = ms.wake(mission_dir, phase_b_items=items, circuit_breaker_dir=None)
        assert result["decision"]["decision"] == SupervisorDecision.PROCEED.value
        assert result["decision"]["task_id"] == "cell:docs:foo.md:de"

    def test_wake_is_idempotent_no_duplicate_blockers(self, mission_dir):
        _write(
            mission_dir,
            _status(
                {
                    "TC-APT-004b": {
                        "status": "BLOCKED_TRUE_EXTERNAL",
                        "blocking_reason": "disk failure on D:",
                        "blocker_type": "hardware_or_disk_failure",
                    }
                }
            ),
        )
        ms.wake(mission_dir, circuit_breaker_dir=None)
        ms.wake(mission_dir, circuit_breaker_dir=None)
        state = cs.load_state(state_file=mission_dir / ms.CONTINUATION_FILE)
        assert len(state["blockers"]) == 1


class TestStatusGuards:
    def test_blocked_true_external_requires_one_of_the_two_reasons(self, mission_dir):
        _write(mission_dir, _status({"TC-APT-026": {"status": "TODO"}}))
        with pytest.raises(ValueError):
            ms.set_taskcard(
                mission_dir,
                "TC-APT-026",
                "BLOCKED_TRUE_EXTERNAL",
                blocking_reason="waiting for operator",
                blocker_type="governance",
            )
        card = ms.set_taskcard(
            mission_dir,
            "TC-APT-026",
            "BLOCKED_TRUE_EXTERNAL",
            blocking_reason="host disk failure",
            blocker_type="hardware_or_disk_failure",
        )
        assert card["status"] == "BLOCKED_TRUE_EXTERNAL"

    def test_invalid_status_file_is_rejected(self, mission_dir):
        (mission_dir / ms.STATUS_FILE).write_text(
            json.dumps({"taskcards": {"X": {"status": "MAYBE"}}}), encoding="utf-8"
        )
        with pytest.raises(ms.MissionStatusError):
            ms.load_status(mission_dir)

    def test_missing_status_file_is_rejected(self, mission_dir):
        with pytest.raises(ms.MissionStatusError):
            ms.load_status(mission_dir)
