"""Fail-closed training contracts, preflight validation, and read-only dry-run."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from dohaaudio.contracts import (
    API_CONTRACT_VERSION,
    PROVIDER_ID,
    FrozenModel,
    ModelManifest,
    StructuredError,
    utc_now,
)
from dohaaudio.datasets import (
    DatasetLicenseStatus,
    DatasetManifest,
    DatasetManifestRegistry,
    DeletionStatus,
    EvidenceReviewStatus,
    TrainingAllowed,
    validate_dataset_manifest,
)
from dohaaudio.errors import ContractError
from dohaaudio.repositories import InMemoryManifestRegistry
from dohaaudio.security import assert_safe_metadata


class Precision(StrEnum):
    FP32 = "fp32"
    FP16 = "fp16"
    BF16 = "bf16"


class TrainingRunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReadinessStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class CheckpointPolicy(FrozenModel):
    logical_target_uri: str
    save_every_steps: int = Field(gt=0)
    max_to_keep: int = Field(gt=0)

    @field_validator("logical_target_uri")
    @classmethod
    def require_logical_uri(cls, value: str) -> str:
        if not value.startswith("artifact://audio/"):
            raise ValueError("checkpoint target must use artifact://audio/")
        return value


class EvaluationCadence(FrozenModel):
    every_steps: int = Field(gt=0)
    evaluation_split: str = "validation"

    @field_validator("evaluation_split")
    @classmethod
    def require_evaluation_split(cls, value: str) -> str:
        if value not in {"validation", "test"}:
            raise ValueError("evaluation split must be validation or test")
        return value


class ResourceConstraints(FrozenModel):
    resource_class: str | None = None
    max_vram_gb: float | None = Field(default=None, gt=0)


class TrainingConfig(FrozenModel):
    config_version: str = Field(min_length=1)
    model_manifest_id: str = Field(min_length=1)
    dataset_manifest_id: str = Field(min_length=1)
    batch_size: int = Field(gt=0)
    learning_rate: float = Field(gt=0)
    max_epochs: int | None = Field(default=None, gt=0)
    max_steps: int | None = Field(default=None, gt=0)
    seed: int
    precision: Precision
    checkpoint_policy: CheckpointPolicy
    evaluation_cadence: EvaluationCadence
    resource_constraints: ResourceConstraints

    @model_validator(mode="after")
    def require_one_training_limit(self) -> TrainingConfig:
        if (self.max_epochs is None) == (self.max_steps is None):
            raise ValueError("exactly one of max_epochs or max_steps is required")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self

    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class TrainingRun(FrozenModel):
    training_run_id: str
    dataset_manifest_id: str
    dataset_version: str
    model_manifest_id: str
    config_snapshot: TrainingConfig
    config_fingerprint: str
    seed: int
    status: TrainingRunStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_checkpoint_artifact_ids: tuple[str, ...] = ()
    error: StructuredError | None = None
    optimizer_step: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_pre_training_state(self) -> TrainingRun:
        if self.status == TrainingRunStatus.PLANNED:
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError("planned training run cannot have execution timestamps")
            if self.optimizer_step != 0 or self.output_checkpoint_artifact_ids:
                raise ValueError("planned training run cannot have execution outputs")
        return self


class TrainingReadinessReport(FrozenModel):
    status: ReadinessStatus
    pre_training_ready: bool
    reasons: tuple[str, ...]
    dataset_manifest_id: str
    model_manifest_id: str
    config_fingerprint: str
    checked_at: datetime


class TrainingDryRunResult(FrozenModel):
    readiness: TrainingReadinessReport
    planned_run: TrainingRun | None
    database_mutations: int = 0
    artifact_mutations: int = 0
    dataset_reads: int = 0
    model_loads: int = 0
    optimizer_steps: int = 0
    gpu_calls: int = 0
    checkpoints_created: int = 0


class TrainingReadinessService:
    def __init__(
        self,
        datasets: DatasetManifestRegistry,
        models: InMemoryManifestRegistry,
    ) -> None:
        self._datasets = datasets
        self._models = models

    def validate_training_readiness(
        self, config: TrainingConfig, *, now: datetime | None = None
    ) -> TrainingReadinessReport:
        checked_at = now or utc_now()
        reasons: list[str] = []
        dataset: DatasetManifest | None = None
        model: ModelManifest | None = None
        try:
            dataset = self._datasets.get(config.dataset_manifest_id)
        except ContractError:
            reasons.append("DATASET_MANIFEST_NOT_FOUND")
        try:
            model = self._models.get(config.model_manifest_id)
        except ContractError:
            reasons.append("MODEL_MANIFEST_NOT_FOUND")
        if dataset is not None:
            reasons.extend(validate_dataset_manifest(dataset))
            reasons.extend(self._rights_reasons(dataset, checked_at))
        if model is not None:
            if model.provider_id != PROVIDER_ID:
                reasons.append("MODEL_PROVIDER_INCOMPATIBLE")
            if model.api_contract_version != API_CONTRACT_VERSION:
                reasons.append("MODEL_CONTRACT_VERSION_INCOMPATIBLE")
            if not model.capabilities:
                reasons.append("MODEL_CAPABILITY_MISSING")
        unique_reasons = tuple(dict.fromkeys(reasons))
        return TrainingReadinessReport(
            status=ReadinessStatus.BLOCKED if unique_reasons else ReadinessStatus.READY,
            pre_training_ready=not unique_reasons,
            reasons=unique_reasons,
            dataset_manifest_id=config.dataset_manifest_id,
            model_manifest_id=config.model_manifest_id,
            config_fingerprint=config.fingerprint(),
            checked_at=checked_at,
        )

    @staticmethod
    def _rights_reasons(manifest: DatasetManifest, now: datetime) -> tuple[str, ...]:
        reasons = []
        if manifest.license_status != DatasetLicenseStatus.APPROVED:
            reasons.append("DATASET_LICENSE_NOT_APPROVED")
        if manifest.training_allowed != TrainingAllowed.TRUE:
            reasons.append("DATASET_TRAINING_NOT_ALLOWED")
        if manifest.deletion_status != DeletionStatus.ACTIVE:
            reasons.append("DATASET_NOT_ACTIVE")
        if not manifest.rights_evidence:
            reasons.append("RIGHTS_EVIDENCE_MISSING")
        for evidence in manifest.rights_evidence:
            if evidence.review_status != EvidenceReviewStatus.VERIFIED:
                reasons.append("RIGHTS_EVIDENCE_NOT_VERIFIED")
            if evidence.effective_at > now:
                reasons.append("RIGHTS_EVIDENCE_NOT_EFFECTIVE")
            if evidence.expires_at is not None and evidence.expires_at <= now:
                reasons.append("RIGHTS_EVIDENCE_EXPIRED")
        return tuple(reasons)

    def dry_run(
        self, config: TrainingConfig, *, now: datetime | None = None
    ) -> TrainingDryRunResult:
        report = self.validate_training_readiness(config, now=now)
        if report.status == ReadinessStatus.BLOCKED:
            return TrainingDryRunResult(readiness=report, planned_run=None)
        dataset = self._datasets.get(config.dataset_manifest_id)
        fingerprint = config.fingerprint()
        planned_run = TrainingRun(
            training_run_id=f"dryrun_{fingerprint[:24]}",
            dataset_manifest_id=dataset.dataset_manifest_id,
            dataset_version=dataset.dataset_version,
            model_manifest_id=config.model_manifest_id,
            config_snapshot=config,
            config_fingerprint=fingerprint,
            seed=config.seed,
            status=TrainingRunStatus.PLANNED,
            created_at=report.checked_at,
        )
        return TrainingDryRunResult(readiness=report, planned_run=planned_run)
