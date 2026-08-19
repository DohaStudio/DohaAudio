"""Provider, Job, Artifact, and Model Manifest contract models."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_CONTRACT_VERSION = "1.0"
PROVIDER_ID = "audio"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def utc_now() -> datetime:
    return datetime.now(UTC)


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Capability(StrEnum):
    MUSIC_GENERATION = "music_generation"
    STEM_SEPARATION = "stem_separation"
    AUDIO_ANALYSIS = "audio_analysis"


class JobType(StrEnum):
    MUSIC_GENERATION = "MusicGenerationJob"
    STEM_SEPARATION = "StemSeparationJob"
    AUDIO_ANALYSIS = "AudioAnalysisJob"


CAPABILITY_JOB_TYPES = {
    Capability.MUSIC_GENERATION: JobType.MUSIC_GENERATION,
    Capability.STEM_SEPARATION: JobType.STEM_SEPARATION,
    Capability.AUDIO_ANALYSIS: JobType.AUDIO_ANALYSIS,
}


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


class ReviewStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RetentionStatus(StrEnum):
    ACTIVE = "active"
    RETAINED = "retained"


class StructuredError(FrozenModel):
    error_code: str
    message: str
    retryable: bool
    stage: str
    details_id: str | None = None


class CreateJobRequest(FrozenModel):
    job_id: str | None = None
    provider_id: str = PROVIDER_ID
    capability: Capability
    api_contract_version: str = API_CONTRACT_VERSION
    idempotency_key: str = Field(min_length=1, max_length=200)
    project_id: str | None = None
    input_asset_version_ids: tuple[str, ...] = ()
    input_artifact_ids: tuple[str, ...] = ()
    model_manifest_id: str
    settings_snapshot: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None

    @field_validator(
        "job_id",
        "project_id",
        "model_manifest_id",
        "requested_by",
        mode="before",
    )
    @classmethod
    def reject_blank_identifiers(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise ValueError("identifier must not be blank")
        return value


class RetryJobRequest(FrozenModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    job_id: str | None = None


class ArtifactMetadata(FrozenModel):
    artifact_id: str
    artifact_kind: str
    media_type: str
    size_bytes: int = Field(ge=0)
    checksum_algorithm: str
    artifact_checksum: str
    producer_type: str
    producer_id: str
    run_id: str | None
    created_at: datetime
    retention_status: RetentionStatus
    logical_uri: str
    source_artifact_ids: tuple[str, ...] = ()
    parent_artifact_ids: tuple[str, ...] = ()

    @field_validator("checksum_algorithm")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if value != "sha256":
            raise ValueError("checksum_algorithm must be sha256")
        return value

    @field_validator("artifact_checksum")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("artifact_checksum must be a lowercase sha256 digest")
        return value

    @field_validator("logical_uri")
    @classmethod
    def validate_logical_uri(cls, value: str) -> str:
        if not value.startswith("artifact://audio/"):
            raise ValueError("logical_uri must use the artifact://audio/ namespace")
        return value


class ModelManifest(FrozenModel):
    model_manifest_id: str
    provider_id: str
    model_id: str
    model_version: str
    checkpoint_version: str
    model_type: str
    capabilities: tuple[Capability, ...]
    input_formats: tuple[str, ...]
    output_formats: tuple[str, ...]
    api_contract_version: str
    dataset_manifest_id: str | None
    training_run_id: str | None
    evaluation_result_id: str | None
    license_status: ReviewStatus
    commercial_usage_status: ReviewStatus
    recommended_vram: str | None
    runtime_environment: dict[str, str]
    artifact_checksum: str
    created_at: datetime

    @field_validator("artifact_checksum")
    @classmethod
    def validate_artifact_checksum(cls, value: str) -> str:
        if not MANIFEST_CHECKSUM_PATTERN.fullmatch(value):
            raise ValueError("artifact_checksum must use sha256:<digest>")
        return value

    @model_validator(mode="after")
    def reject_unverified_vram_claim(self) -> ModelManifest:
        if self.model_id.startswith("fake/") and self.recommended_vram is not None:
            raise ValueError("fake pre-training manifests must not claim measured VRAM")
        return self


class JobRecord(FrozenModel):
    job_id: str
    job_type: JobType
    capability: Capability
    status: JobStatus
    progress_percent: int = Field(ge=0, le=100)
    stage: str
    provider_id: str
    api_contract_version: str
    idempotency_key: str
    request_fingerprint: str
    project_id: str | None
    input_asset_version_ids: tuple[str, ...]
    input_artifact_ids: tuple[str, ...]
    output_artifact_ids: tuple[str, ...] = ()
    model_manifest_id: str
    settings_snapshot: dict[str, Any]
    requested_by: str | None
    retry_of_job_id: str | None = None
    attempt: int = Field(default=1, ge=1)
    error: StructuredError | None = None
    result_metadata: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    claim_token: str | None = None
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    recovery_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_terminal_record(self) -> JobRecord:
        if self.status in TERMINAL_STATUSES and self.completed_at is None:
            raise ValueError("terminal jobs require completed_at")
        if self.status == JobStatus.SUCCEEDED and self.progress_percent != 100:
            raise ValueError("succeeded jobs require 100 percent progress")
        return self


class JobResponse(FrozenModel):
    job_id: str
    job_type: JobType
    status: JobStatus
    progress_percent: int
    stage: str
    provider_id: str
    api_contract_version: str
    model_manifest_id: str
    output_artifact_ids: tuple[str, ...]
    retry_of_job_id: str | None
    attempt: int
    error: StructuredError | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_record(cls, record: JobRecord) -> JobResponse:
        return cls(
            **record.model_dump(
                exclude={
                    "settings_snapshot",
                    "request_fingerprint",
                    "idempotency_key",
                    "capability",
                    "project_id",
                    "input_asset_version_ids",
                    "input_artifact_ids",
                    "requested_by",
                    "result_metadata",
                    "claim_token",
                    "claimed_by",
                    "lease_expires_at",
                    "heartbeat_at",
                    "recovery_count",
                }
            )
        )


class ResultResponse(FrozenModel):
    job_id: str
    status: JobStatus
    provider_id: str
    api_contract_version: str
    output_artifact_ids: tuple[str, ...]
    artifacts: tuple[ArtifactMetadata, ...]
    version_metadata: dict[str, Any]
    model_manifest_id: str
    result_metadata: dict[str, Any] | None


class CapabilityResponse(FrozenModel):
    provider_id: str
    api_contract_versions: tuple[str, ...]
    capabilities: tuple[Capability, ...]
    input_formats: tuple[str, ...]
    output_formats: tuple[str, ...]
    model_manifest_ids: tuple[str, ...]
    ready: bool


class HealthResponse(FrozenModel):
    provider_id: str
    status: str


class ReadinessResponse(FrozenModel):
    provider_id: str
    ready: bool
    reason: str | None = None
