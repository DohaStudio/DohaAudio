from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from dohaaudio.errors import ContractError
from dohaaudio.reviewer_identity import (
    AuthenticatedPrincipal,
    AuthenticatedReviewerResolver,
    AuthenticationAssurance,
    AuthenticationCredentialReference,
    AuthenticationMethod,
    FakeAuthenticationProvider,
    PrincipalVerificationStatus,
    ReviewerIdentityMapping,
    ReviewerIdentityMappingRegistry,
    ReviewerIdentityMappingStatus,
    VerifiedAuthenticationContext,
)
from dohaaudio.semantic_review_workflow import (
    HumanSemanticReviewDecisionRegistry,
    HumanSemanticReviewWorkflow,
    ReviewerAuthorityRegistry,
    SemanticReviewRequestRegistry,
)
from dohaaudio.semantic_role_evidence import (
    HumanReviewOutcome,
    InMemorySemanticRoleEvidenceRegistry,
    ProposedSemanticRole,
    SemanticReviewStatus,
)
from tests.test_semantic_review_workflow import (
    AUTHORITY_ID,
    NOW,
    REVIEWER_ID,
    _authority,
    _fixture,
)

PROVIDER_ID = "auth-provider/test/v1"
ISSUER_ID = "issuer/test/dohaaudio"
AUDIENCE_ID = "audience/dohaaudio/reviewer"
SUBJECT_REFERENCE = "subject-ref/synthetic-reviewer-1"
SESSION_REFERENCE = "session-ref/synthetic-1"
PROOF_REFERENCE = "proof-ref/synthetic-1"
MAPPING_ID = "reviewer-identity-mapping/test/reviewer-1"


def _principal(**updates: object) -> AuthenticatedPrincipal:
    values = {
        "provider_id": PROVIDER_ID,
        "issuer_id": ISSUER_ID,
        "subject_reference": SUBJECT_REFERENCE,
        "audience_id": AUDIENCE_ID,
        "authenticated_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=1),
        "assurance": AuthenticationAssurance.TEST_ONLY,
        "authentication_method": AuthenticationMethod.TEST_FIXTURE,
        "session_reference_id": SESSION_REFERENCE,
        "verification_status": PrincipalVerificationStatus.VERIFIED,
    }
    values.update(updates)
    return AuthenticatedPrincipal(**values)  # type: ignore[arg-type]


def _mapping(**updates: object) -> ReviewerIdentityMapping:
    values = {
        "mapping_id": MAPPING_ID,
        "mapping_version": "1.0.0",
        "provider_id": PROVIDER_ID,
        "issuer_id": ISSUER_ID,
        "subject_reference": SUBJECT_REFERENCE,
        "reviewer_id": REVIEWER_ID,
        "effective_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=1),
        "status": ReviewerIdentityMappingStatus.ACTIVE,
        "revoked_at": None,
        "created_at": NOW - timedelta(days=2),
        "audit_reason_code": "REVIEWER_IDENTITY_SYNTHETIC_MAPPING",
    }
    values.update(updates)
    return ReviewerIdentityMapping(**values)  # type: ignore[arg-type]


def _provider(principal: AuthenticatedPrincipal | None = None) -> FakeAuthenticationProvider:
    provider = FakeAuthenticationProvider(PROVIDER_ID, ISSUER_ID, AUDIENCE_ID)
    provider.add_test_principal(PROOF_REFERENCE, principal or _principal())
    return provider


def _credential(provider_id: str = PROVIDER_ID) -> AuthenticationCredentialReference:
    return AuthenticationCredentialReference(
        provider_id=provider_id,
        reference_id=PROOF_REFERENCE,
    )


def _resolver(
    provider: FakeAuthenticationProvider,
    mappings: ReviewerIdentityMappingRegistry,
    *,
    issuer_id: str = ISSUER_ID,
    audience_id: str = AUDIENCE_ID,
    maximum_age: timedelta | None = None,
) -> AuthenticatedReviewerResolver:
    return AuthenticatedReviewerResolver(
        provider,
        mappings,
        expected_issuer_id=issuer_id,
        expected_audience_id=audience_id,
        maximum_authentication_age=maximum_age,
    )


