"""Replaceable in-memory and SQLite persistence for runtime aggregates."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import uuid4

from dohaaudio.contracts import (
    TERMINAL_STATUSES,
    ArtifactMetadata,
    JobRecord,
    JobStatus,
    ModelManifest,
    StructuredError,
    utc_now,
)
from dohaaudio.errors import ConflictError, NotFoundError


class JobRepository(Protocol):
    """Persistence boundary owned by the Job application service and worker."""

    def get(self, job_id: str) -> JobRecord: ...
    def idempotent_job(self, key: str, fingerprint: str) -> JobRecord | None: ...
    def add(self, job: JobRecord) -> JobRecord: ...
    def replace(self, job: JobRecord) -> None: ...
    def replace_claimed(self, job: JobRecord, claim_token: str) -> None: ...
    def claim_next(self, worker_id: str, lease_seconds: int) -> JobRecord | None: ...
    def recover_stale(self, now: datetime | None = None) -> tuple[str, ...]: ...
    def retries_of(self, job_id: str) -> tuple[JobRecord, ...]: ...
    def count(self) -> int: ...


def _claimed(record: JobRecord, worker_id: str, lease_seconds: int) -> JobRecord:
    now = utc_now()
    return record.model_copy(
        update={
            "status": JobStatus.RUNNING,
            "progress_percent": max(record.progress_percent, 1),
            "stage": "executing",
            "started_at": record.started_at or now,
            "claim_token": f"claim_{uuid4().hex}",
            "claimed_by": worker_id,
            "heartbeat_at": now,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
        },
        deep=True,
    )


def _recovered(record: JobRecord, now: datetime) -> JobRecord:
    return record.model_copy(
        update={
            "status": JobStatus.FAILED,
            "stage": "recovery_failed",
            "error": StructuredError(
                error_code="WORKER_LEASE_EXPIRED",
                message="Worker lease가 만료되어 Job을 안전하게 실패 처리했습니다.",
                retryable=True,
                stage=record.stage,
            ),
            "completed_at": now,
            "claim_token": None,
            "claimed_by": None,
            "lease_expires_at": None,
            "heartbeat_at": None,
            "recovery_count": record.recovery_count + 1,
        },
        deep=True,
    )


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._lock = RLock()

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            try:
                return deepcopy(self._jobs[job_id])
            except KeyError as exc:
                raise NotFoundError("Job") from exc

    def idempotent_job(self, key: str, fingerprint: str) -> JobRecord | None:
        with self._lock:
            entry = self._idempotency.get(key)
            if entry is None:
                return None
            stored_fingerprint, job_id = entry
            if stored_fingerprint != fingerprint:
                raise ConflictError(
                    "IDEMPOTENCY_KEY_CONFLICT",
                    "동일한 idempotency key에 다른 요청을 사용할 수 없습니다.",
                )
            return deepcopy(self._jobs[job_id])

    def add(self, job: JobRecord) -> JobRecord:
        with self._lock:
            entry = self._idempotency.get(job.idempotency_key)
            if entry is not None:
                if entry[0] != job.request_fingerprint:
                    raise ConflictError(
                        "IDEMPOTENCY_KEY_CONFLICT",
                        "동일한 idempotency key에 다른 요청을 사용할 수 없습니다.",
                    )
                return deepcopy(self._jobs[entry[1]])
            if job.job_id in self._jobs:
                raise ConflictError("JOB_ID_CONFLICT", "이미 존재하는 job_id입니다.")
            self._jobs[job.job_id] = deepcopy(job)
            self._idempotency[job.idempotency_key] = (job.request_fingerprint, job.job_id)
            return deepcopy(job)

    def replace(self, job: JobRecord) -> None:
        with self._lock:
            current = self._jobs.get(job.job_id)
            if current is None:
                raise NotFoundError("Job")
            if current.status in TERMINAL_STATUSES and current != job:
                raise ConflictError("JOB_TERMINAL", "종료 상태의 Job은 변경할 수 없습니다.")
            self._jobs[job.job_id] = deepcopy(job)

    def replace_claimed(self, job: JobRecord, claim_token: str) -> None:
        with self._lock:
            current = self._jobs.get(job.job_id)
            if current is None:
                raise NotFoundError("Job")
            if current.status != JobStatus.RUNNING or current.claim_token != claim_token:
                raise ConflictError(
                    "WORKER_CLAIM_LOST", "Worker claim이 더 이상 유효하지 않습니다."
                )
            self._jobs[job.job_id] = deepcopy(job)

    def claim_next(self, worker_id: str, lease_seconds: int) -> JobRecord | None:
        with self._lock:
            queued = sorted(
                (job for job in self._jobs.values() if job.status == JobStatus.QUEUED),
                key=lambda item: (item.created_at, item.job_id),
            )
            if not queued:
                return None
            claimed = _claimed(queued[0], worker_id, lease_seconds)
            self._jobs[claimed.job_id] = claimed
            return deepcopy(claimed)

    def recover_stale(self, now: datetime | None = None) -> tuple[str, ...]:
        recovered_at = now or utc_now()
        with self._lock:
            ids = []
            for job_id, record in tuple(self._jobs.items()):
                if (
                    record.status == JobStatus.RUNNING
                    and record.lease_expires_at is not None
                    and record.lease_expires_at <= recovered_at
                ):
                    self._jobs[job_id] = _recovered(record, recovered_at)
                    ids.append(job_id)
            return tuple(ids)

    def retries_of(self, job_id: str) -> tuple[JobRecord, ...]:
        with self._lock:
            return tuple(
                deepcopy(item)
                for item in sorted(self._jobs.values(), key=lambda value: value.attempt)
                if item.retry_of_job_id == job_id
            )

    def count(self) -> int:
        with self._lock:
            return len(self._jobs)


class SQLiteJobRepository:
    """Single-table local persistence; each aggregate operation is one transaction."""

    TABLE_COUNT = 1

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._bootstrap_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _bootstrap_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_of_job_id TEXT,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs(status, created_at, job_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_jobs_retry ON jobs(retry_of_job_id, job_id)"
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> JobRecord:
        return JobRecord.model_validate_json(row["payload_json"])

    @staticmethod
    def _values(job: JobRecord) -> tuple[object, ...]:
        return (
            job.job_id,
            job.idempotency_key,
            job.request_fingerprint,
            job.status.value,
            job.retry_of_job_id,
            job.created_at.isoformat(),
            job.model_dump_json(),
        )

    def get(self, job_id: str) -> JobRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("Job")
        return self._decode(row)

    def idempotent_job(self, key: str, fingerprint: str) -> JobRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT request_fingerprint, payload_json FROM jobs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        if row["request_fingerprint"] != fingerprint:
            raise ConflictError(
                "IDEMPOTENCY_KEY_CONFLICT",
                "동일한 idempotency key에 다른 요청을 사용할 수 없습니다.",
            )
        return self._decode(row)

    def add(self, job: JobRecord) -> JobRecord:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_fingerprint, payload_json FROM jobs WHERE idempotency_key = ?",
                (job.idempotency_key,),
            ).fetchone()
            if row is not None:
                connection.commit()
                if row["request_fingerprint"] != job.request_fingerprint:
                    raise ConflictError(
                        "IDEMPOTENCY_KEY_CONFLICT",
                        "동일한 idempotency key에 다른 요청을 사용할 수 없습니다.",
                    )
                return self._decode(row)
            try:
                connection.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)", self._values(job)
                )
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ConflictError("JOB_ID_CONFLICT", "이미 존재하는 job_id입니다.") from exc
            connection.commit()
        return deepcopy(job)

    def replace(self, job: JobRecord) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM jobs WHERE job_id = ?", (job.job_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise NotFoundError("Job")
            current = self._decode(row)
            if current.status in TERMINAL_STATUSES and current != job:
                connection.rollback()
                raise ConflictError("JOB_TERMINAL", "종료 상태의 Job은 변경할 수 없습니다.")
            connection.execute(
                """UPDATE jobs SET status = ?, retry_of_job_id = ?, payload_json = ?
                   WHERE job_id = ?""",
                (job.status.value, job.retry_of_job_id, job.model_dump_json(), job.job_id),
            )
            connection.commit()

    def replace_claimed(self, job: JobRecord, claim_token: str) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM jobs WHERE job_id = ?", (job.job_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise NotFoundError("Job")
            current = self._decode(row)
            if current.status != JobStatus.RUNNING or current.claim_token != claim_token:
                connection.rollback()
                raise ConflictError(
                    "WORKER_CLAIM_LOST", "Worker claim이 더 이상 유효하지 않습니다."
                )
            connection.execute(
                "UPDATE jobs SET status = ?, payload_json = ? WHERE job_id = ?",
                (job.status.value, job.model_dump_json(), job.job_id),
            )
            connection.commit()

    def claim_next(self, worker_id: str, lease_seconds: int) -> JobRecord | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT payload_json FROM jobs WHERE status = ?
                   ORDER BY created_at, job_id LIMIT 1""",
                (JobStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            claimed = _claimed(self._decode(row), worker_id, lease_seconds)
            connection.execute(
                "UPDATE jobs SET status = ?, payload_json = ? WHERE job_id = ?",
                (JobStatus.RUNNING.value, claimed.model_dump_json(), claimed.job_id),
            )
            connection.commit()
            return claimed

    def recover_stale(self, now: datetime | None = None) -> tuple[str, ...]:
        recovered_at = now or utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT payload_json FROM jobs WHERE status = ?", (JobStatus.RUNNING.value,)
            ).fetchall()
            recovered = []
            for row in rows:
                record = self._decode(row)
                if record.lease_expires_at is not None and record.lease_expires_at <= recovered_at:
                    updated = _recovered(record, recovered_at)
                    connection.execute(
                        "UPDATE jobs SET status = ?, payload_json = ? WHERE job_id = ?",
                        (updated.status.value, updated.model_dump_json(), updated.job_id),
                    )
                    recovered.append(updated.job_id)
            connection.commit()
            return tuple(recovered)

    def retries_of(self, job_id: str) -> tuple[JobRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM jobs WHERE retry_of_job_id = ? "
                "ORDER BY created_at, job_id",
                (job_id,),
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])


