"""Bounded semantic-role evidence collection and human review boundary."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator
from pydantic_core import to_jsonable_python

from dohaaudio.archive_policy import (
    ArchiveInterpretationInput,
    CompanionDisposition,
    CompanionRole,
    InterpretedArchiveMember,
    InterpretedArchiveMembership,
)
from dohaaudio.archive_role_policy import CandidateRoleDispositionPolicy
from dohaaudio.contracts import FrozenModel
from dohaaudio.errors import ContractError, NotFoundError
from dohaaudio.security import assert_safe_metadata


class EvidenceSamplingStrategy(StrEnum):
    DETERMINISTIC_ARCHIVE_COVERAGE = "deterministic_archive_coverage"


class EvidenceObservationKind(StrEnum):
    JSON_SCHEMA = "json_schema"
    MIDI_HEADER = "midi_header"
    MEMBERSHIP_ONLY = "membership_only"


class ProposedSemanticRole(StrEnum):
    PRIMARY_AUDIO_CANDIDATE = "primary_audio_candidate"
    CONDITIONING_CANDIDATE = "conditioning_candidate"
    SYMBOLIC_COMPANION_CANDIDATE = "symbolic_companion_candidate"
    METADATA_CANDIDATE = "metadata_candidate"
    ANNOTATION_CANDIDATE = "annotation_candidate"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class SemanticReviewStatus(StrEnum):
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class HumanReviewOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class RoleEvidenceSamplingPlan(FrozenModel):
    plan_id: str = Field(min_length=1)
    plan_version: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    structural_role: CompanionRole
    strategy: EvidenceSamplingStrategy
    requested_sample_count: int = Field(ge=0)
    selection_key: str = Field(min_length=1)
    coverage_dimensions: tuple[str, ...]
    max_probe_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_plan(self) -> RoleEvidenceSamplingPlan:
        allowed_dimensions = {"archive_logical_id", "logical_member_identity"}
        if not self.coverage_dimensions or not set(self.coverage_dimensions).issubset(
            allowed_dimensions
        ):
            raise ValueError("sampling coverage dimensions are unsupported")
        if len(set(self.coverage_dimensions)) != len(self.coverage_dimensions):
            raise ValueError("sampling coverage dimensions must be unique")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class JsonSchemaEvidenceSummary(FrozenModel):
    valid_document_count: int = Field(ge=0)
    invalid_document_count: int = Field(ge=0)
    unique_schema_fingerprints: tuple[str, ...]
    dominant_schema_count: int = Field(ge=0)
    schema_mismatch_count: int = Field(ge=0)
    top_level_type_counts: dict[str, int]
    key_category_presence_counts: dict[str, int]

    @model_validator(mode="after")
    def validate_summary(self) -> JsonSchemaEvidenceSummary:
        if any(len(value) != 64 for value in self.unique_schema_fingerprints):
            raise ValueError("schema fingerprints must be SHA-256 digests")
        if self.dominant_schema_count + self.schema_mismatch_count != (self.valid_document_count):
            raise ValueError("schema consistency counts must cover valid documents")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class MidiHeaderEvidenceSummary(FrozenModel):
    valid_header_count: int = Field(ge=0)
    invalid_header_count: int = Field(ge=0)
    format_distribution: dict[str, int]
    track_count_distribution: dict[str, int]
    division_distribution: dict[str, int]
    structural_signature_counts: dict[str, int]

    @model_validator(mode="after")
    def validate_summary(self) -> MidiHeaderEvidenceSummary:
        if any(len(value) != 64 for value in self.structural_signature_counts):
            raise ValueError("MIDI structural signatures must be SHA-256 digests")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class MembershipEvidenceSummary(FrozenModel):
    content_probe_performed: bool = False

    @model_validator(mode="after")
    def reject_content_probe(self) -> MembershipEvidenceSummary:
        if self.content_probe_performed:
            raise ValueError("membership-only evidence cannot claim a content probe")
        return self


class SemanticRoleEvidence(FrozenModel):
    evidence_id: str = Field(min_length=1)
    record_version: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    structural_role: CompanionRole
    sampling_plan_id: str = Field(min_length=1)
    sampling_plan_version: str = Field(min_length=1)
    sampling_strategy: EvidenceSamplingStrategy
    requested_sample_count: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    population_count: int = Field(ge=0)
    sampled_member_ids: tuple[str, ...]
    membership_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    path_policy_id: str = Field(min_length=1)
    path_policy_version: str = Field(min_length=1)
    path_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    companion_policy_id: str = Field(min_length=1)
    companion_policy_version: str = Field(min_length=1)
    role_policy_id: str = Field(min_length=1)
    role_policy_version: str = Field(min_length=1)
    observation_kind: EvidenceObservationKind
    json_summary: JsonSchemaEvidenceSummary | None = None
    midi_summary: MidiHeaderEvidenceSummary | None = None
    membership_summary: MembershipEvidenceSummary | None = None
    raw_evidence_complete: bool
    reason_codes: tuple[str, ...]
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_evidence(self) -> SemanticRoleEvidence:
        if self.sample_count != len(self.sampled_member_ids):
            raise ValueError("sample count must match sampled logical identities")
        if self.sample_count > self.population_count:
            raise ValueError("sample count cannot exceed the role population")
        if len(set(self.sampled_member_ids)) != len(self.sampled_member_ids):
            raise ValueError("sampled logical identities must be unique")
        summaries = {
            EvidenceObservationKind.JSON_SCHEMA: self.json_summary,
            EvidenceObservationKind.MIDI_HEADER: self.midi_summary,
            EvidenceObservationKind.MEMBERSHIP_ONLY: self.membership_summary,
        }
        if (
            summaries[self.observation_kind] is None
            or sum(summary is not None for summary in summaries.values()) != 1
        ):
            raise ValueError("evidence must contain exactly one matching observation summary")
        observed_count = 0
        if self.json_summary is not None:
            observed_count = (
                self.json_summary.valid_document_count + self.json_summary.invalid_document_count
            )
        elif self.midi_summary is not None:
            observed_count = (
                self.midi_summary.valid_header_count + self.midi_summary.invalid_header_count
            )
        if self.observation_kind != EvidenceObservationKind.MEMBERSHIP_ONLY:
            if observed_count != self.sample_count:
                raise ValueError("observation counts must cover the selected sample")
            if self.raw_evidence_complete != (self.sample_count > 0 and _invalid_count(self) == 0):
                raise ValueError("raw evidence completeness must match bounded observations")
        elif self.sample_count or self.raw_evidence_complete:
            raise ValueError("membership-only evidence cannot claim sampled content")
        if not self.reason_codes or any(
            not reason.startswith("SEMANTIC_EVIDENCE_") for reason in self.reason_codes
        ):
            raise ValueError("semantic evidence requires safe deterministic reason codes")
        expected_fingerprint = _fingerprint_payload(
            self.model_dump(
                mode="json",
                exclude={"evidence_id", "evidence_fingerprint"},
            )
        )
        if self.evidence_fingerprint != expected_fingerprint:
            raise ValueError("semantic evidence fingerprint must match the complete record")
        if self.evidence_id != f"semantic-role-evidence/{expected_fingerprint}":
            raise ValueError("semantic evidence identity must match its fingerprint")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class SemanticRoleEvidencePolicy(FrozenModel):
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    structural_role: CompanionRole
    sampling_plan_id: str = Field(min_length=1)
    sampling_plan_version: str = Field(min_length=1)
    path_policy_id: str = Field(min_length=1)
    path_policy_version: str = Field(min_length=1)
    path_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    companion_policy_id: str = Field(min_length=1)
    companion_policy_version: str = Field(min_length=1)
    role_policy_id: str = Field(min_length=1)
    role_policy_version: str = Field(min_length=1)
    required_observation_kind: EvidenceObservationKind
    minimum_sample_count: int = Field(ge=0)
    require_complete_observations: bool = True
    maximum_unique_schema_count: int | None = Field(default=None, gt=0)
    approved_reviewer_authority_ids: tuple[str, ...] = ()
    allow_automatic_approval: bool = False

    @model_validator(mode="after")
    def reject_automatic_approval(self) -> SemanticRoleEvidencePolicy:
        if self.allow_automatic_approval:
            raise ValueError("automated analysis cannot grant semantic approval")
        if len(set(self.approved_reviewer_authority_ids)) != len(
            self.approved_reviewer_authority_ids
        ):
            raise ValueError("reviewer authority identities must be unique")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class HumanSemanticRoleReview(FrozenModel):
    review_id: str = Field(min_length=1)
    reviewer_authority_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    structural_role: CompanionRole
    proposed_semantic_role: ProposedSemanticRole
    evidence_id: str = Field(min_length=1)
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_policy_id: str = Field(min_length=1)
    evidence_policy_version: str = Field(min_length=1)
    outcome: HumanReviewOutcome
    reviewed_at: datetime

    @model_validator(mode="after")
    def validate_review(self) -> HumanSemanticRoleReview:
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class SemanticRoleReviewDecision(FrozenModel):
    decision_id: str = Field(min_length=1)
    record_version: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    structural_role: CompanionRole
    proposed_semantic_role: ProposedSemanticRole
    status: SemanticReviewStatus
    evidence_id: str = Field(min_length=1)
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_policy_id: str = Field(min_length=1)
    evidence_policy_version: str = Field(min_length=1)
    sampling_plan_id: str = Field(min_length=1)
    sampling_plan_version: str = Field(min_length=1)
    path_policy_id: str = Field(min_length=1)
    path_policy_version: str = Field(min_length=1)
    path_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    companion_policy_id: str = Field(min_length=1)
    companion_policy_version: str = Field(min_length=1)
    role_policy_id: str = Field(min_length=1)
    role_policy_version: str = Field(min_length=1)
    human_review_id: str | None = None
    reviewer_authority_id: str | None = None
    reviewed_at: datetime | None = None
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_decision(self) -> SemanticRoleReviewDecision:
        human_fields = (
            self.human_review_id,
            self.reviewer_authority_id,
            self.reviewed_at,
        )
        human_status = self.status in {
            SemanticReviewStatus.APPROVED,
            SemanticReviewStatus.REJECTED,
        }
        if human_status != all(value is not None for value in human_fields):
            raise ValueError(
                "approved or rejected decisions require complete human review authority"
            )
        if not human_status and any(value is not None for value in human_fields):
            raise ValueError("automated decisions cannot claim human review authority")
        if self.status == SemanticReviewStatus.APPROVED and (
            self.proposed_semantic_role == ProposedSemanticRole.UNKNOWN
        ):
            raise ValueError("unknown semantic roles cannot be approved")
        if not self.reason_codes or any(
            not reason.startswith("SEMANTIC_REVIEW_") for reason in self.reason_codes
        ):
            raise ValueError("semantic review requires safe deterministic reason codes")
        decision_payload = self.model_dump(mode="json", exclude={"decision_id"})
        expected_id = f"semantic-role-review/{_fingerprint_payload(decision_payload)}"
        if self.decision_id != expected_id:
            raise ValueError("semantic review identity must match the complete decision")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class InMemorySemanticRoleEvidenceRegistry:
    """Immutable evidence registry; physical sources never enter the stored contract."""

    def __init__(self) -> None:
        self._records: dict[str, SemanticRoleEvidence] = {}

    def publish(self, evidence: SemanticRoleEvidence) -> SemanticRoleEvidence:
        current = self._records.get(evidence.evidence_id)
        if current is not None and current != evidence:
            raise ContractError(
                "SEMANTIC_EVIDENCE_IMMUTABLE_CONFLICT",
                "Published semantic evidence cannot be overwritten.",
            )
        self._records[evidence.evidence_id] = evidence.model_copy(deep=True)
        return evidence.model_copy(deep=True)

    def get(self, evidence_id: str) -> SemanticRoleEvidence:
        try:
            return self._records[evidence_id].model_copy(deep=True)
        except KeyError as exc:
            raise NotFoundError("SemanticRoleEvidence") from exc


def select_evidence_members(
    membership: InterpretedArchiveMembership,
    plan: RoleEvidenceSamplingPlan,
) -> tuple[InterpretedArchiveMember, ...]:
    """Select a stable archive-covered subset without consulting filesystem order."""

    if membership.candidate_id != plan.candidate_id:
        raise ContractError(
            "SEMANTIC_EVIDENCE_CANDIDATE_MISMATCH",
            "Sampling plans cannot cross candidate scopes.",
        )
    population = [member for member in membership.members if member.role == plan.structural_role]
    if not population or plan.requested_sample_count == 0:
        return ()
    by_archive: dict[str, list[InterpretedArchiveMember]] = {}
    for member in population:
        by_archive.setdefault(member.archive_logical_id, []).append(member)
    archives = sorted(
        by_archive,
        key=lambda archive_id: _selection_digest(plan.selection_key, archive_id),
    )
    for archive_id in archives:
        by_archive[archive_id].sort(
            key=lambda member: _selection_digest(
                plan.selection_key,
                archive_id,
                member.interpreted_member_id,
            )
        )
    selected: list[InterpretedArchiveMember] = []
    index = 0
    limit = min(plan.requested_sample_count, len(population))
    while len(selected) < limit:
        made_progress = False
        for archive_id in archives:
            members = by_archive[archive_id]
            if index < len(members):
                selected.append(members[index])
                made_progress = True
                if len(selected) == limit:
                    break
        if not made_progress:
            break
        index += 1
    return tuple(selected)


def collect_semantic_role_evidence(
    inputs: Iterable[ArchiveInterpretationInput],
    membership: InterpretedArchiveMembership,
    role_policy: CandidateRoleDispositionPolicy,
    plan: RoleEvidenceSamplingPlan,
) -> SemanticRoleEvidence:
    """Collect bounded content structure without retaining filenames or raw values."""

    ordered_inputs = tuple(sorted(inputs, key=lambda item: item.source.archive_logical_id))
    _validate_collection_binding(ordered_inputs, membership, role_policy, plan)
    population_count = sum(member.role == plan.structural_role for member in membership.members)
    selected = select_evidence_members(membership, plan)

    if plan.structural_role == CompanionRole.JSON:
        json_summary = _collect_json_summary(ordered_inputs, selected, plan.max_probe_bytes)
        return _build_evidence(
            membership,
            role_policy,
            plan,
            population_count=population_count,
            selected=selected,
            observation_kind=EvidenceObservationKind.JSON_SCHEMA,
            json_summary=json_summary,
            raw_evidence_complete=(bool(selected) and json_summary.invalid_document_count == 0),
        )
    if plan.structural_role == CompanionRole.MIDI:
        midi_summary = _collect_midi_summary(ordered_inputs, selected)
        return _build_evidence(
            membership,
            role_policy,
            plan,
            population_count=population_count,
            selected=selected,
            observation_kind=EvidenceObservationKind.MIDI_HEADER,
            midi_summary=midi_summary,
            raw_evidence_complete=bool(selected) and midi_summary.invalid_header_count == 0,
        )
    return _build_evidence(
        membership,
        role_policy,
        plan,
        population_count=population_count,
        selected=(),
        observation_kind=EvidenceObservationKind.MEMBERSHIP_ONLY,
        membership_summary=MembershipEvidenceSummary(),
        raw_evidence_complete=False,
    )


def review_semantic_role(
    evidence: SemanticRoleEvidence,
    policy: SemanticRoleEvidencePolicy,
    proposed_role: ProposedSemanticRole,
    *,
    human_review: HumanSemanticRoleReview | None = None,
) -> SemanticRoleReviewDecision:
    _validate_review_binding(evidence, policy)
    sufficient = _evidence_is_sufficient(evidence, policy)
    status = SemanticReviewStatus.REVIEW_REQUIRED
    reasons = ["SEMANTIC_REVIEW_HUMAN_APPROVAL_REQUIRED"]
    if not sufficient:
        reasons = ["SEMANTIC_REVIEW_EVIDENCE_INSUFFICIENT"]
    if human_review is not None:
        _validate_human_review_binding(evidence, policy, proposed_role, human_review)
        if human_review.outcome == HumanReviewOutcome.REJECTED:
            status = SemanticReviewStatus.REJECTED
            reasons = ["SEMANTIC_REVIEW_HUMAN_REJECTED"]
        elif sufficient:
            status = SemanticReviewStatus.APPROVED
            reasons = ["SEMANTIC_REVIEW_HUMAN_APPROVED"]
        else:
            status = SemanticReviewStatus.BLOCKED
            reasons = ["SEMANTIC_REVIEW_EVIDENCE_INSUFFICIENT"]
    payload: dict[str, Any] = {
        "record_version": "1.0.0",
        "candidate_id": evidence.candidate_id,
        "structural_role": evidence.structural_role,
        "proposed_semantic_role": proposed_role,
        "status": status,
        "evidence_id": evidence.evidence_id,
        "evidence_fingerprint": evidence.evidence_fingerprint,
        "evidence_policy_id": policy.policy_id,
        "evidence_policy_version": policy.policy_version,
        "sampling_plan_id": evidence.sampling_plan_id,
        "sampling_plan_version": evidence.sampling_plan_version,
        "path_policy_id": evidence.path_policy_id,
        "path_policy_version": evidence.path_policy_version,
        "path_evidence_fingerprint": evidence.path_evidence_fingerprint,
        "companion_policy_id": evidence.companion_policy_id,
        "companion_policy_version": evidence.companion_policy_version,
        "role_policy_id": evidence.role_policy_id,
        "role_policy_version": evidence.role_policy_version,
        "human_review_id": human_review.review_id
        if status in {SemanticReviewStatus.APPROVED, SemanticReviewStatus.REJECTED} and human_review
        else None,
        "reviewer_authority_id": human_review.reviewer_authority_id
        if status in {SemanticReviewStatus.APPROVED, SemanticReviewStatus.REJECTED} and human_review
        else None,
        "reviewed_at": human_review.reviewed_at
        if status in {SemanticReviewStatus.APPROVED, SemanticReviewStatus.REJECTED} and human_review
        else None,
        "reason_codes": tuple(reasons),
    }
    decision_id = f"semantic-role-review/{_fingerprint_payload(_jsonable(payload))}"
    return SemanticRoleReviewDecision(decision_id=decision_id, **payload)


def apply_semantic_review_decisions(
    role_policy: CandidateRoleDispositionPolicy,
    decisions: Iterable[SemanticRoleReviewDecision],
    evidences: Iterable[SemanticRoleEvidence],
    evidence_policies: Iterable[SemanticRoleEvidencePolicy],
) -> CandidateRoleDispositionPolicy:
    decision_records = tuple(decisions)
    evidence_records = tuple(evidences)
    policy_records = tuple(evidence_policies)
    decisions_by_role = {decision.structural_role: decision for decision in decision_records}
    evidences_by_role = {evidence.structural_role: evidence for evidence in evidence_records}
    policies_by_role = {policy.structural_role: policy for policy in policy_records}
    if (
        len(decisions_by_role) != len(decision_records)
        or len(evidences_by_role) != len(evidence_records)
        or len(policies_by_role) != len(policy_records)
    ):
        raise ContractError(
            "SEMANTIC_REVIEW_ROLE_DUPLICATE",
            "Semantic review inputs must contain exactly one record per structural role.",
        )
    if (
        set(decisions_by_role) != set(CompanionRole)
        or set(evidences_by_role) != set(CompanionRole)
        or set(policies_by_role) != set(CompanionRole)
    ):
        raise ContractError(
            "SEMANTIC_REVIEW_ROLE_SET_INCOMPLETE",
            "Every structural role requires evidence, a review decision, and an authority policy.",
        )
    dispositions: dict[CompanionRole, CompanionDisposition] = {}
    for role, decision in decisions_by_role.items():
        evidence = evidences_by_role[role]
        evidence_policy = policies_by_role[role]
        _validate_review_binding(evidence, evidence_policy)
        if (
            decision.candidate_id != evidence.candidate_id
            or decision.structural_role != evidence.structural_role
            or decision.evidence_id != evidence.evidence_id
            or decision.evidence_fingerprint != evidence.evidence_fingerprint
            or decision.sampling_plan_id != evidence.sampling_plan_id
            or decision.sampling_plan_version != evidence.sampling_plan_version
            or decision.path_policy_id != evidence.path_policy_id
            or decision.path_policy_version != evidence.path_policy_version
            or decision.path_evidence_fingerprint != evidence.path_evidence_fingerprint
            or decision.companion_policy_id != evidence.companion_policy_id
            or decision.companion_policy_version != evidence.companion_policy_version
            or decision.role_policy_id != evidence.role_policy_id
            or decision.role_policy_version != evidence.role_policy_version
        ):
            raise ContractError(
                "SEMANTIC_REVIEW_EVIDENCE_MISMATCH",
                "Semantic review decisions must bind the exact current evidence record.",
            )
        if (
            decision.candidate_id != role_policy.candidate_id
            or decision.role_policy_id != role_policy.policy_id
            or decision.role_policy_version != role_policy.policy_version
            or decision.path_policy_id != role_policy.path_policy_id
            or decision.path_policy_version != role_policy.path_policy_version
            or decision.path_evidence_fingerprint != role_policy.path_evidence_fingerprint
            or decision.companion_policy_id != role_policy.companion_policy_id
            or decision.companion_policy_version != role_policy.companion_policy_version
            or evidence_policy.candidate_id != role_policy.candidate_id
            or evidence_policy.path_policy_id != role_policy.path_policy_id
            or evidence_policy.path_policy_version != role_policy.path_policy_version
            or evidence_policy.path_evidence_fingerprint != role_policy.path_evidence_fingerprint
            or evidence_policy.companion_policy_id != role_policy.companion_policy_id
            or evidence_policy.companion_policy_version != role_policy.companion_policy_version
            or evidence_policy.role_policy_id != role_policy.policy_id
            or evidence_policy.role_policy_version != role_policy.policy_version
            or decision.evidence_policy_id != evidence_policy.policy_id
            or decision.evidence_policy_version != evidence_policy.policy_version
            or decision.sampling_plan_id != evidence_policy.sampling_plan_id
            or decision.sampling_plan_version != evidence_policy.sampling_plan_version
        ):
            raise ContractError(
                "SEMANTIC_REVIEW_ROLE_POLICY_MISMATCH",
                "Semantic review decisions must match the complete role policy authority.",
            )
        if (
            decision.status in {SemanticReviewStatus.APPROVED, SemanticReviewStatus.REJECTED}
            and decision.reviewer_authority_id
            not in evidence_policy.approved_reviewer_authority_ids
        ):
            raise ContractError(
                "SEMANTIC_REVIEW_REVIEWER_AUTHORITY_MISMATCH",
                "Semantic decisions require a reviewer registered by the evidence policy.",
            )
        dispositions[role] = _decision_disposition(decision)
    payload = role_policy.model_dump()
    payload["role_dispositions"] = dispositions
    return CandidateRoleDispositionPolicy(**payload)


def _build_evidence(
    membership: InterpretedArchiveMembership,
    role_policy: CandidateRoleDispositionPolicy,
    plan: RoleEvidenceSamplingPlan,
    *,
    population_count: int,
    selected: tuple[InterpretedArchiveMember, ...],
    observation_kind: EvidenceObservationKind,
    raw_evidence_complete: bool,
    json_summary: JsonSchemaEvidenceSummary | None = None,
    midi_summary: MidiHeaderEvidenceSummary | None = None,
    membership_summary: MembershipEvidenceSummary | None = None,
) -> SemanticRoleEvidence:
    reasons: list[str] = []
    if population_count == 0:
        reasons.append("SEMANTIC_EVIDENCE_POPULATION_EMPTY")
    elif observation_kind == EvidenceObservationKind.MEMBERSHIP_ONLY:
        reasons.append("SEMANTIC_EVIDENCE_CONTENT_PROBE_NOT_REQUIRED")
    elif raw_evidence_complete:
        reasons.append("SEMANTIC_EVIDENCE_BOUNDED_SAMPLE_COMPLETE")
    else:
        reasons.append("SEMANTIC_EVIDENCE_BOUNDED_SAMPLE_INCOMPLETE")
    payload: dict[str, Any] = {
        "record_version": "1.0.0",
        "candidate_id": membership.candidate_id,
        "structural_role": plan.structural_role,
        "sampling_plan_id": plan.plan_id,
        "sampling_plan_version": plan.plan_version,
        "sampling_strategy": plan.strategy,
        "requested_sample_count": plan.requested_sample_count,
        "sample_count": len(selected),
        "population_count": population_count,
        "sampled_member_ids": tuple(member.interpreted_member_id for member in selected),
        "membership_fingerprint": membership.evidence_fingerprint,
        "path_policy_id": membership.policy_id,
        "path_policy_version": membership.policy_version,
        "path_evidence_fingerprint": membership.evidence_fingerprint,
        "companion_policy_id": role_policy.companion_policy_id,
        "companion_policy_version": role_policy.companion_policy_version,
        "role_policy_id": role_policy.policy_id,
        "role_policy_version": role_policy.policy_version,
        "observation_kind": observation_kind,
        "json_summary": json_summary,
        "midi_summary": midi_summary,
        "membership_summary": membership_summary,
        "raw_evidence_complete": raw_evidence_complete,
        "reason_codes": tuple(reasons),
    }
    fingerprint = _fingerprint_payload(_jsonable(payload))
    return SemanticRoleEvidence(
        evidence_id=f"semantic-role-evidence/{fingerprint}",
        evidence_fingerprint=fingerprint,
        **payload,
    )


def _collect_json_summary(
    inputs: tuple[ArchiveInterpretationInput, ...],
    selected: tuple[InterpretedArchiveMember, ...],
    max_probe_bytes: int,
) -> JsonSchemaEvidenceSummary:
    observations = _read_selected(inputs, selected, max_probe_bytes=max_probe_bytes)
    schemas: Counter[str] = Counter()
    top_types: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    invalid = 0
    for payload in observations:
        if payload is None:
            invalid += 1
            continue
        try:
            value = json.loads(payload.decode("utf-8-sig"))
            shape = _json_shape(value)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            invalid += 1
            continue
        schemas[_fingerprint_payload(shape)] += 1
        top_types[_json_type(value)] += 1
        categories.update(_json_key_categories(value))
    valid = sum(schemas.values())
    dominant = max(schemas.values(), default=0)
    return JsonSchemaEvidenceSummary(
        valid_document_count=valid,
        invalid_document_count=invalid,
        unique_schema_fingerprints=tuple(sorted(schemas)),
        dominant_schema_count=dominant,
        schema_mismatch_count=valid - dominant,
        top_level_type_counts=dict(sorted(top_types.items())),
        key_category_presence_counts=dict(sorted(categories.items())),
    )


def _collect_midi_summary(
    inputs: tuple[ArchiveInterpretationInput, ...],
    selected: tuple[InterpretedArchiveMember, ...],
) -> MidiHeaderEvidenceSummary:
    observations = _read_selected(inputs, selected, max_probe_bytes=14, exact_bytes=14)
    formats: Counter[str] = Counter()
    tracks: Counter[str] = Counter()
    divisions: Counter[str] = Counter()
    signatures: Counter[str] = Counter()
    invalid = 0
    for header in observations:
        if header is None or len(header) != 14 or header[:4] != b"MThd":
            invalid += 1
            continue
        header_length = int.from_bytes(header[4:8], "big")
        smf_format = int.from_bytes(header[8:10], "big")
        track_count = int.from_bytes(header[10:12], "big")
        division = int.from_bytes(header[12:14], "big")
        if header_length != 6 or smf_format not in {0, 1, 2} or track_count == 0 or division == 0:
            invalid += 1
            continue
        formats[str(smf_format)] += 1
        tracks[str(track_count)] += 1
        divisions[str(division)] += 1
        signatures[_selection_digest(str(smf_format), str(track_count), str(division))] += 1
    return MidiHeaderEvidenceSummary(
        valid_header_count=sum(formats.values()),
        invalid_header_count=invalid,
        format_distribution=dict(sorted(formats.items())),
        track_count_distribution=dict(sorted(tracks.items(), key=lambda item: int(item[0]))),
        division_distribution=dict(sorted(divisions.items(), key=lambda item: int(item[0]))),
        structural_signature_counts=dict(sorted(signatures.items())),
    )


def _read_selected(
    inputs: tuple[ArchiveInterpretationInput, ...],
    selected: tuple[InterpretedArchiveMember, ...],
    *,
    max_probe_bytes: int,
    exact_bytes: int | None = None,
) -> tuple[bytes | None, ...]:
    observed: dict[str, bytes | None] = {}
    by_archive: dict[str, set[str]] = {}
    for member in selected:
        by_archive.setdefault(member.archive_logical_id, set()).add(member.raw_member_fingerprint)
    for item in inputs:
        fingerprints = by_archive.get(item.source.archive_logical_id)
        if not fingerprints:
            continue
        try:
            with zipfile.ZipFile(item.source.path, mode="r") as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    fingerprint = _selection_digest(
                        item.source.candidate_id,
                        item.source.archive_logical_id,
                        info.filename,
                    )
                    if fingerprint not in fingerprints:
                        continue
                    if exact_bytes is None and info.file_size > max_probe_bytes:
                        observed[fingerprint] = None
                    else:
                        with archive.open(info, mode="r") as stream:
                            limit = exact_bytes if exact_bytes is not None else max_probe_bytes + 1
                            payload = stream.read(limit)
                        observed[fingerprint] = (
                            payload
                            if exact_bytes is not None or len(payload) <= max_probe_bytes
                            else None
                        )
        except (
            OSError,
            EOFError,
            RuntimeError,
            ValueError,
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
        ):
            for fingerprint in fingerprints:
                observed.setdefault(fingerprint, None)
    return tuple(observed.get(member.raw_member_fingerprint) for member in selected)


def _validate_collection_binding(
    inputs: tuple[ArchiveInterpretationInput, ...],
    membership: InterpretedArchiveMembership,
    role_policy: CandidateRoleDispositionPolicy,
    plan: RoleEvidenceSamplingPlan,
) -> None:
    if not inputs:
        raise ContractError(
            "SEMANTIC_EVIDENCE_SOURCE_MISSING",
            "Archive interpretation inputs are required for evidence collection.",
        )
    if not (
        membership.candidate_id
        == role_policy.candidate_id
        == plan.candidate_id
        == inputs[0].source.candidate_id
    ) or any(item.source.candidate_id != membership.candidate_id for item in inputs):
        raise ContractError(
            "SEMANTIC_EVIDENCE_CANDIDATE_MISMATCH",
            "Semantic evidence inputs cannot cross candidate scopes.",
        )
    if (
        membership.policy_id != role_policy.path_policy_id
        or membership.policy_version != role_policy.path_policy_version
        or membership.evidence_fingerprint != role_policy.path_evidence_fingerprint
    ):
        raise ContractError(
            "SEMANTIC_EVIDENCE_MEMBERSHIP_MISMATCH",
            "Semantic evidence requires the exact approved path membership fingerprint.",
        )
    archive_ids = {item.source.archive_logical_id for item in inputs}
    if archive_ids != {member.archive_logical_id for member in membership.members}:
        raise ContractError(
            "SEMANTIC_EVIDENCE_SOURCE_MISMATCH",
            "Evidence sources must cover the interpreted archive membership exactly.",
        )


def _validate_review_binding(
    evidence: SemanticRoleEvidence,
    policy: SemanticRoleEvidencePolicy,
) -> None:
    actual = (
        evidence.candidate_id,
        evidence.structural_role,
        evidence.sampling_plan_id,
        evidence.sampling_plan_version,
        evidence.path_policy_id,
        evidence.path_policy_version,
        evidence.path_evidence_fingerprint,
        evidence.companion_policy_id,
        evidence.companion_policy_version,
        evidence.role_policy_id,
        evidence.role_policy_version,
        evidence.observation_kind,
    )
    expected = (
        policy.candidate_id,
        policy.structural_role,
        policy.sampling_plan_id,
        policy.sampling_plan_version,
        policy.path_policy_id,
        policy.path_policy_version,
        policy.path_evidence_fingerprint,
        policy.companion_policy_id,
        policy.companion_policy_version,
        policy.role_policy_id,
        policy.role_policy_version,
        policy.required_observation_kind,
    )
    if actual != expected:
        raise ContractError(
            "SEMANTIC_REVIEW_EVIDENCE_POLICY_MISMATCH",
            "Semantic evidence must match the complete review policy authority.",
        )


def _validate_human_review_binding(
    evidence: SemanticRoleEvidence,
    policy: SemanticRoleEvidencePolicy,
    proposed_role: ProposedSemanticRole,
    review: HumanSemanticRoleReview,
) -> None:
    if (
        review.candidate_id != evidence.candidate_id
        or review.structural_role != evidence.structural_role
        or review.proposed_semantic_role != proposed_role
        or review.evidence_id != evidence.evidence_id
        or review.evidence_fingerprint != evidence.evidence_fingerprint
        or review.evidence_policy_id != policy.policy_id
        or review.evidence_policy_version != policy.policy_version
        or review.reviewer_authority_id not in policy.approved_reviewer_authority_ids
    ):
        raise ContractError(
            "SEMANTIC_REVIEW_HUMAN_AUTHORITY_MISMATCH",
            "Human review authority must bind the exact evidence, policy, and proposed role.",
        )


def _evidence_is_sufficient(
    evidence: SemanticRoleEvidence,
    policy: SemanticRoleEvidencePolicy,
) -> bool:
    if evidence.sample_count < policy.minimum_sample_count:
        return False
    if policy.require_complete_observations and not evidence.raw_evidence_complete:
        return False
    return not (
        policy.maximum_unique_schema_count is not None
        and evidence.json_summary is not None
        and len(evidence.json_summary.unique_schema_fingerprints)
        > policy.maximum_unique_schema_count
    )


def _decision_disposition(decision: SemanticRoleReviewDecision) -> CompanionDisposition:
    if decision.status == SemanticReviewStatus.REVIEW_REQUIRED:
        return CompanionDisposition.REVIEW_REQUIRED
    if decision.status == SemanticReviewStatus.BLOCKED:
        return CompanionDisposition.BLOCKED
    if decision.status == SemanticReviewStatus.REJECTED:
        return CompanionDisposition.EXCLUDE
    mapping = {
        ProposedSemanticRole.PRIMARY_AUDIO_CANDIDATE: CompanionDisposition.INCLUDE_PRIMARY,
        ProposedSemanticRole.CONDITIONING_CANDIDATE: CompanionDisposition.INCLUDE_COMPANION,
        ProposedSemanticRole.SYMBOLIC_COMPANION_CANDIDATE: (CompanionDisposition.INCLUDE_COMPANION),
        ProposedSemanticRole.METADATA_CANDIDATE: CompanionDisposition.METADATA_ONLY,
        ProposedSemanticRole.ANNOTATION_CANDIDATE: CompanionDisposition.METADATA_ONLY,
        ProposedSemanticRole.UNSUPPORTED: CompanionDisposition.EXCLUDE,
    }
    try:
        return mapping[decision.proposed_semantic_role]
    except KeyError as exc:
        raise ContractError(
            "SEMANTIC_REVIEW_APPROVED_ROLE_UNSUPPORTED",
            "Approved semantic role cannot be mapped to a role disposition.",
        ) from exc


def _json_shape(value: Any, *, depth: int = 0) -> Any:
    if depth > 32:
        raise ValueError("JSON nesting exceeds the bounded schema depth")
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {
                str(key): _json_shape(child, depth=depth + 1)
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            },
        }
    if isinstance(value, list):
        element_shapes = {
            json.dumps(_json_shape(child, depth=depth + 1), sort_keys=True, separators=(",", ":"))
            for child in value
        }
        return {"type": "array", "element_shapes": sorted(element_shapes)}
    return {"type": _json_type(value)}


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _json_key_categories(value: Any) -> set[str]:
    categories: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            if "dataset" in normalized:
                categories.add("dataset_like")
            if "annotation" in normalized or "label" in normalized:
                categories.add("annotation_like")
            if any(term in normalized for term in ("source", "reference", "url", "path")):
                categories.add("reference_like")
            categories.update(_json_key_categories(child))
    elif isinstance(value, list):
        for child in value:
            categories.update(_json_key_categories(child))
    return categories


def _invalid_count(evidence: SemanticRoleEvidence) -> int:
    if evidence.json_summary is not None:
        return evidence.json_summary.invalid_document_count
    if evidence.midi_summary is not None:
        return evidence.midi_summary.invalid_header_count
    return 0


def _jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    converted = to_jsonable_python(payload)
    if not isinstance(converted, dict):
        raise TypeError("semantic evidence payload must be a mapping")
    return converted


def _fingerprint_payload(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _selection_digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="surrogatepass")).hexdigest()
