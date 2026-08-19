from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest

from dohaaudio.bootstrap import AudioRuntime, bootstrap_runtime
from dohaaudio.contracts import CreateJobRequest, JobStatus, RetryJobRequest
from dohaaudio.errors import ConflictError, ContractError
from dohaaudio.providers import FakeAudioProvider


class FailingFakeProvider(FakeAudioProvider):
    def execute(self, job):  # type: ignore[no-untyped-def]
        raise RuntimeError("C:\\private\\model token=secret stack trace")


class ToggleReadyFakeProvider(FakeAudioProvider):
    def __init__(self) -> None:
        super().__init__()
        self.accepting_jobs = True

    def readiness(self) -> bool:
        return self.accepting_jobs and self.health()


def test_job_lifecycle_and_terminal_immutability(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    created = runtime.create_job(make_request())
    assert (created.status, created.progress_percent) == (JobStatus.QUEUED, 0)
    running = runtime.start_job(created.job_id)
    assert running.status == JobStatus.RUNNING
    succeeded = runtime.run_job(created.job_id)
    assert (succeeded.status, succeeded.progress_percent) == (JobStatus.SUCCEEDED, 100)
    with pytest.raises(ConflictError):
        runtime.start_job(created.job_id)
    with pytest.raises(ConflictError):
        runtime.cancel_job(created.job_id)


def test_progress_100_does_not_imply_success(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    created = runtime.create_job(make_request())
    runtime.start_job(created.job_id)
    progress = runtime.update_progress(created.job_id, 100, "artifact_validation")
    assert progress.progress_percent == 100
    assert progress.status == JobStatus.RUNNING
    assert runtime.run_job(created.job_id).status == JobStatus.SUCCEEDED


def test_settings_snapshot_is_isolated_from_caller_mutation(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    settings = {"seed": 1, "nested": {"value": "original"}}
    created = runtime.create_job(make_request(settings_snapshot=settings))
    settings["nested"]["value"] = "mutated"
    stored = runtime.jobs.get(created.job_id)
    assert stored.settings_snapshot["nested"]["value"] == "original"


def test_same_idempotency_key_and_request_replays_existing_job(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    first = runtime.create_job(make_request(job_id="job-first"))
    replay = runtime.create_job(make_request(job_id="job-first"))
    assert replay.job_id == first.job_id
    assert runtime.jobs.count() == 1


def test_idempotency_replay_does_not_depend_on_current_readiness(
    make_request: Callable[..., CreateJobRequest],
) -> None:
    provider = ToggleReadyFakeProvider()
    runtime = bootstrap_runtime(provider=provider)
    request = make_request(job_id="job-readiness-replay", idempotency_key="idem-readiness")
    first = runtime.create_job(request)
    provider.accepting_jobs = False

    replay = runtime.create_job(request)

    assert replay.job_id == first.job_id
    assert runtime.jobs.count() == 1
    with pytest.raises(ContractError) as exc_info:
        runtime.create_job(make_request(job_id="job-not-ready", idempotency_key="idem-not-ready"))
    assert exc_info.value.error_code == "PROVIDER_NOT_READY"


def test_idempotency_conflict_creates_no_partial_job(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    runtime.create_job(make_request(job_id="job-first"))
    with pytest.raises(ConflictError) as exc_info:
        runtime.create_job(make_request(job_id="job-second", settings_snapshot={"seed": 9999}))
    assert exc_info.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"
    assert runtime.jobs.count() == 1


def test_concurrent_idempotency_replay_creates_one_job(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    request = make_request(job_id="job-concurrent", idempotency_key="idem-concurrent")
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: runtime.create_job(request), range(16)))
    assert {response.job_id for response in responses} == {"job-concurrent"}
    assert runtime.jobs.count() == 1


def test_queued_and_running_jobs_can_be_cancelled(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    queued = runtime.create_job(make_request())
    assert runtime.cancel_job(queued.job_id).status == JobStatus.CANCELLED

    running = runtime.create_job(make_request(job_id="job-running", idempotency_key="idem-running"))
    runtime.start_job(running.job_id)
    assert runtime.cancel_job(running.job_id).status == JobStatus.CANCELLED


def test_retry_creates_new_job_and_preserves_original(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    original = runtime.create_job(make_request())
    runtime.cancel_job(original.job_id)
    retry = runtime.retry_job(
        original.job_id,
        RetryJobRequest(job_id="job-retry", idempotency_key="idem-retry"),
    )
    assert retry.job_id != original.job_id
    assert retry.retry_of_job_id == original.job_id
    assert retry.attempt == 2
    assert runtime.get_job(original.job_id).status == JobStatus.CANCELLED


def test_failed_job_exposes_only_structured_safe_error(
    make_request: Callable[..., CreateJobRequest],
) -> None:
    runtime = bootstrap_runtime(provider=FailingFakeProvider())
    job = runtime.create_job(make_request())
    failed = runtime.run_job(job.job_id)
    assert failed.status == JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.error_code == "PROVIDER_EXECUTION_FAILED"
    serialized = failed.model_dump_json()
    assert "C:\\private" not in serialized
    assert "stack trace" not in serialized
    assert "token=secret" not in serialized

    retry = runtime.retry_job(
        job.job_id,
        RetryJobRequest(job_id="job-failure-retry", idempotency_key="idem-failure-retry"),
    )
    assert retry.retry_of_job_id == job.job_id
    original = runtime.get_job(job.job_id)
    assert original.error is not None
    assert original.error.error_code == "PROVIDER_EXECUTION_FAILED"
