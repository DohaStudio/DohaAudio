from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from dohaaudio.archive_policy import CompanionDisposition, CompanionRole
from dohaaudio.archive_role_policy import decide_candidate_ingestion
from dohaaudio.errors import ContractError
from dohaaudio.semantic_review_workflow import (
    HumanSemanticReviewDecisionRegistry,
    HumanSemanticReviewWorkflow,
    ReviewerAction,
    ReviewerAuthority,
    ReviewerAuthorityRegistry,
    ReviewerAuthorityStatus,
    SemanticReviewRequest,
    SemanticReviewRequestRegistry,
    SemanticReviewRequestStatus,
)
from dohaaudio.semantic_role_evidence import (
    HumanReviewOutcome,
    InMemorySemanticRoleEvidenceRegistry,
    ProposedSemanticRole,
    SemanticReviewStatus,
    collect_semantic_role_evidence,
)
from tests.test_semantic_role_evidence import _evidence_policy, _pipeline, _plan

NOW = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)
AUTHORITY_ID = "reviewer-authority/reviewer-test/music/json/v1"
REVIEWER_ID = "reviewer-test/music/json/v1"


def _authority(
    evidence,  # type: ignore[no-untyped-def]
    evidence_policy,  # type: ignore[no-untyped-def]
    *,
    authority_id: str = AUTHORITY_ID,
    reviewer_id: str = REVIEWER_ID,
    semantic_role: ProposedSemanticRole = ProposedSemanticRole.METADATA_CANDIDATE,
    status: ReviewerAuthorityStatus = ReviewerAuthorityStatus.ACTIVE,
    effective_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime | None = NOW + timedelta(days=1),
    revoked_at: datetime | None = None,
    actions: tuple[ReviewerAction, ...] = (ReviewerAction.APPROVE, ReviewerAction.REJECT),
) -> ReviewerAuthority:
    return ReviewerAuthority(
        authority_id=authority_id,
        authority_version="1.0.0",
        reviewer_id=reviewer_id,
        candidate_id=evidence.candidate_id,
        structural_roles=(evidence.structural_role,),
        semantic_roles=(semantic_role,),
        evidence_policy_ids=(evidence_policy.policy_id,),
        role_policy_ids=(evidence.role_policy_id,),
        allowed_actions=actions,
        status=status,
        effective_at=effective_at,
        expires_at=expires_at,
        revoked_at=revoked_at,
        created_at=NOW - timedelta(days=2),
        audit_reason_code="SEMANTIC_REVIEW_SYNTHETIC_AUTHORITY",
    )


def _fixture(tmp_path: Path):  # type: ignore[no-untyped-def]
    tmp_path.mkdir(parents=True, exist_ok=True)
    inputs, membership, relationships, role_policy = _pipeline(
        tmp_path,
        (
            {
                "/a.json": b"{}",
                "/a.mid": b"MThd\x00\x00\x00\x06\x00\x01\x00\x02\x00x",
                "/a.wav": b"audio",
            },
        ),
    )
    evidence = collect_semantic_role_evidence(
        inputs, membership, role_policy, _plan(CompanionRole.JSON, count=1)
    )
    policy = _evidence_policy(
        evidence,
        reviewer_authorities=(AUTHORITY_ID,),
    )
    evidence_registry = InMemorySemanticRoleEvidenceRegistry()
    evidence_registry.publish(evidence)
    authorities = ReviewerAuthorityRegistry()
    requests = SemanticReviewRequestRegistry()
    decisions = HumanSemanticReviewDecisionRegistry()
    workflow = HumanSemanticReviewWorkflow(evidence_registry, authorities, requests, decisions)
    return (
        inputs,
        membership,
        relationships,
        role_policy,
        evidence,
        policy,
        authorities,
        requests,
        decisions,
        workflow,
    )


