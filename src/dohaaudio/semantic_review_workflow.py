"""Reviewer authority and immutable human semantic-review workflow."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

from dohaaudio.archive_policy import CompanionRole
from dohaaudio.archive_role_policy import CandidateRoleDispositionPolicy
from dohaaudio.contracts import FrozenModel
from dohaaudio.errors import ConflictError, ContractError, NotFoundError
from dohaaudio.security import assert_safe_metadata
from dohaaudio.semantic_role_evidence import (
    HumanReviewOutcome,
    HumanSemanticRoleReview,
    InMemorySemanticRoleEvidenceRegistry,
    ProposedSemanticRole,
    SemanticReviewStatus,
    SemanticRoleEvidence,
    SemanticRoleEvidencePolicy,
    SemanticRoleReviewDecision,
    apply_semantic_review_decisions,
    review_semantic_role,
)

SAFE_REASON = re.compile(r"^SEMANTIC_REVIEW_[A-Z0-9_]+$")


class ReviewerAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ReviewerAuthorityStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class SemanticReviewRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class ReviewerAuthority(FrozenModel):
    authority_id: str = Field(min_length=1)
    authority_version: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    structural_roles: tuple[CompanionRole, ...]
    semantic_roles: tuple[ProposedSemanticRole, ...]
    evidence_policy_ids: tuple[str, ...]
    role_policy_ids: tuple[str, ...]
    allowed_actions: tuple[ReviewerAction, ...]
    status: ReviewerAuthorityStatus
    effective_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    audit_reason_code: str

    @field_validator("reviewer_id")
    @classmethod
    def require_opaque_reviewer_id(cls, value: str) -> str:
        if "@" in value or "\\" in value or any(character.isspace() for character in value):
            raise ValueError("reviewer identity must be an opaque logical identifier")
        return value

    @model_validator(mode="after")
    def validate_authority(self) -> ReviewerAuthority:
        _require_aware(self.effective_at, self.expires_at, self.revoked_at, self.created_at)
        if self.created_at > self.effective_at:
            raise ValueError("authority cannot be created after it becomes effective")
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("authority expiry must follow its effective time")
        if self.status == ReviewerAuthorityStatus.ACTIVE and self.revoked_at is not None:
            raise ValueError("active authority cannot carry a revocation time")
        if self.status == ReviewerAuthorityStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked authority requires a revocation time")
        if self.revoked_at is not None and self.revoked_at < self.effective_at:
            raise ValueError("authority cannot be revoked before it becomes effective")
        _require_nonempty_unique(self.structural_roles, "structural roles")
        _require_nonempty_unique(self.semantic_roles, "semantic roles")
        _require_nonempty_unique(self.evidence_policy_ids, "evidence policy identities")
        _require_nonempty_unique(self.role_policy_ids, "role policy identities")
        _require_nonempty_unique(self.allowed_actions, "review actions")
        _require_reason(self.audit_reason_code)
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class ReviewerAuthorityRevocation(FrozenModel):
    revocation_id: str
    authority_id: str
    authority_version: str
    revoked_at: datetime
    reason_code: str

    @model_validator(mode="after")
    def validate_revocation(self) -> ReviewerAuthorityRevocation:
        _require_aware(self.revoked_at)
        _require_reason(self.reason_code)
        payload = self.model_dump(mode="json", exclude={"revocation_id"})
        expected = f"reviewer-authority-revocation/{_fingerprint(payload)}"
        if self.revocation_id != expected:
            raise ValueError("authority revocation identity must match the complete record")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class ReviewerAuthorityRegistry:
    """Immutable authority and revocation history; authentication is out of scope."""

    def __init__(self) -> None:
        self._authorities: dict[tuple[str, str], ReviewerAuthority] = {}
        self._revocations: dict[tuple[str, str], ReviewerAuthorityRevocation] = {}

    def register(self, authority: ReviewerAuthority) -> ReviewerAuthority:
        key = (authority.authority_id, authority.authority_version)
        current = self._authorities.get(key)
        if current is not None and current != authority:
            raise ConflictError(
                "REVIEWER_AUTHORITY_IMMUTABLE_CONFLICT",
                "Reviewer authority identity and version cannot be overwritten.",
            )
        validated = ReviewerAuthority(**authority.model_dump())
        self._authorities[key] = validated.model_copy(deep=True)
        return validated.model_copy(deep=True)

    def get(self, authority_id: str, authority_version: str) -> ReviewerAuthority:
        try:
            return self._authorities[(authority_id, authority_version)].model_copy(deep=True)
        except KeyError as exc:
            raise NotFoundError("ReviewerAuthority") from exc

    def revoke(
        self,
        authority_id: str,
        authority_version: str,
        *,
        revoked_at: datetime,
        reason_code: str,
    ) -> ReviewerAuthorityRevocation:
        _require_aware(revoked_at)
        authority = self.get(authority_id, authority_version)
        if revoked_at < authority.effective_at:
            raise ContractError(
                "REVIEWER_AUTHORITY_REVOCATION_TIME_INVALID",
                "Reviewer authority cannot be revoked before its effective time.",
            )
        payload = {
            "authority_id": authority_id,
            "authority_version": authority_version,
            "revoked_at": revoked_at,
            "reason_code": reason_code,
        }
        revocation = ReviewerAuthorityRevocation(
            revocation_id=f"reviewer-authority-revocation/{_fingerprint(payload)}",
            **payload,
        )
        key = (authority_id, authority_version)
        current = self._revocations.get(key)
        if current is not None and current != revocation:
            raise ConflictError(
                "REVIEWER_AUTHORITY_REVOCATION_CONFLICT",
                "Reviewer authority version can have only one immutable revocation.",
            )
        self._revocations[key] = revocation.model_copy(deep=True)
        return revocation.model_copy(deep=True)

    def require_authorized(
        self,
        *,
        authority_id: str,
        authority_version: str,
        reviewer_id: str,
        action: ReviewerAction,
        candidate_id: str,
        structural_role: CompanionRole,
        semantic_role: ProposedSemanticRole,
        evidence_policy_id: str,
        role_policy_id: str,
        at: datetime,
    ) -> ReviewerAuthority:
        _require_aware(at)
        authority = self.get(authority_id, authority_version)
        if authority.status == ReviewerAuthorityStatus.REVOKED or (
            authority.revoked_at is not None and authority.revoked_at <= at
        ):
            raise ContractError(
                "REVIEWER_AUTHORITY_REVOKED", "Revoked reviewer authority cannot be used."
            )
        revocation = self._revocations.get((authority_id, authority_version))
        if revocation is not None and revocation.revoked_at <= at:
            raise ContractError(
                "REVIEWER_AUTHORITY_REVOKED", "Revoked reviewer authority cannot be used."
            )
        if at < authority.effective_at:
            raise ContractError(
                "REVIEWER_AUTHORITY_NOT_EFFECTIVE",
                "Reviewer authority is not effective at the requested time.",
            )
        if authority.expires_at is not None and at >= authority.expires_at:
            raise ContractError(
                "REVIEWER_AUTHORITY_EXPIRED", "Expired reviewer authority cannot be used."
            )
        if authority.reviewer_id != reviewer_id:
            raise ContractError(
                "REVIEWER_AUTHORITY_IDENTITY_MISMATCH",
                "Reviewer identity must match the registered authority.",
            )
        if (
            authority.candidate_id != candidate_id
            or structural_role not in authority.structural_roles
            or semantic_role not in authority.semantic_roles
            or evidence_policy_id not in authority.evidence_policy_ids
            or role_policy_id not in authority.role_policy_ids
            or action not in authority.allowed_actions
        ):
            raise ContractError(
                "REVIEWER_AUTHORITY_SCOPE_MISMATCH",
                "Reviewer authority does not cover the exact review scope.",
            )
        return authority


class SemanticReviewRequest(FrozenModel):
    request_id: str
    request_version: str
    candidate_id: str
    structural_role: CompanionRole
    proposed_semantic_role: ProposedSemanticRole
    evidence_id: str
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    membership_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampling_plan_id: str
    sampling_plan_version: str
    path_policy_id: str
    path_policy_version: str
    path_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    companion_policy_id: str
    companion_policy_version: str
    role_policy_id: str
    role_policy_version: str
    evidence_policy_id: str
    evidence_policy_version: str
    status: SemanticReviewRequestStatus = SemanticReviewRequestStatus.PENDING
    supersedes_request_id: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_request(self) -> SemanticReviewRequest:
        _require_aware(self.created_at)
        if self.status != SemanticReviewRequestStatus.PENDING:
            raise ValueError("new immutable review requests must start pending")
        payload = self.model_dump(mode="json", exclude={"request_id"})
        expected = f"semantic-review-request/{_fingerprint(payload)}"
        if self.request_id != expected:
            raise ValueError("semantic review request identity must match the complete record")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class SemanticReviewRequestResolution(FrozenModel):
    resolution_id: str
    request_id: str
    status: SemanticReviewRequestStatus
    decision_id: str | None = None
    superseding_request_id: str | None = None
    resolved_at: datetime
    reason_code: str

    @model_validator(mode="after")
    def validate_resolution(self) -> SemanticReviewRequestResolution:
        _require_aware(self.resolved_at)
        if self.status == SemanticReviewRequestStatus.PENDING:
            raise ValueError("pending is not a terminal request resolution")
        decision_status = self.status in {
            SemanticReviewRequestStatus.APPROVED,
            SemanticReviewRequestStatus.REJECTED,
        }
        if decision_status != (self.decision_id is not None):
            raise ValueError("approved or rejected request resolution requires a decision")
        if (self.status == SemanticReviewRequestStatus.SUPERSEDED) != (
            self.superseding_request_id is not None
        ):
            raise ValueError("superseded resolution requires the replacement request")
        _require_reason(self.reason_code)
        payload = self.model_dump(mode="json", exclude={"resolution_id"})
        expected = f"semantic-review-resolution/{_fingerprint(payload)}"
        if self.resolution_id != expected:
            raise ValueError("request resolution identity must match the complete record")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class SemanticReviewRequestRegistry:
    def __init__(self) -> None:
        self._requests: dict[str, SemanticReviewRequest] = {}
        self._resolutions: dict[str, SemanticReviewRequestResolution] = {}

    def publish(self, request: SemanticReviewRequest) -> SemanticReviewRequest:
        current = self._requests.get(request.request_id)
        if current is not None and current != request:
            raise ConflictError(
                "SEMANTIC_REVIEW_REQUEST_IMMUTABLE_CONFLICT",
                "Semantic review request identity cannot be overwritten.",
            )
        validated = SemanticReviewRequest(**request.model_dump())
        self._requests[request.request_id] = validated.model_copy(deep=True)
        return validated.model_copy(deep=True)

    def get(self, request_id: str) -> SemanticReviewRequest:
        try:
            return self._requests[request_id].model_copy(deep=True)
        except KeyError as exc:
            raise NotFoundError("SemanticReviewRequest") from exc

    def status(self, request_id: str) -> SemanticReviewRequestStatus:
        self.get(request_id)
        resolution = self._resolutions.get(request_id)
        return resolution.status if resolution is not None else SemanticReviewRequestStatus.PENDING

    def resolve(
        self, resolution: SemanticReviewRequestResolution
    ) -> SemanticReviewRequestResolution:
        self.get(resolution.request_id)
        current = self._resolutions.get(resolution.request_id)
        if current is not None and current != resolution:
            raise ConflictError(
                "SEMANTIC_REVIEW_REQUEST_TERMINAL_CONFLICT",
                "A semantic review request can have only one terminal resolution.",
            )
        validated = SemanticReviewRequestResolution(**resolution.model_dump())
        self._resolutions[validated.request_id] = validated.model_copy(deep=True)
        return validated.model_copy(deep=True)

    def resolution(self, request_id: str) -> SemanticReviewRequestResolution:
        self.get(request_id)
        try:
            return self._resolutions[request_id].model_copy(deep=True)
        except KeyError as exc:
            raise NotFoundError("SemanticReviewRequestResolution") from exc

    def require_pending(self, request_id: str) -> SemanticReviewRequest:
        request = self.get(request_id)
        if self.status(request_id) != SemanticReviewRequestStatus.PENDING:
            raise ConflictError(
                "SEMANTIC_REVIEW_REQUEST_NOT_PENDING",
                "Only a pending semantic review request can be decided.",
            )
        return request


class HumanSemanticReviewDecision(FrozenModel):
    decision_id: str
    decision_version: str
    request_id: str
    reviewer_authority_id: str
    reviewer_authority_version: str
    reviewer_id: str
    status: HumanReviewOutcome
    candidate_id: str
    structural_role: CompanionRole
    proposed_semantic_role: ProposedSemanticRole
    evidence_id: str
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    membership_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_policy_id: str
    evidence_policy_version: str
    sampling_plan_id: str
    sampling_plan_version: str
    path_policy_id: str
    path_policy_version: str
    path_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    companion_policy_id: str
    companion_policy_version: str
    role_policy_id: str
    role_policy_version: str
    reason_code: str
    decided_at: datetime

    @model_validator(mode="after")
    def validate_decision(self) -> HumanSemanticReviewDecision:
        _require_aware(self.decided_at)
        _require_reason(self.reason_code)
        payload = self.model_dump(mode="json", exclude={"decision_id"})
        expected = f"human-semantic-review-decision/{_fingerprint(payload)}"
        if self.decision_id != expected:
            raise ValueError("human semantic decision identity must match the complete record")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class HumanSemanticReviewDecisionRegistry:
    def __init__(self) -> None:
        self._decisions: dict[str, HumanSemanticReviewDecision] = {}
        self._by_request: dict[str, str] = {}

    def publish(self, decision: HumanSemanticReviewDecision) -> HumanSemanticReviewDecision:
        current = self._decisions.get(decision.decision_id)
        if current is not None and current != decision:
            raise ConflictError(
                "HUMAN_SEMANTIC_DECISION_IMMUTABLE_CONFLICT",
                "Human semantic review decision identity cannot be overwritten.",
            )
        validated = HumanSemanticReviewDecision(**decision.model_dump())
        request_decision_id = self._by_request.get(validated.request_id)
        if request_decision_id is not None and request_decision_id != validated.decision_id:
            raise ConflictError(
                "HUMAN_SEMANTIC_DECISION_REQUEST_CONFLICT",
                "A semantic review request can have only one terminal decision.",
            )
        self._decisions[validated.decision_id] = validated.model_copy(deep=True)
        self._by_request[validated.request_id] = validated.decision_id
        return validated.model_copy(deep=True)

    def get_for_request(self, request_id: str) -> HumanSemanticReviewDecision:
        try:
            return self._decisions[self._by_request[request_id]].model_copy(deep=True)
        except KeyError as exc:
            raise NotFoundError("HumanSemanticReviewDecision") from exc


class HumanSemanticReviewWorkflow:
    """Domain authorization workflow; caller authentication remains external."""

    def __init__(
        self,
        evidence_registry: InMemorySemanticRoleEvidenceRegistry,
        authority_registry: ReviewerAuthorityRegistry,
        request_registry: SemanticReviewRequestRegistry,
        decision_registry: HumanSemanticReviewDecisionRegistry,
    ) -> None:
        self._evidence = evidence_registry
        self._authorities = authority_registry
        self._requests = request_registry
        self._decisions = decision_registry

    def create_request(
        self,
        evidence: SemanticRoleEvidence,
        evidence_policy: SemanticRoleEvidencePolicy,
        role_policy: CandidateRoleDispositionPolicy,
        proposed_semantic_role: ProposedSemanticRole,
        *,
        created_at: datetime,
        supersedes_request_id: str | None = None,
    ) -> SemanticReviewRequest:
        self._validate_current(evidence, evidence_policy, role_policy)
        payload: dict[str, Any] = {
            "request_version": "1.0.0",
            "candidate_id": evidence.candidate_id,
            "structural_role": evidence.structural_role,
            "proposed_semantic_role": proposed_semantic_role,
            "evidence_id": evidence.evidence_id,
            "evidence_fingerprint": evidence.evidence_fingerprint,
            "membership_fingerprint": evidence.membership_fingerprint,
            "sampling_plan_id": evidence.sampling_plan_id,
            "sampling_plan_version": evidence.sampling_plan_version,
            "path_policy_id": evidence.path_policy_id,
            "path_policy_version": evidence.path_policy_version,
            "path_evidence_fingerprint": evidence.path_evidence_fingerprint,
            "companion_policy_id": evidence.companion_policy_id,
            "companion_policy_version": evidence.companion_policy_version,
            "role_policy_id": evidence.role_policy_id,
            "role_policy_version": evidence.role_policy_version,
            "evidence_policy_id": evidence_policy.policy_id,
            "evidence_policy_version": evidence_policy.policy_version,
            "status": SemanticReviewRequestStatus.PENDING,
            "supersedes_request_id": supersedes_request_id,
            "created_at": created_at,
        }
        request = SemanticReviewRequest(
            request_id=f"semantic-review-request/{_fingerprint(payload)}", **payload
        )
        if supersedes_request_id is not None:
            previous = self._requests.require_pending(supersedes_request_id)
            if (
                previous.candidate_id != request.candidate_id
                or previous.structural_role != request.structural_role
                or previous.proposed_semantic_role != request.proposed_semantic_role
            ):
                raise ContractError(
                    "SEMANTIC_REVIEW_SUPERSESSION_SCOPE_MISMATCH",
                    "A replacement request must preserve candidate and role scope.",
                )
        published = self._requests.publish(request)
        if supersedes_request_id is not None:
            self._resolve_request(
                supersedes_request_id,
                SemanticReviewRequestStatus.SUPERSEDED,
                created_at,
                "SEMANTIC_REVIEW_REQUEST_SUPERSEDED",
                superseding_request_id=request.request_id,
            )
        return published

    def cancel_request(
        self, request_id: str, *, cancelled_at: datetime
    ) -> SemanticReviewRequestResolution:
        self._requests.require_pending(request_id)
        return self._resolve_request(
            request_id,
            SemanticReviewRequestStatus.CANCELLED,
            cancelled_at,
            "SEMANTIC_REVIEW_REQUEST_CANCELLED",
        )

    def submit_decision(
        self,
        request_id: str,
        *,
        authority_id: str,
        authority_version: str,
        reviewer_id: str,
        outcome: HumanReviewOutcome,
        reason_code: str,
        decided_at: datetime,
        current_evidence: SemanticRoleEvidence,
        current_evidence_policy: SemanticRoleEvidencePolicy,
        current_role_policy: CandidateRoleDispositionPolicy,
    ) -> HumanSemanticReviewDecision:
        request = self._requests.require_pending(request_id)
        self._validate_request_current(
            request, current_evidence, current_evidence_policy, current_role_policy
        )
        action = (
            ReviewerAction.APPROVE
            if outcome == HumanReviewOutcome.APPROVED
            else ReviewerAction.REJECT
        )
        self._require_authority(
            request,
            current_evidence_policy,
            authority_id,
            authority_version,
            reviewer_id,
            action,
            decided_at,
        )
        payload = _decision_payload(
            request,
            authority_id=authority_id,
            authority_version=authority_version,
            reviewer_id=reviewer_id,
            outcome=outcome,
            reason_code=reason_code,
            decided_at=decided_at,
        )
        decision = HumanSemanticReviewDecision(
            decision_id=f"human-semantic-review-decision/{_fingerprint(payload)}", **payload
        )
        preview = self._legacy_decision(decision, current_evidence, current_evidence_policy)
        if (
            outcome == HumanReviewOutcome.APPROVED
            and preview.status != SemanticReviewStatus.APPROVED
        ):
            raise ContractError(
                "HUMAN_SEMANTIC_REVIEW_EVIDENCE_INSUFFICIENT",
                "Human approval cannot bypass semantic evidence sufficiency policy.",
            )
        self._decisions.publish(decision)
        request_status = (
            SemanticReviewRequestStatus.APPROVED
            if outcome == HumanReviewOutcome.APPROVED
            else SemanticReviewRequestStatus.REJECTED
        )
        self._resolve_request(
            request_id,
            request_status,
            decided_at,
            reason_code,
            decision_id=decision.decision_id,
        )
        return decision

    def consume_decision(
        self,
        request_id: str,
        *,
        current_evidence: SemanticRoleEvidence,
        current_evidence_policy: SemanticRoleEvidencePolicy,
        current_role_policy: CandidateRoleDispositionPolicy,
        consumed_at: datetime,
    ) -> SemanticRoleReviewDecision:
        request = self._requests.get(request_id)
        decision = self._decisions.get_for_request(request_id)
        if not _decision_matches_request(decision, request):
            raise ContractError(
                "HUMAN_SEMANTIC_DECISION_REQUEST_MISMATCH",
                "Human semantic decision must bind the exact immutable request.",
            )
        self._validate_request_current(
            request, current_evidence, current_evidence_policy, current_role_policy
        )
        action = (
            ReviewerAction.APPROVE
            if decision.status == HumanReviewOutcome.APPROVED
            else ReviewerAction.REJECT
        )
        self._require_authority(
            request,
            current_evidence_policy,
            decision.reviewer_authority_id,
            decision.reviewer_authority_version,
            decision.reviewer_id,
            action,
            consumed_at,
        )
        expected_status = (
            SemanticReviewRequestStatus.APPROVED
            if decision.status == HumanReviewOutcome.APPROVED
            else SemanticReviewRequestStatus.REJECTED
        )
        resolution = self._requests.resolution(request_id)
        if resolution.status != expected_status or resolution.decision_id != decision.decision_id:
            raise ContractError(
                "SEMANTIC_REVIEW_REQUEST_DECISION_MISMATCH",
                "Request resolution must match its immutable decision.",
            )
        return self._legacy_decision(decision, current_evidence, current_evidence_policy)

    def apply_to_role_policy(
        self,
        role_policy: CandidateRoleDispositionPolicy,
        request_ids: Iterable[str],
        current_evidences: Iterable[SemanticRoleEvidence],
        current_evidence_policies: Iterable[SemanticRoleEvidencePolicy],
        *,
        consumed_at: datetime,
    ) -> CandidateRoleDispositionPolicy:
        request_records = tuple(self._requests.get(request_id) for request_id in request_ids)
        evidence_records = tuple(current_evidences)
        policy_records = tuple(current_evidence_policies)
        requests_by_role = {request.structural_role: request for request in request_records}
        evidences_by_role = {evidence.structural_role: evidence for evidence in evidence_records}
        policies_by_role = {policy.structural_role: policy for policy in policy_records}
        if (
            len(requests_by_role) != len(request_records)
            or len(evidences_by_role) != len(evidence_records)
            or len(policies_by_role) != len(policy_records)
        ):
            raise ContractError(
                "SEMANTIC_REVIEW_WORKFLOW_ROLE_DUPLICATE",
                "Workflow consumption requires one request, evidence, and policy per role.",
            )
        if (
            set(requests_by_role) != set(CompanionRole)
            or set(evidences_by_role) != set(CompanionRole)
            or set(policies_by_role) != set(CompanionRole)
        ):
            raise ContractError(
                "SEMANTIC_REVIEW_WORKFLOW_ROLE_SET_INCOMPLETE",
                "Workflow consumption requires every structural role.",
            )
        decisions = tuple(
            self.consume_decision(
                request.request_id,
                current_evidence=evidences_by_role[role],
                current_evidence_policy=policies_by_role[role],
                current_role_policy=role_policy,
                consumed_at=consumed_at,
            )
            for role, request in requests_by_role.items()
        )
        return apply_semantic_review_decisions(
            role_policy,
            decisions,
            evidence_records,
            policy_records,
        )

    def _validate_current(
        self,
        evidence: SemanticRoleEvidence,
        evidence_policy: SemanticRoleEvidencePolicy,
        role_policy: CandidateRoleDispositionPolicy,
    ) -> None:
        if self._evidence.get(evidence.evidence_id) != evidence:
            raise ContractError(
                "SEMANTIC_REVIEW_CURRENT_EVIDENCE_MISMATCH",
                "Review workflow requires the exact registered current evidence.",
            )
        if not _evidence_policy_matches(evidence, evidence_policy, role_policy):
            raise ContractError(
                "SEMANTIC_REVIEW_CURRENT_POLICY_MISMATCH",
                "Review workflow requires exact current evidence and role policies.",
            )

    def _validate_request_current(
        self,
        request: SemanticReviewRequest,
        evidence: SemanticRoleEvidence,
        evidence_policy: SemanticRoleEvidencePolicy,
        role_policy: CandidateRoleDispositionPolicy,
    ) -> None:
        self._validate_current(evidence, evidence_policy, role_policy)
        if not _request_matches(request, evidence, evidence_policy, role_policy):
            raise ContractError(
                "SEMANTIC_REVIEW_REQUEST_STALE",
                "Review request no longer matches current evidence and policy authority.",
            )

    def _require_authority(
        self,
        request: SemanticReviewRequest,
        evidence_policy: SemanticRoleEvidencePolicy,
        authority_id: str,
        authority_version: str,
        reviewer_id: str,
        action: ReviewerAction,
        at: datetime,
    ) -> ReviewerAuthority:
        if authority_id not in evidence_policy.approved_reviewer_authority_ids:
            raise ContractError(
                "REVIEWER_AUTHORITY_EVIDENCE_POLICY_MISMATCH",
                "Evidence policy must explicitly allow the reviewer authority.",
            )
        return self._authorities.require_authorized(
            authority_id=authority_id,
            authority_version=authority_version,
            reviewer_id=reviewer_id,
            action=action,
            candidate_id=request.candidate_id,
            structural_role=request.structural_role,
            semantic_role=request.proposed_semantic_role,
            evidence_policy_id=request.evidence_policy_id,
            role_policy_id=request.role_policy_id,
            at=at,
        )

    @staticmethod
    def _legacy_decision(
        decision: HumanSemanticReviewDecision,
        evidence: SemanticRoleEvidence,
        evidence_policy: SemanticRoleEvidencePolicy,
    ) -> SemanticRoleReviewDecision:
        human_review = HumanSemanticRoleReview(
            review_id=decision.decision_id,
            reviewer_authority_id=decision.reviewer_authority_id,
            candidate_id=decision.candidate_id,
            structural_role=decision.structural_role,
            proposed_semantic_role=decision.proposed_semantic_role,
            evidence_id=decision.evidence_id,
            evidence_fingerprint=decision.evidence_fingerprint,
            evidence_policy_id=decision.evidence_policy_id,
            evidence_policy_version=decision.evidence_policy_version,
            outcome=decision.status,
            reviewed_at=decision.decided_at,
        )
        return review_semantic_role(
            evidence,
            evidence_policy,
            decision.proposed_semantic_role,
            human_review=human_review,
        )

    def _resolve_request(
        self,
        request_id: str,
        status: SemanticReviewRequestStatus,
        resolved_at: datetime,
        reason_code: str,
        *,
        decision_id: str | None = None,
        superseding_request_id: str | None = None,
    ) -> SemanticReviewRequestResolution:
        payload = {
            "request_id": request_id,
            "status": status,
            "decision_id": decision_id,
            "superseding_request_id": superseding_request_id,
            "resolved_at": resolved_at,
            "reason_code": reason_code,
        }
        resolution = SemanticReviewRequestResolution(
            resolution_id=f"semantic-review-resolution/{_fingerprint(payload)}", **payload
        )
        return self._requests.resolve(resolution)


def _decision_payload(
    request: SemanticReviewRequest,
    *,
    authority_id: str,
    authority_version: str,
    reviewer_id: str,
    outcome: HumanReviewOutcome,
    reason_code: str,
    decided_at: datetime,
) -> dict[str, Any]:
    return {
        "decision_version": "1.0.0",
        "request_id": request.request_id,
        "reviewer_authority_id": authority_id,
        "reviewer_authority_version": authority_version,
        "reviewer_id": reviewer_id,
        "status": outcome,
        "candidate_id": request.candidate_id,
        "structural_role": request.structural_role,
        "proposed_semantic_role": request.proposed_semantic_role,
        "evidence_id": request.evidence_id,
        "evidence_fingerprint": request.evidence_fingerprint,
        "membership_fingerprint": request.membership_fingerprint,
        "evidence_policy_id": request.evidence_policy_id,
        "evidence_policy_version": request.evidence_policy_version,
        "sampling_plan_id": request.sampling_plan_id,
        "sampling_plan_version": request.sampling_plan_version,
        "path_policy_id": request.path_policy_id,
        "path_policy_version": request.path_policy_version,
        "path_evidence_fingerprint": request.path_evidence_fingerprint,
        "companion_policy_id": request.companion_policy_id,
        "companion_policy_version": request.companion_policy_version,
        "role_policy_id": request.role_policy_id,
        "role_policy_version": request.role_policy_version,
        "reason_code": reason_code,
        "decided_at": decided_at,
    }


def _evidence_policy_matches(
    evidence: SemanticRoleEvidence,
    policy: SemanticRoleEvidencePolicy,
    role_policy: CandidateRoleDispositionPolicy,
) -> bool:
    return (
        evidence.candidate_id == policy.candidate_id == role_policy.candidate_id
        and evidence.structural_role == policy.structural_role
        and (evidence.sampling_plan_id, evidence.sampling_plan_version)
        == (policy.sampling_plan_id, policy.sampling_plan_version)
        and (evidence.path_policy_id, evidence.path_policy_version)
        == (policy.path_policy_id, policy.path_policy_version)
        == (role_policy.path_policy_id, role_policy.path_policy_version)
        and evidence.path_evidence_fingerprint
        == policy.path_evidence_fingerprint
        == role_policy.path_evidence_fingerprint
        and (evidence.companion_policy_id, evidence.companion_policy_version)
        == (policy.companion_policy_id, policy.companion_policy_version)
        == (role_policy.companion_policy_id, role_policy.companion_policy_version)
        and (evidence.role_policy_id, evidence.role_policy_version)
        == (policy.role_policy_id, policy.role_policy_version)
        == (role_policy.policy_id, role_policy.policy_version)
        and evidence.observation_kind == policy.required_observation_kind
    )


def _request_matches(
    request: SemanticReviewRequest,
    evidence: SemanticRoleEvidence,
    policy: SemanticRoleEvidencePolicy,
    role_policy: CandidateRoleDispositionPolicy,
) -> bool:
    return _evidence_policy_matches(evidence, policy, role_policy) and (
        request.candidate_id,
        request.structural_role,
        request.evidence_id,
        request.evidence_fingerprint,
        request.membership_fingerprint,
        request.sampling_plan_id,
        request.sampling_plan_version,
        request.path_policy_id,
        request.path_policy_version,
        request.path_evidence_fingerprint,
        request.companion_policy_id,
        request.companion_policy_version,
        request.role_policy_id,
        request.role_policy_version,
        request.evidence_policy_id,
        request.evidence_policy_version,
    ) == (
        evidence.candidate_id,
        evidence.structural_role,
        evidence.evidence_id,
        evidence.evidence_fingerprint,
        evidence.membership_fingerprint,
        evidence.sampling_plan_id,
        evidence.sampling_plan_version,
        evidence.path_policy_id,
        evidence.path_policy_version,
        evidence.path_evidence_fingerprint,
        evidence.companion_policy_id,
        evidence.companion_policy_version,
        evidence.role_policy_id,
        evidence.role_policy_version,
        policy.policy_id,
        policy.policy_version,
    )


def _decision_matches_request(
    decision: HumanSemanticReviewDecision,
    request: SemanticReviewRequest,
) -> bool:
    return (
        decision.request_id,
        decision.candidate_id,
        decision.structural_role,
        decision.proposed_semantic_role,
        decision.evidence_id,
        decision.evidence_fingerprint,
        decision.membership_fingerprint,
        decision.evidence_policy_id,
        decision.evidence_policy_version,
        decision.sampling_plan_id,
        decision.sampling_plan_version,
        decision.path_policy_id,
        decision.path_policy_version,
        decision.path_evidence_fingerprint,
        decision.companion_policy_id,
        decision.companion_policy_version,
        decision.role_policy_id,
        decision.role_policy_version,
    ) == (
        request.request_id,
        request.candidate_id,
        request.structural_role,
        request.proposed_semantic_role,
        request.evidence_id,
        request.evidence_fingerprint,
        request.membership_fingerprint,
        request.evidence_policy_id,
        request.evidence_policy_version,
        request.sampling_plan_id,
        request.sampling_plan_version,
        request.path_policy_id,
        request.path_policy_version,
        request.path_evidence_fingerprint,
        request.companion_policy_id,
        request.companion_policy_version,
        request.role_policy_id,
        request.role_policy_version,
    )


def _fingerprint(payload: Any) -> str:
    canonical = to_jsonable_python(payload)
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_reason(value: str) -> None:
    if not SAFE_REASON.fullmatch(value):
        raise ValueError("semantic review audit metadata requires a safe reason code")


def _require_nonempty_unique(values: tuple[Any, ...], label: str) -> None:
    if not values or len(set(values)) != len(values):
        raise ValueError(f"{label} must be non-empty and unique")


def _require_aware(*values: datetime | None) -> None:
    if any(value is not None and value.tzinfo is None for value in values):
        raise ValueError("semantic review timestamps must be timezone-aware")
