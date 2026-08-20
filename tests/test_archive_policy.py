from __future__ import annotations

import warnings
import zipfile
from pathlib import Path

import pytest

from dohaaudio.archive_policy import (
    ArchiveInterpretationInput,
    ArchivePathInterpretationPolicy,
    ArchivePathInterpretationRule,
    CompanionDisposition,
    CompanionIngestionPolicy,
    CompanionRole,
    analyze_companion_relationships,
    build_candidate_ingestion_view,
    interpret_archive_paths,
)
from dohaaudio.archives import (
    ArchiveInspectionPolicy,
    ArchiveInspectionStatus,
    ArchiveSource,
    ZipArchiveInspector,
)
from dohaaudio.datasets import DatasetManifestRegistry
from dohaaudio.errors import ContractError

CANDIDATE = "archive-policy-candidate"


def _write_zip(path: Path, names: list[str]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.writestr(name, f"synthetic:{name}".encode())


def _inspector() -> ZipArchiveInspector:
    return ZipArchiveInspector(
        ArchiveInspectionPolicy(
            max_members_per_archive=100,
            max_member_uncompressed_bytes=1024,
            max_total_uncompressed_bytes=10_000,
            max_compression_ratio=100.0,
            max_member_name_bytes=512,
            stream_chunk_bytes=17,
        )
    )


def _path_policy(candidate_id: str = CANDIDATE) -> ArchivePathInterpretationPolicy:
    return ArchivePathInterpretationPolicy(
        policy_id=f"archive-path/{candidate_id}/v1",
        policy_version="1.0.0",
        candidate_id=candidate_id,
        rule=ArchivePathInterpretationRule.SINGLE_LEADING_SLASH_ROOT_MARKER,
    )


def _companion_policy(candidate_id: str = CANDIDATE) -> CompanionIngestionPolicy:
    return CompanionIngestionPolicy(
        policy_id=f"archive-companion/{candidate_id}/v1",
        policy_version="1.0.0",
        candidate_id=candidate_id,
        role_dispositions={role: CompanionDisposition.REVIEW_REQUIRED for role in CompanionRole},
    )


def _interpret(path: Path, *, candidate_id: str = CANDIDATE):  # type: ignore[no-untyped-def]
    source = ArchiveSource(
        candidate_id=candidate_id,
        archive_logical_id=f"{candidate_id}/archive/one",
        path=path,
    )
    inspection = _inspector().inspect(source)
    membership = interpret_archive_paths(
        (ArchiveInterpretationInput(source=source, inspection=inspection),),
        _path_policy(candidate_id),
    )
    return inspection, membership


def test_generic_inspector_remains_blocked_while_candidate_policy_interprets(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "valid.zip"
    _write_zip(archive, ["/foo/a.wav", "/foo/a.mid", "/foo/a.json"])
    inspection, membership = _interpret(archive)

    assert inspection.inspection_status == ArchiveInspectionStatus.BLOCKED
    assert inspection.path_safety_pass is False
    assert membership.raw_path_safety_pass is False
    assert membership.path_interpretation_applied is True
    assert membership.path_interpretation_pass is True
    assert membership.interpreted_path_safety_pass is True
    assert membership.interpreted_member_count == 3
    assert all(not member.raw_path_safety_pass for member in membership.members)
    assert all(member.interpreted_path_safety_pass for member in membership.members)


@pytest.mark.parametrize(
    "names",
    [
        ["/foo/a.wav", "foo/a.mid"],
        ["/foo/a.wav", "//foo/a.mid"],
        ["/../escape.wav"],
        ["/C:/escape.wav"],
        ["/\\\\server\\share\\escape.wav"],
        ["/folder:name/escape.wav"],
        ["/%2e%2e/escape.wav"],
        ["/%252e%252e/escape.wav"],
    ],
)
def test_unapproved_or_unsafe_interpretation_patterns_fail_closed(
    tmp_path: Path, names: list[str]
) -> None:
    archive = tmp_path / "blocked.zip"
    _write_zip(archive, names)
    _, membership = _interpret(archive)
    assert membership.path_interpretation_pass is False
    assert membership.post_interpretation_unsafe_count > 0


@pytest.mark.parametrize(
    "names",
    [
        ["/A/a.wav", "/a/A.wav"],
        ["/folder/a.wav", "/folder\\a.wav"],
        ["/caf\u00e9/a.wav", "/cafe\u0301/a.wav"],
    ],
)
def test_interpretation_collisions_fail_closed(tmp_path: Path, names: list[str]) -> None:
    archive = tmp_path / "collision.zip"
    _write_zip(archive, names)
    _, membership = _interpret(archive)
    assert membership.path_interpretation_pass is False
    assert membership.collision_member_count == 2


def test_policy_is_candidate_bound(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.zip"
    _write_zip(archive, ["/a.wav"])
    source = ArchiveSource(candidate_id=CANDIDATE, archive_logical_id="archive/one", path=archive)
    inspection = _inspector().inspect(source)
    with pytest.raises(ContractError) as exc_info:
        interpret_archive_paths(
            (ArchiveInterpretationInput(source=source, inspection=inspection),),
            _path_policy("different-candidate"),
        )
    assert exc_info.value.error_code == "ARCHIVE_INTERPRETATION_CANDIDATE_MISMATCH"


def test_interpreted_mapping_is_deterministic_reversible_and_path_free(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    names = ["/foo/a.wav", "/foo/a.mid", "/foo/a.json"]
    _write_zip(first, names)
    _write_zip(second, list(reversed(names)))
    _, first_result = _interpret(first)
    _, second_result = _interpret(second)
    assert first_result.members == second_result.members
    assert first_result.evidence_fingerprint == second_result.evidence_fingerprint
    serialized = first_result.model_dump_json()
    assert str(tmp_path) not in serialized
    assert all(name not in serialized for name in names)
    assert all(member.raw_member_fingerprint for member in first_result.members)
    assert all(member.interpreted_member_id for member in first_result.members)


def test_complete_triple_and_extension_case_are_grouped(tmp_path: Path) -> None:
    archive = tmp_path / "complete.zip"
    _write_zip(archive, ["/foo/a.WAV", "/foo/a.MID", "/foo/a.JSON"])
    _, membership = _interpret(archive)
    result = analyze_companion_relationships(membership, _companion_policy())
    assert result.relationship_pass is True
    assert result.group_count == result.complete_group_count == 1
    assert result.partial_group_count == result.orphan_group_count == 0


def test_companion_policy_is_candidate_bound(tmp_path: Path) -> None:
    archive = tmp_path / "candidate-companion.zip"
    _write_zip(archive, ["/foo/a.wav", "/foo/a.mid", "/foo/a.json"])
    _, membership = _interpret(archive)
    with pytest.raises(ContractError) as exc_info:
        analyze_companion_relationships(membership, _companion_policy("different-candidate"))
    assert exc_info.value.error_code == "COMPANION_POLICY_CANDIDATE_MISMATCH"


@pytest.mark.parametrize(
    ("names", "missing_role"),
    [
        (["/foo/a.wav", "/foo/a.mid"], CompanionRole.JSON),
        (["/foo/a.wav", "/foo/a.json"], CompanionRole.MIDI),
        (["/foo/a.mid", "/foo/a.json"], CompanionRole.AUDIO),
    ],
)
def test_missing_companion_role_is_partial(
    tmp_path: Path, names: list[str], missing_role: CompanionRole
) -> None:
    archive = tmp_path / "partial.zip"
    _write_zip(archive, names)
    _, membership = _interpret(archive)
    result = analyze_companion_relationships(membership, _companion_policy())
    assert result.relationship_pass is False
    assert result.partial_group_count == 1
    assert missing_role in result.groups[0].missing_roles


def test_duplicate_companion_role_is_blocked(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate-role.zip"
    _write_zip(archive, ["/foo/a.wav", "/foo/a.mid", "/foo/a.midi", "/foo/a.json"])
    _, membership = _interpret(archive)
    result = analyze_companion_relationships(membership, _companion_policy())
    assert result.relationship_pass is False
    assert result.duplicate_role_group_count == 1
    assert CompanionRole.MIDI in result.groups[0].duplicate_roles


def test_orphan_and_directory_bound_same_basename_are_distinct(tmp_path: Path) -> None:
    archive = tmp_path / "groups.zip"
    _write_zip(
        archive,
        [
            "/one/a.wav",
            "/two/a.wav",
            "/two/a.mid",
            "/two/a.json",
        ],
    )
    _, membership = _interpret(archive)
    result = analyze_companion_relationships(membership, _companion_policy())
    assert result.group_count == 2
    assert result.complete_group_count == 1
    assert result.orphan_group_count == 1


def test_companion_result_does_not_disclose_raw_filenames(tmp_path: Path) -> None:
    archive = tmp_path / "private.zip"
    names = ["/private/source.wav", "/private/source.mid", "/private/source.json"]
    _write_zip(archive, names)
    _, membership = _interpret(archive)
    result = analyze_companion_relationships(membership, _companion_policy())
    serialized = result.model_dump_json()
    assert all(name not in serialized for name in names)
    assert str(tmp_path) not in serialized


def test_ingestion_view_stays_blocked_without_semantic_policy_checksums_or_rights(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "integration.zip"
    _write_zip(archive, ["/foo/a.wav", "/foo/a.mid", "/foo/a.json"])
    _, membership = _interpret(archive)
    policy = _companion_policy()
    relationships = analyze_companion_relationships(membership, policy)
    view = build_candidate_ingestion_view(membership, relationships, policy)
    registry = DatasetManifestRegistry()
    rights_gate_pass = False

    assert view.path_interpretation_pass is True
    assert view.companion_relationship_pass is True
    assert view.ingestion_policy_resolved is False
    assert view.content_checksum_complete is False
    assert view.dataset_inventory_ready is False
    assert rights_gate_pass is False
    with pytest.raises(ContractError):
        registry.get("dataset-manifest/not-issued")
