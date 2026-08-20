"""Candidate-bound structural group and semantic role disposition policy."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

from pydantic import Field, model_validator

from dohaaudio.archive_policy import (
    CompanionDisposition,
    CompanionRelationshipGroup,
    CompanionRelationshipResult,
    CompanionRole,
    InterpretedArchiveMember,
    InterpretedArchiveMembership,
)
from dohaaudio.contracts import FrozenModel
from dohaaudio.errors import ContractError
from dohaaudio.security import assert_safe_metadata


class CompanionGroupKind(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ORPHAN = "orphan"
    DUPLICATE = "duplicate"
    BLOCKED = "blocked"


class StructuralGroupDisposition(StrEnum):
    INCLUDE = "structural_include"
    EXCLUDE = "exclude"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"


class CandidateRoleDispositionPolicy(FrozenModel):
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    path_policy_id: str = Field(min_length=1)
    path_policy_version: str = Field(min_length=1)
    path_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    companion_policy_id: str = Field(min_length=1)
    companion_policy_version: str = Field(min_length=1)
    role_dispositions: dict[CompanionRole, CompanionDisposition]
    complete_group_disposition: StructuralGroupDisposition
    partial_group_disposition: StructuralGroupDisposition
    orphan_group_disposition: StructuralGroupDisposition

    @model_validator(mode="after")
    def validate_policy(self) -> CandidateRoleDispositionPolicy:
        if set(self.role_dispositions) != set(CompanionRole):
            raise ValueError("role policy must classify every structural role")
        disallowed = StructuralGroupDisposition.INCLUDE
        if self.partial_group_disposition == disallowed:
            raise ValueError("partial groups cannot be silently included")
        if self.orphan_group_disposition == disallowed:
            raise ValueError("orphan groups cannot be silently included")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class CompanionGroupIngestionDecision(FrozenModel):
    group_logical_id: str = Field(min_length=1)
    group_kind: CompanionGroupKind
    roles: tuple[CompanionRole, ...]
    member_count: int = Field(gt=0)
    disposition: StructuralGroupDisposition
    structural_included: bool
    semantic_review_required: bool
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_decision(self) -> CompanionGroupIngestionDecision:
        if self.member_count != len(self.roles):
            raise ValueError("member count must match classified roles")
        if self.structural_included != (self.disposition == StructuralGroupDisposition.INCLUDE):
            raise ValueError("structural inclusion must match the group disposition")
        if not self.reason_codes or any(
            not reason.startswith("ROLE_POLICY_") for reason in self.reason_codes
        ):
            raise ValueError("group decisions require safe role-policy reason codes")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class CandidateIngestionDecision(FrozenModel):
    candidate_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    path_policy_id: str = Field(min_length=1)
    path_policy_version: str = Field(min_length=1)
    path_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    companion_policy_id: str = Field(min_length=1)
    companion_policy_version: str = Field(min_length=1)
    source_relationship_pass: bool
    path_interpretation_pass: bool
    total_group_count: int = Field(ge=0)
    complete_group_count: int = Field(ge=0)
    partial_group_count: int = Field(ge=0)
    orphan_group_count: int = Field(ge=0)
    duplicate_role_group_count: int = Field(ge=0)
    structurally_included_group_count: int = Field(ge=0)
    review_required_group_count: int = Field(ge=0)
    blocked_group_count: int = Field(ge=0)
    excluded_group_count: int = Field(ge=0)
    role_dispositions: dict[CompanionRole, CompanionDisposition]
    role_policy_resolved: bool
    group_policy_resolved: bool
    structural_candidate_ready: bool
    inventory_ready: bool
    blocking_reasons: tuple[str, ...]
    groups: tuple[CompanionGroupIngestionDecision, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> CandidateIngestionDecision:
        if self.total_group_count != len(self.groups):
            raise ValueError("total group count must match group decisions")
        kinds = Counter(group.group_kind for group in self.groups)
        required_roles = {
            CompanionRole.AUDIO,
            CompanionRole.JSON,
            CompanionRole.MIDI,
        }
        partial_count = sum(not required_roles.issubset(group.roles) for group in self.groups)
        duplicate_count = sum(
            any(count > 1 for count in Counter(group.roles).values()) for group in self.groups
        )
        if self.complete_group_count != kinds[CompanionGroupKind.COMPLETE]:
            raise ValueError("complete group count must match decisions")
        if self.partial_group_count != partial_count:
            raise ValueError("partial group count must match decisions")
        orphan_count = sum(len(set(group.roles) & required_roles) == 1 for group in self.groups)
        if self.orphan_group_count != orphan_count:
            raise ValueError("orphan group count must match decisions")
        if self.duplicate_role_group_count != duplicate_count:
            raise ValueError("duplicate-role group count must match decisions")
        dispositions = Counter(group.disposition for group in self.groups)
        if (
            self.structurally_included_group_count
            != dispositions[StructuralGroupDisposition.INCLUDE]
        ):
            raise ValueError("included group count must match decisions")
        if (
            self.review_required_group_count
            != dispositions[StructuralGroupDisposition.REVIEW_REQUIRED]
        ):
            raise ValueError("review-required group count must match decisions")
        if self.blocked_group_count != dispositions[StructuralGroupDisposition.BLOCKED]:
            raise ValueError("blocked group count must match decisions")
        if self.excluded_group_count != dispositions[StructuralGroupDisposition.EXCLUDE]:
            raise ValueError("excluded group count must match decisions")
        if set(self.role_dispositions) != set(CompanionRole):
            raise ValueError("role dispositions must classify every structural role")

        expected_relationship_pass = (
            self.path_interpretation_pass
            and bool(self.groups)
            and self.complete_group_count == self.total_group_count
        )
        if self.source_relationship_pass != expected_relationship_pass:
            raise ValueError("source relationship pass must match group decisions")
        unresolved_roles = {
            CompanionDisposition.REVIEW_REQUIRED,
            CompanionDisposition.BLOCKED,
        }
        for group in self.groups:
            semantic_review_required = any(
                self.role_dispositions[role] in unresolved_roles for role in set(group.roles)
            )
            if group.semantic_review_required != semantic_review_required:
                raise ValueError("semantic review must match role dispositions")

        role_policy_resolved = not any(
            disposition in unresolved_roles for disposition in self.role_dispositions.values()
        )
        group_policy_resolved = not (
            dispositions[StructuralGroupDisposition.REVIEW_REQUIRED]
            or dispositions[StructuralGroupDisposition.BLOCKED]
        )
        structural_candidate_ready = (
            self.path_interpretation_pass
            and group_policy_resolved
            and dispositions[StructuralGroupDisposition.INCLUDE] > 0
        )
        inventory_ready = structural_candidate_ready and role_policy_resolved
        if self.role_policy_resolved != role_policy_resolved:
            raise ValueError("role-policy resolution must match role dispositions")
        if self.group_policy_resolved != group_policy_resolved:
            raise ValueError("group-policy resolution must match group decisions")
        if self.structural_candidate_ready != structural_candidate_ready:
            raise ValueError("structural readiness must match path and group decisions")
        if self.inventory_ready != inventory_ready:
            raise ValueError("inventory readiness must match structural and role resolution")

        reasons: list[str] = []
        if not self.path_interpretation_pass:
            reasons.append("ROLE_POLICY_PATH_INTERPRETATION_BLOCKED")
        if dispositions[StructuralGroupDisposition.BLOCKED]:
            reasons.append("ROLE_POLICY_GROUP_BLOCKED")
        if dispositions[StructuralGroupDisposition.REVIEW_REQUIRED]:
            reasons.append("ROLE_POLICY_GROUP_REVIEW_REQUIRED")
        if not role_policy_resolved:
            reasons.append("ROLE_POLICY_SEMANTIC_REVIEW_REQUIRED")
        if not dispositions[StructuralGroupDisposition.INCLUDE]:
            reasons.append("ROLE_POLICY_NO_STRUCTURAL_GROUPS")
        if self.blocking_reasons != tuple(reasons):
            raise ValueError("blocking reasons must match decision state")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


def music_loop_role_disposition_policy() -> CandidateRoleDispositionPolicy:
    return _review_required_candidate_policy(
        candidate_id="aihub-098-music-loop-package",
        policy_id="archive-role/aihub-098/structural-review/v1",
        path_policy_id="archive-path/aihub-098/single-root/v1",
        path_evidence_fingerprint=(
            "04255f888f97f3e6813951a304b01dd734da56fb48c4966203a554d694e71f8b"
        ),
        companion_policy_id="archive-companion/aihub-098/directory-stem/v1",
    )


def traditional_music_role_disposition_policy() -> CandidateRoleDispositionPolicy:
    return _review_required_candidate_policy(
        candidate_id="aihub-209-traditional-music-package",
        policy_id="archive-role/aihub-209/structural-review/v1",
        path_policy_id="archive-path/aihub-209/single-root/v1",
        path_evidence_fingerprint=(
            "b5f15f00a650f07d88bb586e6ffbea3f1c6d3a083e58e882a7a0277444ffd7c1"
        ),
        companion_policy_id="archive-companion/aihub-209/directory-stem/v1",
    )


def decide_candidate_ingestion(
    membership: InterpretedArchiveMembership,
    relationships: CompanionRelationshipResult,
    policy: CandidateRoleDispositionPolicy,
) -> CandidateIngestionDecision:
    """Resolve a path-free structural view without issuing enrollment authority."""

    _validate_policy_binding(membership, relationships, policy)
    _validate_relationship_evidence(membership, relationships)
    decisions = tuple(_decide_group(group, policy) for group in relationships.groups)
    dispositions = Counter(decision.disposition for decision in decisions)
    unresolved_roles = {
        CompanionDisposition.REVIEW_REQUIRED,
        CompanionDisposition.BLOCKED,
    }
    role_policy_resolved = not any(
        disposition in unresolved_roles for disposition in policy.role_dispositions.values()
    )
    group_policy_resolved = not (
        dispositions[StructuralGroupDisposition.REVIEW_REQUIRED]
        or dispositions[StructuralGroupDisposition.BLOCKED]
    )
    included_count = dispositions[StructuralGroupDisposition.INCLUDE]
    structural_ready = (
        membership.path_interpretation_pass and group_policy_resolved and included_count > 0
    )
    inventory_ready = structural_ready and role_policy_resolved
    reasons: list[str] = []
    if not membership.path_interpretation_pass:
        reasons.append("ROLE_POLICY_PATH_INTERPRETATION_BLOCKED")
    if dispositions[StructuralGroupDisposition.BLOCKED]:
        reasons.append("ROLE_POLICY_GROUP_BLOCKED")
    if dispositions[StructuralGroupDisposition.REVIEW_REQUIRED]:
        reasons.append("ROLE_POLICY_GROUP_REVIEW_REQUIRED")
    if not role_policy_resolved:
        reasons.append("ROLE_POLICY_SEMANTIC_REVIEW_REQUIRED")
    if not included_count:
        reasons.append("ROLE_POLICY_NO_STRUCTURAL_GROUPS")
    return CandidateIngestionDecision(
        candidate_id=policy.candidate_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        path_policy_id=policy.path_policy_id,
        path_policy_version=policy.path_policy_version,
        path_evidence_fingerprint=policy.path_evidence_fingerprint,
        companion_policy_id=policy.companion_policy_id,
        companion_policy_version=policy.companion_policy_version,
        source_relationship_pass=relationships.relationship_pass,
        path_interpretation_pass=membership.path_interpretation_pass,
        total_group_count=relationships.group_count,
        complete_group_count=relationships.complete_group_count,
        partial_group_count=relationships.partial_group_count,
        orphan_group_count=relationships.orphan_group_count,
        duplicate_role_group_count=relationships.duplicate_role_group_count,
        structurally_included_group_count=included_count,
        review_required_group_count=dispositions[StructuralGroupDisposition.REVIEW_REQUIRED],
        blocked_group_count=dispositions[StructuralGroupDisposition.BLOCKED],
        excluded_group_count=dispositions[StructuralGroupDisposition.EXCLUDE],
        role_dispositions=policy.role_dispositions,
        role_policy_resolved=role_policy_resolved,
        group_policy_resolved=group_policy_resolved,
        structural_candidate_ready=structural_ready,
        inventory_ready=inventory_ready,
        blocking_reasons=tuple(reasons),
        groups=decisions,
    )


def _review_required_candidate_policy(
    *,
    candidate_id: str,
    policy_id: str,
    path_policy_id: str,
    path_evidence_fingerprint: str,
    companion_policy_id: str,
) -> CandidateRoleDispositionPolicy:
    return CandidateRoleDispositionPolicy(
        policy_id=policy_id,
        policy_version="1.0.0",
        candidate_id=candidate_id,
        path_policy_id=path_policy_id,
        path_policy_version="1.0.0",
        path_evidence_fingerprint=path_evidence_fingerprint,
        companion_policy_id=companion_policy_id,
        companion_policy_version="1.0.0",
        role_dispositions={role: CompanionDisposition.REVIEW_REQUIRED for role in CompanionRole},
        complete_group_disposition=StructuralGroupDisposition.INCLUDE,
        partial_group_disposition=StructuralGroupDisposition.REVIEW_REQUIRED,
        orphan_group_disposition=StructuralGroupDisposition.REVIEW_REQUIRED,
    )


def _validate_policy_binding(
    membership: InterpretedArchiveMembership,
    relationships: CompanionRelationshipResult,
    policy: CandidateRoleDispositionPolicy,
) -> None:
    if not (membership.candidate_id == relationships.candidate_id == policy.candidate_id):
        raise ContractError(
            "ROLE_POLICY_CANDIDATE_MISMATCH",
            "Role disposition inputs cannot cross candidate scopes.",
        )
    if (
        membership.policy_id != policy.path_policy_id
        or membership.policy_version != policy.path_policy_version
    ):
        raise ContractError(
            "ROLE_POLICY_PATH_POLICY_MISMATCH",
            "Path interpretation evidence must match the role policy identity and version.",
        )
    if membership.evidence_fingerprint != policy.path_evidence_fingerprint:
        raise ContractError(
            "ROLE_POLICY_PATH_EVIDENCE_MISMATCH",
            "Path interpretation evidence must match the approved role policy fingerprint.",
        )
    if (
        relationships.policy_id != policy.companion_policy_id
        or relationships.policy_version != policy.companion_policy_version
    ):
        raise ContractError(
            "ROLE_POLICY_COMPANION_POLICY_MISMATCH",
            "Companion evidence must match the role policy identity and version.",
        )


def _validate_relationship_evidence(
    membership: InterpretedArchiveMembership,
    relationships: CompanionRelationshipResult,
) -> None:
    grouped_members: dict[str, list[InterpretedArchiveMember]] = {}
    for member in membership.members:
        grouped_members.setdefault(member.companion_group_id, []).append(member)
    if set(grouped_members) != {group.group_logical_id for group in relationships.groups}:
        raise ContractError(
            "ROLE_POLICY_RELATIONSHIP_EVIDENCE_MISMATCH",
            "Companion group evidence does not match interpreted membership.",
        )
    complete_count = 0
    partial_count = 0
    orphan_count = 0
    duplicate_count = 0
    missing_counts: Counter[CompanionRole] = Counter()
    required_roles = (CompanionRole.JSON, CompanionRole.MIDI, CompanionRole.AUDIO)
    for group in relationships.groups:
        members = grouped_members[group.group_logical_id]
        member_ids = Counter(member.interpreted_member_id for member in members)
        roles = Counter(member.role for member in members)
        if member_ids != Counter(group.member_logical_ids) or roles != Counter(group.roles):
            raise ContractError(
                "ROLE_POLICY_RELATIONSHIP_EVIDENCE_MISMATCH",
                "Companion group evidence does not match interpreted membership.",
            )
        missing = tuple(role for role in required_roles if roles[role] == 0)
        duplicates = tuple(role for role in required_roles if roles[role] > 1)
        expected_reasons: list[str] = []
        if missing:
            expected_reasons.append("COMPANION_ROLE_MISSING")
        if duplicates:
            expected_reasons.append("COMPANION_ROLE_DUPLICATE")
        if roles[CompanionRole.OTHER]:
            expected_reasons.append("COMPANION_ROLE_UNSUPPORTED")
        if any(not member.interpreted_path_safety_pass for member in members):
            expected_reasons.append("COMPANION_PATH_INTERPRETATION_BLOCKED")
        blocked = bool(expected_reasons)
        complete = not blocked and all(roles[role] == 1 for role in required_roles)
        if (
            group.missing_roles != missing
            or group.duplicate_roles != duplicates
            or group.relationship_complete != complete
            or group.blocking_reasons != tuple(expected_reasons)
        ):
            raise ContractError(
                "ROLE_POLICY_RELATIONSHIP_EVIDENCE_MISMATCH",
                "Companion group classification does not match interpreted membership.",
            )
        complete_count += complete
        partial_count += bool(missing)
        orphan_count += len(set(group.roles) & set(required_roles)) == 1
        duplicate_count += bool(duplicates)
        missing_counts.update(missing)
    if (
        relationships.complete_group_count != complete_count
        or relationships.partial_group_count != partial_count
        or relationships.orphan_group_count != orphan_count
        or relationships.duplicate_role_group_count != duplicate_count
        or relationships.missing_json_group_count != missing_counts[CompanionRole.JSON]
        or relationships.missing_midi_group_count != missing_counts[CompanionRole.MIDI]
        or relationships.missing_audio_group_count != missing_counts[CompanionRole.AUDIO]
        or relationships.relationship_pass
        != (
            membership.path_interpretation_pass
            and bool(relationships.groups)
            and complete_count == len(relationships.groups)
        )
    ):
        raise ContractError(
            "ROLE_POLICY_RELATIONSHIP_EVIDENCE_MISMATCH",
            "Companion relationship aggregate does not match interpreted membership.",
        )


def _decide_group(
    group: CompanionRelationshipGroup,
    policy: CandidateRoleDispositionPolicy,
) -> CompanionGroupIngestionDecision:
    role_counts = Counter(group.roles)
    required_roles = (CompanionRole.JSON, CompanionRole.MIDI, CompanionRole.AUDIO)
    reasons: list[str] = []
    for role in group.missing_roles:
        reasons.append(f"ROLE_POLICY_MISSING_{role.name}")
    duplicate_roles = tuple(role for role in required_roles if role_counts[role] > 1)
    for role in duplicate_roles:
        reasons.append(f"ROLE_POLICY_DUPLICATE_{role.name}")

    path_blocked = "COMPANION_PATH_INTERPRETATION_BLOCKED" in group.blocking_reasons
    if duplicate_roles:
        kind = CompanionGroupKind.DUPLICATE
        disposition = StructuralGroupDisposition.BLOCKED
        if path_blocked:
            reasons.append("ROLE_POLICY_PATH_INTERPRETATION_BLOCKED")
    elif path_blocked:
        kind = CompanionGroupKind.BLOCKED
        disposition = StructuralGroupDisposition.BLOCKED
        reasons.append("ROLE_POLICY_PATH_INTERPRETATION_BLOCKED")
    elif role_counts[CompanionRole.OTHER]:
        kind = CompanionGroupKind.BLOCKED
        disposition = StructuralGroupDisposition.BLOCKED
        reasons.append("ROLE_POLICY_UNSUPPORTED_ROLE")
    elif group.relationship_complete:
        kind = CompanionGroupKind.COMPLETE
        disposition = policy.complete_group_disposition
        reasons.append("ROLE_POLICY_COMPLETE_GROUP")
    elif len(set(group.roles) & set(required_roles)) == 1:
        kind = CompanionGroupKind.ORPHAN
        disposition = policy.orphan_group_disposition
        reasons.append(
            "ROLE_POLICY_JSON_ORPHAN"
            if role_counts[CompanionRole.JSON]
            else "ROLE_POLICY_ORPHAN_GROUP"
        )
    else:
        kind = CompanionGroupKind.PARTIAL
        disposition = policy.partial_group_disposition
        reasons.append("ROLE_POLICY_PARTIAL_GROUP")

    semantic_review = any(
        policy.role_dispositions[role]
        in {CompanionDisposition.REVIEW_REQUIRED, CompanionDisposition.BLOCKED}
        for role in set(group.roles)
    )
    if semantic_review:
        reasons.append("ROLE_POLICY_SEMANTIC_REVIEW_REQUIRED")
    return CompanionGroupIngestionDecision(
        group_logical_id=group.group_logical_id,
        group_kind=kind,
        roles=group.roles,
        member_count=len(group.member_logical_ids),
        disposition=disposition,
        structural_included=disposition == StructuralGroupDisposition.INCLUDE,
        semantic_review_required=semantic_review,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )
