from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dohaaudio.datasets import (
    CommercialUsageStatus,
    DatasetEntry,
    DatasetLicenseStatus,
    DatasetManifest,
    DatasetSplit,
    EvidenceReviewStatus,
    RightsEvidence,
    TrainingAllowed,
    canonical_dataset_checksum,
)
from dohaaudio.providers import FAKE_MANIFEST_ID
from dohaaudio.training import (
    CheckpointPolicy,
    EvaluationCadence,
    Precision,
    ResourceConstraints,
    TrainingConfig,
)

NOW = datetime(2026, 8, 19, tzinfo=UTC)


def seal_manifest(manifest: DatasetManifest) -> DatasetManifest:
    return manifest.model_copy(update={"manifest_checksum": canonical_dataset_checksum(manifest)})


def valid_dataset_manifest(**updates: object) -> DatasetManifest:
    entries = (
        DatasetEntry(
            sample_id="sample-001",
            content_checksum="1" * 64,
            media_type="audio/wav",
            provenance="fixture/source-a",
        ),
        DatasetEntry(
            sample_id="sample-002",
            content_checksum="2" * 64,
            media_type="audio/flac",
            provenance="fixture/source-b",
        ),
        DatasetEntry(
            sample_id="sample-003",
            content_checksum="3" * 64,
            media_type="audio/mpeg",
            provenance="fixture/source-c",
        ),
    )
    values: dict[str, object] = {
        "dataset_manifest_id": "dataset-manifest/audio/test/v1",
        "dataset_id": "dataset/audio/test",
        "dataset_version": "1.0.0",
        "source": "fixture/approved-source",
        "license_status": DatasetLicenseStatus.APPROVED,
        "training_allowed": TrainingAllowed.TRUE,
        "commercial_usage_status": CommercialUsageStatus.REVIEW_PENDING,
        "redistribution_allowed": TrainingAllowed.PENDING_REVIEW,
        "item_count": 3,
        "manifest_checksum": "0" * 64,
        "content_checksum_set_id": "checksum-set-test-v1",
        "split_id": "split-test-v1",
        "created_at": NOW,
        "entries": entries,
        "split": DatasetSplit(
            split_id="split-test-v1",
            train=("sample-001",),
            validation=("sample-002",),
            test=("sample-003",),
            algorithm_version="fixture-split-v1",
            seed=17,
        ),
        "rights_evidence": (
            RightsEvidence(
                source="fixture/review",
                evidence_id="evidence-test-v1",
                review_status=EvidenceReviewStatus.VERIFIED,
                effective_at=NOW - timedelta(days=1),
                expires_at=NOW + timedelta(days=30),
            ),
        ),
        "normalization_settings": {"profile": "fixture-only-v1"},
    }
    values.update(updates)
    return seal_manifest(DatasetManifest(**values))


def valid_training_config(**updates: object) -> TrainingConfig:
    values: dict[str, object] = {
        "config_version": "1.0.0",
        "model_manifest_id": FAKE_MANIFEST_ID,
        "dataset_manifest_id": "dataset-manifest/audio/test/v1",
        "batch_size": 1,
        "learning_rate": 0.0001,
        "max_steps": 10,
        "seed": 17,
        "precision": Precision.FP32,
        "checkpoint_policy": CheckpointPolicy(
            logical_target_uri="artifact://audio/checkpoints/planned-test",
            save_every_steps=5,
            max_to_keep=1,
        ),
        "evaluation_cadence": EvaluationCadence(every_steps=5),
        "resource_constraints": ResourceConstraints(),
    }
    values.update(updates)
    return TrainingConfig(**values)
