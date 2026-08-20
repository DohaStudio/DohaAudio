from __future__ import annotations

from datetime import timedelta

import pytest

from dohaaudio.admission import DatasetInventory, InventoryItem
from dohaaudio.datasets import (
    CommercialUsageStatus,
    DatasetLicenseStatus,
    DatasetManifestRegistry,
    EvidenceReviewStatus,
    TrainingAllowed,
)
from dohaaudio.enrollment import (
    DatasetEnrollmentProposal,
    DatasetEnrollmentService,
    NormalizedRightsEvidence,
    RightsDecision,
    RightsScope,
    RightsScopeDecision,
    SanitizedMappingRightsEvidenceAdapter,
    deterministic_dataset_split,
)
from dohaaudio.errors import ConflictError, ContractError
from tests.readiness_helpers import NOW


def candidate_inventory(*, first_checksum: str = "1" * 64) -> DatasetInventory:
    items = (
        InventoryItem(
            sample_id="sample-001",
            source_key="source-001",
            media_type="audio/wav",
            size_bytes=1,
            checksum=first_checksum,
            provenance="fixture/source-a",
        ),
        InventoryItem(
            sample_id="sample-002",
            source_key="source-002",
            media_type="audio/flac",
            size_bytes=1,
            checksum="2" * 64,
            provenance="fixture/source-b",
        ),
        InventoryItem(
            sample_id="sample-003",
            source_key="source-003",
            media_type="audio/mpeg",
            size_bytes=1,
            checksum="3" * 64,
            provenance="fixture/source-c",
        ),
    )
    return DatasetInventory(
        authority_id="dohaaudio-local-audio-authority-v1",
        candidate_id="candidate-approved-fixture",
        source_alias="fixture/authority",
        purpose="enrollment-contract-test",
        discovered_file_count=3,
        supported_item_count=3,
        unsupported_file_count=0,
        total_size_bytes=3,
        unsupported_extensions=(),
        duplicate_relative_identity_count=0,
        duplicate_checksum_count=0,
        missing_checksum_count=0,
        items=items,
    )


def enrollment_proposal(**updates: object) -> DatasetEnrollmentProposal:
    values: dict[str, object] = {
        "candidate_id": "candidate-approved-fixture",
        "dataset_manifest_id": "dataset-manifest/audio/enrolled/v1",
        "dataset_id": "dataset/audio/enrolled",
        "dataset_version": "1.0.0",
        "source_alias": "fixture/approved-source",
        "expected_evidence_ids": ("evidence-approved-v1",),
        "license_status": DatasetLicenseStatus.APPROVED,
        "training_allowed": TrainingAllowed.TRUE,
        "commercial_usage_status": CommercialUsageStatus.REVIEW_PENDING,
        "redistribution_allowed": TrainingAllowed.FALSE,
        "content_checksum_set_id": "checksum-set-enrolled-v1",
        "split_id": "split-enrolled-v1",
        "split_algorithm_version": "explicit-count-hash-v1",
        "split_seed": 29,
        "train_count": 1,
        "validation_count": 1,
        "test_count": 1,
        "created_at": NOW,
        "normalization_settings": {"profile": "contract-only"},
    }
    values.update(updates)
    return DatasetEnrollmentProposal(**values)


def rights_evidence(**updates: object) -> NormalizedRightsEvidence:
    values: dict[str, object] = {
        "candidate_id": "candidate-approved-fixture",
        "dataset_manifest_id": "dataset-manifest/audio/enrolled/v1",
        "evidence_id": "evidence-approved-v1",
        "source_alias": "fixture/reviewed-evidence",
        "review_status": EvidenceReviewStatus.VERIFIED,
        "effective_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=30),
        "scope_decisions": (
            RightsScopeDecision(
                scope=RightsScope.DATASET_POSSESSION,
                decision=RightsDecision.APPROVED,
            ),
            RightsScopeDecision(
                scope=RightsScope.DATASET_ACCESS,
                decision=RightsDecision.APPROVED,
            ),
            RightsScopeDecision(
                scope=RightsScope.AI_TRAINING,
                decision=RightsDecision.APPROVED,
            ),
            RightsScopeDecision(
                scope=RightsScope.COMMERCIAL_USE,
                decision=RightsDecision.REVIEW_REQUIRED,
            ),
            RightsScopeDecision(
                scope=RightsScope.REDISTRIBUTION,
                decision=RightsDecision.DENIED,
            ),
            RightsScopeDecision(
                scope=RightsScope.DERIVED_MODEL_DISTRIBUTION,
                decision=RightsDecision.REVIEW_REQUIRED,
            ),
        ),
    }
    values.update(updates)
    return NormalizedRightsEvidence(**values)


