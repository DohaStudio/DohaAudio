from __future__ import annotations

import hashlib
import json
import warnings
import zipfile
from datetime import UTC, datetime
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
    StructuralGroupDisposition,
    decide_candidate_ingestion,
)
from dohaaudio.archives import ArchiveInspectionPolicy, ArchiveSource, ZipArchiveInspector
from dohaaudio.errors import ContractError
from dohaaudio.semantic_role_evidence import (
    EvidenceObservationKind,
    EvidenceSamplingStrategy,
    HumanReviewOutcome,
    HumanSemanticRoleReview,
    InMemorySemanticRoleEvidenceRegistry,
    ProposedSemanticRole,
    RoleEvidenceSamplingPlan,
    SemanticReviewStatus,
    SemanticRoleEvidence,
    SemanticRoleEvidencePolicy,
    SemanticRoleReviewDecision,
    apply_semantic_review_decisions,
    collect_semantic_role_evidence,
    review_semantic_role,
    select_evidence_members,
)

CANDIDATE = "semantic-evidence-candidate"


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries.items():
                archive.writestr(name, payload)


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="surrogatepass")).hexdigest()


def _membership_fingerprint(sources: tuple[ArchiveSource, ...]) -> str:
    records: list[str] = []
    for source in sources:
        with zipfile.ZipFile(source.path, mode="r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                records.append(
                    f"{source.archive_logical_id}:"
                    f"{_digest(source.candidate_id, source.archive_logical_id, info.filename)}:"
                    f"{info.file_size}:{info.CRC:08x}"
                )
    evidence = hashlib.sha256()
    for record in sorted(records):
        evidence.update(record.encode())
    return evidence.hexdigest()


def _pipeline(
    tmp_path: Path,
    archives: tuple[dict[str, bytes], ...],
    *,
    candidate_id: str = CANDIDATE,
):  # type: ignore[no-untyped-def]
    inspector = ZipArchiveInspector(
        ArchiveInspectionPolicy(
            max_members_per_archive=100,
            max_member_uncompressed_bytes=16_384,
            max_total_uncompressed_bytes=100_000,
            max_compression_ratio=1_000,
            max_member_name_bytes=512,
            stream_chunk_bytes=17,
        )
    )
    sources: list[ArchiveSource] = []
    inputs: list[ArchiveInterpretationInput] = []
    for index, entries in enumerate(archives):
        path = tmp_path / f"archive-{index}.zip"
        _write_zip(path, entries)
        source = ArchiveSource(
            candidate_id=candidate_id,
            archive_logical_id=f"{candidate_id}/archive/{index:04d}",
            path=path,
        )
        sources.append(source)
        inputs.append(ArchiveInterpretationInput(source, inspector.inspect(source)))
    fingerprint = _membership_fingerprint(tuple(sources))
    path_policy = ArchivePathInterpretationPolicy(
        policy_id=f"archive-path/{candidate_id}/v1",
        policy_version="1.0.0",
        candidate_id=candidate_id,
        evidence_fingerprint=fingerprint,
        rule=ArchivePathInterpretationRule.SINGLE_LEADING_SLASH_ROOT_MARKER,
    )
    membership = interpret_archive_paths(inputs, path_policy)
    companion = CompanionIngestionPolicy(
        policy_id=f"archive-companion/{candidate_id}/v1",
        policy_version="1.0.0",
        candidate_id=candidate_id,
        role_dispositions={role: CompanionDisposition.REVIEW_REQUIRED for role in CompanionRole},
    )
    relationships = analyze_companion_relationships(membership, companion)
    role_policy = CandidateRoleDispositionPolicy(
        policy_id=f"archive-role/{candidate_id}/v1",
        policy_version="1.0.0",
        candidate_id=candidate_id,
        path_policy_id=path_policy.policy_id,
        path_policy_version=path_policy.policy_version,
        path_evidence_fingerprint=fingerprint,
        companion_policy_id=companion.policy_id,
        companion_policy_version=companion.policy_version,
        role_dispositions={role: CompanionDisposition.REVIEW_REQUIRED for role in CompanionRole},
        complete_group_disposition=StructuralGroupDisposition.INCLUDE,
        partial_group_disposition=StructuralGroupDisposition.REVIEW_REQUIRED,
        orphan_group_disposition=StructuralGroupDisposition.REVIEW_REQUIRED,
    )
    return tuple(inputs), membership, relationships, role_policy