def _workflow_fixture(
    tmp_path: Path,
    *,
    register_mapping: bool = True,
    register_authority: bool = True,
):  # type: ignore[no-untyped-def]
    fixture = _fixture(tmp_path)
    _, _, _, role_policy, evidence, policy, *_ = fixture
    evidence_registry = InMemorySemanticRoleEvidenceRegistry()
    evidence_registry.publish(evidence)
    authorities = ReviewerAuthorityRegistry()
    if register_authority:
        authorities.register(_authority(evidence, policy))
    mappings = ReviewerIdentityMappingRegistry()
    if register_mapping:
        mappings.register(_mapping())
    provider = _provider()
    resolver = _resolver(provider, mappings)
    workflow = HumanSemanticReviewWorkflow(
        evidence_registry,
        authorities,
        SemanticReviewRequestRegistry(),
        HumanSemanticReviewDecisionRegistry(),
        resolver,
    )
    request = workflow.create_request(
        evidence,
        policy,
        role_policy,
        ProposedSemanticRole.METADATA_CANDIDATE,
        created_at=NOW,
    )
    context = provider.verify(_credential(), verified_at=NOW)
    return (
        request,
        role_policy,
        evidence,
        policy,
        authorities,
        mappings,
        provider,
        resolver,
        workflow,
        context,
    )


def _submit_authenticated(
    workflow: HumanSemanticReviewWorkflow,
    context: VerifiedAuthenticationContext,
    request_id: str,
    role_policy,  # type: ignore[no-untyped-def]
    evidence,  # type: ignore[no-untyped-def]
    policy,  # type: ignore[no-untyped-def]
    *,
    authority_id: str = AUTHORITY_ID,
    claimed_reviewer_id: str | None = None,
    decided_at: datetime = NOW,
):
    return workflow.submit_authenticated_decision(
        request_id,
        authentication=context,
        authority_id=authority_id,
        authority_version="1.0.0",
        outcome=HumanReviewOutcome.APPROVED,
        reason_code="SEMANTIC_REVIEW_SYNTHETIC_APPROVED",
        decided_at=decided_at,
        current_evidence=evidence,
        current_evidence_policy=policy,
        current_role_policy=role_policy,
        claimed_reviewer_id=claimed_reviewer_id,
    )


def test_principal_is_frozen_private_and_requires_aware_time() -> None:
    principal = _principal()
    with pytest.raises(ValidationError):
        principal.provider_id = "changed"  # type: ignore[misc]
    for private_value in ("person@example.test", "https://profile.test/person", "*"):
        with pytest.raises(ValidationError):
            _principal(subject_reference=private_value)
    with pytest.raises(ValidationError):
        _principal(authenticated_at=datetime(2026, 8, 20, 15, 0))


def test_fake_provider_verifies_and_revalidates_only_issued_context() -> None:
    provider = _provider()
    context = provider.verify(_credential(), verified_at=NOW)
    assert (
        provider.revalidate(
            context,
            expected_issuer_id=ISSUER_ID,
            expected_audience_id=AUDIENCE_ID,
            at=NOW,
        )
        == _principal()
    )
    assert "subject_reference" not in repr(context)
    assert "provider_witness" not in repr(context)


@pytest.mark.parametrize(
    ("principal", "error_code"),
    (
        (
            _principal(
                authenticated_at=NOW - timedelta(hours=2),
                expires_at=NOW - timedelta(hours=1),
            ),
            "AUTHENTICATION_EXPIRED",
        ),
        (
            _principal(
                authenticated_at=NOW + timedelta(minutes=1),
                expires_at=NOW + timedelta(hours=1),
            ),
            "AUTHENTICATION_NOT_EFFECTIVE",
        ),
        (_principal(issuer_id="issuer/test/other"), "AUTHENTICATION_ISSUER_MISMATCH"),
        (_principal(audience_id="audience/test/other"), "AUTHENTICATION_AUDIENCE_MISMATCH"),
        (_principal(provider_id="auth-provider/test/other"), "AUTHENTICATION_PROVIDER_MISMATCH"),
        (
            _principal(verification_status=PrincipalVerificationStatus.UNVERIFIED),
            "AUTHENTICATION_UNVERIFIED",
        ),
    ),
)
def test_fake_provider_fails_closed_for_invalid_principals(
    principal: AuthenticatedPrincipal, error_code: str
) -> None:
    provider = _provider(principal)
    with pytest.raises(ContractError) as exc_info:
        provider.verify(_credential(), verified_at=NOW)
    assert exc_info.value.error_code == error_code


