"""Read-only local Dataset authority discovery and fail-closed training admission."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from dohaaudio.contracts import SHA256_PATTERN, FrozenModel
from dohaaudio.datasets import (
    DatasetLicenseStatus,
    DatasetManifest,
    EvidenceReviewStatus,
    TrainingAllowed,
    validate_dataset_manifest,
)
from dohaaudio.errors import ContractError
from dohaaudio.security import assert_safe_metadata
from dohaaudio.training import ReadinessStatus, TrainingConfig, TrainingReadinessReport

DATASET_ROOT_ENVIRONMENT_VARIABLE = "DOHAAUDIO_DATASET_ROOT"
DEFAULT_AUTHORITY_ID = "dohaaudio-local-audio-authority-v1"
SUPPORTED_MEDIA_TYPES = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}


@dataclass(frozen=True)
class ResolvedDatasetAuthority:
    """Internal-only resolved root. Never serialize this object into a public contract."""

    authority_id: str
    root: Path


class InventoryItem(FrozenModel):
    sample_id: str = Field(min_length=1)
    source_key: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    checksum: str | None = None
    provenance: str = Field(min_length=1)

    @field_validator("checksum")
    @classmethod
    def validate_checksum(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_PATTERN.fullmatch(value):
            raise ValueError("checksum must be a lowercase sha256 digest")
        return value


class DatasetInventory(FrozenModel):
    authority_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    source_alias: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    discovered_file_count: int = Field(ge=0)
    supported_item_count: int = Field(ge=0)
    unsupported_file_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    unsupported_extensions: tuple[str, ...]
    duplicate_relative_identity_count: int = Field(ge=0)
    duplicate_checksum_count: int = Field(ge=0)
    missing_checksum_count: int = Field(ge=0)
    items: tuple[InventoryItem, ...]

    @model_validator(mode="after")
    def reject_private_metadata(self) -> DatasetInventory:
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class EnvironmentPreflight(FrozenModel):
    python_version: str = Field(min_length=1)
    gpu_model: str | None = None
    vram_mib: int | None = Field(default=None, ge=0)
    driver_version: str | None = None
    cuda_available: bool
    compatible: bool
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def reject_private_metadata(self) -> EnvironmentPreflight:
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class UsageRightsAdmission(FrozenModel):
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    review_status: EvidenceReviewStatus
    effective_at: datetime
    expires_at: datetime | None = None
    dataset_possession_confirmed: bool
    dataset_access_authorized: bool
    ai_training_authorized: bool
    commercial_usage_authorized: bool
    redistribution_authorized: bool
    derived_model_distribution_authorized: bool
    generated_output_usage_authorized: bool

    @model_validator(mode="after")
    def reject_private_metadata(self) -> UsageRightsAdmission:
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class PreprocessingContract(FrozenModel):
    contract_version: str = Field(min_length=1)
    resampling: str = Field(min_length=1)
    channel_handling: str = Field(min_length=1)
    normalization: str = Field(min_length=1)
    duration_policy: str = Field(min_length=1)
    silence_policy: str = Field(min_length=1)
    invalid_or_corrupt_file_policy: str = Field(min_length=1)

    @model_validator(mode="after")
    def reject_private_metadata(self) -> PreprocessingContract:
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class TrainingAdmissionReport(FrozenModel):
    candidate_id: str = Field(min_length=1)
    dataset_manifest_id: str | None = None
    usage_rights: UsageRightsAdmission | None = None
    dataset_authority_valid: bool
    rights_gate_pass: bool
    dataset_integrity_pass: bool
    dataset_split_frozen: bool
    model_selected: bool
    training_config_valid: bool
    environment_preflight_pass: bool
    training_preflight_pass: bool
    training_execution_ready: bool
    training_approval_consumed: bool = False
    reasons: tuple[str, ...]
    checked_at: datetime

    @model_validator(mode="after")
    def require_all_execution_gates(self) -> TrainingAdmissionReport:
        prerequisites = (
            self.dataset_authority_valid,
            self.rights_gate_pass,
            self.dataset_integrity_pass,
            self.dataset_split_frozen,
            self.model_selected,
            self.training_config_valid,
            self.environment_preflight_pass,
            self.training_preflight_pass,
            self.training_approval_consumed,
        )
        if self.training_execution_ready != all(prerequisites):
            raise ValueError("training_execution_ready must equal all admission prerequisites")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class DatasetAuthorityResolver:
    """Resolve an injected root and build path-free, deterministic inventories."""

    def from_environment(
        self,
        environment: Mapping[str, str] | None = None,
        *,
        variable: str = DATASET_ROOT_ENVIRONMENT_VARIABLE,
        authority_id: str = DEFAULT_AUTHORITY_ID,
    ) -> ResolvedDatasetAuthority:
        source = environment if environment is not None else os.environ
        configured = source.get(variable)
        if not configured:
            raise ContractError(
                "DATASET_AUTHORITY_ROOT_MISSING", "Dataset authority root is missing."
            )
        return self.resolve(configured, authority_id=authority_id)

    def resolve(
        self, configured_root: str | Path, *, authority_id: str = DEFAULT_AUTHORITY_ID
    ) -> ResolvedDatasetAuthority:
        root = Path(configured_root)
        if not root.exists():
            raise ContractError(
                "DATASET_AUTHORITY_ROOT_MISSING", "Dataset authority root is missing."
            )
        if not root.is_dir():
            raise ContractError(
                "DATASET_AUTHORITY_ROOT_NOT_DIRECTORY",
                "Dataset authority root is not a directory.",
            )
        if self._is_reparse_point(root):
            raise ContractError(
                "DATASET_AUTHORITY_ROOT_REPARSE_POINT",
                "Dataset authority root cannot be a link or reparse point.",
            )
        return ResolvedDatasetAuthority(authority_id=authority_id, root=root.resolve(strict=True))

    def inventory(
        self,
        authority: ResolvedDatasetAuthority,
        relative_scope: str,
        *,
        candidate_id: str,
        source_alias: str,
        purpose: str,
        include_checksums: bool = False,
    ) -> DatasetInventory:
        scope = self._resolve_scope(authority, relative_scope)
        files: list[Path] = []
        for current, directories, names in os.walk(
            scope, followlinks=False, onerror=self._walk_error
        ):
            current_path = Path(current)
            self._require_contained(authority.root, current_path)
            for directory in tuple(directories):
                child = current_path / directory
                if self._is_reparse_point(child):
                    raise ContractError(
                        "DATASET_AUTHORITY_ROOT_ESCAPE",
                        "Dataset authority scope contains a link or reparse point.",
                    )
                self._require_contained(authority.root, child.resolve(strict=True))
            for name in names:
                child = current_path / name
                if self._is_reparse_point(child):
                    raise ContractError(
                        "DATASET_AUTHORITY_ROOT_ESCAPE",
                        "Dataset authority scope contains a link or reparse point.",
                    )
                self._require_contained(authority.root, child.resolve(strict=True))
                files.append(child)

        items: list[InventoryItem] = []
        unsupported_extensions: set[str] = set()
        relative_identities: list[str] = []
        checksums: list[str] = []
        total_size_bytes = 0
        for path in sorted(files, key=lambda item: item.relative_to(scope).as_posix().casefold()):
            relative = path.relative_to(scope).as_posix()
            normalized_relative = relative.casefold()
            relative_identities.append(normalized_relative)
            total_size_bytes += path.stat().st_size
            extension = path.suffix.casefold() or "<none>"
            media_type = SUPPORTED_MEDIA_TYPES.get(extension)
            if media_type is None:
                unsupported_extensions.add(extension)
                continue
            checksum = self._sha256(path) if include_checksums else None
            if checksum is not None:
                checksums.append(checksum)
            identity_digest = hashlib.sha256(normalized_relative.encode()).hexdigest()
            items.append(
                InventoryItem(
                    sample_id=f"sample_{identity_digest[:24]}",
                    source_key=f"source_{identity_digest[24:48]}",
                    media_type=media_type,
                    size_bytes=path.stat().st_size,
                    checksum=checksum,
                    provenance=source_alias,
                )
            )
        duplicate_relative_count = len(relative_identities) - len(set(relative_identities))
        duplicate_checksum_count = len(checksums) - len(set(checksums))
        return DatasetInventory(
            authority_id=authority.authority_id,
            candidate_id=candidate_id,
            source_alias=source_alias,
            purpose=purpose,
            discovered_file_count=len(files),
            supported_item_count=len(items),
            unsupported_file_count=len(files) - len(items),
            total_size_bytes=total_size_bytes,
            unsupported_extensions=tuple(sorted(unsupported_extensions)),
            duplicate_relative_identity_count=duplicate_relative_count,
            duplicate_checksum_count=duplicate_checksum_count,
            missing_checksum_count=sum(item.checksum is None for item in items),
            items=tuple(items),
        )

    def _resolve_scope(self, authority: ResolvedDatasetAuthority, relative_scope: str) -> Path:
        scope_path = Path(relative_scope)
        if scope_path.is_absolute() or ".." in scope_path.parts:
            raise ContractError(
                "DATASET_AUTHORITY_ROOT_ESCAPE", "Dataset authority scope escapes its root."
            )
        scope = authority.root / scope_path
        if not scope.exists() or not scope.is_dir():
            raise ContractError(
                "DATASET_SCOPE_NOT_FOUND", "Dataset authority scope is unavailable."
            )
        if self._is_reparse_point(scope):
            raise ContractError(
                "DATASET_AUTHORITY_ROOT_ESCAPE",
                "Dataset authority scope contains a link or reparse point.",
            )
        resolved = scope.resolve(strict=True)
        self._require_contained(authority.root, resolved)
        return resolved

    @staticmethod
    def _require_contained(root: Path, candidate: Path) -> None:
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ContractError(
                "DATASET_AUTHORITY_ROOT_ESCAPE", "Dataset authority scope escapes its root."
            ) from exc

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attributes & reparse_flag)

    @staticmethod
    def _sha256(path: Path) -> str:
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ContractError(
                "DATASET_FILE_CHANGED_DURING_INVENTORY",
                "Dataset file changed during read-only inventory.",
            )
        return digest.hexdigest()

    @staticmethod
    def _walk_error(_: OSError) -> None:
        raise ContractError(
            "DATASET_AUTHORITY_READ_FAILED", "Dataset authority scope could not be read."
        )


class TrainingAdmissionService:
    """Keep Dataset admission separate from model/config/environment execution readiness."""

    def assess(
        self,
        *,
        inventory: DatasetInventory,
        authority_validated: bool,
        usage_rights: UsageRightsAdmission | None,
        manifest: DatasetManifest | None,
        config: TrainingConfig | None,
        model_selected: bool,
        environment: EnvironmentPreflight | None,
        readiness: TrainingReadinessReport | None,
        checked_at: datetime,
        training_approval_consumed: bool = False,
    ) -> TrainingAdmissionReport:
        reasons: list[str] = []
        dataset_authority_valid = (
            authority_validated and inventory.duplicate_relative_identity_count == 0
        )
        if not dataset_authority_valid:
            reasons.append("DATASET_AUTHORITY_INVALID")

        integrity_issues = validate_dataset_manifest(manifest) if manifest is not None else ()
        inventory_matches_manifest = manifest is not None and (
            manifest.item_count == inventory.supported_item_count
            and {entry.content_checksum for entry in manifest.entries}
            == {item.checksum for item in inventory.items}
        )
        dataset_integrity_pass = (
            manifest is not None
            and not integrity_issues
            and inventory_matches_manifest
            and inventory.missing_checksum_count == 0
            and inventory.duplicate_checksum_count == 0
            and inventory.unsupported_file_count == 0
        )
        if manifest is None:
            reasons.append("DATASET_MANIFEST_NOT_ADMITTED")
        elif not inventory_matches_manifest:
            reasons.append("DATASET_INVENTORY_MANIFEST_MISMATCH")
        reasons.extend(integrity_issues)
        if inventory.missing_checksum_count:
            reasons.append("DATASET_CHECKSUM_INCOMPLETE")
        if inventory.duplicate_checksum_count:
            reasons.append("DATASET_DUPLICATE_CHECKSUM")
        if inventory.unsupported_file_count:
            reasons.append("DATASET_UNSUPPORTED_FILES_PRESENT")

        rights_gate_pass = self._rights_pass(manifest, usage_rights, checked_at)
        if not rights_gate_pass:
            reasons.append("RIGHTS_GATE_BLOCKED")
        dataset_split_frozen = manifest is not None and not any(
            issue.startswith("DATASET_SPLIT_") for issue in integrity_issues
        )
        if not dataset_split_frozen:
            reasons.append("DATASET_SPLIT_NOT_FROZEN")
        training_config_valid = config is not None
        if not training_config_valid:
            reasons.append("TRAINING_CONFIG_MISSING")
        if not model_selected:
            reasons.append("MODEL_SELECTION_BLOCKED")
        environment_preflight_pass = environment is not None and environment.compatible
        if not environment_preflight_pass:
            reasons.append("ENVIRONMENT_PREFLIGHT_BLOCKED")
        training_preflight_pass = (
            readiness is not None and readiness.status == ReadinessStatus.READY
        )
        if not training_preflight_pass:
            reasons.append("TRAINING_PREFLIGHT_BLOCKED")
        if not training_approval_consumed:
            reasons.append("TRAINING_APPROVAL_NOT_CONSUMED")

        prerequisites = (
            dataset_authority_valid,
            rights_gate_pass,
            dataset_integrity_pass,
            dataset_split_frozen,
            model_selected,
            training_config_valid,
            environment_preflight_pass,
            training_preflight_pass,
            training_approval_consumed,
        )
        return TrainingAdmissionReport(
            candidate_id=inventory.candidate_id,
            dataset_manifest_id=(manifest.dataset_manifest_id if manifest is not None else None),
            usage_rights=usage_rights,
            dataset_authority_valid=dataset_authority_valid,
            rights_gate_pass=rights_gate_pass,
            dataset_integrity_pass=dataset_integrity_pass,
            dataset_split_frozen=dataset_split_frozen,
            model_selected=model_selected,
            training_config_valid=training_config_valid,
            environment_preflight_pass=environment_preflight_pass,
            training_preflight_pass=training_preflight_pass,
            training_execution_ready=all(prerequisites),
            training_approval_consumed=training_approval_consumed,
            reasons=tuple(dict.fromkeys(reasons)),
            checked_at=checked_at,
        )

    @staticmethod
    def _rights_pass(
        manifest: DatasetManifest | None,
        usage_rights: UsageRightsAdmission | None,
        now: datetime,
    ) -> bool:
        if manifest is None or usage_rights is None:
            return False
        if manifest.license_status != DatasetLicenseStatus.APPROVED:
            return False
        if manifest.training_allowed != TrainingAllowed.TRUE or not manifest.rights_evidence:
            return False
        manifest_evidence_valid = all(
            evidence.review_status == EvidenceReviewStatus.VERIFIED
            and evidence.effective_at <= now
            and (evidence.expires_at is None or evidence.expires_at > now)
            for evidence in manifest.rights_evidence
        )
        usage_evidence_valid = (
            usage_rights.review_status == EvidenceReviewStatus.VERIFIED
            and usage_rights.effective_at <= now
            and (usage_rights.expires_at is None or usage_rights.expires_at > now)
        )
        return (
            manifest_evidence_valid
            and usage_evidence_valid
            and usage_rights.dataset_possession_confirmed
            and usage_rights.dataset_access_authorized
            and usage_rights.ai_training_authorized
        )
