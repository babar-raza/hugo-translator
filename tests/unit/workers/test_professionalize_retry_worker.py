from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Thread

import pytest

from src.tm.intent_spool import TMIntentSpool
from src.tm.rejected_task_queue import RejectedTaskQueue
from src.tm.retry_records import RejectedTranslationTask
from src.workers import professionalize_retry_worker as retry_worker_module
from src.workers.professionalize_retry_worker import (
    ProfessionalizeRetryWorker,
    build_campaign_zero_defect_validator,
    build_default_validator,
    load_retry_worker_config,
)


class Provider:
    def __init__(self, value: str = "# translated\n") -> None:
        self.value, self.calls = value, 0

    def generate(self, system_prompt: str, user_text: str):
        self.calls += 1
        return self.value, 11, 7


class TimeoutProvider(Provider):
    def generate(self, system_prompt: str, user_text: str):
        self.calls += 1
        raise TimeoutError("provider timeout")


def task(root: Path, source: str = "# source\n", budget: int = 2) -> RejectedTranslationTask:
    (root / "content/en").mkdir(parents=True, exist_ok=True)
    (root / "content/en/page.md").write_text(source, encoding="utf-8")
    return RejectedTranslationTask.from_mapping({
        "campaign_id": "campaign", "site_id": "docs.aspose.org",
        "source_path": "content/en/page.md", "output_path": "content/de/page.md",
        "source_sha256": sha256((root / "content/en/page.md").read_bytes()).hexdigest(), "target_lang": "de",
        "failure_category": "validation", "failure_fingerprint": "fingerprint",
        "retry_budget": budget, "model_target": "professionalize_llm",
    })


def worker(root: Path, queue: RejectedTaskQueue, spool: TMIntentSpool, provider: Provider, *, live=True, validator=None):
    return ProfessionalizeRetryWorker(queue=queue, intent_spool=spool, provider=provider,
        repository_root=root, live_mode=live, validate_document=validator or (lambda source, candidate, task: None))


def test_accepted_retry_writes_full_document_receipt_then_tm_intent(tmp_path: Path):
    queue, spool = RejectedTaskQueue(tmp_path / "retry.sqlite"), TMIntentSpool(tmp_path / "tm.sqlite")
    queued = task(tmp_path)
    task_id = queue.enqueue(queued)
    result = worker(tmp_path, queue, spool, Provider()).run_once(owner="one")
    assert result["accepted"] == 1
    assert (tmp_path / "content/de/page.md").read_text(encoding="utf-8") == "# translated\n"
    receipt = queue.get(task_id)["receipt"]
    assert receipt["tm_intent_id"]
    assert "translated" not in str(receipt)
    assert spool.stats()["PENDING"] == 1


def test_accepted_retry_preserves_candidate_free_campaign_receipt(tmp_path: Path):
    queue, spool = RejectedTaskQueue(tmp_path / "retry.sqlite"), TMIntentSpool(tmp_path / "tm.sqlite")
    task_id = queue.enqueue(task(tmp_path))
    receipt = {"campaign_id": "campaign", "gate_results": {str(i): {"passed": True} for i in range(1, 45)}}
    assert worker(
        tmp_path, queue, spool, Provider(), validator=lambda _source, _candidate, _task: receipt
    ).run_once(owner="one")["accepted"] == 1
    terminal = queue.get(task_id)["receipt"]
    assert terminal["campaign_receipt"] == receipt
    assert "translated" not in str(terminal)


def test_source_drift_never_calls_provider_or_writes(tmp_path: Path):
    queue, spool, provider = RejectedTaskQueue(tmp_path / "retry.sqlite"), TMIntentSpool(tmp_path / "tm.sqlite"), Provider()
    task_id = queue.enqueue(task(tmp_path))
    (tmp_path / "content/en/page.md").write_text("changed", encoding="utf-8")
    assert worker(tmp_path, queue, spool, provider).run_once(owner="one")["dead_lettered"] == 1
    assert queue.get(task_id)["error_code"] == "SOURCE_DRIFT"
    assert provider.calls == 0 and spool.stats()["PENDING"] == 0


