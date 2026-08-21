from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import ValidationError

from dohaaudio.errors import ContractError
from dohaaudio.production_authentication import (
    CURRENT_PRODUCTION_AUTHENTICATION_SELECTION,
    HISTORICAL_PRODUCTION_AUTHENTICATION_SELECTION,
    AuthenticationProviderFactory,
    AuthenticationProviderSelection,
    DohaMusicDelegatedAssertionPolicy,
    ProductionAuthenticationProviderConfig,
    ProductionAuthenticationProviderType,
    ProviderSelectionStatus,
    ReviewerAssertionLifetime,
    UnavailableProductionAuthenticationProvider,
)
from dohaaudio.reviewer_identity import (
    AuthenticationCredentialReference,
    ReviewerIdentityMappingRegistry,
    ReviewerIdentityMappingStore,
    VerifiedAuthenticationContext,
)

NOW = datetime(2026, 8, 21, tzinfo=UTC)


def _selected(
    provider_type: ProductionAuthenticationProviderType = ProductionAuthenticationProviderType.OIDC,
) -> AuthenticationProviderSelection:
    return AuthenticationProviderSelection(
        decision_version="auth-provider-selection/test/v1",
        status=ProviderSelectionStatus.SELECTED,
        selected_provider_type=provider_type,
        authority_reference_id="test/selection-authority",
        rationale_codes=("SYNTHETIC_SELECTION_FOR_CONTRACT_TEST",),
    )


def _config(**updates: object) -> ProductionAuthenticationProviderConfig:
    values: dict[str, object] = {
        "configuration_version": "production-auth-config/test/v1",
        "provider_id": "production-auth/test",
        "provider_type": ProductionAuthenticationProviderType.OIDC,
        "enabled": True,
        "expected_issuer_id": "issuer/test",
        "expected_audience_id": "audience/dohaaudio/reviewer",
        "allowed_algorithms": ("RS256",),
        "maximum_clock_skew_seconds": 30,
        "maximum_authentication_age_seconds": 900,
        "network_access_required": True,
    }
    values.update(updates)
    return ProductionAuthenticationProviderConfig(**values)  # type: ignore[arg-type]


def _delegated_policy(**updates: object) -> DohaMusicDelegatedAssertionPolicy:
    values: dict[str, object] = {
        "issuer_owner": "DohaMusic",
        "audience": "DohaAudio",
        "lifetime": ReviewerAssertionLifetime.SHORT_LIVED,
        "freshness_required": True,
        "expiry_required": True,
        "replay_resistance_required": True,
        "external_auth_network_required": False,
        "offline_capable": True,
        "upstream_mfa_required": False,
    }
    values.update(updates)
    return DohaMusicDelegatedAssertionPolicy(**values)  # type: ignore[arg-type]


def _delegated_selection(**updates: object) -> AuthenticationProviderSelection:
    values: dict[str, object] = {
        "decision_version": "auth-provider-selection/test/delegated/v1",
        "status": ProviderSelectionStatus.SELECTED,
        "selected_provider_type": (
            ProductionAuthenticationProviderType.DOHAMUSIC_DELEGATED_ASSERTION
        ),
        "selected_external_identity_provider": None,
        "delegated_assertion_policy": _delegated_policy(),
        "authority_reference_id": "dohamusic/adr-038",
        "rationale_codes": ("DOHAMUSIC_V1_PRODUCT_AUTHORITY_CONFIRMED",),
    }
    values.update(updates)
    return AuthenticationProviderSelection(**values)  # type: ignore[arg-type]


def _delegated_config(**updates: object) -> ProductionAuthenticationProviderConfig:
    values: dict[str, object] = {
        "configuration_version": "production-auth-config/test/delegated/v1",
        "provider_id": "dohamusic/delegated-reviewer-assertion",
        "provider_type": ProductionAuthenticationProviderType.DOHAMUSIC_DELEGATED_ASSERTION,
        "enabled": True,
        "expected_issuer_id": "DohaMusic",
        "expected_audience_id": "DohaAudio",
        "allowed_algorithms": (),
        "maximum_clock_skew_seconds": 0,
        "maximum_authentication_age_seconds": None,
        "network_access_required": False,
        "replay_protection_required": True,
    }
    values.update(updates)
    return ProductionAuthenticationProviderConfig(**values)  # type: ignore[arg-type]


