"""TC-APT-056: fleet work-claims helper.

The interim protocol it replaces (ad hoc atomic-append-and-verify, no real
cross-process exclusion) is what data/campaigns/claims.jsonl already has on
disk in production -- rows spelling the timestamp field two different ways
(`claimed_at` vs `acquired_at`) and not always carrying `ttl_minutes`. These
tests seed that exact messy shape to prove the reader tolerates it.
"""

import json
from datetime import datetime, timedelta, timezone

from src.utils.file_lock import FileLock, LockError
from src.workers.work_claims import acquire_claim, active_claim, release_claim

WORK_KEY = "page:content/blog.aspose.org/words/net/words-document-net/index.md"


def _write_row(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row) + "\n")


class TestAcquireClaim:
    def test_an_unclaimed_key_is_acquired(self, tmp_path):
        claims = tmp_path / "claims.jsonl"
        assert acquire_claim(WORK_KEY, "session-a", claims_path=claims) is True
        claim = active_claim(WORK_KEY, claims_path=claims)
        assert claim["session_id"] == "session-a"

    def test_a_second_session_is_blocked_by_a_live_claim(self, tmp_path):
        claims = tmp_path / "claims.jsonl"
        assert acquire_claim(WORK_KEY, "session-a", claims_path=claims) is True
        assert acquire_claim(WORK_KEY, "session-b", claims_path=claims) is False

    def test_the_same_session_can_renew_its_own_claim(self, tmp_path):
        claims = tmp_path / "claims.jsonl"
        assert acquire_claim(WORK_KEY, "session-a", claims_path=claims) is True
        assert acquire_claim(WORK_KEY, "session-a", claims_path=claims) is True

    def test_a_different_session_can_acquire_after_expiry(self, tmp_path):
        claims = tmp_path / "claims.jsonl"
        now = datetime.now(timezone.utc)
        _write_row(claims, {
            "work_key": WORK_KEY,
            "session_id": "session-a",
            "claimed_at": (now - timedelta(minutes=50)).isoformat(),
            "expires_at": (now - timedelta(minutes=5)).isoformat(),
            "action": "CLAIM",
        })
        assert acquire_claim(WORK_KEY, "session-b", claims_path=claims) is True

    def test_a_different_work_key_is_independent(self, tmp_path):
        claims = tmp_path / "claims.jsonl"
        assert acquire_claim(WORK_KEY, "session-a", claims_path=claims) is True
        assert acquire_claim("taskcard:TC-APT-999", "session-b", claims_path=claims) is True

    def test_ttl_and_purpose_are_recorded(self, tmp_path):
        claims = tmp_path / "claims.jsonl"
        acquire_claim(WORK_KEY, "session-a", ttl_minutes=15, purpose="test run", claims_path=claims)
        claim = active_claim(WORK_KEY, claims_path=claims)
        assert claim["ttl_minutes"] == 15
        assert claim["purpose"] == "test run"


class TestReleaseClaim:
    def test_a_released_claim_can_be_immediately_reclaimed_by_another_session(self, tmp_path):
        claims = tmp_path / "claims.jsonl"
        acquire_claim(WORK_KEY, "session-a", claims_path=claims)
        release_claim(WORK_KEY, "session-a", claims_path=claims)
        assert active_claim(WORK_KEY, claims_path=claims) is None
        assert acquire_claim(WORK_KEY, "session-b", claims_path=claims) is True

    def test_a_release_from_a_non_holder_does_not_free_someone_elses_claim(self, tmp_path):
        claims = tmp_path / "claims.jsonl"
        acquire_claim(WORK_KEY, "session-a", claims_path=claims)
        release_claim(WORK_KEY, "session-b", claims_path=claims)  # session-b never held it
        assert active_claim(WORK_KEY, claims_path=claims)["session_id"] == "session-a"


class TestToleratesTheExistingMessySchema:
    def test_reads_legacy_acquired_at_rows(self, tmp_path):
        """Real production rows from before this module existed use `acquired_at`."""
        claims = tmp_path / "claims.jsonl"
        now = datetime.now(timezone.utc)
        _write_row(claims, {
            "work_key": WORK_KEY,
            "session_id": "hugo-translator-legacy",
            "acquired_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=45)).isoformat(),
            "ttl_minutes": 45,
            "purpose": "legacy retrigger",
        })
        claim = active_claim(WORK_KEY, claims_path=claims)
        assert claim["session_id"] == "hugo-translator-legacy"
        assert acquire_claim(WORK_KEY, "someone-else", claims_path=claims) is False

    def test_reads_rows_with_no_action_field_as_a_claim(self, tmp_path):
        """Real production rows before this module existed never set `action` at all."""
        claims = tmp_path / "claims.jsonl"
        now = datetime.now(timezone.utc)
        _write_row(claims, {
            "work_key": WORK_KEY,
            "session_id": "hugo-translator-legacy",
            "claimed_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=45)).isoformat(),
        })
        assert active_claim(WORK_KEY, claims_path=claims)["session_id"] == "hugo-translator-legacy"


class TestRealCrossProcessExclusion:
    def test_acquire_blocks_while_the_lock_file_is_externally_held(self, tmp_path):
        """Proves this actually uses FileLock, not just a read-then-write race."""
        claims = tmp_path / "claims.jsonl"
        lock = FileLock(claims.with_suffix(".jsonl.lock"), timeout=0)
        lock.acquire()
        try:
            try:
                acquire_claim(WORK_KEY, "session-a", claims_path=claims, lock_timeout=0.2)
                raised = False
            except LockError:
                raised = True
            assert raised
        finally:
            lock.release()

        # Once released, acquisition proceeds normally.
        assert acquire_claim(WORK_KEY, "session-a", claims_path=claims) is True
