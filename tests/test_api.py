from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dohaaudio.api import create_app
from dohaaudio.bootstrap import AudioRuntime, bootstrap_runtime
from dohaaudio.contracts import Capability
from dohaaudio.providers import FAKE_MANIFEST_ID


@pytest.fixture
def api_runtime() -> AudioRuntime:
    return bootstrap_runtime()


@pytest.fixture
def client(api_runtime: AudioRuntime) -> TestClient:
    return TestClient(create_app(api_runtime))


def payload(capability: Capability, suffix: str) -> dict[str, object]:
    return {
        "job_id": f"job-api-{suffix}",
        "provider_id": "audio",
        "capability": capability,
        "api_contract_version": "1.0",
        "idempotency_key": f"idem-api-{suffix}",
        "project_id": "project-test",
        "input_asset_version_ids": ["asset-version-test"],
        "input_artifact_ids": [],
        "model_manifest_id": FAKE_MANIFEST_ID,
        "settings_snapshot": {"fixture": suffix},
        "requested_by": "actor-test",
    }


def test_capabilities_health_readiness_and_manifest(client: TestClient) -> None:
    base = "/api/v1/providers/audio"
    assert client.get(f"{base}/capabilities").json()["data"]["ready"] is True
    assert client.get(f"{base}/health").json()["data"]["status"] == "alive"
    assert client.get(f"{base}/readiness").json()["data"]["ready"] is True
    manifest = client.get(f"{base}/model-manifests/{FAKE_MANIFEST_ID}")
    assert manifest.status_code == 200
    assert manifest.json()["data"]["model_id"].startswith("fake/")


@pytest.mark.parametrize("capability", list(Capability))
def test_fake_provider_api_e2e(
    client: TestClient,
    api_runtime: AudioRuntime,
    capability: Capability,
) -> None:
    suffix = capability.value
    response = client.post("/api/v1/providers/audio/jobs", json=payload(capability, suffix))
    assert response.status_code == 202
    job_id = response.json()["data"]["job_id"]
    assert response.json()["data"]["status"] == "queued"

    api_runtime.run_job(job_id)
    status = client.get(f"/api/v1/providers/audio/jobs/{job_id}")
    assert status.json()["data"]["status"] == "succeeded"
    result = client.get(f"/api/v1/providers/audio/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.json()["data"]["output_artifact_ids"]
    assert "C:\\" not in result.text


def test_api_cancel_and_retry(client: TestClient) -> None:
    created = client.post(
        "/api/v1/providers/audio/jobs",
        json=payload(Capability.MUSIC_GENERATION, "cancel"),
    ).json()["data"]
    cancelled = client.post(f"/api/v1/providers/audio/jobs/{created['job_id']}/cancel").json()[
        "data"
    ]
    assert cancelled["status"] == "cancelled"

    retry = client.post(
        f"/api/v1/providers/audio/jobs/{created['job_id']}/retry",
        json={"job_id": "job-api-retry", "idempotency_key": "idem-api-retry"},
    )
    assert retry.status_code == 202
    assert retry.json()["data"]["retry_of_job_id"] == created["job_id"]


def test_invalid_payload_and_version_return_structured_errors(client: TestClient) -> None:
    invalid = client.post("/api/v1/providers/audio/jobs", json={})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["error_code"] == "REQUEST_VALIDATION_FAILED"

    unsupported = payload(Capability.MUSIC_GENERATION, "unsupported")
    unsupported["api_contract_version"] = "2.0"
    response = client.post("/api/v1/providers/audio/jobs", json=unsupported)
    assert response.status_code == 409
    assert response.json()["error"]["error_code"] == "PROVIDER_CONTRACT_VERSION_UNSUPPORTED"


def test_api_does_not_echo_secret_path_or_validation_details(client: TestClient) -> None:
    unsafe = payload(Capability.MUSIC_GENERATION, "unsafe")
    unsafe["settings_snapshot"] = {"token": "secret-value", "path": "C:\\private\\model"}
    response = client.post("/api/v1/providers/audio/jobs", json=unsafe)
    assert response.status_code == 400
    assert "secret-value" not in response.text
    assert "C:\\private" not in response.text
    assert "traceback" not in response.text.casefold()