def _plan(
    role: CompanionRole,
    *,
    candidate_id: str = CANDIDATE,
    count: int = 2,
    version: str = "1.0.0",
) -> RoleEvidenceSamplingPlan:
    return RoleEvidenceSamplingPlan(
        plan_id=f"semantic-sampling/{candidate_id}/{role}/v1",
        plan_version=version,
        candidate_id=candidate_id,
        structural_role=role,
        strategy=EvidenceSamplingStrategy.DETERMINISTIC_ARCHIVE_COVERAGE,
        requested_sample_count=count,
        selection_key="stable-review-key-v1",
        coverage_dimensions=("archive_logical_id", "logical_member_identity"),
        max_probe_bytes=4096,
    )


def _evidence_policy(
    evidence: SemanticRoleEvidence,
    *,
    minimum: int = 1,
    require_complete: bool = True,
    plan_version: str | None = None,
    reviewer_authorities: tuple[str, ...] = (),
) -> SemanticRoleEvidencePolicy:
    return SemanticRoleEvidencePolicy(
        policy_id=f"semantic-evidence-policy/{evidence.candidate_id}/{evidence.structural_role}/v1",
        policy_version="1.0.0",
        candidate_id=evidence.candidate_id,
        structural_role=evidence.structural_role,
        sampling_plan_id=evidence.sampling_plan_id,
        sampling_plan_version=plan_version or evidence.sampling_plan_version,
        path_policy_id=evidence.path_policy_id,
        path_policy_version=evidence.path_policy_version,
        path_evidence_fingerprint=evidence.path_evidence_fingerprint,
        companion_policy_id=evidence.companion_policy_id,
        companion_policy_version=evidence.companion_policy_version,
        role_policy_id=evidence.role_policy_id,
        role_policy_version=evidence.role_policy_version,
        required_observation_kind=evidence.observation_kind,
        minimum_sample_count=minimum,
        require_complete_observations=require_complete,
        approved_reviewer_authority_ids=reviewer_authorities,
    )


def _human_review(
    evidence: SemanticRoleEvidence,
    policy: SemanticRoleEvidencePolicy,
    proposed: ProposedSemanticRole,
    *,
    outcome: HumanReviewOutcome = HumanReviewOutcome.APPROVED,
) -> HumanSemanticRoleReview:
    return HumanSemanticRoleReview(
        review_id=f"synthetic-human-review/{evidence.structural_role}",
        reviewer_authority_id="synthetic-test-review-authority",
        candidate_id=evidence.candidate_id,
        structural_role=evidence.structural_role,
        proposed_semantic_role=proposed,
        evidence_id=evidence.evidence_id,
        evidence_fingerprint=evidence.evidence_fingerprint,
        evidence_policy_id=policy.policy_id,
        evidence_policy_version=policy.policy_version,
        outcome=outcome,
        reviewed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def _midi_header(smf_format: int, tracks: int, division: int) -> bytes:
    return (
        b"MThd"
        + (6).to_bytes(4, "big")
        + smf_format.to_bytes(2, "big")
        + tracks.to_bytes(2, "big")
        + division.to_bytes(2, "big")
    )


def test_sampling_is_deterministic_and_covers_archives(tmp_path: Path) -> None:
    inputs, membership, _, _ = _pipeline(
        tmp_path,
        (
            {"/a/one.json": b"{}", "/a/two.json": b"{}"},
            {"/b/three.json": b"{}", "/b/four.json": b"{}"},
        ),
    )
    plan = _plan(CompanionRole.JSON, count=2)
    selected = select_evidence_members(membership, plan)
    reversed_membership = membership.model_copy(
        update={"members": tuple(reversed(membership.members))}
    )
    assert selected == select_evidence_members(reversed_membership, plan)
    assert len({member.archive_logical_id for member in selected}) == 2
    assert len(inputs) == 2


def test_sampling_fails_closed_across_candidate_and_membership_changes(
    tmp_path: Path,
) -> None:
    inputs, membership, _, role_policy = _pipeline(
        tmp_path,
        ({"/a.json": b"{}"},),
    )
    with pytest.raises(ContractError) as candidate_error:
        collect_semantic_role_evidence(
            inputs,
            membership,
            role_policy,
            _plan(CompanionRole.JSON, candidate_id="other-candidate"),
        )
    assert candidate_error.value.error_code == "SEMANTIC_EVIDENCE_CANDIDATE_MISMATCH"

    changed_membership = membership.model_copy(update={"evidence_fingerprint": "f" * 64})
    with pytest.raises(ContractError) as membership_error:
        collect_semantic_role_evidence(
            inputs,
            changed_membership,
            role_policy,
            _plan(CompanionRole.JSON),
        )
    assert membership_error.value.error_code == "SEMANTIC_EVIDENCE_MEMBERSHIP_MISMATCH"


def test_sampling_clamps_to_population_and_handles_empty_population(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(
        tmp_path,
        ({"/a.json": b"{}", "/b.mid": _midi_header(0, 1, 480)},),
    )
    json_evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.JSON, count=99),
    )
    assert json_evidence.population_count == 1
    assert json_evidence.sample_count == 1

    empty = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.AUDIO, count=99),
    )
    assert empty.population_count == empty.sample_count == 0
    assert empty.observation_kind == EvidenceObservationKind.MEMBERSHIP_ONLY
    assert empty.reason_codes == ("SEMANTIC_EVIDENCE_POPULATION_EMPTY",)