def test_provider_and_resolver_bind_provider_issuer_audience_and_freshness() -> None:
    provider = _provider()
    mappings = ReviewerIdentityMappingRegistry()
    mappings.register(_mapping())
    context = provider.verify(_credential(), verified_at=NOW)

    with pytest.raises(ContractError) as provider_error:
        provider.verify(_credential("auth-provider/test/other"), verified_at=NOW)
    assert provider_error.value.error_code == "AUTHENTICATION_PROVIDER_MISMATCH"

    for resolver, error_code in (
        (
            _resolver(provider, mappings, issuer_id="issuer/test/other"),
            "AUTHENTICATION_ISSUER_MISMATCH",
        ),
        (
            _resolver(provider, mappings, audience_id="audience/test/other"),
            "AUTHENTICATION_AUDIENCE_MISMATCH",
        ),
        (
            _resolver(provider, mappings, maximum_age=timedelta(minutes=1)),
            "AUTHENTICATION_STALE",
        ),
    ):
        with pytest.raises(ContractError) as exc_info:
            resolver.resolve(context, at=NOW)
        assert exc_info.value.error_code == error_code

    with pytest.raises(ContractError) as future_context:
        _resolver(provider, mappings).resolve(context, at=NOW - timedelta(minutes=1))
    assert future_context.value.error_code == "AUTHENTICATION_CONTEXT_FUTURE"

    with pytest.raises(ContractError) as expired_context:
        _resolver(provider, mappings).resolve(context, at=NOW + timedelta(hours=2))
    assert expired_context.value.error_code == "AUTHENTICATION_EXPIRED"


def test_unknown_proof_and_forged_or_modified_context_are_blocked() -> None:
    provider = _provider()
    mappings = ReviewerIdentityMappingRegistry()
    mappings.register(_mapping())
    resolver = _resolver(provider, mappings)
    context = provider.verify(_credential(), verified_at=NOW)

    with pytest.raises(ContractError) as unknown:
        provider.verify(
            AuthenticationCredentialReference(
                provider_id=PROVIDER_ID, reference_id="proof-ref/unknown"
            ),
            verified_at=NOW,
        )
    assert unknown.value.error_code == "AUTHENTICATION_FAILED"

    forged = VerifiedAuthenticationContext(
        verification_id=context.verification_id,
        principal=context.principal,
        verified_at=context.verified_at,
        _provider_witness=object(),
    )
    tampered = replace(
        context,
        principal=context.principal.model_copy(
            update={"subject_reference": "subject-ref/attacker"}
        ),
    )
    for invalid in (forged, tampered, context.principal):
        with pytest.raises(ContractError) as exc_info:
            resolver.resolve(invalid, at=NOW)  # type: ignore[arg-type]
        assert exc_info.value.error_code == "AUTHENTICATION_CONTEXT_UNTRUSTED"

    in_place = provider.verify(_credential(), verified_at=NOW + timedelta(seconds=1))
    object.__setattr__(
        in_place,
        "principal",
        in_place.principal.model_copy(update={"subject_reference": "subject-ref/attacker"}),
    )
    with pytest.raises(ContractError) as in_place_tampering:
        resolver.resolve(in_place, at=NOW + timedelta(seconds=1))
    assert in_place_tampering.value.error_code == "AUTHENTICATION_CONTEXT_TAMPERED"


def test_mapping_registry_is_private_versioned_idempotent_and_immutable() -> None:
    registry = ReviewerIdentityMappingRegistry()
    mapping = _mapping()
    assert registry.register(mapping) == mapping
    assert registry.register(mapping) == mapping
    with pytest.raises(ContractError) as conflict:
        registry.register(mapping.model_copy(update={"reviewer_id": "reviewer-test/other"}))
    assert conflict.value.error_code == "REVIEWER_IDENTITY_MAPPING_IMMUTABLE_CONFLICT"
    assert "candidate_id" not in ReviewerIdentityMapping.model_fields
    assert "email" not in ReviewerIdentityMapping.model_fields
    with pytest.raises(ValidationError):
        _mapping(reviewer_id=SUBJECT_REFERENCE)


@pytest.mark.parametrize(
    ("updates", "error_code"),
    (
        (
            {
                "effective_at": NOW + timedelta(days=1),
                "expires_at": NOW + timedelta(days=2),
            },
            "REVIEWER_IDENTITY_NOT_EFFECTIVE",
        ),
        (
            {
                "effective_at": NOW - timedelta(days=2),
                "expires_at": NOW - timedelta(days=1),
            },
            "REVIEWER_IDENTITY_EXPIRED",
        ),
        (
            {
                "status": ReviewerIdentityMappingStatus.REVOKED,
                "revoked_at": NOW - timedelta(hours=1),
            },
            "REVIEWER_IDENTITY_REVOKED",
        ),
    ),
)
def test_future_expired_and_pre_revoked_mapping_fail_closed(
    updates: dict[str, object], error_code: str
) -> None:
    registry = ReviewerIdentityMappingRegistry()
    registry.register(_mapping(**updates))
    with pytest.raises(ContractError) as exc_info:
        registry.resolve(_principal(), at=NOW)
    assert exc_info.value.error_code == error_code


