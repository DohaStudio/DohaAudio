"""Application service for Provider Job lifecycle and result registration."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from dohaaudio.contracts import (
    API_CONTRACT_VERSION,
    CAPABILITY_JOB_TYPES,
    PROVIDER_ID,
    TERMINAL_STATUSES,
    CapabilityResponse,
    CreateJobRequest,
    HealthResponse,
    JobRecord,
    JobResponse,
    JobStatus,
    ReadinessResponse,
    ResultResponse,
    RetryJobRequest,
    StructuredError,
    utc_now,
)
from dohaaudio.errors import ConflictError, ContractError
from dohaaudio.providers import CapabilityRegistry, ProviderRegistry
from dohaaudio.repositories import (
    InMemoryArtifactCatalog,
    InMemoryManifestRegistry,
    JobRepository,
)
from dohaaudio.security import assert_safe_metadata


def _canonical_fingerprint(request: CreateJobRequest, *, retry_of: str | None = None) -> str:
    canonical = request.model_dump(mode="json")
    canonical.pop("idempotency_key", None)
    if retry_of is not None:
        canonical["retry_of_job_id"] = retry_of
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


class JobApplicationService:
    def __init__(
        self,
        jobs: JobRepository,
        artifacts: InMemoryArtifactCatalog,
        manifests: InMemoryManifestRegistry,
        providers: ProviderRegistry,
        capabilities: CapabilityRegistry,
    ) -> None:
        self.jobs = jobs
        self.artifacts = artifacts
        self.manifests = manifests
        self.providers = providers
        self.capabilities = capabilities

    def create_job(self, request: CreateJobRequest) -> JobResponse:
        self._validate_request_metadata(request)
        fingerprint = _canonical_fingerprint(request)
        replay = self.jobs.idempotent_job(request.idempotency_key, fingerprint)
        if replay is not None:
            return JobResponse.from_record(replay)
        self._validate_new_job(request)
        record = self._new_record(request, fingerprint=fingerprint)
        persisted = self.jobs.add(record)
        return JobResponse.from_record(persisted)

    def get_job(self, job_id: str) -> JobResponse:
        return JobResponse.from_record(self.jobs.get(job_id))

    def start_job(self, job_id: str) -> JobResponse:
        record = self.jobs.get(job_id)
        updated = self._transition(
            record,
            JobStatus.RUNNING,
            progress_percent=max(record.progress_percent, 1),
            stage="executing",
            started_at=record.started_at or utc_now(),
        )
        self.jobs.replace(updated)
        return JobResponse.from_record(updated)

    def run_job(self, job_id: str) -> JobResponse:
        record = self.jobs.get(job_id)
        if record.status == JobStatus.QUEUED:
            self.start_job(job_id)
            record = self.jobs.get(job_id)
        if record.status != JobStatus.RUNNING:
            raise ConflictError("JOB_NOT_RUNNABLE", "running 상태의 Job만 실행할 수 있습니다.")
        provider = self.providers.get(record.provider_id)
        try:
            execution = provider.execute(record)
            artifact_ids = [
                artifact.artifact_id
                for artifact in self.artifacts.register_many(execution.artifacts)
            ]
            updated = self._transition(
                record,
                JobStatus.SUCCEEDED,
                progress_percent=100,
                stage="completed",
                output_artifact_ids=tuple(artifact_ids),
                result_metadata=deepcopy(execution.result_metadata),
                completed_at=utc_now(),
            )
        except ContractError as exc:
            updated = self._failed(record, exc.error_code, exc.message, retryable=True)
        except Exception:
            updated = self._failed(
                record,
                "PROVIDER_EXECUTION_FAILED",
                "Provider 실행 중 안전하게 공개할 수 없는 오류가 발생했습니다.",
                retryable=False,
            )
        self.jobs.replace(updated)
        return JobResponse.from_record(updated)

    def execute_claimed(self, job_id: str, claim_token: str) -> JobResponse:
        """Execute exactly one active worker claim and observe concurrent cancellation."""
        record = self.jobs.get(job_id)
        if record.status != JobStatus.RUNNING or record.claim_token != claim_token:
            raise ConflictError("WORKER_CLAIM_LOST", "Worker claim이 더 이상 유효하지 않습니다.")
        provider = self.providers.get(record.provider_id)
        try:
            execution = provider.execute(record)
            current = self.jobs.get(job_id)
            if current.status == JobStatus.CANCELLED:
                return JobResponse.from_record(current)
            if current.claim_token != claim_token:
                raise ConflictError(
                    "WORKER_CLAIM_LOST", "Worker claim이 더 이상 유효하지 않습니다."
                )
            artifacts = self.artifacts.register_many(execution.artifacts)
            updated = self._transition(
                current,
                JobStatus.SUCCEEDED,
                progress_percent=100,
                stage="completed",
                output_artifact_ids=tuple(item.artifact_id for item in artifacts),
                result_metadata=deepcopy(execution.result_metadata),
                completed_at=utc_now(),
                claim_token=None,
                claimed_by=None,
                lease_expires_at=None,
                heartbeat_at=None,
            )
        except ConflictError as exc:
            if exc.error_code == "WORKER_CLAIM_LOST":
                raise
            current = self.jobs.get(job_id)
            if current.status == JobStatus.CANCELLED:
                return JobResponse.from_record(current)
            updated = self._clear_claim(
                self._failed(current, exc.error_code, exc.message, retryable=True)
            )
        except ContractError as exc:
            current = self.jobs.get(job_id)
            if current.status == JobStatus.CANCELLED:
                return JobResponse.from_record(current)
            updated = self._clear_claim(
                self._failed(current, exc.error_code, exc.message, retryable=True)
            )
        except Exception:
            current = self.jobs.get(job_id)
            if current.status == JobStatus.CANCELLED:
                return JobResponse.from_record(current)
            updated = self._clear_claim(
                self._failed(
                    current,
                    "PROVIDER_EXECUTION_FAILED",
                    "Provider 실행 중 안전하게 공개할 수 없는 오류가 발생했습니다.",
                    retryable=False,
                )
            )
        self.jobs.replace_claimed(updated, claim_token)
        return JobResponse.from_record(updated)

    def update_progress(self, job_id: str, progress_percent: int, stage: str) -> JobResponse:
        record = self.jobs.get(job_id)
        if record.status != JobStatus.RUNNING:
            raise ConflictError(
                "JOB_PROGRESS_INVALID", "running 상태의 Job만 진행률을 갱신할 수 있습니다."
            )
        if not 0 <= progress_percent <= 100:
            raise ContractError("JOB_PROGRESS_INVALID", "진행률은 0부터 100 사이여야 합니다.")
        if progress_percent < record.progress_percent:
            raise ConflictError("JOB_PROGRESS_INVALID", "진행률은 감소할 수 없습니다.")
        updated = record.model_copy(
            update={"progress_percent": progress_percent, "stage": stage}, deep=True
        )
        self.jobs.replace(updated)
        return JobResponse.from_record(updated)

    def cancel_job(self, job_id: str) -> JobResponse:
        record = self.jobs.get(job_id)
        if record.status in TERMINAL_STATUSES:
            raise ConflictError("JOB_TERMINAL", "종료 상태의 Job은 취소할 수 없습니다.")
        updated = self._transition(
            record,
            JobStatus.CANCELLED,
            stage="cancelled",
            completed_at=utc_now(),
            claim_token=None,
            claimed_by=None,
            lease_expires_at=None,
            heartbeat_at=None,
        )
        self.jobs.replace(updated)
        return JobResponse.from_record(updated)

    def retry_job(self, job_id: str, request: RetryJobRequest) -> JobResponse:
        original = self.jobs.get(job_id)
        if original.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            raise ConflictError(
                "JOB_NOT_RETRYABLE",
                "failed 또는 cancelled Job만 새 Job으로 재시도할 수 있습니다.",
            )
        retry_request = CreateJobRequest(
            job_id=request.job_id,
            provider_id=original.provider_id,
            capability=original.capability,
            api_contract_version=original.api_contract_version,
            idempotency_key=request.idempotency_key,
            project_id=original.project_id,
            input_asset_version_ids=original.input_asset_version_ids,
            input_artifact_ids=original.input_artifact_ids,
            model_manifest_id=original.model_manifest_id,
            settings_snapshot=deepcopy(original.settings_snapshot),
            requested_by=original.requested_by,
        )
        fingerprint = _canonical_fingerprint(retry_request, retry_of=original.job_id)
        replay = self.jobs.idempotent_job(request.idempotency_key, fingerprint)
        if replay is not None:
            return JobResponse.from_record(replay)
        record = self._new_record(
            retry_request,
            fingerprint=fingerprint,
            retry_of_job_id=original.job_id,
            attempt=original.attempt + 1,
        )
        persisted = self.jobs.add(record)
        return JobResponse.from_record(persisted)

    def get_result(self, job_id: str) -> ResultResponse:
        record = self.jobs.get(job_id)
        if record.status != JobStatus.SUCCEEDED:
            raise ConflictError("RESULT_NOT_AVAILABLE", "성공한 Job만 결과를 조회할 수 있습니다.")
        artifacts = tuple(self.artifacts.get(item) for item in record.output_artifact_ids)
        return ResultResponse(
            job_id=record.job_id,
            status=record.status,
            provider_id=record.provider_id,
            api_contract_version=record.api_contract_version,
            output_artifact_ids=record.output_artifact_ids,
            artifacts=artifacts,
            version_metadata={
                "version_origin": "ai_generated",
                "source_asset_version_ids": record.input_asset_version_ids,
                "processing_chain_id": None,
                "settings_snapshot": deepcopy(record.settings_snapshot),
            },
            model_manifest_id=record.model_manifest_id,
            result_metadata=deepcopy(record.result_metadata),
        )

    def get_capabilities(self, provider_id: str) -> CapabilityResponse:
        provider = self.providers.get(provider_id)
        return CapabilityResponse(
            provider_id=provider.provider_id,
            api_contract_versions=(API_CONTRACT_VERSION,),
            capabilities=provider.capabilities(),
            input_formats=provider.input_formats(),
            output_formats=provider.output_formats(),
            model_manifest_ids=self.manifests.ids(),
            ready=provider.readiness(),
        )

    def health(self, provider_id: str) -> HealthResponse:
        provider = self.providers.get(provider_id)
        return HealthResponse(
            provider_id=provider.provider_id,
            status="alive" if provider.health() else "unhealthy",
        )

    def readiness(self, provider_id: str) -> ReadinessResponse:
        provider = self.providers.get(provider_id)
        ready = provider.readiness() and bool(self.manifests.ids())
        return ReadinessResponse(
            provider_id=provider.provider_id,
            ready=ready,
            reason=None if ready else "provider_or_manifest_not_ready",
        )

    def _validate_request_metadata(self, request: CreateJobRequest) -> None:
        assert_safe_metadata(request.model_dump(mode="python"))
        if request.provider_id != PROVIDER_ID:
            raise ContractError("PROVIDER_MISMATCH", "요청 Provider가 DohaAudio가 아닙니다.")
        if request.api_contract_version != API_CONTRACT_VERSION:
            raise ConflictError(
                "PROVIDER_CONTRACT_VERSION_UNSUPPORTED",
                "지원하지 않는 Provider contract version입니다.",
            )

    def _validate_new_job(self, request: CreateJobRequest) -> None:
        provider = self.providers.get(request.provider_id)
        if not provider.readiness():
            raise ContractError(
                "PROVIDER_NOT_READY",
                "Provider가 새 Job을 수락할 준비가 되지 않았습니다.",
                status_code=503,
            )
        if not self.capabilities.supports(request.provider_id, request.capability):
            raise ContractError("CAPABILITY_UNSUPPORTED", "지원하지 않는 capability입니다.")
        manifest = self.manifests.get(request.model_manifest_id)
        if (
            manifest.provider_id != request.provider_id
            or request.capability not in manifest.capabilities
        ):
            raise ConflictError(
                "MODEL_MANIFEST_INCOMPATIBLE",
                "Model Manifest가 요청 Provider 또는 capability와 호환되지 않습니다.",
            )
        if manifest.api_contract_version != request.api_contract_version:
            raise ConflictError(
                "MODEL_MANIFEST_INCOMPATIBLE",
                "Model Manifest의 contract version이 요청과 다릅니다.",
            )

    def _new_record(
        self,
        request: CreateJobRequest,
        *,
        fingerprint: str,
        retry_of_job_id: str | None = None,
        attempt: int = 1,
    ) -> JobRecord:
        return JobRecord(
            job_id=request.job_id or f"job_{uuid4().hex}",
            job_type=CAPABILITY_JOB_TYPES[request.capability],
            capability=request.capability,
            status=JobStatus.QUEUED,
            progress_percent=0,
            stage="queued",
            provider_id=request.provider_id,
            api_contract_version=request.api_contract_version,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            project_id=request.project_id,
            input_asset_version_ids=request.input_asset_version_ids,
            input_artifact_ids=request.input_artifact_ids,
            model_manifest_id=request.model_manifest_id,
            settings_snapshot=deepcopy(request.settings_snapshot),
            requested_by=request.requested_by,
            retry_of_job_id=retry_of_job_id,
            attempt=attempt,
            created_at=utc_now(),
        )

    def _transition(self, record: JobRecord, status: JobStatus, **changes: Any) -> JobRecord:
        allowed = {
            JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
            JobStatus.RUNNING: {
                JobStatus.SUCCEEDED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            },
        }
        if status not in allowed.get(record.status, set()):
            raise ConflictError(
                "JOB_STATE_TRANSITION_INVALID",
                f"{record.status}에서 {status}(으)로 전이할 수 없습니다.",
            )
        progress = changes.get("progress_percent", record.progress_percent)
        if progress < record.progress_percent:
            raise ConflictError("JOB_PROGRESS_INVALID", "진행률은 감소할 수 없습니다.")
        return record.model_copy(update={"status": status, **changes}, deep=True)

    def _failed(
        self,
        record: JobRecord,
        error_code: str,
        message: str,
        *,
        retryable: bool,
    ) -> JobRecord:
        return self._transition(
            record,
            JobStatus.FAILED,
            stage="failed",
            error=StructuredError(
                error_code=error_code,
                message=message,
                retryable=retryable,
                stage=record.stage,
            ),
            completed_at=utc_now(),
        )

    @staticmethod
    def _clear_claim(record: JobRecord) -> JobRecord:
        return record.model_copy(
            update={
                "claim_token": None,
                "claimed_by": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
            },
            deep=True,
        )
