from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dohaaudio.bootstrap import bootstrap_persistent_runtime
from dohaaudio.contracts import CreateJobRequest, RetryJobRequest
from dohaaudio.errors import ConflictError
from dohaaudio.repositories import SQLiteJobRepository


def test_sqlite_job_persists_and_replays_after_restart(
    database_path: Path, make_request: Callable[..., CreateJobRequest]
) -> None:
    first_runtime = bootstrap_persistent_runtime(database_path)
    request = make_request(job_id="job-persisted", idempotency_key="idem-persisted")
    created = first_runtime.create_job(request)

    reopened = bootstrap_persistent_runtime(database_path)
    assert reopened.get_job(created.job_id).job_id == created.job_id
    assert reopened.create_job(request).job_id == created.job_id
    assert reopened.jobs.count() == 1


def test_sqlite_idempotency_conflict_rolls_back_atomically(
    database_path: Path, make_request: Callable[..., CreateJobRequest]
) -> None:
    runtime = bootstrap_persistent_runtime(database_path)
    runtime.create_job(make_request(job_id="job-one", idempotency_key="idem-one"))
    with pytest.raises(ConflictError):
        runtime.create_job(
            make_request(
                job_id="job-two",
                idempotency_key="idem-one",
                settings_snapshot={"seed": 999},
            )
        )
    assert runtime.jobs.count() == 1


def test_retry_lineage_and_terminal_state_persist_after_restart(
    database_path: Path, make_request: Callable[..., CreateJobRequest]
) -> None:
    runtime = bootstrap_persistent_runtime(database_path)
    original = runtime.create_job(
        make_request(job_id="job-original", idempotency_key="idem-original")
    )
    runtime.cancel_job(original.job_id)
    retry = runtime.retry_job(
        original.job_id,
        RetryJobRequest(job_id="job-retry", idempotency_key="idem-retry"),
    )

    reopened = bootstrap_persistent_runtime(database_path)
    assert reopened.get_job(original.job_id).status.value == "cancelled"
    assert reopened.jobs.retries_of(original.job_id)[0].job_id == retry.job_id
    with pytest.raises(ConflictError):
        reopened.cancel_job(original.job_id)


def test_sqlite_schema_is_one_job_aggregate_table(database_path: Path) -> None:
    repository = SQLiteJobRepository(database_path)
    assert repository.TABLE_COUNT == 1
