from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dohaaudio.admission import (
    DatasetInventory,
    EnvironmentPreflight,
    InventoryItem,
    PreprocessingContract,
    TrainingAdmissionService,
    UsageRightsAdmission,
)
from dohaaudio.datasets import (
    DatasetLicenseStatus,
    DatasetManifestRegistry,
    EvidenceReviewStatus,
    TrainingAllowed,
)
from dohaaudio.errors import ContractError
from dohaaudio.providers import fake_model_manifest
from dohaaudio.repositories import InMemoryManifestRegistry
from dohaaudio.training import TrainingReadinessService
from tests.readiness_helpers import (
    NOW,
    seal_manifest,
    valid_dataset_manifest,
    valid_training_config,
)


def inventory() -> DatasetInventory:
    return DatasetInventory(
        authority_id="dohaaudio-local-audio-authority-v1",
        candidate_id="candidate-a",
        source_alias="local-authority/candidate-a",
        purpose="admission",
        discovered_file_count=1,
        supported_item_count=1,
        unsupported_file_count=0,
        total_size_bytes=4,
        unsupported_extensions=(),
        duplicate_relative_identity_count=0,
        duplicate_checksum_count=0,
        missing_checksum_count=0,
        items=(
            InventoryItem(
                sample_id="sample-a",
                source_key="source-a",
                media_type="audio/wav",
                size_bytes=4,
                checksum="a" * 64,
                provenance="local-authority/candidate-a",
            ),
        ),
    )


def inventory_for_manifest(manifest) -> DatasetInventory:  # type: ignore[no-untyped-def]
    return DatasetInventory(
        authority_id="dohaaudio-local-audio-authority-v1",
        candidate_id="synthetic-admitted-candidate",
        source_alias="fixture/admitted",
        purpose="contract-test",
        discovered_file_count=manifest.item_count,
        supported_item_count=manifest.item_count,
        unsupported_file_count=0,
        total_size_bytes=manifest.item_count,
        unsupported_extensions=(),
        duplicate_relative_identity_count=0,
        duplicate_checksum_count=0,
        missing_checksum_count=0,
        items=tuple(
            InventoryItem(
                sample_id=entry.sample_id,
                source_key=f"source-{index}",
                media_type=entry.media_type,
                size_bytes=1,
                checksum=entry.content_checksum,
                provenance=entry.provenance,
            )
            for index, entry in enumerate(manifest.entries)
        ),
    )


def test_actual_candidate_without_admitted_manifest_fails_closed() -> None:
    report = TrainingAdmissionService().assess(
        inventory=inventory(),
        authority_validated=True,
        usage_rights=None,
        manifest=None,
        config=None,
        model_selected=False,
        environment=None,
        readiness=None,
        checked_at=NOW,
    )
    assert report.dataset_authority_valid is True
    assert report.rights_gate_pass is False
    assert report.dataset_integrity_pass is False
    assert report.dataset_split_frozen is False
    assert report.model_selected is False
    assert report.training_config_valid is False
    assert report.environment_preflight_pass is False
    assert report.training_preflight_pass is False
    assert report.training_execution_ready is False
    assert report.training_approval_consumed is False
    assert "DATASET_MANIFEST_NOT_ADMITTED" in report.reasons
    assert "MODEL_SELECTION_BLOCKED" in report.reasons


@pytest.mark.parametrize(
    "manifest",
    [
        seal_manifest(
            valid_dataset_manifest().model_copy(
                update={"license_status": DatasetLicenseStatus.UNKNOWN}
            )
        ),
        seal_manifest(
            valid_dataset_manifest().model_copy(
                update={"license_status": DatasetLicenseStatus.REVIEW_REQUIRED}
            )
        ),
        seal_manifest(
            valid_dataset_manifest().model_copy(update={"training_allowed": TrainingAllowed.FALSE})
        ),
        seal_manifest(valid_dataset_manifest().model_copy(update={"rights_evidence": ()})),
    ],
)
def test_rights_states_remain_blocked(manifest) -> None:  # type: ignore[no-untyped-def]
    report = TrainingAdmissionService().assess(
        inventory=inventory(),
        authority_validated=True,
        usage_rights=None,
        manifest=manifest,
        config=None,
        model_selected=False,
        environment=None,
        readiness=None,
        checked_at=NOW,
    )
    assert report.rights_gate_pass is False
    assert "RIGHTS_GATE_BLOCKED" in report.reasons