def test_mapping_revocation_history_rebinding_and_collision_are_fail_closed() -> None:
    registry = ReviewerIdentityMappingRegistry()
    original = _mapping()
    registry.register(original)
    replacement = _mapping(
        mapping_version="2.0.0",
        reviewer_id="reviewer-test/replacement",
        effective_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ContractError) as rebinding:
        registry.register(replacement)
    assert rebinding.value.error_code == "REVIEWER_IDENTITY_REBINDING_CONFLICT"

    revocation = registry.revoke(
        original.mapping_id,
        original.mapping_version,
        revoked_at=NOW + timedelta(minutes=1),
        reason_code="REVIEWER_IDENTITY_MAPPING_REVOKED",
    )
    assert (
        registry.revoke(
            original.mapping_id,
            original.mapping_version,
            revoked_at=NOW + timedelta(minutes=1),
            reason_code="REVIEWER_IDENTITY_MAPPING_REVOKED",
        )
        == revocation
    )
    registry.register(replacement)
    assert registry.resolve(_principal(), at=NOW + timedelta(minutes=2)) == replacement.reviewer_id

    with pytest.raises(ContractError) as collision:
        registry.register(
            _mapping(
                mapping_id="reviewer-identity-mapping/test/collision",
                mapping_version="1.0.0",
                subject_reference="subject-ref/different",
            )
        )
    assert collision.value.error_code == "REVIEWER_IDENTITY_COLLISION"


def test_unauthenticated_unmapped_and_missing_authority_flows_are_blocked(
    tmp_path: Path,
) -> None:
    request, role_policy, evidence, policy, _, mappings, _, _, workflow, context = (
        _workflow_fixture(tmp_path / "unauthenticated")
    )
    with pytest.raises(ContractError) as unauthenticated:
        workflow.submit_decision(
            request.request_id,
            authority_id=AUTHORITY_ID,
            authority_version="1.0.0",
            reviewer_id=REVIEWER_ID,
            outcome=HumanReviewOutcome.APPROVED,
            reason_code="SEMANTIC_REVIEW_SYNTHETIC_APPROVED",
            decided_at=NOW,
            current_evidence=evidence,
            current_evidence_policy=policy,
            current_role_policy=role_policy,
        )
    assert unauthenticated.value.error_code == "REVIEWER_AUTHENTICATION_REQUIRED"

    mappings.revoke(
        MAPPING_ID,
        "1.0.0",
        revoked_at=NOW,
        reason_code="REVIEWER_IDENTITY_MAPPING_REVOKED",
    )
    with pytest.raises(ContractError) as revoked:
        _submit_authenticated(workflow, context, request.request_id, role_policy, evidence, policy)
    assert revoked.value.error_code == "REVIEWER_IDENTITY_REVOKED"

    unmapped = _workflow_fixture(tmp_path / "unmapped", register_mapping=False)
    with pytest.raises(ContractError) as unknown:
        _submit_authenticated(
            unmapped[8], unmapped[9], unmapped[0].request_id, unmapped[1], unmapped[2], unmapped[3]
        )
    assert unknown.value.error_code == "REVIEWER_IDENTITY_NOT_REGISTERED"

    no_authority = _workflow_fixture(tmp_path / "no-authority", register_authority=False)
    with pytest.raises(ContractError) as missing_authority:
        _submit_authenticated(
            no_authority[8],
            no_authority[9],
            no_authority[0].request_id,
            no_authority[1],
            no_authority[2],
            no_authority[3],
        )
    assert missing_authority.value.error_code == "RESOURCE_NOT_FOUND"

    expired_authentication = _workflow_fixture(tmp_path / "expired-authentication")
    with pytest.raises(ContractError) as expired:
        _submit_authenticated(
            expired_authentication[8],
            expired_authentication[9],
            expired_authentication[0].request_id,
            expired_authentication[1],
            expired_authentication[2],
            expired_authentication[3],
            decided_at=NOW + timedelta(hours=2),
        )
    assert expired.value.error_code == "AUTHENTICATION_EXPIRED"


