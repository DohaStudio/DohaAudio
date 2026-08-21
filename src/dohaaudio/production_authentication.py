"""Fail-closed production authentication selection and adapter foundation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from dohaaudio.contracts import FrozenModel
from dohaaudio.errors import ContractError
from dohaaudio.reviewer_identity import (
    AuthenticatedPrincipal,
    AuthenticationCredentialReference,
    AuthenticationProvider,
    VerifiedAuthenticationContext,
)

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
SAFE_ALGORITHM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class ProductionAuthenticationProviderType(StrEnum):
    DOHAMUSIC_DELEGATED_ASSERTION = "DOHAMUSIC_DELEGATED_ASSERTION"
    LOCAL_OPERATOR = "local_operator"
    OIDC = "oidc"
    GITHUB_IDENTITY = "github_identity"
    FAKE = "fake"


class ProviderSelectionStatus(StrEnum):
    SELECTED = "selected"
    PENDING_REQUIREMENTS = "pending_requirements"


class ReviewerAssertionLifetime(StrEnum):
    SHORT_LIVED = "SHORT_LIVED"


class DohaMusicDelegatedAssertionPolicy(FrozenModel):
    """Product-authority constraints for the future delegated assertion adapter."""

    issuer_owner: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    lifetime: ReviewerAssertionLifetime
    freshness_required: bool
    expiry_required: bool
    replay_resistance_required: bool
    external_auth_network_required: bool
    offline_capable: bool
    upstream_mfa_required: bool

    @field_validator("issuer_owner", "audience")
    @classmethod
    def require_safe_authority_identifiers(cls, value: str) -> str:
        return _require_safe_identifier(value, "delegated assertion authority")

    @model_validator(mode="after")
    def require_v1_authority(self) -> DohaMusicDelegatedAssertionPolicy:
        if self.issuer_owner != "DohaMusic":
            raise ValueError("delegated reviewer assertion issuer must be DohaMusic")
        if self.audience != "DohaAudio":
            raise ValueError("delegated reviewer assertion audience must be DohaAudio")
        if not self.freshness_required or not self.expiry_required:
            raise ValueError("delegated reviewer assertions require freshness and expiry")
        if not self.replay_resistance_required:
            raise ValueError("delegated reviewer assertions require replay resistance")
        if self.external_auth_network_required or not self.offline_capable:
            raise ValueError("V1 delegated reviewer authentication must be offline-capable")
        if self.upstream_mfa_required:
            raise ValueError("V1 does not require upstream reviewer MFA")
        return self


class AuthenticationProviderSelection(FrozenModel):
    """Versioned decision, intentionally separate from runtime activation."""

    decision_version: str = Field(min_length=1)
    status: ProviderSelectionStatus
    selected_provider_type: ProductionAuthenticationProviderType | None = None
    selected_external_identity_provider: ProductionAuthenticationProviderType | None = None
    delegated_assertion_policy: DohaMusicDelegatedAssertionPolicy | None = None
    authority_reference_id: str = Field(min_length=1)
    rationale_codes: tuple[str, ...] = Field(min_length=1)
    unresolved_requirement_codes: tuple[str, ...] = ()

    @field_validator("decision_version", "authority_reference_id")
    @classmethod
    def require_safe_version(cls, value: str) -> str:
        return _require_safe_identifier(value, "selection authority identifier")

    @field_validator("rationale_codes", "unresolved_requirement_codes")
    @classmethod
    def require_safe_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("selection decision codes must be unique")
        for value in values:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
                raise ValueError("selection decision codes must be safe uppercase identifiers")
        return values

    @model_validator(mode="after")
    def validate_selection(self) -> AuthenticationProviderSelection:
        if self.status == ProviderSelectionStatus.SELECTED:
            if self.selected_provider_type is None:
                raise ValueError("selected status requires a provider type")
            if self.unresolved_requirement_codes:
                raise ValueError("selected status cannot retain unresolved requirements")
        elif (
            self.selected_provider_type is not None
            or self.selected_external_identity_provider is not None
            or self.delegated_assertion_policy is not None
        ):
            raise ValueError("pending selection cannot name a selected provider or policy")
        elif not self.unresolved_requirement_codes:
            raise ValueError("pending selection requires unresolved requirements")

        if self.selected_external_identity_provider not in (
            None,
            ProductionAuthenticationProviderType.OIDC,
            ProductionAuthenticationProviderType.GITHUB_IDENTITY,
        ):
            raise ValueError("external identity provider must be OIDC, GitHub Identity, or null")
        if (
            self.selected_provider_type
            == ProductionAuthenticationProviderType.DOHAMUSIC_DELEGATED_ASSERTION
        ):
            if self.selected_external_identity_provider is not None:
                raise ValueError("delegated DohaMusic identity cannot select an external IdP")
            if self.delegated_assertion_policy is None:
                raise ValueError("delegated DohaMusic identity requires its authority policy")
        elif self.delegated_assertion_policy is not None:
            raise ValueError("delegated assertion policy requires the delegated provider model")
        return self


class ProductionAuthenticationProviderConfig(FrozenModel):
    """Secret-free public configuration for one explicitly enabled adapter."""

    configuration_version: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    provider_type: ProductionAuthenticationProviderType
    enabled: bool
    expected_issuer_id: str = Field(min_length=1)
    expected_audience_id: str = Field(min_length=1)
    allowed_algorithms: tuple[str, ...] = ()
    maximum_clock_skew_seconds: int = Field(default=0, ge=0, le=300)
    maximum_authentication_age_seconds: int | None = Field(default=None, gt=0)
    network_access_required: bool
    replay_protection_required: bool = False

    @field_validator(
        "configuration_version", "provider_id", "expected_issuer_id", "expected_audience_id"
    )
    @classmethod
    def require_safe_identifiers(cls, value: str) -> str:
        return _require_safe_identifier(value, "provider configuration identifiers")

    @field_validator("allowed_algorithms")
    @classmethod
    def require_algorithm_allowlist(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("allowed algorithms must be unique")
        if any(not SAFE_ALGORITHM.fullmatch(value) for value in values):
            raise ValueError("allowed algorithms must use safe identifiers")
        return values

    @model_validator(mode="after")
    def validate_provider_policy(self) -> ProductionAuthenticationProviderConfig:
        if self.provider_type == ProductionAuthenticationProviderType.OIDC:
            if not self.allowed_algorithms:
                raise ValueError("OIDC configuration requires an explicit algorithm allowlist")
            if not self.network_access_required:
                raise ValueError("OIDC configuration must declare its production network boundary")
        if self.provider_type == ProductionAuthenticationProviderType.DOHAMUSIC_DELEGATED_ASSERTION:
            if self.expected_issuer_id != "DohaMusic":
                raise ValueError("delegated reviewer assertion issuer must be DohaMusic")
            if self.expected_audience_id != "DohaAudio":
                raise ValueError("delegated reviewer assertion audience must be DohaAudio")
            if self.allowed_algorithms:
                raise ValueError("assertion algorithm remains unselected")
            if self.network_access_required:
                raise ValueError("delegated reviewer assertion cannot require an external network")
            if not self.replay_protection_required:
                raise ValueError("delegated reviewer assertion requires replay protection")
        return self


class SecretResolver(Protocol):
    """Private composition boundary; returned material must never enter domain records."""

    def resolve(self, secret_reference: str) -> bytes: ...


class ProductionAuthenticationProvider(AuthenticationProvider, Protocol):
    @property
    def provider_type(self) -> ProductionAuthenticationProviderType: ...

    @property
    def operational(self) -> bool: ...


class UnavailableProductionAuthenticationProvider:
    """Design stub that cannot issue or revalidate authentication proof."""

    def __init__(self, config: ProductionAuthenticationProviderConfig) -> None:
        self._config = config

    @property
    def provider_id(self) -> str:
        return self._config.provider_id

    @property
    def provider_type(self) -> ProductionAuthenticationProviderType:
        return self._config.provider_type

    @property
    def operational(self) -> bool:
        return False

    def verify(
        self,
        credential: AuthenticationCredentialReference,
        *,
        verified_at: datetime,
    ) -> VerifiedAuthenticationContext:
        del credential, verified_at
        raise ContractError(
            "AUTH_PROVIDER_NOT_OPERATIONAL",
            "Production authentication verification is not implemented.",
        )

    def revalidate(
        self,
        context: VerifiedAuthenticationContext,
        *,
        expected_issuer_id: str,
        expected_audience_id: str,
        at: datetime,
    ) -> AuthenticatedPrincipal:
        del context, expected_issuer_id, expected_audience_id, at
        raise ContractError(
            "AUTH_PROVIDER_NOT_OPERATIONAL",
            "Production authentication verification is not implemented.",
        )


class ProductionAuthenticationReadiness(FrozenModel):
    provider_selected: bool
    provider_configured: bool
    provider_operational: bool
    private_identity_store_operational: bool
    human_review_operational: bool
    reason_code: str


@dataclass(frozen=True, slots=True)
class ProductionAuthenticationBootstrap:
    readiness: ProductionAuthenticationReadiness
    provider: UnavailableProductionAuthenticationProvider | None = None


class AuthenticationProviderFactory:
    """Creates only explicit production stubs; it never falls back to a fake provider."""

    def bootstrap(
        self,
        selection: AuthenticationProviderSelection,
        config: ProductionAuthenticationProviderConfig | None,
        *,
        private_identity_store_operational: bool = False,
    ) -> ProductionAuthenticationBootstrap:
        if selection.status != ProviderSelectionStatus.SELECTED:
            return _unavailable("AUTH_PROVIDER_NOT_SELECTED")
        if selection.selected_provider_type == ProductionAuthenticationProviderType.FAKE:
            raise ContractError(
                "AUTH_PROVIDER_FAKE_FORBIDDEN",
                "Fake authentication providers cannot be activated in production.",
            )
        if config is None:
            return _unavailable("AUTH_PROVIDER_NOT_CONFIGURED", selected=True)
        if config.provider_type == ProductionAuthenticationProviderType.FAKE:
            raise ContractError(
                "AUTH_PROVIDER_FAKE_FORBIDDEN",
                "Fake authentication providers cannot be activated in production.",
            )
        if config.provider_type != selection.selected_provider_type:
            raise ContractError(
                "AUTH_PROVIDER_SELECTION_MISMATCH",
                "Provider configuration does not match the recorded selection.",
            )
        if not config.enabled:
            return _unavailable("AUTH_PROVIDER_DISABLED", selected=True)

        provider = UnavailableProductionAuthenticationProvider(config)
        readiness = ProductionAuthenticationReadiness(
            provider_selected=True,
            provider_configured=True,
            provider_operational=False,
            private_identity_store_operational=private_identity_store_operational,
            human_review_operational=False,
            reason_code="AUTH_PROVIDER_NOT_OPERATIONAL",
        )
        return ProductionAuthenticationBootstrap(readiness=readiness, provider=provider)


def _unavailable(reason_code: str, *, selected: bool = False) -> ProductionAuthenticationBootstrap:
    return ProductionAuthenticationBootstrap(
        readiness=ProductionAuthenticationReadiness(
            provider_selected=selected,
            provider_configured=False,
            provider_operational=False,
            private_identity_store_operational=False,
            human_review_operational=False,
            reason_code=reason_code,
        )
    )


def _require_safe_identifier(value: str, label: str) -> str:
    if not SAFE_IDENTIFIER.fullmatch(value) or "*" in value or "?" in value:
        raise ValueError(f"{label} must use an exact safe logical identifier")
    return value


HISTORICAL_PRODUCTION_AUTHENTICATION_SELECTION = AuthenticationProviderSelection(
    decision_version="auth-provider-selection/v1",
    status=ProviderSelectionStatus.PENDING_REQUIREMENTS,
    authority_reference_id="dohaaudio/adr-014",
    rationale_codes=("REPOSITORY_EVIDENCE_INSUFFICIENT",),
    unresolved_requirement_codes=(
        "DEPLOYMENT_TOPOLOGY_UNRESOLVED",
        "IDENTITY_ISSUER_UNRESOLVED",
        "ACCOUNT_LIFECYCLE_OWNER_UNRESOLVED",
        "LOGIN_FLOW_UNRESOLVED",
    ),
)


CURRENT_PRODUCTION_AUTHENTICATION_SELECTION = AuthenticationProviderSelection(
    decision_version="auth-provider-selection/v2",
    status=ProviderSelectionStatus.SELECTED,
    selected_provider_type=ProductionAuthenticationProviderType.DOHAMUSIC_DELEGATED_ASSERTION,
    selected_external_identity_provider=None,
    delegated_assertion_policy=DohaMusicDelegatedAssertionPolicy(
        issuer_owner="DohaMusic",
        audience="DohaAudio",
        lifetime=ReviewerAssertionLifetime.SHORT_LIVED,
        freshness_required=True,
        expiry_required=True,
        replay_resistance_required=True,
        external_auth_network_required=False,
        offline_capable=True,
        upstream_mfa_required=False,
    ),
    authority_reference_id="dohamusic/adr-038",
    rationale_codes=(
        "DOHAMUSIC_V1_PRODUCT_AUTHORITY_CONFIRMED",
        "DELEGATED_ASSERTION_PROVIDER_MODEL_SELECTED",
    ),
)