class InMemoryArtifactCatalog:
    def __init__(self) -> None:
        self._artifacts: dict[str, ArtifactMetadata] = {}
        self._lock = RLock()

    def register(self, artifact: ArtifactMetadata) -> ArtifactMetadata:
        return self.register_many((artifact,))[0]

    def register_many(
        self, artifacts: tuple[ArtifactMetadata, ...]
    ) -> tuple[ArtifactMetadata, ...]:
        with self._lock:
            pending: dict[str, ArtifactMetadata] = {}
            for artifact in artifacts:
                existing = self._artifacts.get(artifact.artifact_id) or pending.get(
                    artifact.artifact_id
                )
                if existing is not None and existing != artifact:
                    raise ConflictError(
                        "ARTIFACT_IMMUTABILITY_CONFLICT",
                        "기존 Artifact payload metadata를 덮어쓸 수 없습니다.",
                    )
                pending[artifact.artifact_id] = artifact
            self._artifacts.update(pending)
            return tuple(deepcopy(self._artifacts[item.artifact_id]) for item in artifacts)

    def get(self, artifact_id: str) -> ArtifactMetadata:
        with self._lock:
            try:
                return deepcopy(self._artifacts[artifact_id])
            except KeyError as exc:
                raise NotFoundError("Artifact") from exc

    def count(self) -> int:
        with self._lock:
            return len(self._artifacts)


class InMemoryManifestRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, ModelManifest] = {}
        self._lock = RLock()

    def register(self, manifest: ModelManifest) -> ModelManifest:
        with self._lock:
            existing = self._manifests.get(manifest.model_manifest_id)
            if existing is not None and existing != manifest:
                raise ConflictError(
                    "MANIFEST_IMMUTABILITY_CONFLICT",
                    "게시된 Model Manifest를 변경할 수 없습니다.",
                )
            if existing is None:
                self._manifests[manifest.model_manifest_id] = manifest
            return deepcopy(self._manifests[manifest.model_manifest_id])

    def get(self, manifest_id: str) -> ModelManifest:
        with self._lock:
            try:
                return deepcopy(self._manifests[manifest_id])
            except KeyError as exc:
                raise NotFoundError("Model Manifest") from exc

    def ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._manifests))
