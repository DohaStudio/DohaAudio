"""Private authentication boundary for resolving opaque reviewer identities."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

from dohaaudio.contracts import FrozenModel
from dohaaudio.errors import ConflictError, ContractError, NotFoundError

OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
SAFE_REASON = re.compile(r"^REVIEWER_IDENTITY_[A-Z0-9_]+$")


class PrincipalVerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class AuthenticationAssurance(StrEnum):
    TEST_ONLY = "test_only"
    PROVIDER_ASSERTED = "provider_asserted"
    MULTI_FACTOR_ASSERTED = "multi_factor_asserted"


class AuthenticationMethod(StrEnum):
    TEST_FIXTURE = "test_fixture"
    PROVIDER_SESSION = "provider_session"
    PROVIDER_ASSERTION = "provider_assertion"


class ReviewerIdentityMappingStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class AuthenticationCredentialReference(FrozenModel):
    """Ephemeral reference consumed by a provider; it contains no credential material."""

    provider_id: str = Field(min_length=1)
    reference_id: str = Field(min_length=1)

    @field_validator("provider_id", "reference_id")
    @classmethod
    def require_opaque_reference(cls, value: str) -> str:
        return _require_opaque(value, "authentication references")


class AuthenticatedPrincipal(FrozenModel):
    """Sanitized private principal returned by a trusted authentication provider."""

    provider_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    subject_reference: str = Field(min_length=1, repr=False)
    audience_id: str = Field(min_length=1)
    authenticated_at: datetime
    expires_at: datetime
    assurance: AuthenticationAssurance
    authentication_method: AuthenticationMethod
    session_reference_id: str = Field(min_length=1, repr=False)
    verification_status: PrincipalVerificationStatus

    @field_validator(
        "provider_id", "issuer_id", "subject_reference", "audience_id", "session_reference_id"
    )
    @classmethod
    def require_private_opaque_identifiers(cls, value: str) -> str:
        return _require_opaque(value, "authenticated principal identifiers")

    @model_validator(mode="after")
    def validate_principal(self) -> AuthenticatedPrincipal:
        _require_aware(self.authenticated_at, self.expires_at)
        if self.expires_at <= self.authenticated_at:
            raise ValueError("authentication expiry must follow authentication time")
        return self


@dataclass(frozen=True, slots=True)
class VerifiedAuthenticationContext:
    """Provider-issued capability; a deserialized principal alone is not verified."""

    verification_id: str
    principal: AuthenticatedPrincipal = field(repr=False)
    verified_at: datetime
    _provider_witness: object = field(repr=False, compare=False)


class AuthenticationProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def verify(
        self,
        credential: AuthenticationCredentialReference,
        *,
        verified_at: datetime,
    ) -> VerifiedAuthenticationContext: ...

    def revalidate(
        self,
        context: VerifiedAuthenticationContext,
        *,
        expected_issuer_id: str,
        expected_audience_id: str,
        at: datetime,
    ) -> AuthenticatedPrincipal: ...


class FakeAuthenticationProvider:
    """Deterministic test provider. It is not a production authentication adapter."""

    def __init__(self, provider_id: str, issuer_id: str, audience_id: str) -> None:
        self._provider_id = _require_opaque(provider_id, "provider identity")
        self._issuer_id = _require_opaque(issuer_id, "issuer identity")
        self._audience_id = _require_opaque(audience_id, "audience identity")
        self._principals: dict[str, AuthenticatedPrincipal] = {}
        self._issued: dict[
            str, tuple[AuthenticatedPrincipal, datetime, VerifiedAuthenticationContext]
        ] = {}
        self._witness = object()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def add_test_principal(
        self, reference_id: str, principal: AuthenticatedPrincipal
    ) -> AuthenticatedPrincipal:
        reference_id = _require_opaque(reference_id, "fake authentication reference")
        validated = AuthenticatedPrincipal(**principal.model_dump())
        current = self._principals.get(reference_id)
        if current is not None and current != validated:
            raise ConflictError(
                "FAKE_AUTHENTICATION_REFERENCE_CONFLICT",
                "A fake authentication reference cannot be overwritten.",
            )
        self._principals[reference_id] = validated.model_copy(deep=True)
        return validated.model_copy(deep=True)

    def verify(
        self,
        credential: AuthenticationCredentialReference,
        *,
        verified_at: datetime,
    ) -> VerifiedAuthenticationContext:
        _require_aware(verified_at)
        if credential.provider_id != self.provider_id:
            raise ContractError(
                "AUTHENTICATION_PROVIDER_MISMATCH",
                "Authentication input does not belong to the selected provider.",
            )
        try:
            principal = self._principals[credential.reference_id].model_copy(deep=True)
        except KeyError as exc:
            raise ContractError(
                "AUTHENTICATION_FAILED", "Authentication proof could not be verified."
            ) from exc
        self._validate_principal(
            principal,
            expected_issuer_id=self._issuer_id,
            expected_audience_id=self._audience_id,
            at=verified_at,
        )
        payload = {
            "principal": principal,
            "reference_id": credential.reference_id,
            "verified_at": verified_at,
        }
        context = VerifiedAuthenticationContext(
            verification_id=f"verified-authentication/{_fingerprint(payload)}",
            principal=principal,
            verified_at=verified_at,
            _provider_witness=self._witness,
        )
        self._issued[context.verification_id] = (
            principal.model_copy(deep=True),
            verified_at,
            context,
        )
        return context

    def revalidate(
        self,
        context: VerifiedAuthenticationContext,
        *,
        expected_issuer_id: str,
        expected_audience_id: str,
        at: datetime,
    ) -> AuthenticatedPrincipal:
        _require_aware(at)
        issued = (
            self._issued.get(context.verification_id)
            if isinstance(context, VerifiedAuthenticationContext)
            else None
        )
        if (
            not isinstance(context, VerifiedAuthenticationContext)
            or context._provider_witness is not self._witness
            or issued is None
            or issued[2] is not context
        ):
            raise ContractError(
                "AUTHENTICATION_CONTEXT_UNTRUSTED",
                "Authentication requires a current provider-issued verification context.",
            )
        if context.principal != issued[0] or context.verified_at != issued[1]:
            raise ContractError(
                "AUTHENTICATION_CONTEXT_TAMPERED",
                "Provider-issued authentication context cannot be modified.",
            )
        if context.verified_at > at:
            raise ContractError(
                "AUTHENTICATION_CONTEXT_FUTURE",
                "Authentication verification time cannot be in the future.",
            )
        self._validate_principal(
            context.principal,
            expected_issuer_id=expected_issuer_id,
            expected_audience_id=expected_audience_id,
            at=at,
        )
        return context.principal.model_copy(deep=True)

    def _validate_principal(
        self,
        principal: AuthenticatedPrincipal,
        *,
        expected_issuer_id: str,
        expected_audience_id: str,
        at: datetime,
    ) -> None:
        if principal.verification_status != PrincipalVerificationStatus.VERIFIED:
            raise ContractError(
                "AUTHENTICATION_UNVERIFIED", "Only a verified principal can be used."
            )
        if principal.provider_id != self.provider_id:
            raise ContractError(
                "AUTHENTICATION_PROVIDER_MISMATCH",
                "Authenticated principal provider does not match the verifier.",
            )
        if principal.issuer_id != expected_issuer_id:
            raise ContractError(
                "AUTHENTICATION_ISSUER_MISMATCH",
                "Authenticated principal issuer does not match the expected issuer.",
            )
        if principal.audience_id != expected_audience_id:
            raise ContractError(
                "AUTHENTICATION_AUDIENCE_MISMATCH",
                "Authenticated principal audience does not match the expected audience.",
            )
        if principal.authenticated_at > at:
            raise ContractError(
                "AUTHENTICATION_NOT_EFFECTIVE",
                "Authentication time cannot be in the future.",
            )
        if at >= principal.expires_at:
            raise ContractError("AUTHENTICATION_EXPIRED", "Expired authentication cannot be used.")


class ReviewerIdentityMapping(FrozenModel):
    """Private immutable binding from a provider principal to an opaque reviewer ID."""

    mapping_id: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    subject_reference: str = Field(min_length=1, repr=False)
    reviewer_id: str = Field(min_length=1)
    effective_at: datetime
    expires_at: datetime | None = None
    status: ReviewerIdentityMappingStatus
    revoked_at: datetime | None = None
    created_at: datetime
    audit_reason_code: str

    @field_validator(
        "mapping_id",
        "mapping_version",
        "provider_id",
        "issuer_id",
        "subject_reference",
        "reviewer_id",
    )
    @classmethod
    def require_private_opaque_identifiers(cls, value: str) -> str:
        return _require_opaque(value, "reviewer identity mapping identifiers")

    @model_validator(mode="after")
    def validate_mapping(self) -> ReviewerIdentityMapping:
        _require_aware(self.effective_at, self.expires_at, self.revoked_at, self.created_at)
        if self.created_at > self.effective_at:
            raise ValueError("identity mapping cannot be created after it becomes effective")
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("identity mapping expiry must follow its effective time")
        if self.status == ReviewerIdentityMappingStatus.ACTIVE and self.revoked_at is not None:
            raise ValueError("active identity mapping cannot carry a revocation time")
        if self.status == ReviewerIdentityMappingStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked identity mapping requires a revocation time")
        if self.revoked_at is not None and self.revoked_at < self.effective_at:
            raise ValueError("identity mapping cannot be revoked before it becomes effective")
        if self.subject_reference == self.reviewer_id:
            raise ValueError("opaque reviewer identity must differ from provider subject reference")
        _require_reason(self.audit_reason_code)
        return self


class ReviewerIdentityMappingRevocation(FrozenModel):
    revocation_id: str
    mapping_id: str
    mapping_version: str
    revoked_at: datetime
    reason_code: str

    @model_validator(mode="after")
    def validate_revocation(self) -> ReviewerIdentityMappingRevocation:
        _require_aware(self.revoked_at)
        _require_reason(self.reason_code)
        payload = self.model_dump(mode="json", exclude={"revocation_id"})
        expected = f"reviewer-identity-revocation/{_fingerprint(payload)}"
        if self.revocation_id != expected:
            raise ValueError("identity mapping revocation identity must match the complete record")
        return self


class ReviewerIdentityMappingRegistry:
    """Private in-memory mapping and revocation registry."""

    def __init__(self) -> None:
        self._mappings: dict[tuple[str, str], ReviewerIdentityMapping] = {}
        self._by_principal: dict[tuple[str, str, str], set[tuple[str, str]]] = {}
        self._by_reviewer: dict[str, set[tuple[str, str]]] = {}
        self._revocations: dict[tuple[str, str], ReviewerIdentityMappingRevocation] = {}

    def register(self, mapping: ReviewerIdentityMapping) -> ReviewerIdentityMapping:
        validated = ReviewerIdentityMapping(**mapping.model_dump())
        key = (validated.mapping_id, validated.mapping_version)
        current = self._mappings.get(key)
        if current is not None:
            if current != validated:
                raise ConflictError(
                    "REVIEWER_IDENTITY_MAPPING_IMMUTABLE_CONFLICT",
                    "Reviewer identity mapping identity and version cannot be overwritten.",
                )
            return current.model_copy(deep=True)

        principal_key = _principal_key(validated)
        for existing_key in self._by_principal.get(principal_key, set()):
            existing = self._mappings[existing_key]
            if existing.reviewer_id != validated.reviewer_id or existing_key != key:
                self._require_predecessor_revoked(existing, validated)
        for existing_key in self._by_reviewer.get(validated.reviewer_id, set()):
            existing = self._mappings[existing_key]
            if _principal_key(existing) != principal_key:
                raise ConflictError(
                    "REVIEWER_IDENTITY_COLLISION",
                    "An opaque reviewer identity cannot bind different provider principals.",
                )

        self._mappings[key] = validated.model_copy(deep=True)
        self._by_principal.setdefault(principal_key, set()).add(key)
        self._by_reviewer.setdefault(validated.reviewer_id, set()).add(key)
        return validated.model_copy(deep=True)

    def get(self, mapping_id: str, mapping_version: str) -> ReviewerIdentityMapping:
        try:
            return self._mappings[(mapping_id, mapping_version)].model_copy(deep=True)
        except KeyError as exc:
            raise NotFoundError("ReviewerIdentityMapping") from exc

    def revoke(
        self,
        mapping_id: str,
        mapping_version: str,
        *,
        revoked_at: datetime,
        reason_code: str,
    ) -> ReviewerIdentityMappingRevocation:
        _require_aware(revoked_at)
        mapping = self.get(mapping_id, mapping_version)
        if revoked_at < mapping.effective_at:
            raise ContractError(
                "REVIEWER_IDENTITY_REVOCATION_TIME_INVALID",
                "Identity mapping cannot be revoked before its effective time.",
            )
        payload = {
            "mapping_id": mapping_id,
            "mapping_version": mapping_version,
            "revoked_at": revoked_at,
            "reason_code": reason_code,
        }
        revocation = ReviewerIdentityMappingRevocation(
            revocation_id=f"reviewer-identity-revocation/{_fingerprint(payload)}", **payload
        )
        key = (mapping_id, mapping_version)
        current = self._revocations.get(key)
        if current is not None and current != revocation:
            raise ConflictError(
                "REVIEWER_IDENTITY_REVOCATION_CONFLICT",
                "An identity mapping version can have only one immutable revocation.",
            )
        self._revocations[key] = revocation.model_copy(deep=True)
        return revocation.model_copy(deep=True)

    def resolve(self, principal: AuthenticatedPrincipal, *, at: datetime) -> str:
        keys = self._by_principal.get(_principal_key(principal), set())
        if not keys:
            raise ContractError(
                "REVIEWER_IDENTITY_NOT_REGISTERED",
                "Authenticated principal has no registered reviewer identity mapping.",
            )
        current = self._current(tuple(self._mappings[key] for key in keys), at=at)
        return current.reviewer_id

    def require_reviewer_current(
        self, reviewer_id: str, *, at: datetime
    ) -> ReviewerIdentityMapping:
        keys = self._by_reviewer.get(reviewer_id, set())
        if not keys:
            raise ContractError(
                "REVIEWER_IDENTITY_NOT_REGISTERED",
                "Reviewer identity has no current private mapping.",
            )
        return self._current(tuple(self._mappings[key] for key in keys), at=at)

    def _current(
        self, mappings: tuple[ReviewerIdentityMapping, ...], *, at: datetime
    ) -> ReviewerIdentityMapping:
        _require_aware(at)
        available: list[ReviewerIdentityMapping] = []
        failure_codes: set[str] = set()
        for mapping in mappings:
            try:
                self._require_current(mapping, at=at)
            except ContractError as exc:
                failure_codes.add(exc.error_code)
            else:
                available.append(mapping)
        if len(available) > 1:
            raise ContractError(
                "REVIEWER_IDENTITY_MAPPING_AMBIGUOUS",
                "Multiple reviewer identity mappings are current.",
            )
        if not available:
            messages = {
                "REVIEWER_IDENTITY_REVOKED": "Revoked reviewer identity mapping cannot be used.",
                "REVIEWER_IDENTITY_EXPIRED": "Expired reviewer identity mapping cannot be used.",
                "REVIEWER_IDENTITY_NOT_EFFECTIVE": "Reviewer identity mapping is not effective.",
            }
            failure_code = next(
                code
                for code in (
                    "REVIEWER_IDENTITY_REVOKED",
                    "REVIEWER_IDENTITY_EXPIRED",
                    "REVIEWER_IDENTITY_NOT_EFFECTIVE",
                )
                if code in failure_codes
            )
            raise ContractError(failure_code, messages[failure_code])
        return available[0].model_copy(deep=True)

    def _require_current(self, mapping: ReviewerIdentityMapping, *, at: datetime) -> None:
        if mapping.status == ReviewerIdentityMappingStatus.REVOKED or (
            mapping.revoked_at is not None and mapping.revoked_at <= at
        ):
            raise ContractError(
                "REVIEWER_IDENTITY_REVOKED", "Revoked reviewer identity mapping cannot be used."
            )
        revocation = self._revocations.get((mapping.mapping_id, mapping.mapping_version))
        if revocation is not None and revocation.revoked_at <= at:
            raise ContractError(
                "REVIEWER_IDENTITY_REVOKED", "Revoked reviewer identity mapping cannot be used."
            )
        if at < mapping.effective_at:
            raise ContractError(
                "REVIEWER_IDENTITY_NOT_EFFECTIVE", "Reviewer identity mapping is not effective."
            )
        if mapping.expires_at is not None and at >= mapping.expires_at:
            raise ContractError(
                "REVIEWER_IDENTITY_EXPIRED", "Expired reviewer identity mapping cannot be used."
            )

    def _require_predecessor_revoked(
        self, existing: ReviewerIdentityMapping, replacement: ReviewerIdentityMapping
    ) -> None:
        revocation = self._revocations.get((existing.mapping_id, existing.mapping_version))
        revoked_at = revocation.revoked_at if revocation is not None else existing.revoked_at
        if revoked_at is None or revoked_at > replacement.effective_at:
            raise ConflictError(
                "REVIEWER_IDENTITY_REBINDING_CONFLICT",
                "Principal rebinding requires explicit predecessor revocation.",
            )


class AuthenticatedReviewerResolver:
    """Resolves only trusted, current authentication contexts to private mappings."""

    def __init__(
        self,
        provider: AuthenticationProvider,
        mappings: ReviewerIdentityMappingRegistry,
        *,
        expected_issuer_id: str,
        expected_audience_id: str,
        maximum_authentication_age: timedelta | None = None,
    ) -> None:
        if maximum_authentication_age is not None and maximum_authentication_age <= timedelta(0):
            raise ValueError("maximum authentication age must be positive")
        self._provider = provider
        self._mappings = mappings
        self._expected_issuer_id = _require_opaque(expected_issuer_id, "expected issuer")
        self._expected_audience_id = _require_opaque(expected_audience_id, "expected audience")
        self._maximum_age = maximum_authentication_age

    def resolve(
        self,
        context: VerifiedAuthenticationContext,
        *,
        at: datetime,
        claimed_reviewer_id: str | None = None,
    ) -> str:
        principal = self._provider.revalidate(
            context,
            expected_issuer_id=self._expected_issuer_id,
            expected_audience_id=self._expected_audience_id,
            at=at,
        )
        if self._maximum_age is not None and at - principal.authenticated_at > self._maximum_age:
            raise ContractError(
                "AUTHENTICATION_STALE", "Authentication is older than the configured policy."
            )
        reviewer_id = self._mappings.resolve(principal, at=at)
        if claimed_reviewer_id is not None and claimed_reviewer_id != reviewer_id:
            raise ContractError(
                "AUTHENTICATED_REVIEWER_IDENTITY_MISMATCH",
                "Caller reviewer identity does not match the authenticated mapping.",
            )
        return reviewer_id

    def require_reviewer_current(self, reviewer_id: str, *, at: datetime) -> None:
        self._mappings.require_reviewer_current(reviewer_id, at=at)


def _principal_key(
    value: AuthenticatedPrincipal | ReviewerIdentityMapping,
) -> tuple[str, str, str]:
    return (value.provider_id, value.issuer_id, value.subject_reference)


def _require_opaque(value: str, label: str) -> str:
    if not OPAQUE_ID.fullmatch(value) or "*" in value or "?" in value:
        raise ValueError(f"{label} must use an exact opaque logical identifier")
    return value


def _require_reason(value: str) -> None:
    if not SAFE_REASON.fullmatch(value):
        raise ValueError("identity mapping audit metadata requires a safe reason code")


def _require_aware(*values: datetime | None) -> None:
    if any(value is not None and value.tzinfo is None for value in values):
        raise ValueError("authentication timestamps must be timezone-aware")


def _fingerprint(payload: object) -> str:
    canonical = to_jsonable_python(payload)
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