def test_historical_repository_decision_remains_unselected_without_activation() -> None:
    result = AuthenticationProviderFactory().bootstrap(
        HISTORICAL_PRODUCTION_AUTHENTICATION_SELECTION,
        _config(),
        private_identity_store_operational=True,
    )

    assert HISTORICAL_PRODUCTION_AUTHENTICATION_SELECTION.selected_provider_type is None
    assert result.provider is None
    assert result.readiness.model_dump() == {
        "provider_selected": False,
        "provider_configured": False,
        "provider_operational": False,
        "private_identity_store_operational": False,
        "human_review_operational": False,
        "reason_code": "AUTH_PROVIDER_NOT_SELECTED",
    }


def test_selection_record_rejects_contradictory_states() -> None:
    with pytest.raises(ValidationError):
        AuthenticationProviderSelection(
            decision_version="v1",
            status=ProviderSelectionStatus.SELECTED,
            authority_reference_id="test/authority",
            rationale_codes=("MISSING_PROVIDER",),
        )
    with pytest.raises(ValidationError):
        AuthenticationProviderSelection(
            decision_version="v1",
            status=ProviderSelectionStatus.PENDING_REQUIREMENTS,
            selected_provider_type=ProductionAuthenticationProviderType.OIDC,
            authority_reference_id="test/authority",
            rationale_codes=("CONTRADICTORY",),
            unresolved_requirement_codes=("ISSUER_UNRESOLVED",),
        )


def test_current_dohamusic_selection_is_exact_but_not_configured_or_operational() -> None:
    selection = CURRENT_PRODUCTION_AUTHENTICATION_SELECTION
    result = AuthenticationProviderFactory().bootstrap(
        selection,
        None,
        private_identity_store_operational=True,
    )

    assert selection.status == ProviderSelectionStatus.SELECTED
    assert (
        selection.selected_provider_type
        == ProductionAuthenticationProviderType.DOHAMUSIC_DELEGATED_ASSERTION
    )
    assert selection.selected_provider_type.value == "DOHAMUSIC_DELEGATED_ASSERTION"
    assert selection.selected_external_identity_provider is None
    assert selection.authority_reference_id == "dohamusic/adr-038"
    assert selection.delegated_assertion_policy == _delegated_policy()
    assert result.provider is None
    assert result.readiness.model_dump() == {
        "provider_selected": True,
        "provider_configured": False,
        "provider_operational": False,
        "private_identity_store_operational": False,
        "human_review_operational": False,
        "reason_code": "AUTH_PROVIDER_NOT_CONFIGURED",
    }


def test_pending_historical_selection_blocks_active_delegated_config() -> None:
    result = AuthenticationProviderFactory().bootstrap(
        HISTORICAL_PRODUCTION_AUTHENTICATION_SELECTION,
        _delegated_config(),
        private_identity_store_operational=True,
    )

    assert result.provider is None
    assert result.readiness.provider_selected is False
    assert result.readiness.provider_configured is False
    assert result.readiness.provider_operational is False
    assert result.readiness.private_identity_store_operational is False
    assert result.readiness.reason_code == "AUTH_PROVIDER_NOT_SELECTED"