def test_authenticated_flow_rejects_injection_and_wrong_scope_then_succeeds(
    tmp_path: Path,
) -> None:
    request, role_policy, evidence, policy, *_rest, workflow, context = _workflow_fixture(tmp_path)
    with pytest.raises(ContractError) as injected:
        _submit_authenticated(
            workflow,
            context,
            request.request_id,
            role_policy,
            evidence,
            policy,
            claimed_reviewer_id="reviewer-test/attacker",
        )
    assert injected.value.error_code == "AUTHENTICATED_REVIEWER_IDENTITY_MISMATCH"

    wrong_scope_fixture = _workflow_fixture(tmp_path / "wrong-scope", register_authority=False)
    wrong_scope_fixture[4].register(
        _authority(
            wrong_scope_fixture[2],
            wrong_scope_fixture[3],
            semantic_role=ProposedSemanticRole.ANNOTATION_CANDIDATE,
        )
    )
    with pytest.raises(ContractError) as wrong_scope:
        _submit_authenticated(
            wrong_scope_fixture[8],
            wrong_scope_fixture[9],
            wrong_scope_fixture[0].request_id,
            wrong_scope_fixture[1],
            wrong_scope_fixture[2],
            wrong_scope_fixture[3],
        )
    assert wrong_scope.value.error_code == "REVIEWER_AUTHORITY_SCOPE_MISMATCH"

    decision = _submit_authenticated(
        workflow, context, request.request_id, role_policy, evidence, policy
    )
    assert decision.reviewer_id == REVIEWER_ID
    assert decision.status == HumanReviewOutcome.APPROVED
    assert "subject_reference" not in type(decision).model_fields
    assert "session_reference_id" not in type(decision).model_fields


def test_mapping_and_authority_are_revalidated_when_decision_is_consumed(tmp_path: Path) -> None:
    request, role_policy, evidence, policy, authorities, mappings, _, _, workflow, context = (
        _workflow_fixture(tmp_path)
    )
    _submit_authenticated(workflow, context, request.request_id, role_policy, evidence, policy)
    approved = workflow.consume_decision(
        request.request_id,
        current_evidence=evidence,
        current_evidence_policy=policy,
        current_role_policy=role_policy,
        consumed_at=NOW,
    )
    assert approved.status == SemanticReviewStatus.APPROVED

    after_authentication_expiry = workflow.consume_decision(
        request.request_id,
        current_evidence=evidence,
        current_evidence_policy=policy,
        current_role_policy=role_policy,
        consumed_at=NOW + timedelta(hours=2),
    )
    assert after_authentication_expiry.status == SemanticReviewStatus.APPROVED

    mappings.revoke(
        MAPPING_ID,
        "1.0.0",
        revoked_at=NOW + timedelta(hours=3),
        reason_code="REVIEWER_IDENTITY_MAPPING_REVOKED",
    )
    with pytest.raises(ContractError) as revoked_mapping:
        workflow.consume_decision(
            request.request_id,
            current_evidence=evidence,
            current_evidence_policy=policy,
            current_role_policy=role_policy,
            consumed_at=NOW + timedelta(hours=4),
        )
    assert revoked_mapping.value.error_code == "REVIEWER_IDENTITY_REVOKED"

    expired_mapping = _workflow_fixture(tmp_path / "expired-mapping", register_mapping=False)
    expired_mapping[5].register(_mapping(expires_at=NOW + timedelta(hours=1)))
    _submit_authenticated(
        expired_mapping[8],
        expired_mapping[9],
        expired_mapping[0].request_id,
        expired_mapping[1],
        expired_mapping[2],
        expired_mapping[3],
    )
    with pytest.raises(ContractError) as mapping_expired:
        expired_mapping[8].consume_decision(
            expired_mapping[0].request_id,
            current_evidence=expired_mapping[2],
            current_evidence_policy=expired_mapping[3],
            current_role_policy=expired_mapping[1],
            consumed_at=NOW + timedelta(hours=2),
        )
    assert mapping_expired.value.error_code == "REVIEWER_IDENTITY_EXPIRED"

    other = _workflow_fixture(tmp_path / "authority")
    _submit_authenticated(other[8], other[9], other[0].request_id, other[1], other[2], other[3])
    authorities = other[4]
    authorities.revoke(
        AUTHORITY_ID,
        "1.0.0",
        revoked_at=NOW + timedelta(minutes=1),
        reason_code="SEMANTIC_REVIEW_AUTHORITY_REVOKED",
    )
    with pytest.raises(ContractError) as revoked_authority:
        other[8].consume_decision(
            other[0].request_id,
            current_evidence=other[2],
            current_evidence_policy=other[3],
            current_role_policy=other[1],
            consumed_at=NOW + timedelta(minutes=2),
        )
    assert revoked_authority.value.error_code == "REVIEWER_AUTHORITY_REVOKED"
