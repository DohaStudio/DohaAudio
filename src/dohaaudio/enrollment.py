"""Rights-evidence normalization and fail-closed Dataset enrollment."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field, model_validator

from dohaaudio.admission import (
    DatasetInventory,
    TrainingAdmissionReport,
    TrainingAdmissionService,
    UsageRightsAdmission,
)
from dohaaudio.contracts import FrozenModel
from dohaaudio.datasets import (
    SUPPORTED_AUDIO_MEDIA_TYPES,
    CommercialUsageStatus,
    DatasetEntry,
    DatasetLicenseStatus,
    DatasetManifest,
    DatasetManifestRegistry,
    DatasetSplit,
    DeletionStatus,
    EvidenceReviewStatus,
    RightsEvidence,
    TrainingAllowed,
    canonical_dataset_checksum,
)
from dohaaudio.errors import ContractError
from dohaaudio.security import assert_safe_metadata


class RightsScope(StrEnum):
    DATASET_POSSESSION = "dataset_possession"
    DATASET_ACCESS = "dataset_access"
    AI_TRAINING = "ai_training"
    COMMERCIAL_USE = "commercial_use"
    REDISTRIBUTION = "redistribution"
    DERIVED_MODEL_DISTRIBUTION = "derived_model_distribution"
    GENERATED_OUTPUT_USAGE = "generated_output_usage"


class RightsDecision(StrEnum):
    APPROVED = "approved"
    DENIED = "denied"
    REVIEW_REQUIRED = "review_required"
    UNKNOWN = "unknown"


class RightsScopeDecision(FrozenModel):
    scope: RightsScope
    decision: RightsDecision


class NormalizedRightsEvidence(FrozenModel):
    candidate_id: str = Field(min_length=1)
    dataset_manifest_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    source_alias: str = Field(min_length=1)
    review_status: EvidenceReviewStatus
    effective_at: datetime
    expires_at: datetime | None = None
    scope_decisions: tuple[RightsScopeDecision, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_normalized_evidence(self) -> NormalizedRightsEvidence:
        scopes = [item.scope for item in self.scope_decisions]
        if len(scopes) != len(set(scopes)):
            raise ValueError("rights evidence cannot repeat a scope")
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("rights evidence expiry must follow its effective time")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class RightsEvidenceSource(Protocol):
    def normalize(self) -> tuple[NormalizedRightsEvidence, ...]: ...


class SanitizedMappingRightsEvidenceAdapter:
    """Normalize already-sanitized records without embedding provider parsing in the core."""

    def __init__(self, records: Iterable[Mapping[str, Any]]) -> None:
        self._records = tuple(dict(record) for record in records)

    def normalize(self) -> tuple[NormalizedRightsEvidence, ...]:
        return tuple(NormalizedRightsEvidence.model_validate(record) for record in self._records)


class DatasetEnrollmentProposal(FrozenModel):
    candidate_id: str = Field(min_length=1)
    dataset_manifest_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    source_alias: str = Field(min_length=1)
    expected_evidence_ids: tuple[str, ...] = Field(min_length=1)
    license_status: DatasetLicenseStatus
    training_allowed: TrainingAllowed
    commercial_usage_status: CommercialUsageStatus
    redistribution_allowed: TrainingAllowed
    content_checksum_set_id: str = Field(min_length=1)
    split_id: str = Field(min_length=1)
    split_algorithm_version: str = Field(min_length=1)
    split_seed: int
    train_count: int = Field(ge=0)
    validation_count: int = Field(ge=0)
    test_count: int = Field(ge=0)
    created_at: datetime
    supersedes_dataset_version: str | None = None
    deletion_status: DeletionStatus = DeletionStatus.ACTIVE
    normalization_settings: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_safe_proposal(self) -> DatasetEnrollmentProposal:
        if len(self.expected_evidence_ids) != len(set(self.expected_evidence_ids)):
            raise ValueError("expected evidence IDs must be unique")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class DatasetEnrollmentResult(FrozenModel):
    candidate_id: str
    rights_gate_pass: bool
    manifest_enrolled: bool
    dataset_version_issued: bool
    integrity_pass: bool
    split_frozen: bool
    dataset_manifest_id: str | None = None
    dataset_version: str | None = None
    reasons: tuple[str, ...]
    admission: TrainingAdmissionReport

    @model_validator(mode="after")
    def validate_enrollment_state(self) -> DatasetEnrollmentResult:
        enrollment_states = {
            self.manifest_enrolled,
            self.dataset_version_issued,
            self.integrity_pass,
            self.split_frozen,
        }
        if len(enrollment_states) != 1:
            raise ValueError("Manifest, DatasetVersion, integrity, and split must advance together")
        if self.manifest_enrolled and not self.rights_gate_pass:
            raise ValueError("Dataset enrollment requires a passing rights Gate")
        if self.manifest_enrolled != (self.dataset_manifest_id is not None):
            raise ValueError("enrolled Manifest requires its logical ID")
        if self.dataset_version_issued != (self.dataset_version is not None):
            raise ValueError("issued DatasetVersion requires its version ID")
        return self


def deterministic_dataset_split(
    sample_ids: tuple[str, ...],
    *,
    split_id: str,
    algorithm_version: str,
    seed: int,
    train_count: int,
    validation_count: int,
    test_count: int,
) -> DatasetSplit:
    if len(sample_ids) != len(set(sample_ids)):
        raise ContractError("DATASET_DUPLICATE_SAMPLE_ID", "Dataset sample IDs are duplicated.")
    if train_count + validation_count + test_count != len(sample_ids):
        raise ContractError(
            "DATASET_SPLIT_COUNT_MISMATCH",
            "Dataset split counts do not cover the exact membership.",
        )
    ranked = tuple(
        sorted(
            sample_ids,
            key=lambda item: hashlib.sha256(
                f"{algorithm_version}:{seed}:{item}".encode()
            ).hexdigest(),
        )
    )
    validation_end = train_count + validation_count
    return DatasetSplit(
        split_id=split_id,
        train=ranked[:train_count],
        validation=ranked[train_count:validation_end],
        test=ranked[validation_end:],
        algorithm_version=algorithm_version,
        seed=seed,
    )


class DatasetEnrollmentService:
    def __init__(self, registry: DatasetManifestRegistry) -> None:
        self._registry = registry
        self._admission = TrainingAdmissionService()

    def enroll(
        self,
        *,
        inventory: DatasetInventory,
        proposal: DatasetEnrollmentProposal,
        evidence_source: RightsEvidenceSource,
        authority_validated: bool,
        checked_at: datetime,
    ) -> DatasetEnrollmentResult:
        evidence = evidence_source.normalize()
        reasons = self._preflight_reasons(
            inventory=inventory,
            proposal=proposal,
            evidence=evidence,
            authority_validated=authority_validated,
            checked_at=checked_at,
        )
        if reasons:
            return self._blocked(inventory, checked_at, reasons, authority_validated)

        manifest = self._build_manifest(inventory, proposal, evidence)
        usage_rights = self._usage_rights(inventory, proposal, evidence)
        admission = self._admission.assess(
            inventory=inventory,
            authority_validated=authority_validated,
            usage_rights=usage_rights,
            manifest=manifest,
            config=None,
            model_selected=False,
            environment=None,
            readiness=None,
            checked_at=checked_at,
        )
        enrollment_ready = (
            admission.dataset_authority_valid
            and admission.rights_gate_pass
            and admission.dataset_integrity_pass
            and admission.dataset_split_frozen
        )
        if not enrollment_ready:
            return DatasetEnrollmentResult(
                candidate_id=inventory.candidate_id,
                rights_gate_pass=admission.rights_gate_pass,
                manifest_enrolled=False,
                dataset_version_issued=False,
                integrity_pass=False,
                split_frozen=False,
                reasons=admission.reasons,
                admission=admission,
            )

        registered = self._registry.register(manifest)
        return DatasetEnrollmentResult(
            candidate_id=inventory.candidate_id,
            rights_gate_pass=True,
            manifest_enrolled=True,
            dataset_version_issued=True,
            integrity_pass=True,
            split_frozen=True,
            dataset_manifest_id=registered.dataset_manifest_id,
            dataset_version=registered.dataset_version,
            reasons=admission.reasons,
            admission=admission,
        )

    @staticmethod
    def _preflight_reasons(
        *,
        inventory: DatasetInventory,
        proposal: DatasetEnrollmentProposal,
        evidence: tuple[NormalizedRightsEvidence, ...],
        authority_validated: bool,
        checked_at: datetime,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not authority_validated or inventory.duplicate_relative_identity_count:
            reasons.append("DATASET_AUTHORITY_INVALID")
        if inventory.candidate_id != proposal.candidate_id:
            reasons.append("PROPOSAL_CANDIDATE_MISMATCH")
        if (
            inventory.discovered_file_count
            != inventory.supported_item_count + inventory.unsupported_file_count
            or inventory.supported_item_count != len(inventory.items)
        ):
            reasons.append("DATASET_INVENTORY_COUNT_MISMATCH")
        if inventory.discovered_file_count != inventory.supported_item_count:
            reasons.append("DATASET_UNSUPPORTED_FILES_PRESENT")
        if inventory.missing_checksum_count:
            reasons.append("DATASET_CHECKSUM_INCOMPLETE")
        sample_ids = [item.sample_id for item in inventory.items]
        checksums = [item.checksum for item in inventory.items if item.checksum is not None]
        if len(sample_ids) != len(set(sample_ids)):
            reasons.append("DATASET_DUPLICATE_SAMPLE_ID")
        if inventory.duplicate_checksum_count or len(checksums) != len(set(checksums)):
            reasons.append("DATASET_DUPLICATE_CHECKSUM")
        if any(item.media_type not in SUPPORTED_AUDIO_MEDIA_TYPES for item in inventory.items):
            reasons.append("DATASET_MEDIA_TYPE_UNSUPPORTED")
        if any(not item.provenance for item in inventory.items):
            reasons.append("DATASET_PROVENANCE_MISSING")
        if not evidence:
            reasons.append("RIGHTS_EVIDENCE_MISSING")
        evidence_ids = [item.evidence_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            reasons.append("RIGHTS_EVIDENCE_ID_DUPLICATE")
        if set(evidence_ids) != set(proposal.expected_evidence_ids):
            reasons.append("RIGHTS_EVIDENCE_ID_MISMATCH")
        for item in evidence:
            if item.candidate_id != inventory.candidate_id:
                reasons.append("RIGHTS_EVIDENCE_CANDIDATE_MISMATCH")
            if item.dataset_manifest_id != proposal.dataset_manifest_id:
                reasons.append("RIGHTS_EVIDENCE_MANIFEST_MISMATCH")
            if item.review_status != EvidenceReviewStatus.VERIFIED:
                reasons.append("RIGHTS_EVIDENCE_NOT_VERIFIED")
            if item.effective_at > checked_at:
                reasons.append("RIGHTS_EVIDENCE_NOT_EFFECTIVE")
            if item.expires_at is not None and item.expires_at <= checked_at:
                reasons.append("RIGHTS_EVIDENCE_EXPIRED")
        decisions = DatasetEnrollmentService._approved_scopes(evidence)
        for scope, reason in (
            (RightsScope.DATASET_POSSESSION, "DATASET_POSSESSION_NOT_CONFIRMED"),
            (RightsScope.DATASET_ACCESS, "DATASET_ACCESS_NOT_AUTHORIZED"),
            (RightsScope.AI_TRAINING, "AI_TRAINING_SCOPE_NOT_APPROVED"),
        ):
            if scope not in decisions:
                reasons.append(reason)
        if proposal.license_status != DatasetLicenseStatus.APPROVED:
            reasons.append("DATASET_LICENSE_NOT_APPROVED")
        if proposal.training_allowed != TrainingAllowed.TRUE:
            reasons.append("DATASET_TRAINING_NOT_ALLOWED")
        if proposal.deletion_status != DeletionStatus.ACTIVE:
            reasons.append("DATASET_NOT_ACTIVE")
        if (
            proposal.commercial_usage_status == CommercialUsageStatus.APPROVED
            and RightsScope.COMMERCIAL_USE not in decisions
        ):
            reasons.append("COMMERCIAL_SCOPE_NOT_APPROVED")
        if (
            proposal.redistribution_allowed == TrainingAllowed.TRUE
            and RightsScope.REDISTRIBUTION not in decisions
        ):
            reasons.append("REDISTRIBUTION_SCOPE_NOT_APPROVED")
        expected_count = proposal.train_count + proposal.validation_count + proposal.test_count
        if expected_count != inventory.supported_item_count:
            reasons.append("DATASET_SPLIT_COUNT_MISMATCH")
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _approved_scopes(
        evidence: tuple[NormalizedRightsEvidence, ...],
    ) -> frozenset[RightsScope]:
        decisions: dict[RightsScope, list[RightsDecision]] = {}
        for item in evidence:
            for scoped in item.scope_decisions:
                decisions.setdefault(scoped.scope, []).append(scoped.decision)
        return frozenset(
            scope
            for scope, values in decisions.items()
            if values and all(value == RightsDecision.APPROVED for value in values)
        )

    @staticmethod
    def _build_manifest(
        inventory: DatasetInventory,
        proposal: DatasetEnrollmentProposal,
        evidence: tuple[NormalizedRightsEvidence, ...],
    ) -> DatasetManifest:
        split = deterministic_dataset_split(
            tuple(item.sample_id for item in inventory.items),
            split_id=proposal.split_id,
            algorithm_version=proposal.split_algorithm_version,
            seed=proposal.split_seed,
            train_count=proposal.train_count,
            validation_count=proposal.validation_count,
            test_count=proposal.test_count,
        )
        manifest = DatasetManifest(
            dataset_manifest_id=proposal.dataset_manifest_id,
            dataset_id=proposal.dataset_id,
            dataset_version=proposal.dataset_version,
            source=proposal.source_alias,
            license_status=proposal.license_status,
            training_allowed=proposal.training_allowed,
            commercial_usage_status=proposal.commercial_usage_status,
            redistribution_allowed=proposal.redistribution_allowed,
            item_count=len(inventory.items),
            manifest_checksum="0" * 64,
            content_checksum_set_id=proposal.content_checksum_set_id,
            split_id=proposal.split_id,
            created_at=proposal.created_at,
            supersedes_dataset_version=proposal.supersedes_dataset_version,
            deletion_status=proposal.deletion_status,
            entries=tuple(
                DatasetEntry(
                    sample_id=item.sample_id,
                    content_checksum=item.checksum or "",
                    media_type=item.media_type,
                    provenance=item.provenance,
                )
                for item in inventory.items
            ),
            split=split,
            rights_evidence=tuple(
                RightsEvidence(
                    source=item.source_alias,
                    evidence_id=item.evidence_id,
                    review_status=item.review_status,
                    effective_at=item.effective_at,
                    expires_at=item.expires_at,
                )
                for item in evidence
            ),
            normalization_settings=proposal.normalization_settings,
        )
        return manifest.model_copy(
            update={"manifest_checksum": canonical_dataset_checksum(manifest)}
        )

    @staticmethod
    def _usage_rights(
        inventory: DatasetInventory,
        proposal: DatasetEnrollmentProposal,
        evidence: tuple[NormalizedRightsEvidence, ...],
    ) -> UsageRightsAdmission:
        scopes = DatasetEnrollmentService._approved_scopes(evidence)
        expiries = [item.expires_at for item in evidence if item.expires_at is not None]
        return UsageRightsAdmission(
            candidate_id=inventory.candidate_id,
            dataset_manifest_id=proposal.dataset_manifest_id,
            evidence_ids=tuple(item.evidence_id for item in evidence),
            scopes=tuple(sorted(scope.value for scope in scopes)),
            review_status=EvidenceReviewStatus.VERIFIED,
            effective_at=max(item.effective_at for item in evidence),
            expires_at=min(expiries) if expiries else None,
            dataset_possession_confirmed=RightsScope.DATASET_POSSESSION in scopes,
            dataset_access_authorized=RightsScope.DATASET_ACCESS in scopes,
            ai_training_authorized=RightsScope.AI_TRAINING in scopes,
            commercial_usage_authorized=RightsScope.COMMERCIAL_USE in scopes,
            redistribution_authorized=RightsScope.REDISTRIBUTION in scopes,
            derived_model_distribution_authorized=(
                RightsScope.DERIVED_MODEL_DISTRIBUTION in scopes
            ),
            generated_output_usage_authorized=RightsScope.GENERATED_OUTPUT_USAGE in scopes,
        )

    def _blocked(
        self,
        inventory: DatasetInventory,
        checked_at: datetime,
        reasons: tuple[str, ...],
        authority_validated: bool,
    ) -> DatasetEnrollmentResult:
        admission = self._admission.assess(
            inventory=inventory,
            authority_validated=authority_validated,
            usage_rights=None,
            manifest=None,
            config=None,
            model_selected=False,
            environment=None,
            readiness=None,
            checked_at=checked_at,
        )
        return DatasetEnrollmentResult(
            candidate_id=inventory.candidate_id,
            rights_gate_pass=False,
            manifest_enrolled=False,
            dataset_version_issued=False,
            integrity_pass=False,
            split_frozen=False,
            reasons=tuple(dict.fromkeys((*reasons, *admission.reasons))),
            admission=admission,
        )
