from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from dohaaudio.bootstrap import AudioRuntime, bootstrap_runtime
from dohaaudio.contracts import ArtifactMetadata, CreateJobRequest, ModelManifest, ReviewStatus
from dohaaudio.errors import ConflictError
from dohaaudio.manifests import JsonModelManifestLoader
from dohaaudio.providers import FAKE_MANIFEST_ID, fake_model_manifest


def test_fake_manifest_has_explicit_pre_training_unknowns(runtime: AudioRuntime) -> None:
    manifest = runtime.get_manifest(FAKE_MANIFEST_ID)
    assert manifest.model_id.startswith("fake/")
    assert manifest.dataset_manifest_id is None
    assert manifest.training_run_id is None
    assert manifest.evaluation_result_id is None
    assert manifest.recommended_vram is None
    assert manifest.license_status == ReviewStatus.NOT_APPLICABLE
    assert manifest.commercial_usage_status == ReviewStatus.NOT_APPLICABLE


def test_packaged_fake_manifest_loader_and_schema_fixture() -> None:
    manifest = JsonModelManifestLoader().load_package_fixture("fake-model-manifest.json")
    assert manifest.model_manifest_id == FAKE_MANIFEST_ID
    assert manifest.api_contract_version == "1.0"


def test_manifest_loader_rejects_non_object_json() -> None:
    with pytest.raises(ValueError):
        JsonModelManifestLoader().load_json("[]")


def test_tracked_json_schema_covers_the_fake_fixture() -> None:
    schema = json.loads(Path("schemas/model-manifest.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads(
        Path("src/dohaaudio/fixtures/fake-model-manifest.json").read_text(encoding="utf-8")
    )
    assert set(schema["required"]) == set(fixture)
    assert schema["properties"]["artifact_checksum"]["pattern"].startswith("^sha256:")


def test_manifest_required_fields_and_checksum_are_validated() -> None:
    payload = fake_model_manifest().model_dump()
    payload.pop("provider_id")
    with pytest.raises(ValidationError):
        ModelManifest(**payload)

    payload = fake_model_manifest().model_dump()
    payload["artifact_checksum"] = "C:\\checkpoint.bin"
    with pytest.raises(ValidationError):
        ModelManifest(**payload)


def test_manifest_is_immutable_in_registry(runtime: AudioRuntime) -> None:
    manifest = fake_model_manifest().model_copy(update={"model_version": "changed"})
    with pytest.raises(ConflictError) as exc_info:
        runtime.manifests.register(manifest)
    assert exc_info.value.error_code == "MANIFEST_IMMUTABILITY_CONFLICT"


def test_artifacts_are_deterministic_and_immutable(
    runtime: AudioRuntime, make_request: Callable[..., CreateJobRequest]
) -> None:
    job = runtime.create_job(make_request())
    runtime.run_job(job.job_id)
    result = runtime.get_result(job.job_id)
    artifact = result.artifacts[0]
    assert artifact.logical_uri.startswith("artifact://audio/")
    assert len(artifact.artifact_checksum) == 64

    changed = artifact.model_copy(update={"size_bytes": artifact.size_bytes + 1})
    with pytest.raises(ConflictError) as exc_info:
        runtime.artifacts.register(changed)
    assert exc_info.value.error_code == "ARTIFACT_IMMUTABILITY_CONFLICT"


def test_fake_outputs_are_deterministic(
    make_request: Callable[..., CreateJobRequest],
) -> None:
    first_runtime = bootstrap_runtime()
    second_runtime = bootstrap_runtime()
    first = first_runtime.create_job(make_request())
    second = second_runtime.create_job(make_request())
    first_runtime.run_job(first.job_id)
    second_runtime.run_job(second.job_id)
    first_artifact = first_runtime.get_result(first.job_id).artifacts[0]
    second_artifact = second_runtime.get_result(second.job_id).artifacts[0]
    assert first_artifact.artifact_id == second_artifact.artifact_id
    assert first_artifact.artifact_checksum == second_artifact.artifact_checksum
    assert first_artifact.size_bytes == second_artifact.size_bytes


def test_artifact_metadata_rejects_invalid_checksum_and_path_uri() -> None:
    payload = {
        "artifact_id": "fake/audio/item",
        "artifact_kind": "audio",
        "media_type": "audio/wav",
        "size_bytes": 1,
        "checksum_algorithm": "sha256",
        "artifact_checksum": "invalid",
        "producer_type": "provider",
        "producer_id": "audio",
        "run_id": "job",
        "created_at": "2026-08-19T00:00:00Z",
        "retention_status": "active",
        "logical_uri": "C:\\artifacts\\output.wav",
    }
    with pytest.raises(ValidationError):
        ArtifactMetadata(**payload)
