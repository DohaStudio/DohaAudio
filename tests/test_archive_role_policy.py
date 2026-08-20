from __future__ import annotations

import hashlib
import warnings
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from dohaaudio.archive_policy import (
    ArchiveInterpretationInput,
    ArchivePathInterpretationPolicy,
    ArchivePathInterpretationRule,
    CompanionDisposition,
    CompanionIngestionPolicy,
    CompanionRole,
    analyze_companion_relationships,
    interpret_archive_paths,
)
from dohaaudio.archive_role_policy import (
    CandidateRoleDispositionPolicy,
    CompanionGroupKind,
    StructuralGroupDisposition,
    decide_candidate_ingestion,
    music_loop_role_disposition_policy,
    traditional_music_role_disposition_policy,
)
from dohaaudio.archives import ArchiveInspectionPolicy, ArchiveSource, ZipArchiveInspector
from dohaaudio.errors import ContractError

CANDIDATE = "role-policy-candidate"


def _write_zip(path: Path, names: list[str]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.writestr(name, f"synthetic:{name}".encode())


def _evidence_fingerprint(source: ArchiveSource) -> str:
    records: list[str] = []
    with zipfile.ZipFile(source.path, mode="r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw_fingerprint = hashlib.sha256(
                "\x1f".join((source.candidate_id, source.archive_logical_id, info.filename)).encode(
                    "utf-8", errors="surrogatepass"
                )
            ).hexdigest()
            records.append(
                f"{source.archive_logical_id}:{raw_fingerprint}:{info.file_size}:{info.CRC:08x}"
            )
    evidence = hashlib.sha256()
    for record in sorted(records):
        evidence.update(record.encode())
    return evidence.hexdigest()


def _relationship(
    path: Path,
    names: list[str],
    *,
    candidate_id: str = CANDIDATE,
):  # type: ignore[no-untyped-def]
    _write_zip(path, names)
    source = ArchiveSource(
        candidate_id=candidate_id,
        archive_logical_id=f"{candidate_id}/archive/one",
        path=path,
    )
    inspector = ZipArchiveInspector(
        ArchiveInspectionPolicy(
            max_members_per_archive=100,
            max_member_uncompressed_bytes=1024,
            max_total_uncompressed_bytes=10_000,
            max_compression_ratio=100.0,
            max_member_name_bytes=512,
            stream_chunk_bytes=17,
        )
    )
    inspection = inspector.inspect(source)
    path_policy = ArchivePathInterpretationPolicy(
        policy_id=f"archive-path/{candidate_id}/v1",
        policy_version="1.0.0",
        candidate_id=candidate_id,
        evidence_fingerprint=_evidence_fingerprint(source),
        rule=ArchivePathInterpretationRule.SINGLE_LEADING_SLASH_ROOT_MARKER,
    )
    membership = interpret_archive_paths(
        (ArchiveInterpretationInput(source=source, inspection=inspection),),
        path_policy,
    )
    companion_policy = CompanionIngestionPolicy(
        policy_id=f"archive-companion/{candidate_id}/v1",
        policy_version="1.0.0",
        candidate_id=candidate_id,
        role_dispositions={role: CompanionDisposition.REVIEW_REQUIRED for role in CompanionRole},
    )
    relationships = analyze_companion_relationships(membership, companion_policy)
    return membership, relationships, companion_policy


def _role_policy(
    membership,  # type: ignore[no-untyped-def]
    companion_policy: CompanionIngestionPolicy,
    *,
    candidate_id: str = CANDIDATE,
    role_dispositions: dict[CompanionRole, CompanionDisposition] | None = None,
    complete: StructuralGroupDisposition = StructuralGroupDisposition.INCLUDE,
    partial: StructuralGroupDisposition = StructuralGroupDisposition.REVIEW_REQUIRED,
    orphan: StructuralGroupDisposition = StructuralGroupDisposition.REVIEW_REQUIRED,
) -> CandidateRoleDispositionPolicy:
    return CandidateRoleDispositionPolicy(
        policy_id=f"archive-role/{candidate_id}/v1",
        policy_version="1.0.0",
        candidate_id=candidate_id,
        path_policy_id=membership.policy_id,
        path_policy_version=membership.policy_version,
        path_evidence_fingerprint=membership.evidence_fingerprint,
        companion_policy_id=companion_policy.policy_id,
        companion_policy_version=companion_policy.policy_version,
        role_dispositions=role_dispositions
        or {role: CompanionDisposition.REVIEW_REQUIRED for role in CompanionRole},
        complete_group_disposition=complete,
        partial_group_disposition=partial,
        orphan_group_disposition=orphan,
    )


def test_complete_group_is_structurally_included_but_semantically_unresolved(
    tmp_path: Path,
) -> None:
    names = ["/complete/a.wav", "/complete/a.mid", "/complete/a.json"]
    membership, relationships, companion = _relationship(tmp_path / "complete.zip", names)
    decision = decide_candidate_ingestion(
        membership,
        relationships,
        _role_policy(membership, companion),
    )

    assert decision.source_relationship_pass is True
    assert decision.structurally_included_group_count == 1
    assert decision.structural_candidate_ready is True
    assert decision.role_policy_resolved is False
    assert decision.inventory_ready is False
    assert decision.groups[0].group_kind == CompanionGroupKind.COMPLETE
    assert decision.groups[0].semantic_review_required is True
    assert "ROLE_POLICY_COMPLETE_GROUP" in decision.groups[0].reason_codes


def test_real_candidate_policies_are_independent_and_conservative() -> None:
    music = music_loop_role_disposition_policy()
    traditional = traditional_music_role_disposition_policy()

    assert music.candidate_id != traditional.candidate_id
    assert music.policy_id != traditional.policy_id
    assert music.path_evidence_fingerprint != traditional.path_evidence_fingerprint
    for policy in (music, traditional):
        assert set(policy.role_dispositions.values()) == {CompanionDisposition.REVIEW_REQUIRED}
        assert policy.complete_group_disposition == StructuralGroupDisposition.INCLUDE
        assert policy.partial_group_disposition == StructuralGroupDisposition.REVIEW_REQUIRED
        assert policy.orphan_group_disposition == StructuralGroupDisposition.REVIEW_REQUIRED


@pytest.mark.parametrize(
    ("names", "kind", "reason"),
    [
        (
            ["/partial/a.mid", "/partial/a.wav"],
            CompanionGroupKind.PARTIAL,
            "ROLE_POLICY_MISSING_JSON",
        ),
        (["/orphan/a.json"], CompanionGroupKind.ORPHAN, "ROLE_POLICY_JSON_ORPHAN"),
        (["/orphan/a.wav"], CompanionGroupKind.ORPHAN, "ROLE_POLICY_ORPHAN_GROUP"),
        (["/orphan/a.mid"], CompanionGroupKind.ORPHAN, "ROLE_POLICY_ORPHAN_GROUP"),
        (
            ["/partial/a.json", "/partial/a.wav"],
            CompanionGroupKind.PARTIAL,
            "ROLE_POLICY_MISSING_MIDI",
        ),
        (
            ["/partial/a.json", "/partial/a.mid"],
            CompanionGroupKind.PARTIAL,
            "ROLE_POLICY_MISSING_AUDIO",
        ),
    ],
)
def test_incomplete_groups_require_explicit_review_without_silent_skip(
    tmp_path: Path,
    names: list[str],
    kind: CompanionGroupKind,
    reason: str,
) -> None:
    membership, relationships, companion = _relationship(tmp_path / "partial.zip", names)
    decision = decide_candidate_ingestion(
        membership,
        relationships,
        _role_policy(membership, companion),
    )

    group = decision.groups[0]
    assert group.group_kind == kind
    assert group.disposition == StructuralGroupDisposition.REVIEW_REQUIRED
    assert group.structural_included is False
    assert reason in group.reason_codes
    assert decision.review_required_group_count == 1
    assert decision.excluded_group_count == 0
    assert decision.inventory_ready is False


@pytest.mark.parametrize(
    ("names", "reason"),
    [
        (
            ["/duplicate/a.wav", "/duplicate/a.wav", "/duplicate/a.mid", "/duplicate/a.json"],
            "ROLE_POLICY_DUPLICATE_AUDIO",
        ),
        (
            [
                "/duplicate/a.wav",
                "/duplicate/a.mid",
                "/duplicate/a.midi",
                "/duplicate/a.json",
            ],
            "ROLE_POLICY_DUPLICATE_MIDI",
        ),
        (
            ["/duplicate/a.wav", "/duplicate/a.mid", "/duplicate/a.json", "/duplicate/a.json"],
            "ROLE_POLICY_DUPLICATE_JSON",
        ),
    ],
)
def test_duplicate_roles_are_blocked(
    tmp_path: Path,
    names: list[str],
    reason: str,
) -> None:
    membership, relationships, companion = _relationship(tmp_path / "duplicate.zip", names)
    decision = decide_candidate_ingestion(
        membership,
        relationships,
        _role_policy(membership, companion),
    )

    assert decision.duplicate_role_group_count == 1
    assert decision.blocked_group_count == 1
    assert decision.groups[0].group_kind == CompanionGroupKind.DUPLICATE
    assert reason in decision.groups[0].reason_codes
    assert decision.inventory_ready is False


def test_mixed_candidate_preserves_complete_and_partial_counts(tmp_path: Path) -> None:
    names = [
        "/complete/a.wav",
        "/complete/a.mid",
        "/complete/a.json",
        "/partial/b.mid",
        "/partial/b.wav",
    ]
    membership, relationships, companion = _relationship(tmp_path / "mixed.zip", names)
    decision = decide_candidate_ingestion(
        membership,
        relationships,
        _role_policy(membership, companion),
    )

    assert decision.total_group_count == 2
    assert decision.complete_group_count == 1
    assert decision.partial_group_count == 1
    assert decision.structurally_included_group_count == 1
    assert decision.review_required_group_count == 1
    assert decision.structural_candidate_ready is False
    assert decision.inventory_ready is False


def test_explicit_partial_exclusion_supports_a_traceable_complete_only_view(
    tmp_path: Path,
) -> None:
    names = [
        "/complete/a.wav",
        "/complete/a.mid",
        "/complete/a.json",
        "/partial/b.mid",
        "/partial/b.wav",
    ]
    membership, relationships, companion = _relationship(tmp_path / "complete-only.zip", names)
    resolved_roles = {
        CompanionRole.AUDIO: CompanionDisposition.INCLUDE_PRIMARY,
        CompanionRole.MIDI: CompanionDisposition.INCLUDE_COMPANION,
        CompanionRole.JSON: CompanionDisposition.METADATA_ONLY,
        CompanionRole.OTHER: CompanionDisposition.EXCLUDE,
    }
    policy = _role_policy(
        membership,
        companion,
        role_dispositions=resolved_roles,
        partial=StructuralGroupDisposition.EXCLUDE,
        orphan=StructuralGroupDisposition.EXCLUDE,
    )
    decision = decide_candidate_ingestion(membership, relationships, policy)

    assert decision.source_relationship_pass is False
    assert decision.structurally_included_group_count == 1
    assert decision.excluded_group_count == 1
    assert decision.review_required_group_count == 0
    assert decision.structural_candidate_ready is True
    assert decision.inventory_ready is True


def test_all_partial_candidate_has_no_structural_candidate(tmp_path: Path) -> None:
    membership, relationships, companion = _relationship(
        tmp_path / "all-partial.zip",
        ["/one/a.mid", "/one/a.wav", "/two/b.json", "/two/b.wav"],
    )
    decision = decide_candidate_ingestion(
        membership,
        relationships,
        _role_policy(membership, companion),
    )
    assert decision.complete_group_count == 0
    assert decision.partial_group_count == 2
    assert decision.structurally_included_group_count == 0
    assert "ROLE_POLICY_NO_STRUCTURAL_GROUPS" in decision.blocking_reasons
    assert decision.inventory_ready is False


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("candidate_id", "different-candidate", "ROLE_POLICY_CANDIDATE_MISMATCH"),
        ("path_policy_id", "different-path-policy", "ROLE_POLICY_PATH_POLICY_MISMATCH"),
        ("path_policy_version", "2.0.0", "ROLE_POLICY_PATH_POLICY_MISMATCH"),
        ("path_evidence_fingerprint", "f" * 64, "ROLE_POLICY_PATH_EVIDENCE_MISMATCH"),
        (
            "companion_policy_id",
            "different-companion-policy",
            "ROLE_POLICY_COMPANION_POLICY_MISMATCH",
        ),
        ("companion_policy_version", "2.0.0", "ROLE_POLICY_COMPANION_POLICY_MISMATCH"),
    ],
)
def test_policy_identity_and_evidence_mismatches_fail_closed(
    tmp_path: Path,
    field: str,
    value: str,
    error_code: str,
) -> None:
    membership, relationships, companion = _relationship(
        tmp_path / "binding.zip",
        ["/a.wav", "/a.mid", "/a.json"],
    )
    policy = _role_policy(membership, companion).model_copy(update={field: value})
    with pytest.raises(ContractError) as exc_info:
        decide_candidate_ingestion(membership, relationships, policy)
    assert exc_info.value.error_code == error_code


