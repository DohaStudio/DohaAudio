from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event, Lock

from dohaaudio.bootstrap import bootstrap_persistent_runtime, bootstrap_runtime
from dohaaudio.contracts import CreateJobRequest, JobStatus, utc_now
from dohaaudio.providers import FakeAudioProvider


class CountingProvider(FakeAudioProvider):
    def __init__(self) -> None:
        super().__init__()
        self.invocations = 0
        self._lock = Lock()

    def execute(self, job):  # type: ignore[no-untyped-def]
        with self._lock:
            self.invocations += 1
        return super().execute(job)


class BlockingProvider(FakeAudioProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def execute(self, job):  # type: ignore[no-untyped-def]
        self.started.set()
        assert self.release.wait(timeout=5)
        return super().execute(job)


class FailingProvider(FakeAudioProvider):
    def execute(self, job):  # type: ignore[no-untyped-def]
        raise RuntimeError("C:\\private\\dataset token=secret")


def test_atomic_claim_prevents_duplicate_execution(
    make_request: Callable[..., CreateJobRequest],
) -> None:
    provider = CountingProvider()
    runtime = bootstrap_runtime(provider=provider)
    runtime.create_job(make_request(job_id="job-claim", idempotency_key="idem-claim"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: runtime.run_worker_once(), range(8)))
    completed = [result for result in results if result is not None]
    assert len(completed) == 1
    assert completed[0].status == JobStatus.SUCCEEDED
    assert provider.invocations == 1
    assert runtime.artifacts.count() == 1


def test_sqlite_atomic_claim_survives_multiple_runtime_instances(
    database_path: Path,
    make_request: Callable[..., CreateJobRequest],
) -> None:
    provider = CountingProvider()
    first = bootstrap_persistent_runtime(database_path, provider=provider)
    second = bootstrap_persistent_runtime(database_path, provider=provider)
    first.create_job(make_request(job_id="job-sqlite-claim", idempotency_key="idem-sqlite-claim"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda runtime: runtime.run_worker_once(), (first, second)))
    assert len([result for result in results if result is not None]) == 1
    assert provider.invocations == 1
    assert first.get_job("job-sqlite-claim").status == JobStatus.SUCCEEDED


def test_worker_observes_running_cancellation_without_artifact_registration(
    make_request: Callable[..., CreateJobRequest],
) -> None:
    provider = BlockingProvider()
    runtime = bootstrap_runtime(provider=provider)
    job = runtime.create_job(
        make_request(job_id="job-cancel-worker", idempotency_key="idem-cancel-worker")
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime.run_worker_once)
        assert provider.started.wait(timeout=5)
        assert runtime.cancel_job(job.job_id).status == JobStatus.CANCELLED
        provider.release.set()
        assert future.result(timeout=5).status == JobStatus.CANCELLED
    assert runtime.artifacts.count() == 0


def test_worker_failure_is_structured_and_registers_no_partial_artifact(
    make_request: Callable[..., CreateJobRequest],
) -> None:
    runtime = bootstrap_runtime(provider=FailingProvider())
    job = runtime.create_job(
        make_request(job_id="job-worker-fail", idempotency_key="idem-worker-fail")
    )
    failed = runtime.run_worker_once()
    assert failed is not None and failed.status == JobStatus.FAILED
    assert failed.error is not None and failed.error.error_code == "PROVIDER_EXECUTION_FAILED"
    assert runtime.get_job(job.job_id).status == JobStatus.FAILED
    assert runtime.artifacts.count() == 0


def test_stale_running_job_is_failed_not_implicitly_requeued(
    make_request: Callable[..., CreateJobRequest],
) -> None:
    runtime = bootstrap_runtime()
    job = runtime.create_job(make_request(job_id="job-stale", idempotency_key="idem-stale"))
    claimed = runtime.jobs.claim_next("worker-crashed", 60)
    assert claimed is not None
    recovered = runtime.jobs.recover_stale(utc_now() + timedelta(minutes=2))
    assert recovered == (job.job_id,)
    record = runtime.jobs.get(job.job_id)
    assert record.status == JobStatus.FAILED
    assert record.error is not None and record.error.retryable is True
