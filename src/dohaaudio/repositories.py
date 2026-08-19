"""Small in-memory persistence implementations for the runtime foundation."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock

from dohaaudio.contracts import ArtifactMetadata, JobRecord, ModelManifest
from dohaaudio.errors import ConflictError, NotFoundError


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
            if job.job_id not in self._jobs:
                raise NotFoundError("Job")
            self._jobs[job.job_id] = deepcopy(job)

    def count(self) -> int:
        with self._lock:
            return len(self._jobs)


class InMemoryArtifactCatalog:
    def __init__(self) -> None:
        self._artifacts: dict[str, ArtifactMetadata] = {}
        self._lock = RLock()

    def register(self, artifact: ArtifactMetadata) -> ArtifactMetadata:
        with self._lock:
            existing = self._artifacts.get(artifact.artifact_id)
            if existing is not None and existing != artifact:
                raise ConflictError(
                    "ARTIFACT_IMMUTABILITY_CONFLICT",
                    "기존 Artifact payload metadata를 덮어쓸 수 없습니다.",
                )
            if existing is None:
                self._artifacts[artifact.artifact_id] = artifact
            return deepcopy(self._artifacts[artifact.artifact_id])

    def get(self, artifact_id: str) -> ArtifactMetadata:
        with self._lock:
            try:
                return deepcopy(self._artifacts[artifact_id])
            except KeyError as exc:
                raise NotFoundError("Artifact") from exc


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
