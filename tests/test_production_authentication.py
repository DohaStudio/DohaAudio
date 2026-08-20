from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dohaaudio.errors import ContractError
from dohaaudio.production_authentication import (
    CURRENT_PRODUCTION_AUTHENTICATION_SELECTION,
    AuthenticationProviderFactory,
    AuthenticationProviderSelection,
    ProductionAuthenticationProviderConfig,
    ProductionAuthenticationProviderType,
    ProviderSelectionStatus,
    UnavailableProductionAuthenticationProvider,
)
from dohaaudio.reviewer_identity import (
    AuthenticationCredentialReference,
    ReviewerIdentityMappingRegistry,
    ReviewerIdentityMappingStore,
)

NOW = datetime(2026, 8, 21, tzinfo=UTC)


def _selected(
    provider_type: ProductionAuthenticationProviderType = ProductionAuthenticationProviderType.OIDC,
) -> AuthenticationProviderSelection:
    return AuthenticationProviderSelection(
        decision_version="auth-provider-selection/test/v1",
        status=ProviderSelectionStatus.SELECTED,
        selected_provider_type=provider_type,
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


def test_repository_decision_can_remain_unselected_without_activation() -> None:
    result = AuthenticationProviderFactory().bootstrap(
        CURRENT_PRODUCTION_AUTHENTICATION_SELECTION, None
    )

    assert CURRENT_PRODUCTION_AUTHENTICATION_SELECTION.selected_provider_type is None
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
            rationale_codes=("MISSING_PROVIDER",),
        )
    with pytest.raises(ValidationError):
        AuthenticationProviderSelection(
            decision_version="v1",
            status=ProviderSelectionStatus.PENDING_REQUIREMENTS,
            selected_provider_type=ProductionAuthenticationProviderType.OIDC,
            rationale_codes=("CONTRADICTORY",),
            unresolved_requirement_codes=("ISSUER_UNRESOLVED",),
        )


def test_selected_provider_config_is_accepted_but_stub_is_not_operational() -> None:
    result = AuthenticationProviderFactory().bootstrap(_selected(), _config())

    assert isinstance(result.provider, UnavailableProductionAuthenticationProvider)
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
    fake_selection = _selected(ProductionAuthenticationProviderType.FAKE)
    with pytest.raises(ContractError) as error:
        AuthenticationProviderFactory().bootstrap(fake_selection, None)
    assert error.value.error_code == "AUTH_PROVIDER_FAKE_FORBIDDEN"

    fake_config = _config(
        provider_type=ProductionAuthenticationProviderType.FAKE,
        allowed_algorithms=(),
        network_access_required=False,
    )
    with pytest.raises(ContractError) as error:
        AuthenticationProviderFactory().bootstrap(_selected(), fake_config)
    assert error.value.error_code == "AUTH_PROVIDER_FAKE_FORBIDDEN"


def test_config_rejects_secret_fields_and_invalid_oidc_policy() -> None:
    for secret_field in ("secret", "token", "private_key", "password", "client_secret"):
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
    for forbidden in ("secret", "token", "private_key", "password", "credential"):
        assert forbidden not in rendered.lower()


def test_existing_registry_satisfies_private_mapping_store_protocol() -> None:
    store = ReviewerIdentityMappingRegistry()
    assert isinstance(store, ReviewerIdentityMappingStore)
