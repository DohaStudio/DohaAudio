"""Composition root for the standalone fake provider runtime."""

from __future__ import annotations

from dataclasses import dataclass

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
)
from dohaaudio.services import JobApplicationService


@dataclass(frozen=True)
class AudioRuntime:
    jobs: InMemoryJobRepository
    artifacts: InMemoryArtifactCatalog
    manifests: InMemoryManifestRegistry
    providers: ProviderRegistry
    capabilities: CapabilityRegistry
    service: JobApplicationService

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


def bootstrap_runtime(*, provider: FakeAudioProvider | None = None) -> AudioRuntime:
    jobs = InMemoryJobRepository()
    artifacts = InMemoryArtifactCatalog()
    manifests = InMemoryManifestRegistry()
    providers = ProviderRegistry()
    providers.register(provider or FakeAudioProvider())
    capabilities = CapabilityRegistry(providers)
    manifests.register(fake_model_manifest())
    service = JobApplicationService(jobs, artifacts, manifests, providers, capabilities)
    return AudioRuntime(jobs, artifacts, manifests, providers, capabilities, service)
