"""Composition root for the standalone fake provider runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dohaaudio.artifacts import ArtifactResolver, InMemoryArtifactResolver
from dohaaudio.contracts import (
    CapabilityResponse,
    CreateJobRequest,
    HealthResponse,
    JobResponse,
    ModelManifest,
    ReadinessResponse,
    ResultResponse,
    RetryJobRequest,
)
from dohaaudio.providers import (
    CapabilityRegistry,
    FakeAudioProvider,
    ProviderRegistry,
    fake_model_manifest,
)
from dohaaudio.repositories import (
    InMemoryArtifactCatalog,
    InMemoryJobRepository,
    InMemoryManifestRegistry,
    JobRepository,
    SQLiteJobRepository,
)
from dohaaudio.services import JobApplicationService
from dohaaudio.workers import ExecutionWorker


@dataclass(frozen=True)
class AudioRuntime:
    jobs: JobRepository
    artifacts: InMemoryArtifactCatalog
    artifact_resolver: ArtifactResolver
    manifests: InMemoryManifestRegistry
    providers: ProviderRegistry
    capabilities: CapabilityRegistry
    service: JobApplicationService
    worker: ExecutionWorker

    def create_job(self, request: CreateJobRequest) -> JobResponse:
        return self.service.create_job(request)

    def get_job(self, job_id: str) -> JobResponse:
        return self.service.get_job(job_id)

    def start_job(self, job_id: str) -> JobResponse:
        return self.service.start_job(job_id)

    def run_job(self, job_id: str) -> JobResponse:
        return self.service.run_job(job_id)

    def update_progress(self, job_id: str, progress_percent: int, stage: str) -> JobResponse:
        return self.service.update_progress(job_id, progress_percent, stage)

    def cancel_job(self, job_id: str) -> JobResponse:
        return self.service.cancel_job(job_id)

    def retry_job(self, job_id: str, request: RetryJobRequest) -> JobResponse:
        return self.service.retry_job(job_id, request)

    def get_result(self, job_id: str) -> ResultResponse:
        return self.service.get_result(job_id)

    def get_manifest(self, manifest_id: str) -> ModelManifest:
        return self.manifests.get(manifest_id)

    def get_capabilities(self, provider_id: str) -> CapabilityResponse:
        return self.service.get_capabilities(provider_id)

    def health(self, provider_id: str) -> HealthResponse:
        return self.service.health(provider_id)

    def readiness(self, provider_id: str) -> ReadinessResponse:
        return self.service.readiness(provider_id)

    def run_worker_once(self) -> JobResponse | None:
        return self.worker.run_once()

    def recover_stale_jobs(self) -> tuple[str, ...]:
        return self.worker.recover_stale()


def bootstrap_runtime(
    *,
    provider: FakeAudioProvider | None = None,
    jobs: JobRepository | None = None,
    artifact_resolver: ArtifactResolver | None = None,
) -> AudioRuntime:
    job_repository = jobs or InMemoryJobRepository()
    artifacts = InMemoryArtifactCatalog()
    resolver = artifact_resolver or InMemoryArtifactResolver()
    manifests = InMemoryManifestRegistry()
    providers = ProviderRegistry()
    providers.register(provider or FakeAudioProvider())
    capabilities = CapabilityRegistry(providers)
    manifests.register(fake_model_manifest())
    service = JobApplicationService(job_repository, artifacts, manifests, providers, capabilities)
    worker = ExecutionWorker(job_repository, service)
    return AudioRuntime(
        job_repository,
        artifacts,
        resolver,
        manifests,
        providers,
        capabilities,
        service,
        worker,
    )


def bootstrap_persistent_runtime(
    database_path: str | Path,
    *,
    provider: FakeAudioProvider | None = None,
) -> AudioRuntime:
    """Create a local SQLite runtime with an explicitly injected database location."""
    return bootstrap_runtime(provider=provider, jobs=SQLiteJobRepository(database_path))
