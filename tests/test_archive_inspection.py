from __future__ import annotations

import hashlib
import struct
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest

from dohaaudio.archives import (
    ArchiveInspectionMode,
    ArchiveInspectionPolicy,
    ArchiveInspectionStatus,
    ArchiveMemberSupport,
    ArchiveSource,
    ChecksumStatus,
    CrcValidationStatus,
    ZipArchiveInspector,
    archive_inspections_to_inventory,
    inspect_archive_set_summary,
)
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
)
from dohaaudio.errors import ContractError
from tests.readiness_helpers import NOW


def policy(**updates: object) -> ArchiveInspectionPolicy:
    values: dict[str, object] = {
        "max_members_per_archive": 20,
        "max_member_uncompressed_bytes": 1024 * 1024,
        "max_total_uncompressed_bytes": 4 * 1024 * 1024,
        "max_compression_ratio": 100.0,
        "max_member_name_bytes": 256,
        "stream_chunk_bytes": 17,
    }
    values.update(updates)
    return ArchiveInspectionPolicy(**values)


def write_zip(path: Path, entries: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)


def source(path: Path, *, archive_id: str = "candidate/archive/test-v1") -> ArchiveSource:
    return ArchiveSource(
        candidate_id="archive-candidate",
        archive_logical_id=archive_id,
        path=path,
    )


def inspect(path: Path, **policy_updates: object):  # type: ignore[no-untyped-def]
    return ZipArchiveInspector(policy(**policy_updates)).inspect(source(path))