def _request(fixture):  # type: ignore[no-untyped-def]
    *_, role_policy, evidence, policy, authorities, requests, decisions, workflow = fixture
    authority = _authority(evidence, policy)
    authorities.register(authority)
    request = workflow.create_request(
        evidence,
        policy,
        role_policy,
        ProposedSemanticRole.METADATA_CANDIDATE,
        created_at=NOW,
    )
    return (
        request,
        authority,
        role_policy,
        evidence,
        policy,
        authorities,
        requests,
        decisions,
        workflow,
    )


def _submit(
    workflow: HumanSemanticReviewWorkflow,
    request_id: str,
    role_policy,  # type: ignore[no-untyped-def]
    evidence,  # type: ignore[no-untyped-def]
    policy,  # type: ignore[no-untyped-def]
    *,
    outcome: HumanReviewOutcome = HumanReviewOutcome.APPROVED,
):
    return workflow.submit_decision(
        request_id,
        authority_id=AUTHORITY_ID,
        authority_version="1.0.0",
        reviewer_id=REVIEWER_ID,
        outcome=outcome,
        reason_code=(
            "SEMANTIC_REVIEW_SYNTHETIC_APPROVED"
            if outcome == HumanReviewOutcome.APPROVED
            else "SEMANTIC_REVIEW_SYNTHETIC_REJECTED"
        ),
        decided_at=NOW,
        current_evidence=evidence,
        current_evidence_policy=policy,
        current_role_policy=role_policy,
    )


def test_authority_registry_is_versioned_idempotent_immutable_and_private(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _, authority, _, evidence, policy, authorities, *_ = _request(fixture)
    assert authorities.register(authority) == authority
    with pytest.raises(ContractError) as conflict:
        authorities.register(
            authority.model_copy(update={"semantic_roles": (ProposedSemanticRole.UNKNOWN,)})
        )
    assert conflict.value.error_code == "REVIEWER_AUTHORITY_IMMUTABLE_CONFLICT"

    with pytest.raises(ValidationError):
        _authority(evidence, policy, reviewer_id="private@reviewer")


@pytest.mark.parametrize(
    ("authority_update", "error_code"),
    (
        (
            {
                "effective_at": NOW + timedelta(days=1),
                "expires_at": NOW + timedelta(days=2),
            },
            "REVIEWER_AUTHORITY_NOT_EFFECTIVE",
        ),
        (
            {
                "effective_at": NOW - timedelta(days=2),
                "expires_at": NOW - timedelta(days=1),
            },
            "REVIEWER_AUTHORITY_EXPIRED",
        ),
        (
            {
                "status": ReviewerAuthorityStatus.REVOKED,
                "revoked_at": NOW - timedelta(hours=1),
            },
            "REVIEWER_AUTHORITY_REVOKED",
        ),
    ),
)
def test_future_expired_and_pre_revoked_authorities_fail_closed(
    tmp_path: Path,
    authority_update: dict[str, object],
    error_code: str,
) -> None:
    fixture = _fixture(tmp_path)
    _, _, role_policy, evidence, policy, authorities, _, _, workflow = _request(fixture)
    replacement = _authority(evidence, policy).model_copy(update=authority_update)
    replacement = ReviewerAuthority(**replacement.model_dump())
    other_authorities = ReviewerAuthorityRegistry()
    other_authorities.register(replacement)
    evidence_registry = InMemorySemanticRoleEvidenceRegistry()
    evidence_registry.publish(evidence)
    isolated = HumanSemanticReviewWorkflow(
        evidence_registry,
        other_authorities,
        SemanticReviewRequestRegistry(),
        HumanSemanticReviewDecisionRegistry(),
    )
    request = isolated.create_request(
        evidence,
        policy,
        role_policy,
        ProposedSemanticRole.METADATA_CANDIDATE,
        created_at=NOW,
    )
    with pytest.raises(ContractError) as exc_info:
        _submit(isolated, request.request_id, role_policy, evidence, policy)
    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    "authority_update",
    (
        {"candidate_id": "different-candidate"},
        {"structural_roles": (CompanionRole.MIDI,)},
        {"semantic_roles": (ProposedSemanticRole.ANNOTATION_CANDIDATE,)},
        {"evidence_policy_ids": ("different-evidence-policy",)},
        {"role_policy_ids": ("different-role-policy",)},
        {"allowed_actions": (ReviewerAction.REJECT,)},
    ),
)
def test_authority_scope_is_exact(tmp_path: Path, authority_update: dict[str, object]) -> None:
    fixture = _fixture(tmp_path)
    _, _, role_policy, evidence, policy, _, _, _, workflow = _request(fixture)
    authorities = ReviewerAuthorityRegistry()
    authorities.register(_authority(evidence, policy).model_copy(update=authority_update))
    evidence_registry = InMemorySemanticRoleEvidenceRegistry()
    evidence_registry.publish(evidence)
    isolated_requests = SemanticReviewRequestRegistry()
    isolated = HumanSemanticReviewWorkflow(
        evidence_registry,
        authorities,
        isolated_requests,
        HumanSemanticReviewDecisionRegistry(),
    )
    request = isolated.create_request(
        evidence,
        policy,
        role_policy,
        ProposedSemanticRole.METADATA_CANDIDATE,
        created_at=NOW,
    )
    with pytest.raises(ContractError) as exc_info:
        _submit(isolated, request.request_id, role_policy, evidence, policy)
    assert exc_info.value.error_code == "REVIEWER_AUTHORITY_SCOPE_MISMATCH"