def test_future_and_expired_evidence_remain_blocked() -> None:
    base = valid_dataset_manifest()
    for effective_at, expires_at in (
        (NOW + timedelta(seconds=1), NOW + timedelta(days=1)),
        (NOW - timedelta(days=1), NOW),
    ):
        evidence = base.rights_evidence[0].model_copy(
            update={
                "review_status": EvidenceReviewStatus.VERIFIED,
                "effective_at": effective_at,
                "expires_at": expires_at,
            }
        )
        manifest = seal_manifest(base.model_copy(update={"rights_evidence": (evidence,)}))
        report = TrainingAdmissionService().assess(
            inventory=inventory(),
            authority_validated=True,
            usage_rights=None,
            manifest=manifest,
            config=None,
            model_selected=False,
            environment=None,
            readiness=None,
            checked_at=NOW,
        )
        assert report.rights_gate_pass is False


def test_environment_snapshot_is_sanitized_and_does_not_imply_compatibility() -> None:
    environment = EnvironmentPreflight(
        python_version="3.12.5",
        gpu_model="test-gpu",
        vram_mib=8192,
        driver_version="test-driver",
        cuda_available=True,
        compatible=False,
        reasons=("MODEL_AND_CONFIG_NOT_SELECTED",),
    )
    report = TrainingAdmissionService().assess(
        inventory=inventory(),
        authority_validated=True,
        usage_rights=None,
        manifest=None,
        config=None,
        model_selected=False,
        environment=environment,
        readiness=None,
        checked_at=NOW,
    )
    assert report.environment_preflight_pass is False
    assert report.training_execution_ready is False


