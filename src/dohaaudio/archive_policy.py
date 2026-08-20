"""Candidate-bound logical path interpretation and companion relationship policy."""

from __future__ import annotations

import hashlib
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from urllib.parse import unquote

from pydantic import Field, model_validator

from dohaaudio.archives import (
    WINDOWS_DRIVE_PATH,
    ArchiveInspectionResult,
    ArchiveInspectionStatus,
    ArchiveSource,
)
from dohaaudio.contracts import FrozenModel
from dohaaudio.errors import ContractError
from dohaaudio.security import assert_safe_metadata

INTERPRETABLE_RAW_REASONS = frozenset(
    {"ARCHIVE_MEMBER_PATH_UNSAFE", "ARCHIVE_MEMBER_MEDIA_UNSUPPORTED"}
)


class ArchivePathInterpretationRule(StrEnum):
    SINGLE_LEADING_SLASH_ROOT_MARKER = "single_leading_slash_root_marker"


class CompanionRole(StrEnum):
    AUDIO = "audio_member"
    MIDI = "midi_member"
    JSON = "json_member"
    OTHER = "other_member"


class CompanionDisposition(StrEnum):
    INCLUDE_PRIMARY = "include_primary"
    INCLUDE_COMPANION = "include_companion"
    METADATA_ONLY = "metadata_only"
    EXCLUDE = "exclude"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"


class ArchivePathInterpretationPolicy(FrozenModel):
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule: ArchivePathInterpretationRule

    @model_validator(mode="after")
    def reject_private_metadata(self) -> ArchivePathInterpretationPolicy:
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class CompanionIngestionPolicy(FrozenModel):
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    role_dispositions: dict[CompanionRole, CompanionDisposition]

    @model_validator(mode="after")
    def require_all_roles(self) -> CompanionIngestionPolicy:
        if set(self.role_dispositions) != set(CompanionRole):
            raise ValueError("companion policy must classify every member role")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


@dataclass(frozen=True)
class ArchiveInterpretationInput:
    """Internal source/result binding; physical paths are never serialized."""

    source: ArchiveSource
    inspection: ArchiveInspectionResult