@pytest.mark.parametrize(
    "updates",
    [
        {"issuer_owner": "OtherIssuer"},
        {"audience": "OtherAudience"},
        {"lifetime": "LONG_LIVED"},
        {"freshness_required": False},
        {"expiry_required": False},
        {"replay_resistance_required": False},
        {"external_auth_network_required": True},
        {"offline_capable": False},
        {"upstream_mfa_required": True},
    ],
)
def test_delegated_policy_rejects_authority_contradictions(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _delegated_policy(**updates)


@pytest.mark.parametrize(
    "external_provider",
    [
        ProductionAuthenticationProviderType.OIDC,
        ProductionAuthenticationProviderType.GITHUB_IDENTITY,
    ],
)
def test_delegated_selection_rejects_external_identity_provider(
    external_provider: ProductionAuthenticationProviderType,
) -> None:
    with pytest.raises(ValidationError):
        _delegated_selection(selected_external_identity_provider=external_provider)


def test_delegated_selection_requires_exact_model_and_policy_binding() -> None:
    with pytest.raises(ValidationError):
        _delegated_selection(selected_provider_type=ProductionAuthenticationProviderType.OIDC)
    with pytest.raises(ValidationError):
        _delegated_selection(delegated_assertion_policy=None)
    with pytest.raises(ValidationError):
        _delegated_selection(selected_provider_type="unknown")


def test_selected_provider_config_is_accepted_but_stub_is_not_operational() -> None:
    factory = AuthenticationProviderFactory()
    result = factory.bootstrap(_selected(), _config())
    replay = factory.bootstrap(_selected(), _config())

    assert isinstance(result.provider, UnavailableProductionAuthenticationProvider)
    assert isinstance(replay.provider, UnavailableProductionAuthenticationProvider)
    assert replay.readiness == result.readiness
    assert replay.provider.provider_id == result.provider.provider_id
    assert replay.provider.provider_type == result.provider.provider_type
    assert result.readiness.provider_selected is True
    assert result.readiness.provider_configured is True
    assert result.readiness.provider_operational is False
    assert result.readiness.human_review_operational is False
    with pytest.raises(ContractError, match="not implemented") as error:
        result.provider.verify(
            AuthenticationCredentialReference(
                provider_id="production-auth/test", reference_id="ephemeral/test"
            ),
            verified_at=NOW,
        )
    assert error.value.error_code == "AUTH_PROVIDER_NOT_OPERATIONAL"
    with pytest.raises(ContractError, match="not implemented") as error:
        result.provider.revalidate(
            cast(VerifiedAuthenticationContext, object()),
            expected_issuer_id="issuer/test",
            expected_audience_id="audience/dohaaudio/reviewer",
            at=NOW,
        )
    assert error.value.error_code == "AUTH_PROVIDER_NOT_OPERATIONAL"


def test_selected_delegated_config_uses_unavailable_adapter_without_dummy_context() -> None:
    result = AuthenticationProviderFactory().bootstrap(
        CURRENT_PRODUCTION_AUTHENTICATION_SELECTION,
        _delegated_config(),
        private_identity_store_operational=False,
    )

    assert isinstance(result.provider, UnavailableProductionAuthenticationProvider)
    assert result.readiness.provider_selected is True
    assert result.readiness.provider_configured is True
    assert result.readiness.provider_operational is False
    assert result.readiness.private_identity_store_operational is False
    assert result.readiness.human_review_operational is False
    with pytest.raises(ContractError) as verify_error:
        result.provider.verify(
            AuthenticationCredentialReference(
                provider_id="dohamusic/delegated-reviewer-assertion",
                reference_id="ephemeral/test",
            ),
            verified_at=NOW,
        )
    assert verify_error.value.error_code == "AUTH_PROVIDER_NOT_OPERATIONAL"
    with pytest.raises(ContractError) as revalidate_error:
        result.provider.revalidate(
            cast(VerifiedAuthenticationContext, object()),
            expected_issuer_id="DohaMusic",
            expected_audience_id="DohaAudio",
            at=NOW,
        )
    assert revalidate_error.value.error_code == "AUTH_PROVIDER_NOT_OPERATIONAL"


@pytest.mark.parametrize(
    "updates",
    [
        {"expected_issuer_id": "OtherIssuer"},
        {"expected_audience_id": "OtherAudience"},
        {"allowed_algorithms": ("RS256",)},
        {"network_access_required": True},
        {"replay_protection_required": False},
    ],
)
def test_delegated_config_rejects_unsafe_or_unresolved_policy(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _delegated_config(**updates)


@pytest.mark.parametrize(
    "config",
    [
        _config(),
        _config(
            provider_type=ProductionAuthenticationProviderType.GITHUB_IDENTITY,
            allowed_algorithms=(),
            network_access_required=False,
        ),
    ],
)
def test_current_delegated_selection_rejects_wrong_provider_config(
    config: ProductionAuthenticationProviderConfig,
) -> None:
    with pytest.raises(ContractError) as error:
        AuthenticationProviderFactory().bootstrap(
            CURRENT_PRODUCTION_AUTHENTICATION_SELECTION,
            config,
        )
    assert error.value.error_code == "AUTH_PROVIDER_SELECTION_MISMATCH"


@pytest.mark.parametrize(
    ("selection", "config", "error_code"),
    [
        (_selected(), None, "AUTH_PROVIDER_NOT_CONFIGURED"),
        (_selected(), _config(enabled=False), "AUTH_PROVIDER_DISABLED"),
    ],
)
def test_missing_and_disabled_config_fail_closed(
    selection: AuthenticationProviderSelection,
    config: ProductionAuthenticationProviderConfig | None,
    error_code: str,
) -> None:
    result = AuthenticationProviderFactory().bootstrap(selection, config)
    assert result.provider is None
    assert result.readiness.provider_operational is False
    assert result.readiness.reason_code == error_code


def test_unsupported_provider_and_selection_mismatch_are_blocked() -> None:
    with pytest.raises(ValidationError):
        _config(provider_type="unknown")
    with pytest.raises(ContractError) as error:
        AuthenticationProviderFactory().bootstrap(
            _selected(ProductionAuthenticationProviderType.LOCAL_OPERATOR), _config()
        )
    assert error.value.error_code == "AUTH_PROVIDER_SELECTION_MISMATCH"


def test_fake_provider_cannot_be_selected_or_configured_for_production() -> None:
    factory = AuthenticationProviderFactory()
    fake_selection = _selected(ProductionAuthenticationProviderType.FAKE)
    with pytest.raises(ContractError) as error:
        factory.bootstrap(fake_selection, None)
    assert error.value.error_code == "AUTH_PROVIDER_FAKE_FORBIDDEN"

    fake_config = _config(
        provider_type=ProductionAuthenticationProviderType.FAKE,
        allowed_algorithms=(),
        network_access_required=False,
    )
    with pytest.raises(ContractError) as error:
        factory.bootstrap(_selected(), fake_config)
    assert error.value.error_code == "AUTH_PROVIDER_FAKE_FORBIDDEN"
    assert factory.bootstrap(_selected(), _config()).readiness.provider_operational is False


def test_config_rejects_secret_fields_and_invalid_oidc_policy() -> None:
    for secret_field in (
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "private_key",
        "signing_key",
        "verification_key",
        "password",
        "client_secret",
        "session_secret",
        "credential",
        "assertion",
        "raw_assertion",
    ):
        with pytest.raises(ValidationError):
            _config(**{secret_field: "synthetic-do-not-store"})
    with pytest.raises(ValidationError):
        _config(allowed_algorithms=())
    with pytest.raises(ValidationError):
        _config(allowed_algorithms=("RS256", "RS256"))
    with pytest.raises(ValidationError):
        _config(allowed_algorithms=("not allowed",))
    with pytest.raises(ValidationError):
        _config(network_access_required=False)


def test_public_config_serialization_contains_no_secret_material() -> None:
    rendered = _config().model_dump_json()
    for forbidden in (
        "secret",
        "token",
        "private_key",
        "signing_key",
        "verification_key",
        "password",
        "credential",
        "raw_assertion",
        "subject_reference",
        "reviewer_id",
    ):
        assert forbidden not in rendered.lower()


def test_existing_registry_satisfies_private_mapping_store_protocol() -> None:
    store = ReviewerIdentityMappingRegistry()
    assert isinstance(store, ReviewerIdentityMappingStore)