def test_all_admission_gates_still_require_separate_execution_approval() -> None:
    manifest = valid_dataset_manifest()
    admitted_inventory = inventory_for_manifest(manifest)
    datasets = DatasetManifestRegistry()
    datasets.register(manifest)
    models = InMemoryManifestRegistry()
    models.register(fake_model_manifest())
    config = valid_training_config()
    readiness = TrainingReadinessService(datasets, models).validate_training_readiness(
        config, now=NOW
    )
    environment = EnvironmentPreflight(
        python_version="test-python",
        gpu_model="test-gpu",
        vram_mib=1,
        driver_version="test-driver",
        cuda_available=True,
        compatible=True,
    )
    usage_rights = UsageRightsAdmission(
        candidate_id=admitted_inventory.candidate_id,
        dataset_manifest_id=manifest.dataset_manifest_id,
        evidence_ids=("evidence-test-v1",),
        scopes=("ai_training",),
        review_status=EvidenceReviewStatus.VERIFIED,
        effective_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
        dataset_possession_confirmed=True,
        dataset_access_authorized=True,
        ai_training_authorized=True,
        commercial_usage_authorized=False,
        redistribution_authorized=False,
        derived_model_distribution_authorized=False,
        generated_output_usage_authorized=False,
    )
    report = TrainingAdmissionService().assess(
        inventory=admitted_inventory,
        authority_validated=True,
        usage_rights=usage_rights,
        manifest=manifest,
        config=config,
        model_selected=True,
        environment=environment,
        readiness=readiness,
        checked_at=NOW,
        training_approval_consumed=False,
    )
    assert report.dataset_authority_valid is True
    assert report.rights_gate_pass is True
    assert report.dataset_integrity_pass is True
    assert report.dataset_split_frozen is True
    assert report.training_preflight_pass is True
    assert report.training_execution_ready is False
    assert report.reasons == ("TRAINING_APPROVAL_NOT_CONSUMED",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_id", "different-sample"),
        ("checksum", "f" * 64),
        ("media_type", "audio/flac"),
        ("provenance", "fixture/different-source"),
    ],
)
def test_inventory_manifest_membership_requires_exact_records(field: str, value: str) -> None:
    manifest = valid_dataset_manifest()
    candidate = inventory_for_manifest(manifest)
    mismatched = candidate.items[0].model_copy(update={field: value})
    candidate = candidate.model_copy(update={"items": (mismatched, *candidate.items[1:])})
    report = TrainingAdmissionService().assess(
        inventory=candidate,
        authority_validated=True,
        usage_rights=None,
        manifest=manifest,
        config=None,
        model_selected=False,
        environment=None,
        readiness=None,
        checked_at=NOW,
    )
    assert report.dataset_integrity_pass is False
    assert "DATASET_INVENTORY_MANIFEST_MISMATCH" in report.reasons


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_inventory_manifest_membership_rejects_missing_or_extra_member(change: str) -> None:
    manifest = valid_dataset_manifest()
    candidate = inventory_for_manifest(manifest)
    if change == "missing":
        items = candidate.items[:-1]
    else:
        items = (
            *candidate.items,
            candidate.items[0].model_copy(
                update={"sample_id": "extra-sample", "checksum": "f" * 64}
            ),
        )
    candidate = candidate.model_copy(
        update={
            "items": items,
            "supported_item_count": len(items),
            "discovered_file_count": len(items),
        }
    )
    report = TrainingAdmissionService().assess(
        inventory=candidate,
        authority_validated=True,
        usage_rights=None,
        manifest=manifest,
        config=None,
        model_selected=False,
        environment=None,
        readiness=None,
        checked_at=NOW,
    )
    assert report.dataset_integrity_pass is False
    assert "DATASET_INVENTORY_MANIFEST_MISMATCH" in report.reasons


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_id", "different-candidate"),
        ("dataset_manifest_id", "different-manifest"),
        ("evidence_ids", ("different-evidence",)),
        ("scopes", ("commercial_usage",)),
    ],
)
def test_usage_rights_must_match_candidate_manifest_evidence_and_scope(
    field: str, value: object
) -> None:
    manifest = valid_dataset_manifest()
    candidate = inventory().model_copy(update={"candidate_id": "candidate-a"})
    rights = UsageRightsAdmission(
        candidate_id=candidate.candidate_id,
        dataset_manifest_id=manifest.dataset_manifest_id,
        evidence_ids=("evidence-test-v1",),
        scopes=("ai_training",),
        review_status=EvidenceReviewStatus.VERIFIED,
        effective_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
        dataset_possession_confirmed=True,
        dataset_access_authorized=True,
        ai_training_authorized=True,
        commercial_usage_authorized=False,
        redistribution_authorized=False,
        derived_model_distribution_authorized=False,
        generated_output_usage_authorized=False,
    ).model_copy(update={field: value})
    report = TrainingAdmissionService().assess(
        inventory=candidate,
        authority_validated=True,
        usage_rights=rights,
        manifest=manifest,
        config=None,
        model_selected=False,
        environment=None,
        readiness=None,
        checked_at=NOW,
    )
    assert report.rights_gate_pass is False
    assert "RIGHTS_GATE_BLOCKED" in report.reasons


def test_preprocessing_contract_requires_explicit_path_free_policies() -> None:
    contract = PreprocessingContract(
        contract_version="fixture-v1",
        resampling="caller-defined",
        channel_handling="caller-defined",
        normalization="caller-defined",
        duration_policy="caller-defined",
        silence_policy="caller-defined",
        invalid_or_corrupt_file_policy="fail-closed",
    )
    assert contract.invalid_or_corrupt_file_policy == "fail-closed"
    payload = contract.model_dump()
    payload.pop("resampling")
    with pytest.raises(ValidationError):
        PreprocessingContract(**payload)
    with pytest.raises(ContractError) as path_error:
        PreprocessingContract(
            **contract.model_dump(exclude={"normalization"}),
            normalization="C:\\private\\normalization",
        )
    assert getattr(path_error.value, "error_code", None) == "ABSOLUTE_PATH_FORBIDDEN"
