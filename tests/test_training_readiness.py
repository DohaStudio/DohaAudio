from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dohaaudio.datasets import (
    DatasetLicenseStatus,
    DatasetManifestRegistry,
    EvidenceReviewStatus,
    TrainingAllowed,
)
from dohaaudio.providers import fake_model_manifest
from dohaaudio.repositories import InMemoryManifestRegistry
from dohaaudio.training import ReadinessStatus, TrainingConfig, TrainingReadinessService
from tests.readiness_helpers import (
    NOW,
    seal_manifest,
    valid_dataset_manifest,
    valid_training_config,
)


def readiness_service(manifest=None) -> TrainingReadinessService:  # type: ignore[no-untyped-def]
    datasets = DatasetManifestRegistry()
    datasets.register(manifest or valid_dataset_manifest())
    models = InMemoryManifestRegistry()
    models.register(fake_model_manifest())
    return TrainingReadinessService(datasets, models)


def test_all_preflight_gates_pass_and_dry_run_is_side_effect_free() -> None:
    service = readiness_service()
    config = valid_training_config()
    report = service.validate_training_readiness(config, now=NOW)
    dry_run = service.dry_run(config, now=NOW)
    assert report.status == ReadinessStatus.READY
    assert report.pre_training_ready is True
    assert report.reasons == ()
    assert dry_run.planned_run is not None
    assert dry_run.planned_run.started_at is None
    assert dry_run.planned_run.optimizer_step == 0
    assert dry_run.planned_run.output_checkpoint_artifact_ids == ()
    assert (
        dry_run.database_mutations,
        dry_run.artifact_mutations,
        dry_run.dataset_reads,
        dry_run.model_loads,
        dry_run.optimizer_steps,
        dry_run.gpu_calls,
        dry_run.checkpoints_created,
    ) == (0, 0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"license_status": DatasetLicenseStatus.UNKNOWN}, "DATASET_LICENSE_NOT_APPROVED"),
        ({"license_status": DatasetLicenseStatus.REVIEW_REQUIRED}, "DATASET_LICENSE_NOT_APPROVED"),
        ({"training_allowed": TrainingAllowed.PENDING_REVIEW}, "DATASET_TRAINING_NOT_ALLOWED"),
        ({"training_allowed": TrainingAllowed.FALSE}, "DATASET_TRAINING_NOT_ALLOWED"),
        ({"rights_evidence": ()}, "RIGHTS_EVIDENCE_MISSING"),
    ],
)
def test_rights_and_eligibility_fail_closed(updates: dict[str, object], reason: str) -> None:
    manifest = seal_manifest(valid_dataset_manifest().model_copy(update=updates))
    report = readiness_service(manifest).validate_training_readiness(
        valid_training_config(), now=NOW
    )
    assert report.status == ReadinessStatus.BLOCKED
    assert report.pre_training_ready is False
    assert reason in report.reasons


def test_expired_and_unreviewed_evidence_are_blocked() -> None:
    manifest = valid_dataset_manifest()
    evidence = manifest.rights_evidence[0].model_copy(
        update={
            "review_status": EvidenceReviewStatus.REVIEW_REQUIRED,
            "expires_at": NOW - timedelta(seconds=1),
        }
    )
    changed = seal_manifest(manifest.model_copy(update={"rights_evidence": (evidence,)}))
    report = readiness_service(changed).validate_training_readiness(
        valid_training_config(), now=NOW
    )
    assert "RIGHTS_EVIDENCE_NOT_VERIFIED" in report.reasons
    assert "RIGHTS_EVIDENCE_EXPIRED" in report.reasons


def test_invalid_dataset_and_contract_mismatch_are_blocked() -> None:
    manifest = valid_dataset_manifest().model_copy(update={"manifest_checksum": "f" * 64})
    datasets = DatasetManifestRegistry()
    datasets.register(manifest)
    models = InMemoryManifestRegistry()
    incompatible = fake_model_manifest().model_copy(
        update={"model_manifest_id": "fake/incompatible", "api_contract_version": "2.0"}
    )
    models.register(incompatible)
    service = TrainingReadinessService(datasets, models)
    report = service.validate_training_readiness(
        valid_training_config(model_manifest_id=incompatible.model_manifest_id), now=NOW
    )
    assert report.status == ReadinessStatus.BLOCKED
    assert "DATASET_MANIFEST_CHECKSUM_MISMATCH" in report.reasons
    assert "MODEL_CONTRACT_VERSION_INCOMPATIBLE" in report.reasons


def test_invalid_training_config_and_output_policy_are_rejected() -> None:
    payload = valid_training_config().model_dump()
    payload["batch_size"] = 0
    with pytest.raises(ValidationError):
        TrainingConfig(**payload)
    payload = valid_training_config().model_dump()
    payload["checkpoint_policy"]["logical_target_uri"] = "C:\\checkpoints"
    with pytest.raises(ValidationError):
        TrainingConfig(**payload)


def test_training_config_fingerprint_is_canonical_and_immutable() -> None:
    config = valid_training_config()
    same = TrainingConfig(**config.model_dump())
    assert same.fingerprint() == config.fingerprint()
    with pytest.raises(ValidationError):
        config.batch_size = 2  # type: ignore[misc]
