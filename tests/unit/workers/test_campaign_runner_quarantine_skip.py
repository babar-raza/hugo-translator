"""TC-APT-038: CampaignRunner._run_campaign_job must skip a quarantined
(target_lang, root_cause_class) pair instead of spending a fresh set of
model retries on a cell whose defect class is already proven systemic
across the portfolio -- and must NOT skip an unseen candidate (a cell with
no prior failure history), per plan §3 item 4 ("never quarantine an unseen
candidate").

Constructs a bare CampaignRunner via __new__ and stubs only the handful of
collaborators _run_campaign_job touches before reaching the quarantine
check, since the class has no existing test scaffolding and a full engine
instantiation is out of scope for this one branch.
"""

import json
from types import SimpleNamespace

from src.workers.campaign_runner import CampaignLedger, CampaignRunner

SOURCE_REL = "content/blog.aspose.org/words/net/words-document-net/index.md"


def _make_runner(tmp_path, *, heal_queue_tickets=(), with_prior_failure=False, gate="StructureValidator"):
    content_repo = tmp_path / "content_repo"
    content_repo.mkdir()
    (content_repo / "index.md").write_text("stub", encoding="utf-8")

    campaigns_root = tmp_path / "campaigns"
    campaigns_root.mkdir()
    ledger = CampaignLedger(campaigns_root / "gate5-stub", "gate5-stub")
    heal_queue_path = ledger.root.parent / "heal_queue.jsonl"
    heal_queue_path.parent.mkdir(parents=True, exist_ok=True)
    with heal_queue_path.open("w", encoding="utf-8") as f:
        for ticket in heal_queue_tickets:
            f.write(json.dumps(ticket) + "\n")

    expected_output = str(content_repo / "index.ar.md")
    if with_prior_failure:
        ledger.append_failure(
            source_path=SOURCE_REL,
            output_path=expected_output,
            target_lang="ar",
            error="structure mismatch",
            gate=gate,
        )

    runner = CampaignRunner.__new__(CampaignRunner)
    runner.content_repo = content_repo
    runner.ledger = ledger
    expected = content_repo / "index.ar.md"
    runner.engine = SimpleNamespace(
        config=SimpleNamespace(get_site_profile=lambda site_id: object()),
        _get_output_path=lambda source_path, locale, profile: expected,
    )
    source = SimpleNamespace(
        site_id="blog.aspose.org",
        source_path=SOURCE_REL,
        replacement_for=lambda locale: None,
    )
    calls = {"heal_ticket": 0}
    runner._append_heal_ticket = lambda **kwargs: calls.__setitem__(
        "heal_ticket", calls["heal_ticket"] + 1
    )
    return runner, source, str(expected), calls


def _ticket(lang, root_cause_class, source_path):
    return {
        "ticket_id": f"{source_path}:{lang}",
        "source_path": source_path,
        "target_lang": lang,
        "root_cause_class": root_cause_class,
        "status": "OPEN",
    }


class TestQuarantineSkip:
    def test_a_quarantined_pair_is_skipped_before_any_translation_attempt(self, tmp_path):
        runner, source, expected_output, calls = _make_runner(
            tmp_path,
            heal_queue_tickets=[
                _ticket("ar", "auto:StructureValidator", f"page{i}") for i in range(3)
            ],
            with_prior_failure=True,
        )

        accepted, output = runner._run_campaign_job(
            shard={"shard_id": "s0"}, source=source, locale="ar", expected_output=expected_output
        )

        assert accepted is False
        assert output == str((tmp_path / "content_repo" / "index.ar.md").resolve())
        assert calls["heal_ticket"] == 1

    def test_an_unseen_candidate_with_no_prior_failure_is_not_skipped(self, tmp_path):
        runner, source, expected_output, calls = _make_runner(
            tmp_path,
            heal_queue_tickets=[
                _ticket("ar", "auto:StructureValidator", f"page{i}") for i in range(3)
            ],
            with_prior_failure=False,
        )
        runner.manifest = SimpleNamespace(retry_policy={})

        try:
            runner._run_campaign_job(
                shard={"shard_id": "s0"},
                source=source,
                locale="ar",
                expected_output=expected_output,
            )
        except KeyError:
            # Expected: it fell through the quarantine check (no prior
            # failure -> not skipped) and hit the next line needing a real
            # retry_policy, which this stub deliberately doesn't provide.
            # The point under test is which branch was reached, not the
            # full job execution.
            pass
        assert calls["heal_ticket"] == 0

    def test_a_pair_below_threshold_is_not_skipped(self, tmp_path):
        runner, source, expected_output, calls = _make_runner(
            tmp_path,
            heal_queue_tickets=[_ticket("ar", "auto:StructureValidator", "page0")],
            with_prior_failure=True,
        )
        runner.manifest = SimpleNamespace(retry_policy={})

        try:
            runner._run_campaign_job(
                shard={"shard_id": "s0"},
                source=source,
                locale="ar",
                expected_output=expected_output,
            )
        except KeyError:
            pass
        assert calls["heal_ticket"] == 0

    def test_a_file_quarantined_across_many_locales_is_skipped_even_for_an_unseen_locale(
        self, tmp_path
    ):
        """QU-02: reproduces the exact live gap. quickstart.md-shaped source
        accumulated one LinkValidator ticket each across 7 distinct locales --
        no single locale reaches the per-locale threshold of 3, and the
        locale under test ("ar") has never failed at all (an unseen
        candidate), yet the file-level dimension must still skip it."""
        runner, source, expected_output, calls = _make_runner(
            tmp_path,
            heal_queue_tickets=[
                _ticket(lang, "auto:LinkValidator", SOURCE_REL)
                for lang in ("de", "fr", "es", "it", "hi", "ja", "ko")
            ],
            with_prior_failure=False,
        )

        accepted, output = runner._run_campaign_job(
            shard={"shard_id": "s0"}, source=source, locale="ar", expected_output=expected_output
        )

        assert accepted is False
        assert output == str((tmp_path / "content_repo" / "index.ar.md").resolve())
        assert calls["heal_ticket"] == 1

    def test_a_file_below_the_per_file_threshold_is_not_skipped(self, tmp_path):
        runner, source, expected_output, calls = _make_runner(
            tmp_path,
            heal_queue_tickets=[
                _ticket(lang, "auto:LinkValidator", SOURCE_REL) for lang in ("de", "fr")
            ],
            with_prior_failure=False,
        )
        runner.manifest = SimpleNamespace(retry_policy={})

        try:
            runner._run_campaign_job(
                shard={"shard_id": "s0"},
                source=source,
                locale="ar",
                expected_output=expected_output,
            )
        except KeyError:
            pass
        assert calls["heal_ticket"] == 0