def test_candidate_policies_cannot_cross_music_and_traditional_scopes(tmp_path: Path) -> None:
    music_membership, music_relationships, music_companion = _relationship(
        tmp_path / "music.zip",
        ["/a.wav", "/a.mid", "/a.json"],
        candidate_id="music-candidate",
    )
    traditional_membership, _, traditional_companion = _relationship(
        tmp_path / "traditional.zip",
        ["/a.wav", "/a.mid", "/a.json"],
        candidate_id="traditional-candidate",
    )
    traditional_policy = _role_policy(
        traditional_membership,
        traditional_companion,
        candidate_id="traditional-candidate",
    )

    with pytest.raises(ContractError) as exc_info:
        decide_candidate_ingestion(
            music_membership,
            music_relationships,
            traditional_policy,
        )
    assert exc_info.value.error_code == "ROLE_POLICY_CANDIDATE_MISMATCH"
    assert {member.companion_group_id for member in music_membership.members}.isdisjoint(
        member.companion_group_id for member in traditional_membership.members
    )
    assert music_companion.candidate_id != traditional_companion.candidate_id


def test_relationship_evidence_cannot_change_group_classification(tmp_path: Path) -> None:
    membership, relationships, companion = _relationship(
        tmp_path / "relationship-evidence.zip",
        ["/a.wav", "/a.mid", "/a.json"],
    )
    changed_group = relationships.groups[0].model_copy(update={"relationship_complete": False})
    changed_relationships = relationships.model_copy(update={"groups": (changed_group,)})

    with pytest.raises(ContractError) as exc_info:
        decide_candidate_ingestion(
            membership,
            changed_relationships,
            _role_policy(membership, companion),
        )
    assert exc_info.value.error_code == "ROLE_POLICY_RELATIONSHIP_EVIDENCE_MISMATCH"


@pytest.mark.parametrize("field", ["partial_group_disposition", "orphan_group_disposition"])
def test_policy_rejects_silent_inclusion_of_incomplete_groups(
    tmp_path: Path,
    field: str,
) -> None:
    membership, _, companion = _relationship(
        tmp_path / "invalid-policy.zip",
        ["/a.wav", "/a.mid", "/a.json"],
    )
    payload = _role_policy(membership, companion).model_dump()
    payload[field] = StructuralGroupDisposition.INCLUDE
    with pytest.raises(ValidationError):
        CandidateRoleDispositionPolicy(**payload)


def test_decision_contract_is_path_and_raw_filename_free(tmp_path: Path) -> None:
    names = ["/private/a.wav", "/private/a.mid", "/private/a.json"]
    membership, relationships, companion = _relationship(tmp_path / "private.zip", names)
    decision = decide_candidate_ingestion(
        membership,
        relationships,
        _role_policy(membership, companion),
    )
    serialized = decision.model_dump_json()
    assert str(tmp_path) not in serialized
    assert all(name not in serialized for name in names)
