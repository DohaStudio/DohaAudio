"""Immutable Dataset Manifest, split, integrity, and rights contracts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from enum import StrEnum
from threading import RLock

from pydantic import Field, field_validator, model_validator

from dohaaudio.contracts import SHA256_PATTERN, FrozenModel
from dohaaudio.errors import ConflictError, NotFoundError
from dohaaudio.security import assert_safe_metadata

SUPPORTED_AUDIO_MEDIA_TYPES = frozenset({"audio/wav", "audio/flac", "audio/mpeg"})


class TrainingAllowed(StrEnum):
    TRUE = "true"
    FALSE = "false"
    PENDING_REVIEW = "pending_review"


class DatasetLicenseStatus(StrEnum):
    APPROVED = "approved"
    REVIEW_REQUIRED = "review_required"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


class CommercialUsageStatus(StrEnum):
    RESEARCH_ONLY = "research_only"
    REVIEW_PENDING = "commercial_review_pending"
    APPROVED = "commercial_approved"
    REJECTED = "commercial_rejected"


class EvidenceReviewStatus(StrEnum):
    VERIFIED = "verified"
    REVIEW_REQUIRED = "review_required"
    REJECTED = "rejected"


class DeletionStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    DELETED = "deleted"


class RightsEvidence(FrozenModel):
    source: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    review_status: EvidenceReviewStatus
    effective_at: datetime
    expires_at: datetime | None = None


class DatasetEntry(FrozenModel):
    sample_id: str = Field(min_length=1)
    content_checksum: str
    media_type: str
    provenance: str = Field(min_length=1)

    @field_validator("content_checksum")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("content_checksum must be a lowercase sha256 digest")
        return value


class DatasetSplit(FrozenModel):
    split_id: str = Field(min_length=1)
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]
    algorithm_version: str = Field(min_length=1)
    seed: int


class DatasetManifest(FrozenModel):
    dataset_manifest_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    dataset_domain: str = "audio"
    source: str = Field(min_length=1)
    license_status: DatasetLicenseStatus
    training_allowed: TrainingAllowed
    commercial_usage_status: CommercialUsageStatus
    redistribution_allowed: TrainingAllowed
    item_count: int = Field(ge=0)
    manifest_checksum: str
    content_checksum_set_id: str = Field(min_length=1)
    split_id: str = Field(min_length=1)
    created_at: datetime
    supersedes_dataset_version: str | None = None
    deletion_status: DeletionStatus = DeletionStatus.ACTIVE
    entries: tuple[DatasetEntry, ...]
    split: DatasetSplit
    rights_evidence: tuple[RightsEvidence, ...]
    normalization_settings: dict[str, str] = Field(default_factory=dict)

    @field_validator("manifest_checksum")
    @classmethod
    def validate_manifest_checksum(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("manifest_checksum must be a lowercase sha256 digest")
        return value

    @model_validator(mode="after")
    def reject_private_metadata(self) -> DatasetManifest:
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


def canonical_dataset_checksum(manifest: DatasetManifest) -> str:
    payload = manifest.model_dump(mode="json", exclude={"manifest_checksum"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def validate_dataset_manifest(manifest: DatasetManifest) -> tuple[str, ...]:
    issues: list[str] = []
    entries = manifest.entries
    sample_ids = [item.sample_id for item in entries]
    checksums = [item.content_checksum for item in entries]
    if manifest.dataset_domain != "audio":
        issues.append("DATASET_DOMAIN_UNSUPPORTED")
    if manifest.item_count != len(entries):
        issues.append("DATASET_ITEM_COUNT_MISMATCH")
    if len(sample_ids) != len(set(sample_ids)):
        issues.append("DATASET_DUPLICATE_SAMPLE_ID")
    if len(checksums) != len(set(checksums)):
        issues.append("DATASET_DUPLICATE_CHECKSUM")
    if any(item.media_type not in SUPPORTED_AUDIO_MEDIA_TYPES for item in entries):
        issues.append("DATASET_MEDIA_TYPE_UNSUPPORTED")
    if manifest.split_id != manifest.split.split_id:
        issues.append("DATASET_SPLIT_ID_MISMATCH")
    split_lists = (manifest.split.train, manifest.split.validation, manifest.split.test)
    flattened = [sample_id for split in split_lists for sample_id in split]
    if len(flattened) != len(set(flattened)):
        issues.append("DATASET_SPLIT_OVERLAP")
    if set(flattened) != set(sample_ids):
        issues.append("DATASET_SPLIT_MEMBERSHIP_MISMATCH")
    if manifest.manifest_checksum != canonical_dataset_checksum(manifest):
        issues.append("DATASET_MANIFEST_CHECKSUM_MISMATCH")
    return tuple(issues)


class DatasetManifestRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, DatasetManifest] = {}
        self._version_ids: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def register(self, manifest: DatasetManifest) -> DatasetManifest:
        with self._lock:
            existing = self._manifests.get(manifest.dataset_manifest_id)
            version_key = (manifest.dataset_id, manifest.dataset_version)
            version_manifest_id = self._version_ids.get(version_key)
            if existing is not None and existing != manifest:
                raise ConflictError(
                    "DATASET_MANIFEST_IMMUTABILITY_CONFLICT",
                    "게시된 Dataset Manifest를 변경할 수 없습니다.",
                )
            if version_manifest_id is not None:
                version = self._manifests[version_manifest_id]
                if version != manifest:
                    raise ConflictError(
                        "DATASET_VERSION_IMMUTABILITY_CONFLICT",
                        "동일 Dataset version의 membership, split 또는 권리 상태를 "
                        "변경할 수 없습니다.",
                    )
            self._manifests.setdefault(manifest.dataset_manifest_id, deepcopy(manifest))
            self._version_ids.setdefault(version_key, manifest.dataset_manifest_id)
            return deepcopy(self._manifests[manifest.dataset_manifest_id])

    def get(self, manifest_id: str) -> DatasetManifest:
        with self._lock:
            try:
                return deepcopy(self._manifests[manifest_id])
            except KeyError as exc:
                raise NotFoundError("Dataset Manifest") from exc