def test_valid_zip_discovery_is_deterministic_path_free_and_metadata_only(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.zip"
    second_path = tmp_path / "second.zip"
    entries = [("audio/b.wav", b"b"), ("audio/a.flac", b"a")]
    write_zip(first_path, entries)
    write_zip(second_path, list(reversed(entries)))

    first = inspect(first_path)
    second = inspect(second_path)
    assert first.inspection_status == ArchiveInspectionStatus.COMPLETE
    assert first.member_count == first.supported_member_count == 2
    assert first.archive_metadata_fingerprint == second.archive_metadata_fingerprint
    assert first.members == second.members
    assert len({member.provenance_identity for member in first.members}) == 2
    assert all(member.content_sha256 is None for member in first.members)
    assert all(
        member.crc_validation_status == CrcValidationStatus.NOT_PERFORMED
        for member in first.members
    )
    serialized = first.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "audio/a.flac" not in serialized
    assert [member.member_logical_id for member in first.members] == sorted(
        member.member_logical_id for member in first.members
    )


@pytest.mark.parametrize(
    "name",
    [
        "../escape.wav",
        "..\\escape.wav",
        "safe/..\\escape.wav",
        "C:\\escape.wav",
        "\\\\server\\share\\escape.wav",
        "/root/escape.wav",
        "%2e%2e/escape.wav",
        "%252e%252e/escape.wav",
    ],
)
def test_unsafe_member_paths_are_blocked_without_echoing_names(tmp_path: Path, name: str) -> None:
    archive_path = tmp_path / "unsafe.zip"
    write_zip(archive_path, [(name, b"unsafe")])
    result = inspect(archive_path)
    assert result.inspection_status == ArchiveInspectionStatus.BLOCKED
    assert result.inspection_complete is True
    assert result.path_safety_pass is False
    assert result.unsafe_member_count == 1
    assert result.members[0].support_status == ArchiveMemberSupport.BLOCKED
    assert name not in result.model_dump_json()


@pytest.mark.parametrize(
    "names",
    [
        ("A/B.wav", "a\\b.wav"),
        ("audio/./same.wav", "audio/same.wav"),
    ],
)
def test_duplicate_normalized_or_casefolded_member_identity_is_blocked(
    tmp_path: Path, names: tuple[str, str]
) -> None:
    archive_path = tmp_path / "duplicates.zip"
    write_zip(archive_path, [(names[0], b"a"), (names[1], b"b")])
    result = inspect(archive_path)
    assert "ARCHIVE_DUPLICATE_MEMBER_IDENTITY" in result.blocking_reasons
    assert all(member.support_status == ArchiveMemberSupport.BLOCKED for member in result.members)


def test_nested_and_unsupported_members_are_classified_without_recursion(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "classification.zip"
    write_zip(archive_path, [("nested.zip", b"PK"), ("notes.txt", b"notes")])
    result = inspect(archive_path)
    assert result.nested_archive_count == 1
    assert result.unsupported_member_count == 2
    assert all(member.checksum_status == ChecksumStatus.NOT_REQUESTED for member in result.members)


def _set_encrypted_flag(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    local_flags = struct.unpack_from("<H", payload, local + 6)[0] | 0x1
    central_flags = struct.unpack_from("<H", payload, central + 8)[0] | 0x1
    struct.pack_into("<H", payload, local + 6, local_flags)
    struct.pack_into("<H", payload, central + 8, central_flags)
    path.write_bytes(payload)


def test_encrypted_member_is_blocked_without_password_attempt(tmp_path: Path) -> None:
    archive_path = tmp_path / "encrypted.zip"
    write_zip(archive_path, [("audio.wav", b"audio")])
    _set_encrypted_flag(archive_path)
    result = inspect(archive_path)
    assert result.encrypted_member_count == 1
    assert result.members[0].support_status == ArchiveMemberSupport.BLOCKED
    assert result.members[0].checksum_status == ChecksumStatus.NOT_REQUESTED


def test_corrupt_and_empty_archives_fail_closed(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"not-a-zip")
    empty = tmp_path / "empty.zip"
    write_zip(empty, [])
    corrupt_result = inspect(corrupt)
    empty_result = inspect(empty)
    assert corrupt_result.inspection_status == ArchiveInspectionStatus.FAILED
    assert corrupt_result.inspection_complete is False
    assert corrupt_result.membership_known is False
    assert empty_result.inspection_status == ArchiveInspectionStatus.BLOCKED
    assert empty_result.inspection_complete is True
    assert "ARCHIVE_EMPTY" in empty_result.blocking_reasons


def test_directory_entries_are_counted_but_not_dataset_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "directory.zip"
    write_zip(archive_path, [("audio/", b""), ("audio/sample.wav", b"audio")])
    result = inspect(archive_path)
    assert result.directory_entry_count == 1
    assert result.member_count == result.supported_member_count == 1


@pytest.mark.parametrize(
    ("policy_updates", "reason"),
    [
        ({"max_members_per_archive": 1}, "ARCHIVE_MEMBER_COUNT_LIMIT_EXCEEDED"),
        (
            {"max_member_uncompressed_bytes": 3},
            "ARCHIVE_MEMBER_UNCOMPRESSED_LIMIT_EXCEEDED",
        ),
        (
            {"max_total_uncompressed_bytes": 5},
            "ARCHIVE_TOTAL_UNCOMPRESSED_LIMIT_EXCEEDED",
        ),
        ({"max_member_name_bytes": 5}, "ARCHIVE_MEMBER_NAME_LIMIT_EXCEEDED"),
    ],
)
def test_explicit_resource_guards_block_unsafe_metadata(
    tmp_path: Path, policy_updates: dict[str, object], reason: str
) -> None:
    archive_path = tmp_path / "limits.zip"
    write_zip(archive_path, [("first.wav", b"1234"), ("second.wav", b"5678")])
    result = inspect(archive_path, **policy_updates)
    assert result.inspection_status == ArchiveInspectionStatus.BLOCKED
    assert reason in result.blocking_reasons


def test_compression_ratio_guard_blocks_bomb_like_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "ratio.zip"
    write_zip(archive_path, [("zeros.wav", b"\x00" * 100_000)])
    result = inspect(archive_path, max_compression_ratio=2.0)
    assert "ARCHIVE_MEMBER_COMPRESSION_RATIO_EXCEEDED" in result.blocking_reasons


def test_full_checksum_streams_sha256_and_distinguishes_crc(tmp_path: Path) -> None:
    archive_path = tmp_path / "checksums.zip"
    different_path = tmp_path / "different.zip"
    content = b"bounded-stream-content"
    write_zip(archive_path, [("audio.wav", content)])
    write_zip(different_path, [("audio.wav", b"different")])
    before = {path.name for path in tmp_path.iterdir()}
    result = ZipArchiveInspector(policy()).inspect(
        source(archive_path), mode=ArchiveInspectionMode.FULL_CHECKSUM
    )
    different = ZipArchiveInspector(policy()).inspect(
        source(different_path), mode=ArchiveInspectionMode.FULL_CHECKSUM
    )
    member = result.members[0]
    assert member.content_sha256 == hashlib.sha256(content).hexdigest()
    assert member.crc32 != member.content_sha256
    assert member.checksum_status == ChecksumStatus.VERIFIED
    assert member.crc_validation_status == CrcValidationStatus.VERIFIED
    assert result.archive_checksum == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert member.content_sha256 != different.members[0].content_sha256
    assert {path.name for path in tmp_path.iterdir()} == before


def test_duplicate_extra_field_is_blocked(tmp_path: Path) -> None:
    archive_path = tmp_path / "extra.zip"
    info = zipfile.ZipInfo("audio.wav")
    info.extra = b"\x01\x00\x00\x00\x01\x00\x00\x00"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, b"audio")
    result = inspect(archive_path)
    assert "ARCHIVE_EXTRA_FIELD_INVALID" in result.blocking_reasons


def test_non_zip_source_is_rejected_before_inspection(tmp_path: Path) -> None:
    source_path = tmp_path / "archive.tar"
    source_path.write_bytes(b"archive")
    with pytest.raises(ContractError) as exc_info:
        ZipArchiveInspector(policy()).inspect(source(source_path))
    assert exc_info.value.error_code == "ARCHIVE_FORMAT_UNSUPPORTED"


def test_crc_mismatch_is_not_silently_accepted(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad-crc.zip"
    write_zip(archive_path, [("audio.wav", b"audio")])
    payload = bytearray(archive_path.read_bytes())
    central = payload.index(b"PK\x01\x02")
    struct.pack_into("<I", payload, central + 16, 0)
    archive_path.write_bytes(payload)
    result = ZipArchiveInspector(policy()).inspect(
        source(archive_path), mode=ArchiveInspectionMode.FULL_CHECKSUM
    )
    assert result.inspection_status == ArchiveInspectionStatus.BLOCKED
    assert result.members[0].checksum_status == ChecksumStatus.FAILED
    assert result.members[0].crc_validation_status == CrcValidationStatus.FAILED


def test_archive_set_detects_duplicate_identity_and_checksum(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    write_zip(first, [("audio.wav", b"same")])
    second.write_bytes(first.read_bytes())
    inspector = ZipArchiveInspector(policy())
    duplicate_identity = inspect_archive_set_summary(
        inspector,
        [source(first), source(second)],
        candidate_id="archive-candidate",
    )
    duplicate_checksum = inspect_archive_set_summary(
        inspector,
        [
            source(first, archive_id="candidate/archive/one"),
            source(second, archive_id="candidate/archive/two"),
        ],
        candidate_id="archive-candidate",
        mode=ArchiveInspectionMode.FULL_CHECKSUM,
    )
    assert "ARCHIVE_SET_DUPLICATE_IDENTITY" in duplicate_identity.blocking_reasons
    assert "ARCHIVE_SET_DUPLICATE_CHECKSUM" in duplicate_checksum.blocking_reasons


def test_partial_archive_set_cannot_report_complete_membership(tmp_path: Path) -> None:
    archive_path = tmp_path / "present.zip"
    write_zip(archive_path, [("audio.wav", b"audio")])
    present = source(archive_path, archive_id="candidate/archive/present")

    summary = inspect_archive_set_summary(
        ZipArchiveInspector(policy()),
        [present],
        candidate_id="archive-candidate",
        expected_archive_ids=frozenset({"candidate/archive/present", "candidate/archive/missing"}),
    )

    assert summary.inspected_archive_count == 1
    assert summary.archive_inspection_complete is False
    assert summary.archive_membership_known is False
    assert summary.archive_path_safety_pass is False
    assert "ARCHIVE_SET_EXPECTED_IDENTITY_MISMATCH" in summary.blocking_reasons


def _proposal(item_count: int) -> DatasetEnrollmentProposal:
    return DatasetEnrollmentProposal(
        candidate_id="archive-candidate",
        dataset_manifest_id="dataset-manifest/audio/archive/v1",
        dataset_id="dataset/audio/archive",
        dataset_version="1.0.0",
        source_alias="archive/approved-source",
        expected_evidence_ids=("archive-evidence-v1",),
        license_status=DatasetLicenseStatus.APPROVED,
        training_allowed=TrainingAllowed.TRUE,
        commercial_usage_status=CommercialUsageStatus.REVIEW_PENDING,
        redistribution_allowed=TrainingAllowed.FALSE,
        content_checksum_set_id="archive-checksum-set-v1",
        split_id="archive-split-v1",
        split_algorithm_version="explicit-count-hash-v1",
        split_seed=31,
        train_count=item_count,
        validation_count=0,
        test_count=0,
        created_at=NOW,
    )


def _evidence(decision: RightsDecision) -> SanitizedMappingRightsEvidenceAdapter:
    evidence = NormalizedRightsEvidence(
        candidate_id="archive-candidate",
        dataset_manifest_id="dataset-manifest/audio/archive/v1",
        evidence_id="archive-evidence-v1",
        source_alias="archive/reviewed-evidence",
        review_status=EvidenceReviewStatus.VERIFIED,
        effective_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
        scope_decisions=(
            RightsScopeDecision(
                scope=RightsScope.DATASET_POSSESSION,
                decision=RightsDecision.APPROVED,
            ),
            RightsScopeDecision(
                scope=RightsScope.DATASET_ACCESS,
                decision=RightsDecision.APPROVED,
            ),
            RightsScopeDecision(scope=RightsScope.AI_TRAINING, decision=decision),
        ),
    )
    return SanitizedMappingRightsEvidenceAdapter((evidence.model_dump(mode="json"),))


def test_full_archive_membership_reuses_existing_enrollment_and_rights_gate(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "enrollment.zip"
    write_zip(archive_path, [("one.wav", b"one"), ("two.flac", b"two")])
    inspection = ZipArchiveInspector(policy()).inspect(
        source(archive_path), mode=ArchiveInspectionMode.FULL_CHECKSUM
    )
    inventory = archive_inspections_to_inventory(
        (inspection,),
        authority_id="archive-authority-v1",
        candidate_id="archive-candidate",
        source_alias="archive/candidate",
    )

    approved_registry = DatasetManifestRegistry()
    approved = DatasetEnrollmentService(approved_registry).enroll(
        inventory=inventory,
        proposal=_proposal(2),
        evidence_source=_evidence(RightsDecision.APPROVED),
        authority_validated=True,
        checked_at=NOW,
    )
    denied_registry = DatasetManifestRegistry()
    denied = DatasetEnrollmentService(denied_registry).enroll(
        inventory=inventory,
        proposal=_proposal(2),
        evidence_source=_evidence(RightsDecision.DENIED),
        authority_validated=True,
        checked_at=NOW,
    )
    assert approved.manifest_enrolled is True
    assert approved.dataset_version_issued is True
    assert approved.split_frozen is True
    assert denied.rights_gate_pass is False
    assert denied.manifest_enrolled is False
    assert denied.dataset_version_issued is False
    assert denied.split_frozen is False
    with pytest.raises(ContractError):
        denied_registry.get("dataset-manifest/audio/archive/v1")


def test_discovery_inventory_cannot_pass_integrity_without_member_sha256(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "discovery.zip"
    write_zip(archive_path, [("audio.wav", b"audio")])
    inspection = inspect(archive_path)
    inventory = archive_inspections_to_inventory(
        (inspection,),
        authority_id="archive-authority-v1",
        candidate_id="archive-candidate",
        source_alias="archive/candidate",
    )
    assert inventory.missing_checksum_count == 1
    result = DatasetEnrollmentService(DatasetManifestRegistry()).enroll(
        inventory=inventory,
        proposal=_proposal(1),
        evidence_source=_evidence(RightsDecision.APPROVED),
        authority_validated=True,
        checked_at=NOW,
    )
    assert result.rights_gate_pass is False
    assert result.integrity_pass is False
    assert result.manifest_enrolled is False
    assert "DATASET_CHECKSUM_INCOMPLETE" in result.reasons


def test_partial_or_cross_candidate_inspection_cannot_map_to_inventory(
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"bad")
    failed = inspect(corrupt)
    with pytest.raises(ContractError) as incomplete:
        archive_inspections_to_inventory(
            (failed,),
            authority_id="archive-authority-v1",
            candidate_id="archive-candidate",
            source_alias="archive/candidate",
        )
    assert incomplete.value.error_code == "ARCHIVE_INSPECTION_INCOMPLETE"

    valid = tmp_path / "valid.zip"
    write_zip(valid, [("audio.wav", b"audio")])
    valid_inspection = inspect(valid)
    unsafe = valid_inspection.model_copy(update={"path_safety_pass": False})
    with pytest.raises(ContractError) as unsafe_mapping:
        archive_inspections_to_inventory(
            (unsafe,),
            authority_id="archive-authority-v1",
            candidate_id="archive-candidate",
            source_alias="archive/candidate",
        )
    assert unsafe_mapping.value.error_code == "ARCHIVE_INSPECTION_INCOMPLETE"

    inspection = valid_inspection.model_copy(update={"candidate_id": "different-candidate"})
    with pytest.raises(ContractError) as mismatch:
        archive_inspections_to_inventory(
            (inspection,),
            authority_id="archive-authority-v1",
            candidate_id="archive-candidate",
            source_alias="archive/candidate",
        )
    assert mismatch.value.error_code == "ARCHIVE_CANDIDATE_MISMATCH"