def adapter(evidence: NormalizedRightsEvidence | None) -> SanitizedMappingRightsEvidenceAdapter:
    records = () if evidence is None else (evidence.model_dump(mode="json"),)
    return SanitizedMappingRightsEvidenceAdapter(records)


def test_sanitized_evidence_adapter_normalizes_strict_path_free_records() -> None:
    evidence = rights_evidence()
    normalized = adapter(evidence).normalize()
    assert normalized == (evidence,)
    unsafe = evidence.model_dump(mode="json")
    unsafe["source_alias"] = "C:\\private\\rights.txt"
    with pytest.raises(ContractError) as exc_info:
        SanitizedMappingRightsEvidenceAdapter((unsafe,)).normalize()
    assert exc_info.value.error_code == "ABSOLUTE_PATH_FORBIDDEN"


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("missing", "RIGHTS_EVIDENCE_MISSING"),
        ("candidate", "RIGHTS_EVIDENCE_CANDIDATE_MISMATCH"),
        ("manifest", "RIGHTS_EVIDENCE_MANIFEST_MISMATCH"),
        ("evidence_id", "RIGHTS_EVIDENCE_ID_MISMATCH"),
        ("scope", "AI_TRAINING_SCOPE_NOT_APPROVED"),
        ("expired", "RIGHTS_EVIDENCE_EXPIRED"),
        ("future", "RIGHTS_EVIDENCE_NOT_EFFECTIVE"),
        ("review", "RIGHTS_EVIDENCE_NOT_VERIFIED"),
        ("training_false", "DATASET_TRAINING_NOT_ALLOWED"),
        ("commercial_claim", "COMMERCIAL_SCOPE_NOT_APPROVED"),
        ("redistribution_claim", "REDISTRIBUTION_SCOPE_NOT_APPROVED"),
    ],
)
def test_rights_failures_issue_no_manifest_version_or_split(case: str, reason: str) -> None:
    registry = DatasetManifestRegistry()
    proposal = enrollment_proposal()
    evidence: NormalizedRightsEvidence | None = rights_evidence()
    if case == "missing":
        evidence = None
    elif case == "candidate":
        evidence = rights_evidence(candidate_id="different-candidate")
    elif case == "manifest":
        evidence = rights_evidence(dataset_manifest_id="different-manifest")
    elif case == "evidence_id":
        evidence = rights_evidence(evidence_id="different-evidence")
    elif case == "scope":
        evidence = rights_evidence(
            scope_decisions=tuple(
                item
                for item in rights_evidence().scope_decisions
                if item.scope != RightsScope.AI_TRAINING
            )
        )
    elif case == "expired":
        evidence = rights_evidence(
            effective_at=NOW - timedelta(days=2),
            expires_at=NOW - timedelta(days=1),
        )
    elif case == "future":
        evidence = rights_evidence(
            effective_at=NOW + timedelta(days=1),
            expires_at=NOW + timedelta(days=2),
        )
    elif case == "review":
        evidence = rights_evidence(review_status=EvidenceReviewStatus.REVIEW_REQUIRED)
    elif case == "training_false":
        proposal = enrollment_proposal(training_allowed=TrainingAllowed.FALSE)
    elif case == "commercial_claim":
        proposal = enrollment_proposal(commercial_usage_status=CommercialUsageStatus.APPROVED)
    elif case == "redistribution_claim":
        proposal = enrollment_proposal(redistribution_allowed=TrainingAllowed.TRUE)

    result = DatasetEnrollmentService(registry).enroll(
        inventory=candidate_inventory(),
        proposal=proposal,
        evidence_source=adapter(evidence),
        authority_validated=True,
        checked_at=NOW,
    )
    assert result.rights_gate_pass is False
    assert result.manifest_enrolled is False
    assert result.dataset_version_issued is False
    assert result.split_frozen is False
    assert reason in result.reasons
    with pytest.raises(ContractError):
        registry.get(proposal.dataset_manifest_id)