class InterpretedArchiveMember(FrozenModel):
    archive_logical_id: str = Field(min_length=1)
    raw_member_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    interpreted_member_id: str = Field(min_length=1)
    companion_group_id: str = Field(min_length=1)
    extension: str
    role: CompanionRole
    raw_path_safety_pass: bool
    path_interpretation_applied: bool
    interpreted_path_safety_pass: bool
    blocking_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> InterpretedArchiveMember:
        if self.raw_path_safety_pass and self.path_interpretation_applied:
            raise ValueError("interpretation must not hide a passing raw path")
        if self.interpreted_path_safety_pass and not self.path_interpretation_applied:
            raise ValueError("safe interpreted path requires an applied policy")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class InterpretedArchiveMembership(FrozenModel):
    policy_id: str
    policy_version: str
    candidate_id: str
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_count: int = Field(ge=0)
    raw_member_count: int = Field(ge=0)
    leading_slash_member_count: int = Field(ge=0)
    policy_eligible_member_count: int = Field(ge=0)
    interpretation_failure_count: int = Field(ge=0)
    post_interpretation_unsafe_count: int = Field(ge=0)
    collision_member_count: int = Field(ge=0)
    interpreted_member_count: int = Field(ge=0)
    raw_path_safety_pass: bool
    path_interpretation_applied: bool
    path_interpretation_pass: bool
    interpreted_path_safety_pass: bool
    blocking_reasons: tuple[str, ...]
    members: tuple[InterpretedArchiveMember, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> InterpretedArchiveMembership:
        if self.raw_member_count != len(self.members):
            raise ValueError("raw member count must cover every interpreted record")
        if self.interpreted_member_count != sum(
            member.interpreted_path_safety_pass for member in self.members
        ):
            raise ValueError("interpreted member count must match safe interpreted records")
        if self.path_interpretation_pass != self.interpreted_path_safety_pass:
            raise ValueError("candidate path gates must advance together")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class CompanionRelationshipGroup(FrozenModel):
    group_logical_id: str = Field(min_length=1)
    member_logical_ids: tuple[str, ...]
    roles: tuple[CompanionRole, ...]
    relationship_complete: bool
    missing_roles: tuple[CompanionRole, ...]
    duplicate_roles: tuple[CompanionRole, ...]
    blocking_reasons: tuple[str, ...]


class CompanionRelationshipResult(FrozenModel):
    policy_id: str
    policy_version: str
    candidate_id: str
    group_count: int = Field(ge=0)
    complete_group_count: int = Field(ge=0)
    partial_group_count: int = Field(ge=0)
    orphan_group_count: int = Field(ge=0)
    duplicate_role_group_count: int = Field(ge=0)
    missing_json_group_count: int = Field(ge=0)
    missing_midi_group_count: int = Field(ge=0)
    missing_audio_group_count: int = Field(ge=0)
    relationship_pass: bool
    blocking_reasons: tuple[str, ...]
    groups: tuple[CompanionRelationshipGroup, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> CompanionRelationshipResult:
        if self.group_count != len(self.groups):
            raise ValueError("group count must match relationship records")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class CandidateArchiveIngestionView(FrozenModel):
    candidate_id: str
    path_policy_id: str
    companion_policy_id: str
    path_interpretation_pass: bool
    companion_relationship_pass: bool
    role_dispositions: dict[CompanionRole, CompanionDisposition]
    content_checksum_complete: bool
    ingestion_policy_resolved: bool
    dataset_inventory_ready: bool
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True)
class _InterpretedCandidate:
    archive_logical_id: str
    raw_fingerprint: str
    canonical_path: str | None
    collision_key: str | None
    member_id: str
    group_id: str
    extension: str
    role: CompanionRole
    applied: bool
    reasons: tuple[str, ...]
    size: int
    crc: int


def interpret_archive_paths(
    inputs: Iterable[ArchiveInterpretationInput],
    policy: ArchivePathInterpretationPolicy,
) -> InterpretedArchiveMembership:
    """Apply one evidence-bound logical interpretation without changing source archives."""

    ordered = tuple(sorted(inputs, key=lambda item: item.source.archive_logical_id))
    if not ordered:
        raise ContractError("ARCHIVE_INTERPRETATION_INPUT_MISSING", "Archive input is required.")
    archive_ids = [item.source.archive_logical_id for item in ordered]
    if len(archive_ids) != len(set(archive_ids)):
        raise ContractError(
            "ARCHIVE_INTERPRETATION_DUPLICATE_ARCHIVE",
            "Archive identities must be unique within an interpretation scope.",
        )

    reasons: list[str] = []
    candidates: list[_InterpretedCandidate] = []
    evidence_records: list[str] = []
    for item in ordered:
        _validate_binding(item, policy)
        unexpected = set(item.inspection.blocking_reasons) - INTERPRETABLE_RAW_REASONS
        if unexpected:
            reasons.append("ARCHIVE_INTERPRETATION_RAW_BLOCKER")
        try:
            with zipfile.ZipFile(item.source.path, mode="r") as archive:
                infos = [info for info in archive.infolist() if not info.is_dir()]
        except (OSError, EOFError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
            reasons.append("ARCHIVE_INTERPRETATION_SOURCE_UNREADABLE")
            continue
        if len(infos) != item.inspection.member_count:
            reasons.append("ARCHIVE_INTERPRETATION_MEMBERSHIP_MISMATCH")
        for info in infos:
            candidate = _interpret_member(
                info.filename,
                archive_logical_id=item.source.archive_logical_id,
                candidate_id=policy.candidate_id,
                size=info.file_size,
                crc=info.CRC,
            )
            candidates.append(candidate)
            evidence_records.append(
                f"{candidate.archive_logical_id}:{candidate.raw_fingerprint}:"
                f"{candidate.size}:{candidate.crc:08x}"
            )

    evidence = hashlib.sha256()
    for record in sorted(evidence_records):
        evidence.update(record.encode())
    evidence_fingerprint = evidence.hexdigest()
    if evidence_fingerprint != policy.evidence_fingerprint:
        reasons.append("ARCHIVE_INTERPRETATION_EVIDENCE_MISMATCH")

    collisions = _collision_indexes(candidates)
    members: list[InterpretedArchiveMember] = []
    for index, candidate in enumerate(candidates):
        member_reasons = list(candidate.reasons)
        if index in collisions:
            member_reasons.append("ARCHIVE_INTERPRETATION_COLLISION")
        safe = candidate.applied and not member_reasons
        members.append(
            InterpretedArchiveMember(
                archive_logical_id=candidate.archive_logical_id,
                raw_member_fingerprint=candidate.raw_fingerprint,
                interpreted_member_id=candidate.member_id,
                companion_group_id=candidate.group_id,
                extension=candidate.extension,
                role=candidate.role,
                raw_path_safety_pass=_raw_path_safe(candidate.canonical_path, candidate.applied),
                path_interpretation_applied=candidate.applied,
                interpreted_path_safety_pass=safe,
                blocking_reasons=tuple(dict.fromkeys(member_reasons)),
            )
        )
    members.sort(key=lambda member: (member.archive_logical_id, member.interpreted_member_id))
    for member in members:
        reasons.extend(member.blocking_reasons)
    reasons = list(dict.fromkeys(reasons))
    raw_count = len(members)
    leading_count = sum(member.path_interpretation_applied for member in members)
    eligible_count = sum(
        member.path_interpretation_applied
        and "ARCHIVE_INTERPRETATION_PATTERN_UNSUPPORTED" not in member.blocking_reasons
        for member in members
    )
    unsafe_count = sum(not member.interpreted_path_safety_pass for member in members)
    collision_count = sum(
        "ARCHIVE_INTERPRETATION_COLLISION" in member.blocking_reasons for member in members
    )
    pass_gate = (
        bool(members)
        and not reasons
        and all(
            item.inspection.inspection_complete and item.inspection.membership_known
            for item in ordered
        )
    )
    return InterpretedArchiveMembership(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        candidate_id=policy.candidate_id,
        evidence_fingerprint=evidence_fingerprint,
        archive_count=len(ordered),
        raw_member_count=raw_count,
        leading_slash_member_count=leading_count,
        policy_eligible_member_count=eligible_count,
        interpretation_failure_count=sum(
            not member.path_interpretation_applied for member in members
        ),
        post_interpretation_unsafe_count=unsafe_count,
        collision_member_count=collision_count,
        interpreted_member_count=raw_count - unsafe_count,
        raw_path_safety_pass=all(item.inspection.path_safety_pass for item in ordered),
        path_interpretation_applied=leading_count > 0,
        path_interpretation_pass=pass_gate,
        interpreted_path_safety_pass=pass_gate,
        blocking_reasons=tuple(reasons),
        members=tuple(members),
    )


def analyze_companion_relationships(
    membership: InterpretedArchiveMembership,
    policy: CompanionIngestionPolicy,
) -> CompanionRelationshipResult:
    if membership.candidate_id != policy.candidate_id:
        raise ContractError(
            "COMPANION_POLICY_CANDIDATE_MISMATCH",
            "Companion policy cannot cross candidate scopes.",
        )
    grouped: dict[str, list[InterpretedArchiveMember]] = {}
    for member in membership.members:
        grouped.setdefault(member.companion_group_id, []).append(member)
    required = (CompanionRole.JSON, CompanionRole.MIDI, CompanionRole.AUDIO)
    groups: list[CompanionRelationshipGroup] = []
    reasons: list[str] = []
    for group_id, members in sorted(grouped.items()):
        counts = Counter(member.role for member in members)
        missing = tuple(role for role in required if counts[role] == 0)
        duplicates = tuple(role for role in required if counts[role] > 1)
        group_reasons: list[str] = []
        if missing:
            group_reasons.append("COMPANION_ROLE_MISSING")
        if duplicates:
            group_reasons.append("COMPANION_ROLE_DUPLICATE")
        if counts[CompanionRole.OTHER]:
            group_reasons.append("COMPANION_ROLE_UNSUPPORTED")
        if any(not member.interpreted_path_safety_pass for member in members):
            group_reasons.append("COMPANION_PATH_INTERPRETATION_BLOCKED")
        complete = not group_reasons and all(counts[role] == 1 for role in required)
        reasons.extend(group_reasons)
        groups.append(
            CompanionRelationshipGroup(
                group_logical_id=group_id,
                member_logical_ids=tuple(
                    sorted(member.interpreted_member_id for member in members)
                ),
                roles=tuple(sorted((member.role for member in members), key=str)),
                relationship_complete=complete,
                missing_roles=missing,
                duplicate_roles=duplicates,
                blocking_reasons=tuple(group_reasons),
            )
        )
    reasons = list(dict.fromkeys(reasons))
    complete_count = sum(group.relationship_complete for group in groups)
    partial_count = sum(bool(group.missing_roles) for group in groups)
    orphan_count = sum(len(set(group.roles) & set(required)) == 1 for group in groups)
    duplicate_count = sum(bool(group.duplicate_roles) for group in groups)
    pass_gate = membership.path_interpretation_pass and bool(groups) and not reasons
    if not membership.path_interpretation_pass:
        reasons.insert(0, "COMPANION_PATH_INTERPRETATION_BLOCKED")
        reasons = list(dict.fromkeys(reasons))
    return CompanionRelationshipResult(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        candidate_id=policy.candidate_id,
        group_count=len(groups),
        complete_group_count=complete_count,
        partial_group_count=partial_count,
        orphan_group_count=orphan_count,
        duplicate_role_group_count=duplicate_count,
        missing_json_group_count=sum(CompanionRole.JSON in group.missing_roles for group in groups),
        missing_midi_group_count=sum(CompanionRole.MIDI in group.missing_roles for group in groups),
        missing_audio_group_count=sum(
            CompanionRole.AUDIO in group.missing_roles for group in groups
        ),
        relationship_pass=pass_gate,
        blocking_reasons=tuple(reasons),
        groups=tuple(groups),
    )


def build_candidate_ingestion_view(
    membership: InterpretedArchiveMembership,
    relationships: CompanionRelationshipResult,
    policy: CompanionIngestionPolicy,
    *,
    content_checksum_complete: bool = False,
) -> CandidateArchiveIngestionView:
    if not (membership.candidate_id == relationships.candidate_id == policy.candidate_id):
        raise ContractError(
            "ARCHIVE_INGESTION_CANDIDATE_MISMATCH",
            "Archive ingestion inputs cannot cross candidate scopes.",
        )
    if (
        relationships.policy_id != policy.policy_id
        or relationships.policy_version != policy.policy_version
    ):
        raise ContractError(
            "ARCHIVE_INGESTION_COMPANION_POLICY_MISMATCH",
            "Companion relationship evidence must match the ingestion policy identity and version.",
        )
    unresolved = {
        CompanionDisposition.REVIEW_REQUIRED,
        CompanionDisposition.BLOCKED,
    }
    policy_resolved = not any(value in unresolved for value in policy.role_dispositions.values())
    ready = (
        membership.path_interpretation_pass
        and relationships.relationship_pass
        and policy_resolved
        and content_checksum_complete
    )
    reasons: list[str] = []
    if not membership.path_interpretation_pass:
        reasons.append("ARCHIVE_PATH_INTERPRETATION_BLOCKED")
    if not relationships.relationship_pass:
        reasons.append("COMPANION_RELATIONSHIP_BLOCKED")
    if not policy_resolved:
        reasons.append("COMPANION_INGESTION_POLICY_REVIEW_REQUIRED")
    if not content_checksum_complete:
        reasons.append("DATASET_CHECKSUM_INCOMPLETE")
    return CandidateArchiveIngestionView(
        candidate_id=policy.candidate_id,
        path_policy_id=membership.policy_id,
        companion_policy_id=policy.policy_id,
        path_interpretation_pass=membership.path_interpretation_pass,
        companion_relationship_pass=relationships.relationship_pass,
        role_dispositions=policy.role_dispositions,
        content_checksum_complete=content_checksum_complete,
        ingestion_policy_resolved=policy_resolved,
        dataset_inventory_ready=ready,
        blocking_reasons=tuple(reasons),
    )


def _validate_binding(
    item: ArchiveInterpretationInput, policy: ArchivePathInterpretationPolicy
) -> None:
    source = item.source
    inspection = item.inspection
    if source.candidate_id != policy.candidate_id or inspection.candidate_id != policy.candidate_id:
        raise ContractError(
            "ARCHIVE_INTERPRETATION_CANDIDATE_MISMATCH",
            "Path interpretation policy cannot cross candidate scopes.",
        )
    if source.archive_logical_id != inspection.archive_logical_id:
        raise ContractError(
            "ARCHIVE_INTERPRETATION_ARCHIVE_MISMATCH",
            "Archive source and inspection identity must match.",
        )
    if (
        inspection.inspection_status == ArchiveInspectionStatus.FAILED
        or not inspection.inspection_complete
        or not inspection.membership_known
    ):
        raise ContractError(
            "ARCHIVE_INTERPRETATION_INSPECTION_INCOMPLETE",
            "Complete known raw membership is required before interpretation.",
        )


def _interpret_member(
    name: str,
    *,
    archive_logical_id: str,
    candidate_id: str,
    size: int,
    crc: int,
) -> _InterpretedCandidate:
    raw_fingerprint = _digest(candidate_id, archive_logical_id, name)
    extension = PurePosixPath(
        unicodedata.normalize("NFKC", name).replace("\\", "/")
    ).suffix.casefold()
    placeholder = f"blocked/{_digest(candidate_id, archive_logical_id, raw_fingerprint)}"
    if not name.startswith("/") or name.startswith("//"):
        raw_canonical = (
            _canonical_relative_path(name)
            if not name.startswith("/") and _validate_interpreted_relative_path(name) is None
            else None
        )
        return _InterpretedCandidate(
            archive_logical_id,
            raw_fingerprint,
            raw_canonical,
            None,
            placeholder,
            f"companion/{_digest(candidate_id, archive_logical_id, raw_fingerprint, 'group')}",
            extension,
            _role(extension),
            False,
            ("ARCHIVE_INTERPRETATION_PATTERN_UNSUPPORTED",),
            size,
            crc,
        )
    stripped = name[1:]
    invalid = _validate_interpreted_relative_path(stripped)
    if invalid is not None:
        return _InterpretedCandidate(
            archive_logical_id,
            raw_fingerprint,
            None,
            None,
            placeholder,
            f"companion/{_digest(candidate_id, archive_logical_id, raw_fingerprint, 'group')}",
            extension,
            _role(extension),
            True,
            (invalid,),
            size,
            crc,
        )
    canonical = _canonical_relative_path(stripped)
    extension = PurePosixPath(canonical).suffix.casefold()
    stem = str(PurePosixPath(canonical).with_suffix("")).casefold()
    return _InterpretedCandidate(
        archive_logical_id,
        raw_fingerprint,
        canonical,
        canonical.casefold(),
        f"interpreted-member/{_digest(candidate_id, canonical.casefold())}",
        f"companion/{_digest(candidate_id, stem)}",
        extension,
        _role(extension),
        True,
        (),
        size,
        crc,
    )


def _validate_interpreted_relative_path(value: str) -> str | None:
    if not value or "\x00" in value:
        return "ARCHIVE_INTERPRETATION_PATH_UNSAFE"
    decoded = value
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    for candidate in (value, decoded):
        normalized = unicodedata.normalize("NFKC", candidate).replace("\\", "/")
        if (
            normalized.startswith("/")
            or WINDOWS_DRIVE_PATH.match(normalized)
            or any(part == ".." or ":" in part for part in normalized.split("/"))
        ):
            return "ARCHIVE_INTERPRETATION_PATH_UNSAFE"
    if not _canonical_relative_path(value):
        return "ARCHIVE_INTERPRETATION_PATH_UNSAFE"
    return None


def _raw_path_safe(canonical_path: str | None, interpretation_applied: bool) -> bool:
    return canonical_path is not None and not interpretation_applied


def _canonical_relative_path(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\\", "/")
    return "/".join(part for part in normalized.split("/") if part not in ("", "."))


def _collision_indexes(candidates: list[_InterpretedCandidate]) -> set[int]:
    by_key: dict[str, list[int]] = {}
    for index, candidate in enumerate(candidates):
        if candidate.collision_key is not None:
            by_key.setdefault(candidate.collision_key, []).append(index)
    return {index for indexes in by_key.values() if len(indexes) > 1 for index in indexes}


def _role(extension: str) -> CompanionRole:
    if extension == ".wav":
        return CompanionRole.AUDIO
    if extension in {".mid", ".midi"}:
        return CompanionRole.MIDI
    if extension == ".json":
        return CompanionRole.JSON
    return CompanionRole.OTHER


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="surrogatepass")).hexdigest()
