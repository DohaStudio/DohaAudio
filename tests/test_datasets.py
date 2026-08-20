from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dohaaudio.datasets import (
    DatasetEntry,
    DatasetManifest,
    DatasetManifestRegistry,
    DatasetSplit,
    validate_dataset_manifest,
)
from dohaaudio.errors import ConflictError, ContractError
from tests.readiness_helpers import seal_manifest, valid_dataset_manifest


def test_valid_dataset_manifest_and_deterministic_split() -> None:
    manifest = valid_dataset_manifest()
    assert validate_dataset_manifest(manifest) == ()
    assert manifest.split.seed == 17
    assert manifest.split.algorithm_version == "fixture-split-v1"


def test_packaged_dataset_fixture_matches_schema_and_integrity_contract() -> None:
    fixture = json.loads(
        Path("src/dohaaudio/fixtures/fake-dataset-manifest.json").read_text(encoding="utf-8")
    )
    schema = json.loads(Path("schemas/dataset-manifest.schema.json").read_text(encoding="utf-8"))
    manifest = DatasetManifest.model_validate(fixture)
    assert set(schema["required"]) == set(fixture)
    assert schema["$id"].endswith("dataset-manifest-v1.schema.json")
    assert validate_dataset_manifest(manifest) == ()


def test_dataset_manifest_rejects_an_unrecognized_schema_version_field() -> None:
    payload = valid_dataset_manifest().model_dump()
    payload["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        DatasetManifest(**payload)


def test_dataset_manifest_rejects_missing_or_invalid_checksum() -> None:
    payload = valid_dataset_manifest().model_dump()
    payload.pop("manifest_checksum")
    with pytest.raises(ValidationError):
        DatasetManifest(**payload)
    payload["manifest_checksum"] = "invalid"
    with pytest.raises(ValidationError):
        DatasetManifest(**payload)


def test_dataset_integrity_detects_duplicate_sample_and_checksum() -> None:
    manifest = valid_dataset_manifest()
    duplicate = manifest.entries[0].model_copy(update={"sample_id": "sample-002"})
    broken = seal_manifest(manifest.model_copy(update={"entries": (*manifest.entries, duplicate)}))
    issues = validate_dataset_manifest(broken)
    assert "DATASET_DUPLICATE_SAMPLE_ID" in issues
    assert "DATASET_DUPLICATE_CHECKSUM" in issues


def test_dataset_integrity_detects_split_overlap_and_missing_membership() -> None:
    manifest = valid_dataset_manifest()
    split = DatasetSplit(
        split_id=manifest.split_id,
        train=("sample-001", "sample-002"),
        validation=("sample-002",),
        test=(),
        algorithm_version="fixture-split-v1",
        seed=17,
    )
    broken = seal_manifest(manifest.model_copy(update={"split": split}))
    issues = validate_dataset_manifest(broken)
    assert "DATASET_SPLIT_OVERLAP" in issues
    assert "DATASET_SPLIT_MEMBERSHIP_MISMATCH" in issues


def test_dataset_integrity_detects_unsupported_media_type() -> None:
    manifest = valid_dataset_manifest()
    entry = DatasetEntry(
        sample_id="sample-unsupported",
        content_checksum="9" * 64,
        media_type="application/octet-stream",
        provenance="fixture/source",
    )
    broken = seal_manifest(
        manifest.model_copy(
            update={
                "entries": (entry,),
                "item_count": 1,
                "split": manifest.split.model_copy(
                    update={"train": (entry.sample_id,), "validation": (), "test": ()}
                ),
            }
        )
    )
    assert "DATASET_MEDIA_TYPE_UNSUPPORTED" in validate_dataset_manifest(broken)


def test_dataset_version_is_immutable() -> None:
    registry = DatasetManifestRegistry()
    manifest = valid_dataset_manifest()
    registry.register(manifest)
    changed = seal_manifest(
        manifest.model_copy(
            update={
                "dataset_manifest_id": "dataset-manifest/audio/test/v1-mutated",
                "normalization_settings": {"profile": "changed"},
            }
        )
    )
    with pytest.raises(ConflictError) as exc_info:
        registry.register(changed)
    assert exc_info.value.error_code == "DATASET_VERSION_IMMUTABILITY_CONFLICT"


def test_dataset_manifest_rejects_private_path_and_secret_metadata() -> None:
    with pytest.raises(ContractError) as path_error:
        valid_dataset_manifest(source="C:\\private\\dataset")
    assert path_error.value.error_code == "ABSOLUTE_PATH_FORBIDDEN"
    with pytest.raises(ContractError) as secret_error:
        valid_dataset_manifest(normalization_settings={"api_key": "secret"})
    assert secret_error.value.error_code == "UNSAFE_REQUEST_METADATA"
