"""TC-APT-082: end-of-iteration state digest.

Acceptance (plan §11): "a wake with unchanged stamps demonstrably orients
from the digest alone; a stamp change triggers the full re-read."
"""

import json

from scripts.ops.write_state_digest import build_digest, main


def _write_taskcard_status(path, *, plan_revision=16, wave_scale=None, capacity_clause=None, taskcards=None):
    payload = {
        "plan_revision": plan_revision,
        "wave_scale": wave_scale,
        "capacity_clause": capacity_clause,
        "taskcards": taskcards or {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_loop_prompt(path, version):
    path.write_text(f"some header\n\n`loop_prompt_version: {version}`\n\nbody\n", encoding="utf-8")


class TestBuildDigest:
    def test_never_stores_candidate_or_translated_text(self, tmp_path):
        status_path = tmp_path / "taskcard_status.json"
        loop_prompt_path = tmp_path / "loop-prompt.md"
        _write_taskcard_status(status_path)
        _write_loop_prompt(loop_prompt_path, "10.5 (2026-09-06)")

        digest = build_digest(
            taskcard_status_path=status_path,
            loop_prompt_path=loop_prompt_path,
            next_action="continue",
            generated_at="2026-09-06T00:00:00+00:00",
        )
        assert set(digest.keys()) == {
            "generated_at", "stamps", "open_obligations", "active_clauses", "next_action",
        }

    def test_stamps_come_from_the_live_files(self, tmp_path):
        status_path = tmp_path / "taskcard_status.json"
        loop_prompt_path = tmp_path / "loop-prompt.md"
        _write_taskcard_status(status_path, plan_revision=17)
        _write_loop_prompt(loop_prompt_path, "10.6 (2026-09-07)")

        digest = build_digest(taskcard_status_path=status_path, loop_prompt_path=loop_prompt_path)
        assert digest["stamps"] == {
            "loop_prompt_version": "10.6 (2026-09-07)",
            "plan_revision": 17,
        }

    def test_open_obligations_are_exactly_the_in_progress_taskcards(self, tmp_path):
        status_path = tmp_path / "taskcard_status.json"
        loop_prompt_path = tmp_path / "loop-prompt.md"
        _write_taskcard_status(
            status_path,
            taskcards={
                "TC-APT-001": {"status": "DONE"},
                "TC-APT-002": {"status": "IN_PROGRESS"},
                "TC-APT-003": {"status": "TODO"},
                "TC-APT-004": {"status": "IN_PROGRESS"},
            },
        )
        _write_loop_prompt(loop_prompt_path, "10.5")

        digest = build_digest(taskcard_status_path=status_path, loop_prompt_path=loop_prompt_path)
        assert digest["open_obligations"] == ["TC-APT-002", "TC-APT-004"]

    def test_active_clauses_carry_wave_scale_and_capacity_clause(self, tmp_path):
        status_path = tmp_path / "taskcard_status.json"
        loop_prompt_path = tmp_path / "loop-prompt.md"
        wave_scale = {"value": 2, "previous": 1}
        capacity_clause = {"engaged": True, "reason": "KPI below floor"}
        _write_taskcard_status(status_path, wave_scale=wave_scale, capacity_clause=capacity_clause)
        _write_loop_prompt(loop_prompt_path, "10.5")

        digest = build_digest(taskcard_status_path=status_path, loop_prompt_path=loop_prompt_path)
        assert digest["active_clauses"]["wave_scale"] == wave_scale
        assert digest["active_clauses"]["capacity_clause"] == capacity_clause

    def test_missing_loop_prompt_version_line_is_none_not_a_crash(self, tmp_path):
        status_path = tmp_path / "taskcard_status.json"
        loop_prompt_path = tmp_path / "loop-prompt.md"
        _write_taskcard_status(status_path)
        loop_prompt_path.write_text("no version line here\n", encoding="utf-8")

        digest = build_digest(taskcard_status_path=status_path, loop_prompt_path=loop_prompt_path)
        assert digest["stamps"]["loop_prompt_version"] is None

    def test_a_stamp_change_is_detectable_by_comparison(self, tmp_path):
        """Proves the acceptance criterion mechanically: comparing two digests'
        stamps is how a session decides whether to re-read the full documents."""
        status_path = tmp_path / "taskcard_status.json"
        loop_prompt_path = tmp_path / "loop-prompt.md"
        _write_taskcard_status(status_path, plan_revision=16)
        _write_loop_prompt(loop_prompt_path, "10.5")
        first = build_digest(taskcard_status_path=status_path, loop_prompt_path=loop_prompt_path)

        _write_loop_prompt(loop_prompt_path, "10.6")
        second = build_digest(taskcard_status_path=status_path, loop_prompt_path=loop_prompt_path)

        assert first["stamps"] != second["stamps"]


class TestMainWritesTheFile:
    def test_writes_valid_json_to_the_requested_path(self, tmp_path, monkeypatch):
        status_path = tmp_path / "taskcard_status.json"
        loop_prompt_path = tmp_path / "loop-prompt.md"
        out_path = tmp_path / "state_digest.json"
        _write_taskcard_status(status_path)
        _write_loop_prompt(loop_prompt_path, "10.5")

        exit_code = main([
            "--taskcard-status", str(status_path),
            "--loop-prompt", str(loop_prompt_path),
            "--out", str(out_path),
            "--next-action", "sync to v10.5",
        ])

        assert exit_code == 0
        written = json.loads(out_path.read_text(encoding="utf-8"))
        assert written["next_action"] == "sync to v10.5"