def test_json_evidence_reports_consistent_schema_without_raw_values(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(
        tmp_path,
        (
            {
                "/a.json": json.dumps(
                    {"dataSet": {"sourceUrl": "private-title-one", "labels": [1, 2]}}
                ).encode(),
                "/b.json": json.dumps(
                    {"dataSet": {"sourceUrl": "private-title-two", "labels": [3, 4]}}
                ).encode(),
            },
        ),
    )
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.JSON),
    )
    assert evidence.json_summary is not None
    assert evidence.json_summary.valid_document_count == 2
    assert len(evidence.json_summary.unique_schema_fingerprints) == 1
    assert evidence.json_summary.schema_mismatch_count == 0
    assert evidence.json_summary.key_category_presence_counts == {
        "annotation_like": 2,
        "dataset_like": 2,
        "reference_like": 2,
    }
    serialized = evidence.model_dump_json()
    assert "private-title-one" not in serialized
    assert "private-title-two" not in serialized
    assert "/a.json" not in serialized


def test_json_evidence_detects_nested_and_array_schema_variation(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(
        tmp_path,
        (
            {
                "/a.json": b'{"annotation":{"items":[1,2]}}',
                "/b.json": b'{"annotation":{"items":["x"]}}',
                "/c.json": b'{"other":true}',
            },
        ),
    )
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.JSON, count=3),
    )
    assert evidence.json_summary is not None
    assert len(evidence.json_summary.unique_schema_fingerprints) == 3
    assert evidence.json_summary.schema_mismatch_count == 2
    assert evidence.json_summary.key_category_presence_counts["annotation_like"] == 2


def test_json_evidence_handles_invalid_json_and_has_deterministic_fingerprint(
    tmp_path: Path,
) -> None:
    inputs, membership, _, role_policy = _pipeline(
        tmp_path,
        ({"/a.json": b"not-json", "/b.json": b"{}"},),
    )
    plan = _plan(CompanionRole.JSON)
    first = collect_semantic_role_evidence(inputs, membership, role_policy, plan)
    second = collect_semantic_role_evidence(inputs, membership, role_policy, plan)
    assert first == second
    assert first.json_summary is not None
    assert first.json_summary.invalid_document_count == 1
    assert first.raw_evidence_complete is False


def test_midi_evidence_reports_only_bounded_header_distributions(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(
        tmp_path,
        (
            {
                "/a.mid": _midi_header(0, 1, 480) + b"private-midi-body",
                "/b.mid": _midi_header(1, 3, 120) + b"private-midi-body",
            },
        ),
    )
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.MIDI),
    )
    assert evidence.midi_summary is not None
    assert evidence.midi_summary.format_distribution == {"0": 1, "1": 1}
    assert evidence.midi_summary.track_count_distribution == {"1": 1, "3": 1}
    assert evidence.midi_summary.division_distribution == {"120": 1, "480": 1}
    assert "private-midi-body" not in evidence.model_dump_json()


@pytest.mark.parametrize(
    "payload",
    [b"MThd", b"invalid-header!", b"MThd" + (7).to_bytes(4, "big") + b"\x00" * 6],
)
def test_midi_evidence_rejects_invalid_or_truncated_headers(
    tmp_path: Path,
    payload: bytes,
) -> None:
    inputs, membership, _, role_policy = _pipeline(tmp_path, ({"/a.mid": payload},))
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.MIDI, count=1),
    )
    assert evidence.midi_summary is not None
    assert evidence.midi_summary.invalid_header_count == 1
    assert evidence.raw_evidence_complete is False


def test_audio_evidence_is_membership_only_and_performs_no_wav_probe(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(
        tmp_path,
        ({"/a.wav": b"not-read-as-audio"},),
    )
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.AUDIO, count=0),
    )
    assert evidence.population_count == 1
    assert evidence.sample_count == 0
    assert evidence.membership_summary is not None
    assert evidence.membership_summary.content_probe_performed is False
    assert "not-read-as-audio" not in evidence.model_dump_json()