def test_request_identity_registry_and_deserialization_are_immutable(tmp_path: Path) -> None:
    request, _, _, _, _, _, requests, _, _ = _request(_fixture(tmp_path))
    assert requests.publish(request) == request
    with pytest.raises(ContractError) as conflict:
        requests.publish(request.model_copy(update={"candidate_id": "different-candidate"}))
    assert conflict.value.error_code == "SEMANTIC_REVIEW_REQUEST_IMMUTABLE_CONFLICT"

    payload = request.model_dump()
    payload["evidence_fingerprint"] = "f" * 64
    with pytest.raises(ValidationError):
        SemanticReviewRequest(**payload)


def test_request_supersession_and_cancellation_keep_immutable_history(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    request, _, role_policy, evidence, policy, _, requests, _, workflow = _request(fixture)
    replacement = workflow.create_request(
        evidence,
        policy,
        role_policy,
        ProposedSemanticRole.METADATA_CANDIDATE,
        created_at=NOW + timedelta(minutes=1),
        supersedes_request_id=request.request_id,
    )
    assert requests.status(request.request_id) == SemanticReviewRequestStatus.SUPERSEDED
    assert requests.status(replacement.request_id) == SemanticReviewRequestStatus.PENDING
    workflow.cancel_request(replacement.request_id, cancelled_at=NOW + timedelta(minutes=2))
    assert requests.status(replacement.request_id) == SemanticReviewRequestStatus.CANCELLED
    with pytest.raises(ContractError) as terminal:
        _submit(workflow, replacement.request_id, role_policy, evidence, policy)
    assert terminal.value.error_code == "SEMANTIC_REVIEW_REQUEST_NOT_PENDING"


def test_registered_authority_can_approve_or_reject_once(tmp_path: Path) -> None:
    request, _, role_policy, evidence, policy, _, requests, decisions, workflow = _request(
        _fixture(tmp_path)
    )
    approved = _submit(workflow, request.request_id, role_policy, evidence, policy)
    assert approved.status == HumanReviewOutcome.APPROVED
    assert requests.status(request.request_id) == SemanticReviewRequestStatus.APPROVED
    assert decisions.publish(approved) == approved

    with pytest.raises(ContractError) as second:
        _submit(
            workflow,
            request.request_id,
            role_policy,
            evidence,
            policy,
            outcome=HumanReviewOutcome.REJECTED,
        )
    assert second.value.error_code == "SEMANTIC_REVIEW_REQUEST_NOT_PENDING"

    rejected_fixture = _fixture(tmp_path / "reject")
    (
        rejected_request,
        _,
        rejected_role_policy,
        rejected_evidence,
        rejected_policy,
        *_,
        rejected_workflow,
    ) = _request(rejected_fixture)
    rejected = _submit(
        rejected_workflow,
        rejected_request.request_id,
        rejected_role_policy,
        rejected_evidence,
        rejected_policy,
        outcome=HumanReviewOutcome.REJECTED,
    )
    assert rejected.status == HumanReviewOutcome.REJECTED


def test_unregistered_identity_and_forged_decision_fail_closed(tmp_path: Path) -> None:
    request, _, role_policy, evidence, policy, _, _, decisions, workflow = _request(
        _fixture(tmp_path)
    )
    with pytest.raises(ContractError) as identity:
        workflow.submit_decision(
            request.request_id,
            authority_id=AUTHORITY_ID,
            authority_version="1.0.0",
            reviewer_id="reviewer-test/forged/v1",
            outcome=HumanReviewOutcome.APPROVED,
            reason_code="SEMANTIC_REVIEW_SYNTHETIC_APPROVED",
            decided_at=NOW,
            current_evidence=evidence,
            current_evidence_policy=policy,
            current_role_policy=role_policy,
        )
    assert identity.value.error_code == "REVIEWER_AUTHORITY_IDENTITY_MISMATCH"

    with pytest.raises(ContractError) as version:
        workflow.submit_decision(
            request.request_id,
            authority_id=AUTHORITY_ID,
            authority_version="2.0.0",
            reviewer_id=REVIEWER_ID,
            outcome=HumanReviewOutcome.APPROVED,
            reason_code="SEMANTIC_REVIEW_SYNTHETIC_APPROVED",
            decided_at=NOW,
            current_evidence=evidence,
            current_evidence_policy=policy,
            current_role_policy=role_policy,
        )
    assert version.value.error_code == "RESOURCE_NOT_FOUND"

    decision = _submit(workflow, request.request_id, role_policy, evidence, policy)
    payload = decision.model_dump()
    payload["request_id"] = "semantic-review-request/forged"
    with pytest.raises(ValidationError):
        type(decision)(**payload)

    with pytest.raises(ValidationError):
        decisions.publish(
            decision.model_copy(
                update={
                    "decision_id": "human-semantic-review-decision/forged",
                    "status": HumanReviewOutcome.REJECTED,
                }
            )
        )


def test_stale_evidence_and_policy_versions_block_decision(tmp_path: Path) -> None:
    request, _, role_policy, evidence, policy, _, _, _, workflow = _request(_fixture(tmp_path))
    with pytest.raises(ContractError) as evidence_error:
        _submit(
            workflow,
            request.request_id,
            role_policy,
            evidence.model_copy(update={"membership_fingerprint": "f" * 64}),
            policy,
        )
    assert evidence_error.value.error_code == "SEMANTIC_REVIEW_CURRENT_EVIDENCE_MISMATCH"

    with pytest.raises(ContractError) as policy_error:
        _submit(
            workflow,
            request.request_id,
            role_policy.model_copy(update={"policy_version": "2.0.0"}),
            evidence,
            policy,
        )
    assert policy_error.value.error_code == "SEMANTIC_REVIEW_CURRENT_POLICY_MISMATCH"


def test_later_authority_revocation_blocks_downstream_consumption(tmp_path: Path) -> None:
    request, authority, role_policy, evidence, policy, authorities, _, _, workflow = _request(
        _fixture(tmp_path)
    )
    _submit(workflow, request.request_id, role_policy, evidence, policy)
    approved = workflow.consume_decision(
        request.request_id,
        current_evidence=evidence,
        current_evidence_policy=policy,
        current_role_policy=role_policy,
        consumed_at=NOW,
    )
    assert approved.status == SemanticReviewStatus.APPROVED

    revocation = authorities.revoke(
        authority.authority_id,
        authority.authority_version,
        revoked_at=NOW + timedelta(minutes=1),
        reason_code="SEMANTIC_REVIEW_AUTHORITY_REVOKED",
    )
    assert (
        authorities.revoke(
            authority.authority_id,
            authority.authority_version,
            revoked_at=NOW + timedelta(minutes=1),
            reason_code="SEMANTIC_REVIEW_AUTHORITY_REVOKED",
        )
        == revocation
    )
    with pytest.raises(ContractError) as revoked:
        workflow.consume_decision(
            request.request_id,
            current_evidence=evidence,
            current_evidence_policy=policy,
            current_role_policy=role_policy,
            consumed_at=NOW + timedelta(minutes=2),
        )
    assert revoked.value.error_code == "REVIEWER_AUTHORITY_REVOKED"


def test_synthetic_four_role_workflow_integrates_with_role_policy(tmp_path: Path) -> None:
    inputs, membership, relationships, role_policy = _pipeline(
        tmp_path,
        (
            {
                "/a.json": b"{}",
                "/a.mid": b"MThd\x00\x00\x00\x06\x00\x01\x00\x02\x00x",
                "/a.wav": b"audio",
            },
        ),
    )
    proposed = {
        CompanionRole.AUDIO: ProposedSemanticRole.PRIMARY_AUDIO_CANDIDATE,
        CompanionRole.MIDI: ProposedSemanticRole.SYMBOLIC_COMPANION_CANDIDATE,
        CompanionRole.JSON: ProposedSemanticRole.METADATA_CANDIDATE,
        CompanionRole.OTHER: ProposedSemanticRole.UNSUPPORTED,
    }
    evidence_registry = InMemorySemanticRoleEvidenceRegistry()
    authorities = ReviewerAuthorityRegistry()
    requests = SemanticReviewRequestRegistry()
    workflow = HumanSemanticReviewWorkflow(
        evidence_registry,
        authorities,
        requests,
        HumanSemanticReviewDecisionRegistry(),
    )
    evidences = []
    policies = []
    request_ids = []
    for role in CompanionRole:
        evidence = collect_semantic_role_evidence(
            inputs,
            membership,
            role_policy,
            _plan(role, count=0 if role in {CompanionRole.AUDIO, CompanionRole.OTHER} else 1),
        )
        authority_id = f"reviewer-authority/reviewer-test/music/{role}/v1"
        reviewer_id = f"reviewer-test/music/{role}/v1"
        membership_only = role in {CompanionRole.AUDIO, CompanionRole.OTHER}
        policy = _evidence_policy(
            evidence,
            minimum=0 if membership_only else 1,
            require_complete=not membership_only,
            reviewer_authorities=(authority_id,),
        )
        evidence_registry.publish(evidence)
        authority = _authority(
            evidence,
            policy,
            authority_id=authority_id,
            reviewer_id=reviewer_id,
            semantic_role=proposed[role],
        )
        authorities.register(authority)
        request = workflow.create_request(
            evidence,
            policy,
            role_policy,
            proposed[role],
            created_at=NOW,
        )
        workflow.submit_decision(
            request.request_id,
            authority_id=authority_id,
            authority_version="1.0.0",
            reviewer_id=reviewer_id,
            outcome=HumanReviewOutcome.APPROVED,
            reason_code="SEMANTIC_REVIEW_SYNTHETIC_APPROVED",
            decided_at=NOW,
            current_evidence=evidence,
            current_evidence_policy=policy,
            current_role_policy=role_policy,
        )
        request_ids.append(request.request_id)
        evidences.append(evidence)
        policies.append(policy)

    resolved_policy = workflow.apply_to_role_policy(
        role_policy,
        request_ids,
        evidences,
        policies,
        consumed_at=NOW,
    )
    ingestion = decide_candidate_ingestion(membership, relationships, resolved_policy)
    assert ingestion.inventory_ready is True
    assert all(
        disposition not in {CompanionDisposition.REVIEW_REQUIRED, CompanionDisposition.BLOCKED}
        for disposition in resolved_policy.role_dispositions.values()
    )
