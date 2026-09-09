from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Barrier, Thread

from src.tm.intent_spool import TMIntentSpool
from src.tm.rejected_task_queue import RejectedTaskQueue
from src.tm.retry_records import RejectedTranslationTask
from src.workers.professionalize_retry_worker import ProfessionalizeRetryWorker


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
        "source_sha256": sha256(source.encode()).hexdigest(), "target_lang": "de",
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