def test_validation_failure_retries_then_dead_letters_at_budget(tmp_path: Path):
    queue, spool = RejectedTaskQueue(tmp_path / "retry.sqlite"), TMIntentSpool(tmp_path / "tm.sqlite")
    task_id = queue.enqueue(task(tmp_path, budget=2))
    def failure(source, candidate, retry_task):
        del source, candidate, retry_task
        raise ValueError("invalid")
    assert worker(tmp_path, queue, spool, Provider(), validator=failure).run_once(owner="one")["retried"] == 1
    assert worker(tmp_path, queue, spool, Provider(), validator=failure).run_once(owner="two")["dead_lettered"] == 1
    assert queue.get(task_id)["state"] == "DEAD_LETTER"
    assert not (tmp_path / "content/de/page.md").exists()


def test_two_consumers_claim_one_task_once(tmp_path: Path):
    queue, spool = RejectedTaskQueue(tmp_path / "retry.sqlite"), TMIntentSpool(tmp_path / "tm.sqlite")
    queue.enqueue(task(tmp_path))
    provider, barrier, results = Provider(), Barrier(2), []

    def run(owner):
        barrier.wait()
        results.append(worker(tmp_path, queue, spool, provider).run_once(owner=owner))

    threads = [Thread(target=run, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(item["accepted"] for item in results) == 1
    assert provider.calls == 1 and spool.stats()["PENDING"] == 1


def test_disabled_live_mode_never_calls_provider(tmp_path: Path):
    queue, spool, provider = RejectedTaskQueue(tmp_path / "retry.sqlite"), TMIntentSpool(tmp_path / "tm.sqlite"), Provider()
    queue.enqueue(task(tmp_path))
    assert worker(tmp_path, queue, spool, provider, live=False).run_once(owner="one")["retried"] == 1
    assert provider.calls == 0


def test_duplicate_enqueue_has_one_task_and_one_provider_call(tmp_path: Path):
    queue, spool, provider = RejectedTaskQueue(tmp_path / "retry.sqlite"), TMIntentSpool(tmp_path / "tm.sqlite"), Provider()
    retry_task = task(tmp_path)
    assert queue.enqueue(retry_task) == queue.enqueue(retry_task)
    assert worker(tmp_path, queue, spool, provider).run_once(owner="one")["accepted"] == 1
    assert provider.calls == 1
    assert queue.stats()["ACCEPTED"] == 1


def test_provider_timeout_retries_without_output_or_tm_intent(tmp_path: Path):
    queue, spool, provider = RejectedTaskQueue(tmp_path / "retry.sqlite"), TMIntentSpool(tmp_path / "tm.sqlite"), TimeoutProvider()
    queue.enqueue(task(tmp_path, budget=2))
    assert worker(tmp_path, queue, spool, provider).run_once(owner="one")["retried"] == 1
    assert provider.calls == 1
    assert not (tmp_path / "content/de/page.md").exists()
    assert spool.stats()["PENDING"] == 0


def test_worker_config_rejects_parallel_consumer_or_bad_limits(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "global.yaml").write_text("professionalize_retry:\n  concurrency: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="concurrency"):
        load_retry_worker_config(config)
    (config / "global.yaml").write_text("professionalize_retry:\n  limit: 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="positive"):
        load_retry_worker_config(config)


def test_worker_config_uses_additive_defaults(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "global.yaml").write_text("professionalize_retry:\n  model_id: test-model\n", encoding="utf-8")
    loaded = load_retry_worker_config(config)
    assert loaded["model_id"] == "test-model"
    assert loaded["live_mode"] is False
    assert loaded["concurrency"] == 1


def test_default_validator_accepts_a_clean_pair(tmp_path: Path):
    validate = build_default_validator()
    validate("# Hello\n\nWorld.\n", "# Hallo\n\nWelt.\n", task(tmp_path))


def test_default_validator_raises_on_dropped_link_and_heading(tmp_path: Path):
    validate = build_default_validator()
    with pytest.raises(ValueError, match="StructureValidator"):
        validate(
            "# Hello [link](/a)\n",
            "Something else entirely with no link at all\n",
            task(tmp_path),
        )


def test_campaign_zero_defect_validator_returns_engine_receipt_for_exact_task_bytes(tmp_path: Path):
    retry_task = task(tmp_path, source="# source\r\n")
    calls = []

    class Accepted:
        def receipt(self):
            return {"campaign_id": "campaign", "gate_results": {str(i): {"passed": True} for i in range(1, 45)}}

    class Engine:
        def accept_candidate_bytes(self, **kwargs):
            calls.append(kwargs)
            return Accepted()

    receipt = build_campaign_zero_defect_validator(Engine(), tmp_path)(
        "# source\r\n", "# translated\n", retry_task
    )

    assert receipt["campaign_id"] == "campaign"
    assert calls[0]["source_bytes"] == b"# source\r\n"
    assert calls[0]["output_path"] == (tmp_path / "content/de/page.md").resolve()
    assert calls[0]["model_fingerprint"] == "professionalize_llm"


def test_build_professionalize_provider_acquires_slot_around_generate(monkeypatch):
    calls = []

    class FakeSlot:
        def __enter__(self):
            calls.append("enter")

        def __exit__(self, *exc):
            calls.append("exit")
            return False

    class FakeProvider:
        def generate(self, system_prompt, user_text):
            calls.append("generate")
            return "candidate", 3, 2

    class FakeBackend:
        def __init__(self):
            self._provider = FakeProvider()

        def load(self):
            calls.append("load")

        def _llm_slot(self):
            return FakeSlot()

    fake_backend = FakeBackend()
    monkeypatch.setattr(
        "src.model_runtime.registry.ModelRegistry.get_model", lambda self, model_id: object()
    )
    monkeypatch.setattr(
        "src.model_runtime.llm_backend.LLMModelBackend",
        lambda model_info, device: fake_backend,
    )

    provider = retry_worker_module.build_professionalize_provider()
    result = provider.generate("system", "text")

    assert result == ("candidate", 3, 2)
    assert calls == ["load", "enter", "generate", "exit"]


def test_main_dry_run_never_calls_provider_and_retries(tmp_path: Path, capsys):
    source = tmp_path / "content/en/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("# source\n", encoding="utf-8")
    queue = RejectedTaskQueue(tmp_path / "queue.sqlite")
    queue.enqueue(
        RejectedTranslationTask.from_mapping(
            {
                "campaign_id": "c",
                "site_id": "docs.aspose.org",
                "source_path": "content/en/page.md",
                "output_path": "content/de/page.md",
                "source_sha256": sha256(source.read_bytes()).hexdigest(),
                "target_lang": "de",
                "failure_category": "x",
                "failure_fingerprint": "x",
                "retry_budget": 2,
                "model_target": "professionalize_llm",
            }
        )
    )

    exit_code = retry_worker_module.main(
        [
            "--repository-root",
            str(tmp_path),
            "--queue-path",
            str(tmp_path / "queue.sqlite"),
            "--intent-spool-path",
            str(tmp_path / "intents.sqlite"),
        ]
    )

    assert exit_code == 0
    assert not (tmp_path / "content/de/page.md").exists()
    result = json.loads(capsys.readouterr().out)
    assert result["retried"] == 1
    assert result["accepted"] == 0


def test_main_stats_never_constructs_provider_or_claims(tmp_path: Path, monkeypatch, capsys):
    queue = RejectedTaskQueue(tmp_path / "queue.sqlite")
    provider_calls = []
    monkeypatch.setattr(
        retry_worker_module,
        "build_professionalize_provider",
        lambda *args: provider_calls.append(args),
    )

    exit_code = retry_worker_module.main(
        ["--repository-root", str(tmp_path), "--queue-path", str(tmp_path / "queue.sqlite"),
         "--heartbeat-path", str(tmp_path / "heartbeat.json"), "--action", "stats"]
    )

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert {key: result[key] for key in queue.stats()} == queue.stats()
    assert result["oldest_active_age_seconds"] is None
    assert result["expired_claims"] == 0
    assert provider_calls == []
    heartbeat = json.loads((tmp_path / "heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat["status"] == "stats" and heartbeat["QUEUED"] == 0


def test_main_enqueue_validates_canonical_task_and_is_idempotent(tmp_path: Path, capsys):
    source = tmp_path / "content/en/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("# source\n", encoding="utf-8")
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps({
        "campaign_id": "c", "site_id": "docs.aspose.org",
        "source_path": "content/en/page.md", "output_path": "content/de/page.md",
        "source_sha256": sha256(source.read_bytes()).hexdigest(), "target_lang": "de",
        "failure_category": "validation", "failure_fingerprint": "f", "retry_budget": 2,
        "model_target": "professionalize_llm",
    }), encoding="utf-8")
    args = ["--repository-root", str(tmp_path), "--queue-path", str(tmp_path / "queue.sqlite"),
            "--action", "enqueue", "--task-json", str(task_path)]

    assert retry_worker_module.main(args) == 0
    first = json.loads(capsys.readouterr().out)["task_id"]
    assert retry_worker_module.main(args) == 0
    assert json.loads(capsys.readouterr().out)["task_id"] == first
    assert RejectedTaskQueue(tmp_path / "queue.sqlite").stats()["QUEUED"] == 1


def test_main_enqueue_refuses_noncanonical_task(tmp_path: Path):
    task_path = tmp_path / "invalid.json"
    task_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        retry_worker_module.main([
            "--repository-root", str(tmp_path), "--queue-path", str(tmp_path / "queue.sqlite"),
            "--action", "enqueue", "--task-json", str(task_path),
        ])


def test_main_dead_letter_requires_explicit_task_and_reason(tmp_path: Path, capsys):
    queue = RejectedTaskQueue(tmp_path / "queue.sqlite")
    task_id = queue.enqueue(task(tmp_path))
    assert retry_worker_module.main([
        "--repository-root", str(tmp_path), "--queue-path", str(tmp_path / "queue.sqlite"),
        "--action", "dead-letter", "--task-id", task_id, "--reason", "operator_cancelled",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {"state": "DEAD_LETTER", "task_id": task_id}
    assert queue.get(task_id)["state"] == "DEAD_LETTER"


def test_main_reconcile_reports_both_expired_claim_classes(tmp_path: Path, capsys):
    queue = RejectedTaskQueue(tmp_path / "queue.sqlite")
    queue.enqueue(task(tmp_path))
    queue.claim("crashed", lease_seconds=0.01)
    spool = TMIntentSpool(tmp_path / "intents.sqlite")
    spool.enqueue({"site_id": "docs.aspose.org", "src_lang": "en", "tgt_lang": "de", "text": "a", "translation": "b"})
    spool.claim("crashed", lease_seconds=0.01)
    import time
    time.sleep(0.02)

    assert retry_worker_module.main([
        "--repository-root", str(tmp_path), "--queue-path", str(tmp_path / "queue.sqlite"),
        "--intent-spool-path", str(tmp_path / "intents.sqlite"), "--action", "reconcile",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "retry_claims_requeued": 1, "tm_intent_claims_requeued": 1,
    }


def test_main_live_mode_builds_a_real_provider(tmp_path: Path, monkeypatch, capsys):
    """--live must reach build_professionalize_provider(), not the dry-run
    _InertProvider -- proven by monkeypatching the factory function itself
    rather than the model registry, so this stays independent of how the
    real provider happens to be constructed."""
    source = tmp_path / "content/en/page.md"
    source.parent.mkdir(parents=True)
    source.write_text("# source\n", encoding="utf-8")
    queue = RejectedTaskQueue(tmp_path / "queue.sqlite")
    queue.enqueue(
        RejectedTranslationTask.from_mapping(
            {
                "campaign_id": "c",
                "site_id": "docs.aspose.org",
                "source_path": "content/en/page.md",
                "output_path": "content/de/page.md",
                "source_sha256": sha256(source.read_bytes()).hexdigest(),
                "target_lang": "de",
                "failure_category": "x",
                "failure_fingerprint": "x",
                "retry_budget": 2,
                "model_target": "professionalize_llm",
            }
        )
    )
    built = []

    def fake_build_provider(model_id="professionalize_llm"):
        assert model_id == "professionalize_llm"
        built.append(True)
        return Provider("# translated\n")

    monkeypatch.setattr(retry_worker_module, "build_professionalize_provider", fake_build_provider)
    validator_calls = []

    def fake_campaign_validator(**kwargs):
        validator_calls.append(kwargs)
        return lambda _source, _candidate, _task: {"campaign_id": "c"}

    monkeypatch.setattr(retry_worker_module, "build_campaign_validator_from_manifest", fake_campaign_validator)

    exit_code = retry_worker_module.main(
        [
            "--repository-root",
            str(tmp_path),
            "--queue-path",
            str(tmp_path / "queue.sqlite"),
            "--intent-spool-path",
            str(tmp_path / "intents.sqlite"),
            "--campaign-manifest",
            str(tmp_path / "campaign.yaml"),
            "--live",
        ]
    )

    assert exit_code == 0
    assert built == [True]
    assert validator_calls[0]["repository_root"] == tmp_path
    result = json.loads(capsys.readouterr().out)
    assert result["accepted"] == 1
    assert (tmp_path / "content/de/page.md").read_text(encoding="utf-8") == "# translated\n"


def test_main_live_mode_requires_campaign_manifest(tmp_path: Path):
    with pytest.raises(ValueError, match="campaign-manifest"):
        retry_worker_module.main(["--repository-root", str(tmp_path), "--live"])