def test_approved_evidence_enrolls_exact_manifest_version_and_split_only() -> None:
    registry = DatasetManifestRegistry()
    inventory = candidate_inventory()
    proposal = enrollment_proposal()
    result = DatasetEnrollmentService(registry).enroll(
        inventory=inventory,
        proposal=proposal,
        evidence_source=adapter(rights_evidence()),
        authority_validated=True,
        checked_at=NOW,
    )
    manifest = registry.get(proposal.dataset_manifest_id)
    assert result.rights_gate_pass is True
    assert result.manifest_enrolled is True
    assert result.dataset_version_issued is True
    assert result.integrity_pass is True
    assert result.split_frozen is True
    assert result.admission.model_selected is False
    assert result.admission.training_config_valid is False
    assert result.admission.environment_preflight_pass is False
    assert result.admission.training_preflight_pass is False
    assert result.admission.training_execution_ready is False
    assert result.admission.training_approval_consumed is False
    assert result.admission.usage_rights is not None
    assert result.admission.usage_rights.commercial_usage_authorized is False
    assert result.admission.usage_rights.redistribution_authorized is False
    assert result.admission.usage_rights.derived_model_distribution_authorized is False
    assert {
        (entry.sample_id, entry.content_checksum, entry.media_type, entry.provenance)
        for entry in manifest.entries
    } == {
        (item.sample_id, item.checksum, item.media_type, item.provenance)
        for item in inventory.items
    }


def test_deterministic_split_requires_exact_membership_counts() -> None:
    kwargs = {
        "split_id": "split-test-v1",
        "algorithm_version": "explicit-count-hash-v1",
        "seed": 29,
        "train_count": 1,
        "validation_count": 1,
        "test_count": 1,
    }
    first = deterministic_dataset_split(("a", "b", "c"), **kwargs)
    second = deterministic_dataset_split(("c", "a", "b"), **kwargs)
    assert first == second
    assert set((*first.train, *first.validation, *first.test)) == {"a", "b", "c"}
    with pytest.raises(ContractError) as exc_info:
        deterministic_dataset_split(("a", "b", "c"), **{**kwargs, "test_count": 0})
    assert exc_info.value.error_code == "DATASET_SPLIT_COUNT_MISMATCH"


def test_enrolled_dataset_version_is_immutable() -> None:
    registry = DatasetManifestRegistry()
    service = DatasetEnrollmentService(registry)
    service.enroll(
        inventory=candidate_inventory(),
        proposal=enrollment_proposal(),
        evidence_source=adapter(rights_evidence()),
        authority_validated=True,
        checked_at=NOW,
    )
    changed_proposal = enrollment_proposal(
        dataset_manifest_id="dataset-manifest/audio/enrolled/changed-v1",
        expected_evidence_ids=("evidence-changed-v1",),
    )
    changed_evidence = rights_evidence(
        dataset_manifest_id=changed_proposal.dataset_manifest_id,
        evidence_id="evidence-changed-v1",
    )
    with pytest.raises(ConflictError) as exc_info:
        service.enroll(
            inventory=candidate_inventory(first_checksum="f" * 64),
            proposal=changed_proposal,
            evidence_source=adapter(changed_evidence),
            authority_validated=True,
            checked_at=NOW,
        )
    assert exc_info.value.error_code == "DATASET_VERSION_IMMUTABILITY_CONFLICT"