def test_evidence_deserialization_and_registry_are_immutable(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(tmp_path, ({"/a.json": b"{}"},))
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.JSON, count=1),
    )
    payload = evidence.model_dump()
    payload["population_count"] = 2
    with pytest.raises(ValidationError):
        SemanticRoleEvidence(**payload)

    registry = InMemorySemanticRoleEvidenceRegistry()
    assert registry.publish(evidence) == evidence
    tampered = evidence.model_copy(update={"reason_codes": ("SEMANTIC_EVIDENCE_TAMPERED",)})
    with pytest.raises(ContractError) as exc_info:
        registry.publish(tampered)
    assert exc_info.value.error_code == "SEMANTIC_EVIDENCE_IMMUTABLE_CONFLICT"


def test_automated_analysis_never_approves_semantic_roles(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(tmp_path, ({"/a.json": b"{}"},))
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.JSON, count=1),
    )
    policy = _evidence_policy(
        evidence,
        reviewer_authorities=("synthetic-test-review-authority",),
    )
    decision = review_semantic_role(
        evidence,
        policy,
        ProposedSemanticRole.METADATA_CANDIDATE,
    )
    assert decision.status == SemanticReviewStatus.REVIEW_REQUIRED
    assert decision.human_review_id is None
    assert decision.reason_codes == ("SEMANTIC_REVIEW_HUMAN_APPROVAL_REQUIRED",)
    with pytest.raises(ValidationError):
        SemanticRoleEvidencePolicy(**(policy.model_dump() | {"allow_automatic_approval": True}))


def test_review_rejects_plan_policy_and_evidence_binding_mismatches(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(tmp_path, ({"/a.json": b"{}"},))
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.JSON, count=1),
    )
    policy = _evidence_policy(
        evidence,
        reviewer_authorities=("synthetic-test-review-authority",),
    )
    mismatches = (
        {"candidate_id": "other-candidate"},
        {"sampling_plan_version": "2.0.0"},
        {"path_evidence_fingerprint": "f" * 64},
        {"role_policy_version": "2.0.0"},
    )
    for update in mismatches:
        with pytest.raises(ContractError) as exc_info:
            review_semantic_role(
                evidence,
                policy.model_copy(update=update),
                ProposedSemanticRole.METADATA_CANDIDATE,
            )
        assert exc_info.value.error_code == "SEMANTIC_REVIEW_EVIDENCE_POLICY_MISMATCH"


def test_human_review_can_approve_or_reject_only_exact_sufficient_evidence(
    tmp_path: Path,
) -> None:
    inputs, membership, _, role_policy = _pipeline(tmp_path, ({"/a.json": b"{}"},))
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.JSON, count=1),
    )
    policy = _evidence_policy(
        evidence,
        reviewer_authorities=("synthetic-test-review-authority",),
    )
    proposed = ProposedSemanticRole.METADATA_CANDIDATE
    approved = review_semantic_role(
        evidence,
        policy,
        proposed,
        human_review=_human_review(evidence, policy, proposed),
    )
    rejected = review_semantic_role(
        evidence,
        policy,
        proposed,
        human_review=_human_review(
            evidence,
            policy,
            proposed,
            outcome=HumanReviewOutcome.REJECTED,
        ),
    )
    assert approved.status == SemanticReviewStatus.APPROVED
    assert rejected.status == SemanticReviewStatus.REJECTED

    wrong_review = _human_review(evidence, policy, proposed).model_copy(
        update={"evidence_fingerprint": "f" * 64}
    )
    with pytest.raises(ContractError) as exc_info:
        review_semantic_role(evidence, policy, proposed, human_review=wrong_review)
    assert exc_info.value.error_code == "SEMANTIC_REVIEW_HUMAN_AUTHORITY_MISMATCH"

    no_authority_policy = _evidence_policy(evidence)
    with pytest.raises(ContractError) as no_authority_error:
        review_semantic_role(
            evidence,
            no_authority_policy,
            proposed,
            human_review=_human_review(evidence, no_authority_policy, proposed),
        )
    assert no_authority_error.value.error_code == "SEMANTIC_REVIEW_HUMAN_AUTHORITY_MISMATCH"


