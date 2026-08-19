from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from dohaaudio.bootstrap import AudioRuntime, bootstrap_runtime
from dohaaudio.contracts import Capability, CreateJobRequest, JobType
from dohaaudio.errors import ConflictError, ContractError, NotFoundError
from dohaaudio.providers import FakeAudioProvider


def test_runtime_bootstrap_registers_fake_provider(runtime: AudioRuntime) -> None:
    capabilities = runtime.get_capabilities("audio")
    assert capabilities.capabilities == tuple(Capability)
    assert capabilities.api_contract_versions == ("1.0",)
    assert capabilities.ready is True
    assert runtime.health("audio").status == "alive"
    assert runtime.readiness("audio").ready is True


def test_health_and_readiness_are_distinct() -> None:
    runtime = bootstrap_runtime(provider=FakeAudioProvider(healthy=True, ready=False))
    assert runtime.health("audio").status == "alive"
    assert runtime.readiness("audio").ready is False


@pytest.mark.parametrize(
    ("capability", "expected"),
    [
        (Capability.MUSIC_GENERATION, JobType.MUSIC_GENERATION),
        (Capability.STEM_SEPARATION, JobType.STEM_SEPARATION),
        (Capability.AUDIO_ANALYSIS, JobType.AUDIO_ANALYSIS),
    ],
)
def test_supported_job_types_are_created(
    runtime: AudioRuntime,
    make_request: Callable[..., CreateJobRequest],
    capability: Capability,
    expected: JobType,
) -> None:
    response = runtime.create_job(
        make_request(
            job_id=f"job-{capability}",
            idempotency_key=f"idem-{capability}",
            capability=capability,
        )
    )
    assert response.job_type == expected


def test_invalid_job_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateJobRequest(
            capability="EvaluationJob",
            idempotency_key="idem",
            model_manifest_id="manifest",
        )


def test_unknown_provider_is_rejected(runtime: AudioRuntime) -> None:
    with pytest.raises(NotFoundError):
        runtime.get_capabilities("unknown")


def test_unsupported_contract_version_is_rejected(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    with pytest.raises(ConflictError) as exc_info:
        runtime.create_job(make_request(api_contract_version="2.0"))
    assert exc_info.value.error_code == "PROVIDER_CONTRACT_VERSION_UNSUPPORTED"


def test_absolute_path_and_secret_settings_are_rejected(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    with pytest.raises(ContractError) as path_error:
        runtime.create_job(make_request(settings_snapshot={"model_path": "C:\\models\\fake"}))
    assert path_error.value.error_code == "ABSOLUTE_PATH_FORBIDDEN"

    with pytest.raises(ContractError) as secret_error:
        runtime.create_job(
            make_request(job_id="job-secret", settings_snapshot={"api_key": "not-a-secret"})
        )
    assert secret_error.value.error_code == "UNSAFE_REQUEST_METADATA"