def test_insufficient_evidence_blocks_human_approval_and_forged_status(tmp_path: Path) -> None:
    inputs, membership, _, role_policy = _pipeline(tmp_path, ({"/a.json": b"{}"},))
    evidence = collect_semantic_role_evidence(
        inputs,
        membership,
        role_policy,
        _plan(CompanionRole.JSON, count=1),
    )
    policy = _evidence_policy(
        evidence,
        minimum=2,
        reviewer_authorities=("synthetic-test-review-authority",),
    )
    proposed = ProposedSemanticRole.METADATA_CANDIDATE
    blocked = review_semantic_role(
        evidence,
        policy,
        proposed,
        human_review=_human_review(evidence, policy, proposed),
    )
    assert blocked.status == SemanticReviewStatus.BLOCKED
    assert blocked.human_review_id is None

    payload = blocked.model_dump()
    payload["status"] = SemanticReviewStatus.APPROVED
    with pytest.raises(ValidationError):
        SemanticRoleReviewDecision(**payload)


def test_role_policy_integration_keeps_automatic_reviews_closed_and_accepts_synthetic_human_fixture(
    tmp_path: Path,
) -> None:
    inputs, membership, relationships, role_policy = _pipeline(
        tmp_path,
        (
            {
                "/a.json": b"{}",
                "/a.mid": _midi_header(1, 2, 120),
                "/a.wav": b"membership-only",
            },
        ),
    )
    proposed_roles = {
        CompanionRole.AUDIO: ProposedSemanticRole.PRIMARY_AUDIO_CANDIDATE,
        CompanionRole.MIDI: ProposedSemanticRole.SYMBOLIC_COMPANION_CANDIDATE,
        CompanionRole.JSON: ProposedSemanticRole.METADATA_CANDIDATE,
        CompanionRole.OTHER: ProposedSemanticRole.UNSUPPORTED,
    }
    automatic = []
    human_approved = []
    evidence_records = []
    evidence_policies = []
    for role in CompanionRole:
        evidence = collect_semantic_role_evidence(
            inputs,
            membership,
            role_policy,
            _plan(role, count=0 if role in {CompanionRole.AUDIO, CompanionRole.OTHER} else 1),
        )
        membership_only = evidence.observation_kind == EvidenceObservationKind.MEMBERSHIP_ONLY
        policy = _evidence_policy(
            evidence,
            minimum=0 if membership_only else 1,
            require_complete=not membership_only,
            reviewer_authorities=("synthetic-test-review-authority",),
        )
        proposed = proposed_roles[role]
        evidence_records.append(evidence)
        evidence_policies.append(policy)
        automatic.append(review_semantic_role(evidence, policy, proposed))
        human_approved.append(
            review_semantic_role(
                evidence,
                policy,
                proposed,
                human_review=_human_review(evidence, policy, proposed),
            )
        )

    automatic_policy = apply_semantic_review_decisions(
        role_policy,
        automatic,
        evidence_records,
        evidence_policies,
    )
    automatic_decision = decide_candidate_ingestion(
        membership,
        relationships,
        automatic_policy,
    )
    assert automatic_decision.inventory_ready is False
    assert all(
        status == CompanionDisposition.REVIEW_REQUIRED
        for status in automatic_policy.role_dispositions.values()
    )

    approved_policy = apply_semantic_review_decisions(
        role_policy,
        human_approved,
        evidence_records,
        evidence_policies,
    )
    approved_decision = decide_candidate_ingestion(
        membership,
        relationships,
        approved_policy,
    )
    assert approved_decision.inventory_ready is True
    assert all(decision.status == SemanticReviewStatus.APPROVED for decision in human_approved)

    policies_without_authority = [
        policy.model_copy(update={"approved_reviewer_authority_ids": ()})
        for policy in evidence_policies
    ]
    with pytest.raises(ContractError) as forged_error:
        apply_semantic_review_decisions(
            role_policy,
            human_approved,
            evidence_records,
            policies_without_authority,
        )
    assert forged_error.value.error_code == "SEMANTIC_REVIEW_REVIEWER_AUTHORITY_MISMATCH"

    forged_decisions = list(human_approved)
    forged_decisions[0] = forged_decisions[0].model_copy(update={"evidence_fingerprint": "f" * 64})
    with pytest.raises(ContractError) as evidence_error:
        apply_semantic_review_decisions(
            role_policy,
            forged_decisions,
            evidence_records,
            evidence_policies,
        )
    assert evidence_error.value.error_code == "SEMANTIC_REVIEW_EVIDENCE_MISMATCH"

    with pytest.raises(ContractError) as duplicate_error:
        apply_semantic_review_decisions(
            role_policy,
            [*human_approved, human_approved[0]],
            evidence_records,
            evidence_policies,
        )
    assert duplicate_error.value.error_code == "SEMANTIC_REVIEW_ROLE_DUPLICATE"
