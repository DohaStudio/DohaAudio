"""Read-only archive membership inspection for Dataset enrollment candidates."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import unquote

from pydantic import Field, model_validator

from dohaaudio.admission import SUPPORTED_MEDIA_TYPES, DatasetInventory, InventoryItem
from dohaaudio.contracts import SHA256_PATTERN, FrozenModel
from dohaaudio.errors import ContractError
from dohaaudio.security import assert_safe_metadata

ARCHIVE_EXTENSIONS = frozenset({".7z", ".bz2", ".gz", ".rar", ".tar", ".tgz", ".xz", ".zip"})
SUPPORTED_ZIP_COMPRESSION = frozenset(
    {
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
        zipfile.ZIP_BZIP2,
        zipfile.ZIP_LZMA,
    }
)
WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:")


class ArchiveInspectionMode(StrEnum):
    DISCOVERY = "discovery"
    FULL_CHECKSUM = "full_checksum"


class ArchiveInspectionStatus(StrEnum):
    COMPLETE = "complete"
    BLOCKED = "blocked"
    FAILED = "failed"


class ArchiveMemberSupport(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


class ChecksumStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    VERIFIED = "verified"
    FAILED = "failed"


class CrcValidationStatus(StrEnum):
    NOT_PERFORMED = "not_performed"
    VERIFIED = "verified"
    FAILED = "failed"


class ArchiveInspectionPolicy(FrozenModel):
    """Caller-owned safety ceilings; no production Dataset thresholds are inferred here."""

    max_members_per_archive: int = Field(gt=0)
    max_member_uncompressed_bytes: int = Field(gt=0)
    max_total_uncompressed_bytes: int = Field(gt=0)
    max_compression_ratio: float = Field(gt=0)
    max_member_name_bytes: int = Field(gt=0)
    stream_chunk_bytes: int = Field(default=1024 * 1024, gt=0, le=16 * 1024 * 1024)


class ArchiveMemberInspection(FrozenModel):
    member_logical_id: str = Field(min_length=1)
    normalized_relative_identity: str = Field(min_length=1)
    extension: str
    media_type: str | None = None
    compressed_size: int = Field(ge=0)
    uncompressed_size: int = Field(ge=0)
    crc32: str = Field(pattern=r"^[0-9a-f]{8}$")
    checksum_status: ChecksumStatus
    content_sha256: str | None = None
    crc_validation_status: CrcValidationStatus
    provenance_identity: str = Field(min_length=1)
    support_status: ArchiveMemberSupport
    blocking_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_member(self) -> ArchiveMemberInspection:
        if (self.content_sha256 is not None) != (self.checksum_status == ChecksumStatus.VERIFIED):
            raise ValueError("verified checksum status and SHA-256 must advance together")
        if self.content_sha256 is not None and not SHA256_PATTERN.fullmatch(self.content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class ArchiveInspectionResult(FrozenModel):
    candidate_id: str = Field(min_length=1)
    archive_logical_id: str = Field(min_length=1)
    archive_metadata_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_checksum: str | None = None
    archive_checksum_status: ChecksumStatus
    archive_size_bytes: int = Field(ge=0)
    archive_format: str
    member_count: int = Field(ge=0)
    directory_entry_count: int = Field(ge=0)
    supported_member_count: int = Field(ge=0)
    unsupported_member_count: int = Field(ge=0)
    encrypted_member_count: int = Field(ge=0)
    nested_archive_count: int = Field(ge=0)
    unsafe_member_count: int = Field(ge=0)
    total_compressed_bytes: int = Field(ge=0)
    total_uncompressed_bytes: int = Field(ge=0)
    inspection_mode: ArchiveInspectionMode
    inspection_status: ArchiveInspectionStatus
    inspection_complete: bool
    membership_known: bool
    path_safety_pass: bool
    blocking_reasons: tuple[str, ...]
    members: tuple[ArchiveMemberInspection, ...]

    @model_validator(mode="after")
    def validate_result(self) -> ArchiveInspectionResult:
        if self.member_count != len(self.members):
            raise ValueError("member_count must match file member records")
        if self.supported_member_count + self.unsupported_member_count != self.member_count:
            raise ValueError("supported and unsupported counts must cover every file member")
        if self.inspection_complete != (self.inspection_status != ArchiveInspectionStatus.FAILED):
            raise ValueError("only failed central-directory inspection is incomplete")
        if self.inspection_complete and not self.membership_known:
            raise ValueError("complete inspection requires known membership")
        if self.archive_checksum is not None and not SHA256_PATTERN.fullmatch(
            self.archive_checksum
        ):
            raise ValueError("archive_checksum must be a lowercase SHA-256 digest")
        if (self.archive_checksum is not None) != (
            self.archive_checksum_status == ChecksumStatus.VERIFIED
        ):
            raise ValueError("archive checksum and status must advance together")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


class ArchiveSetInspectionSummary(FrozenModel):
    candidate_id: str = Field(min_length=1)
    archive_count: int = Field(ge=0)
    inspected_archive_count: int = Field(ge=0)
    aggregate_archive_bytes: int = Field(ge=0)
    member_count: int = Field(ge=0)
    supported_member_count: int = Field(ge=0)
    unsupported_member_count: int = Field(ge=0)
    encrypted_member_count: int = Field(ge=0)
    nested_archive_count: int = Field(ge=0)
    unsafe_member_count: int = Field(ge=0)
    corrupt_archive_count: int = Field(ge=0)
    extension_counts: dict[str, int]
    media_type_counts: dict[str, int]
    archive_inspection_complete: bool
    archive_membership_known: bool
    archive_path_safety_pass: bool
    blocking_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def validate_summary(self) -> ArchiveSetInspectionSummary:
        if self.inspected_archive_count > self.archive_count:
            raise ValueError("inspected archive count cannot exceed archive count")
        if self.supported_member_count + self.unsupported_member_count != self.member_count:
            raise ValueError("member classifications must cover all inspected file members")
        assert_safe_metadata(self.model_dump(mode="python"))
        return self


@dataclass(frozen=True)
class ArchiveSource:
    """Internal source reference. The physical path is never serialized."""

    candidate_id: str
    archive_logical_id: str
    path: Path


class ArchiveInspector(Protocol):
    def inspect(
        self,
        source: ArchiveSource,
        *,
        mode: ArchiveInspectionMode = ArchiveInspectionMode.DISCOVERY,
    ) -> ArchiveInspectionResult: ...


@dataclass(frozen=True)
class _NormalizedMemberName:
    collision_key: str | None
    logical_identity: str
    extension: str
    invalid_reason: str | None


class ZipArchiveInspector:
    def __init__(self, policy: ArchiveInspectionPolicy) -> None:
        self._policy = policy

    def inspect(
        self,
        source: ArchiveSource,
        *,
        mode: ArchiveInspectionMode = ArchiveInspectionMode.DISCOVERY,
    ) -> ArchiveInspectionResult:
        self._validate_source(source)
        archive_size = self._archive_size(source.path)
        archive_checksum = (
            self._stream_file_sha256(source.path)
            if mode == ArchiveInspectionMode.FULL_CHECKSUM
            else None
        )
        try:
            with zipfile.ZipFile(source.path, mode="r") as archive:
                return self._inspect_open_archive(
                    archive,
                    source=source,
                    archive_size=archive_size,
                    archive_checksum=archive_checksum,
                    mode=mode,
                )
        except (OSError, EOFError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
            return self._failed_result(
                source=source,
                archive_size=archive_size,
                archive_checksum=archive_checksum,
                mode=mode,
            )

    def _inspect_open_archive(
        self,
        archive: zipfile.ZipFile,
        *,
        source: ArchiveSource,
        archive_size: int,
        archive_checksum: str | None,
        mode: ArchiveInspectionMode,
    ) -> ArchiveInspectionResult:
        infos = archive.infolist()
        directories = sum(info.is_dir() for info in infos)
        file_infos = [info for info in infos if not info.is_dir()]
        reasons: list[str] = []
        if not file_infos:
            reasons.append("ARCHIVE_EMPTY")
        if len(file_infos) > self._policy.max_members_per_archive:
            reasons.append("ARCHIVE_MEMBER_COUNT_LIMIT_EXCEEDED")

        total_uncompressed = sum(info.file_size for info in file_infos)
        total_compressed = sum(info.compress_size for info in file_infos)
        if total_uncompressed > self._policy.max_total_uncompressed_bytes:
            reasons.append("ARCHIVE_TOTAL_UNCOMPRESSED_LIMIT_EXCEEDED")

        members: list[ArchiveMemberInspection] = []
        collision_indexes: dict[str, list[int]] = {}
        for info in file_infos:
            normalized = self._normalize_member_name(
                info.filename,
                archive_logical_id=source.archive_logical_id,
            )
            member = self._inspect_member(
                archive,
                info,
                source=source,
                normalized=normalized,
                mode=mode,
            )
            members.append(member)
            if normalized.collision_key is not None:
                collision_indexes.setdefault(normalized.collision_key, []).append(len(members) - 1)

        duplicate_indexes = {
            index for indexes in collision_indexes.values() if len(indexes) > 1 for index in indexes
        }
        if duplicate_indexes:
            reasons.append("ARCHIVE_DUPLICATE_MEMBER_IDENTITY")
            for index in duplicate_indexes:
                current = members[index]
                members[index] = current.model_copy(
                    update={
                        "support_status": ArchiveMemberSupport.BLOCKED,
                        "blocking_reasons": tuple(
                            dict.fromkeys(
                                (*current.blocking_reasons, "ARCHIVE_DUPLICATE_MEMBER_IDENTITY")
                            )
                        ),
                    }
                )

        members.sort(key=lambda item: item.member_logical_id)
        for member in members:
            reasons.extend(member.blocking_reasons)
        reasons = list(dict.fromkeys(reasons))
        unsafe_count = sum(
            "ARCHIVE_MEMBER_PATH_UNSAFE" in member.blocking_reasons for member in members
        )
        supported_count = sum(
            member.support_status == ArchiveMemberSupport.SUPPORTED for member in members
        )
        encrypted_count = sum(
            "ARCHIVE_MEMBER_ENCRYPTED" in member.blocking_reasons for member in members
        )
        nested_count = sum(
            "ARCHIVE_NESTED_ARCHIVE" in member.blocking_reasons for member in members
        )
        status = (
            ArchiveInspectionStatus.COMPLETE if not reasons else ArchiveInspectionStatus.BLOCKED
        )
        metadata_fingerprint = self._metadata_fingerprint(
            source.archive_logical_id,
            archive_size,
            directories,
            members,
        )
        return ArchiveInspectionResult(
            candidate_id=source.candidate_id,
            archive_logical_id=source.archive_logical_id,
            archive_metadata_fingerprint=metadata_fingerprint,
            archive_checksum=archive_checksum,
            archive_checksum_status=(
                ChecksumStatus.VERIFIED
                if archive_checksum is not None
                else ChecksumStatus.NOT_REQUESTED
            ),
            archive_size_bytes=archive_size,
            archive_format="zip",
            member_count=len(members),
            directory_entry_count=directories,
            supported_member_count=supported_count,
            unsupported_member_count=len(members) - supported_count,
            encrypted_member_count=encrypted_count,
            nested_archive_count=nested_count,
            unsafe_member_count=unsafe_count,
            total_compressed_bytes=total_compressed,
            total_uncompressed_bytes=total_uncompressed,
            inspection_mode=mode,
            inspection_status=status,
            inspection_complete=True,
            membership_known=True,
            path_safety_pass=unsafe_count == 0,
            blocking_reasons=tuple(reasons),
            members=tuple(members),
        )

    def _inspect_member(
        self,
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        *,
        source: ArchiveSource,
        normalized: _NormalizedMemberName,
        mode: ArchiveInspectionMode,
    ) -> ArchiveMemberInspection:
        reasons: list[str] = []
        support = ArchiveMemberSupport.SUPPORTED
        if normalized.invalid_reason is not None:
            reasons.append(normalized.invalid_reason)
            support = ArchiveMemberSupport.BLOCKED
        if len(info.filename.encode("utf-8", errors="surrogatepass")) > (
            self._policy.max_member_name_bytes
        ):
            reasons.append("ARCHIVE_MEMBER_NAME_LIMIT_EXCEEDED")
            support = ArchiveMemberSupport.BLOCKED
        if info.flag_bits & 0x1:
            reasons.append("ARCHIVE_MEMBER_ENCRYPTED")
            support = ArchiveMemberSupport.BLOCKED
        if info.compress_type not in SUPPORTED_ZIP_COMPRESSION:
            reasons.append("ARCHIVE_COMPRESSION_METHOD_UNSUPPORTED")
            support = ArchiveMemberSupport.BLOCKED
        if not self._valid_extra_fields(info.extra):
            reasons.append("ARCHIVE_EXTRA_FIELD_INVALID")
            support = ArchiveMemberSupport.BLOCKED
        if normalized.extension in ARCHIVE_EXTENSIONS:
            reasons.append("ARCHIVE_NESTED_ARCHIVE")
            if support != ArchiveMemberSupport.BLOCKED:
                support = ArchiveMemberSupport.UNSUPPORTED

        media_type = SUPPORTED_MEDIA_TYPES.get(normalized.extension)
        if media_type is None and normalized.extension not in ARCHIVE_EXTENSIONS:
            reasons.append("ARCHIVE_MEMBER_MEDIA_UNSUPPORTED")
            if support != ArchiveMemberSupport.BLOCKED:
                support = ArchiveMemberSupport.UNSUPPORTED
        if info.file_size > self._policy.max_member_uncompressed_bytes:
            reasons.append("ARCHIVE_MEMBER_UNCOMPRESSED_LIMIT_EXCEEDED")
            support = ArchiveMemberSupport.BLOCKED
        ratio = self._compression_ratio(info)
        if ratio > self._policy.max_compression_ratio:
            reasons.append("ARCHIVE_MEMBER_COMPRESSION_RATIO_EXCEEDED")
            support = ArchiveMemberSupport.BLOCKED

        checksum: str | None = None
        checksum_status = ChecksumStatus.NOT_REQUESTED
        crc_status = CrcValidationStatus.NOT_PERFORMED
        if (
            mode == ArchiveInspectionMode.FULL_CHECKSUM
            and support == ArchiveMemberSupport.SUPPORTED
        ):
            try:
                checksum = self._stream_member_sha256(archive, info)
                checksum_status = ChecksumStatus.VERIFIED
                crc_status = CrcValidationStatus.VERIFIED
            except (OSError, EOFError, RuntimeError, zipfile.BadZipFile):
                reasons.append("ARCHIVE_MEMBER_CRC_OR_READ_FAILED")
                support = ArchiveMemberSupport.BLOCKED
                checksum_status = ChecksumStatus.FAILED
                crc_status = CrcValidationStatus.FAILED

        return ArchiveMemberInspection(
            member_logical_id=self._member_logical_id(
                source.candidate_id,
                source.archive_logical_id,
                normalized.logical_identity,
            ),
            normalized_relative_identity=normalized.logical_identity,
            extension=normalized.extension,
            media_type=media_type,
            compressed_size=info.compress_size,
            uncompressed_size=info.file_size,
            crc32=f"{info.CRC:08x}",
            checksum_status=checksum_status,
            content_sha256=checksum,
            crc_validation_status=crc_status,
            provenance_identity=self._provenance_identity(source, normalized),
            support_status=support,
            blocking_reasons=tuple(dict.fromkeys(reasons)),
        )

    def _normalize_member_name(
        self, name: str, *, archive_logical_id: str
    ) -> _NormalizedMemberName:
        opaque_invalid = f"invalid-member/{self._opaque_digest(archive_logical_id, name)}"
        extension = PurePosixPath(
            unicodedata.normalize("NFKC", name).replace("\\", "/")
        ).suffix.casefold()
        if not name or "\x00" in name:
            return _NormalizedMemberName(
                None, opaque_invalid, extension, "ARCHIVE_MEMBER_PATH_UNSAFE"
            )

        decoded = name
        for _ in range(3):
            next_value = unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        candidates = (name, decoded)
        for candidate in candidates:
            normalized = unicodedata.normalize("NFKC", candidate).replace("\\", "/")
            if (
                normalized.startswith(("/", "//"))
                or WINDOWS_DRIVE_PATH.match(normalized)
                or any(part == ".." for part in normalized.split("/"))
                or any(":" in part for part in normalized.split("/"))
            ):
                return _NormalizedMemberName(
                    None, opaque_invalid, extension, "ARCHIVE_MEMBER_PATH_UNSAFE"
                )

        normalized = unicodedata.normalize("NFKC", name).replace("\\", "/")
        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        if not parts:
            return _NormalizedMemberName(
                None, opaque_invalid, extension, "ARCHIVE_MEMBER_PATH_UNSAFE"
            )
        canonical = "/".join(parts)
        collision_key = canonical.casefold()
        extension = PurePosixPath(canonical).suffix.casefold()
        logical_identity = f"member/{self._opaque_digest(archive_logical_id, collision_key)}"
        return _NormalizedMemberName(collision_key, logical_identity, extension, None)

    @staticmethod
    def _compression_ratio(info: zipfile.ZipInfo) -> float:
        if info.file_size == 0:
            return 0.0
        if info.compress_size == 0:
            return math.inf
        return info.file_size / info.compress_size

    @staticmethod
    def _valid_extra_fields(extra: bytes) -> bool:
        offset = 0
        tags: set[int] = set()
        while offset < len(extra):
            if len(extra) - offset < 4:
                return False
            tag = int.from_bytes(extra[offset : offset + 2], "little")
            size = int.from_bytes(extra[offset + 2 : offset + 4], "little")
            if tag in tags or offset + 4 + size > len(extra):
                return False
            tags.add(tag)
            offset += 4 + size
        return True

    def _stream_file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(self._policy.stream_chunk_bytes):
                digest.update(chunk)
        return digest.hexdigest()

    def _stream_member_sha256(self, archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
        digest = hashlib.sha256()
        with archive.open(info, mode="r") as stream:
            while chunk := stream.read(self._policy.stream_chunk_bytes):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _metadata_fingerprint(
        archive_logical_id: str,
        archive_size: int,
        directories: int,
        members: list[ArchiveMemberInspection],
    ) -> str:
        digest = hashlib.sha256()
        digest.update(f"{archive_logical_id}:{archive_size}:{directories}".encode())
        for member in sorted(members, key=lambda item: item.member_logical_id):
            digest.update(
                (
                    f"{member.member_logical_id}:{member.compressed_size}:"
                    f"{member.uncompressed_size}:{member.crc32}:{member.extension}"
                ).encode()
            )
        return digest.hexdigest()

    @staticmethod
    def _member_logical_id(candidate_id: str, archive_id: str, identity: str) -> str:
        digest = ZipArchiveInspector._opaque_digest(candidate_id, archive_id, identity)
        return f"archive-member/{digest}"

    @staticmethod
    def _provenance_identity(source: ArchiveSource, normalized: _NormalizedMemberName) -> str:
        digest = ZipArchiveInspector._opaque_digest(
            source.candidate_id,
            source.archive_logical_id,
            normalized.logical_identity,
        )
        return f"archive-provenance/{digest}"

    @staticmethod
    def _opaque_digest(*parts: str) -> str:
        return hashlib.sha256(
            "\x1f".join(parts).encode("utf-8", errors="surrogatepass")
        ).hexdigest()

    @staticmethod
    def _archive_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError as exc:
            raise ContractError(
                "ARCHIVE_SOURCE_READ_FAILED", "Archive source cannot be read."
            ) from exc

    @staticmethod
    def _validate_source(source: ArchiveSource) -> None:
        assert_safe_metadata(
            {
                "candidate_id": source.candidate_id,
                "archive_logical_id": source.archive_logical_id,
            }
        )
        if source.path.suffix.casefold() != ".zip":
            raise ContractError("ARCHIVE_FORMAT_UNSUPPORTED", "Only ZIP inspection is supported.")

    @staticmethod
    def _failed_result(
        *,
        source: ArchiveSource,
        archive_size: int,
        archive_checksum: str | None,
        mode: ArchiveInspectionMode,
    ) -> ArchiveInspectionResult:
        fingerprint = hashlib.sha256(
            f"{source.archive_logical_id}:{archive_size}:failed".encode()
        ).hexdigest()
        return ArchiveInspectionResult(
            candidate_id=source.candidate_id,
            archive_logical_id=source.archive_logical_id,
            archive_metadata_fingerprint=fingerprint,
            archive_checksum=archive_checksum,
            archive_checksum_status=(
                ChecksumStatus.VERIFIED
                if archive_checksum is not None
                else ChecksumStatus.NOT_REQUESTED
            ),
            archive_size_bytes=archive_size,
            archive_format="zip",
            member_count=0,
            directory_entry_count=0,
            supported_member_count=0,
            unsupported_member_count=0,
            encrypted_member_count=0,
            nested_archive_count=0,
            unsafe_member_count=0,
            total_compressed_bytes=0,
            total_uncompressed_bytes=0,
            inspection_mode=mode,
            inspection_status=ArchiveInspectionStatus.FAILED,
            inspection_complete=False,
            membership_known=False,
            path_safety_pass=False,
            blocking_reasons=("ARCHIVE_CENTRAL_DIRECTORY_UNREADABLE",),
            members=(),
        )


def archive_inspections_to_inventory(
    inspections: Iterable[ArchiveInspectionResult],
    *,
    authority_id: str,
    candidate_id: str,
    source_alias: str,
    purpose: str = "archive-membership-enrollment-candidate",
) -> DatasetInventory:
    """Map complete archive membership to the existing Dataset inventory contract."""

    ordered = tuple(sorted(inspections, key=lambda item: item.archive_logical_id))
    if not ordered:
        raise ContractError("ARCHIVE_INSPECTION_MISSING", "Archive inspection is required.")
    if any(item.candidate_id != candidate_id for item in ordered):
        raise ContractError(
            "ARCHIVE_CANDIDATE_MISMATCH", "Archive inspections cannot cross candidate scopes."
        )
    archive_ids = [item.archive_logical_id for item in ordered]
    if len(archive_ids) != len(set(archive_ids)):
        raise ContractError(
            "ARCHIVE_SET_DUPLICATE_IDENTITY",
            "Duplicate archive identities cannot become Dataset membership.",
        )
    if any(
        not item.inspection_complete or item.inspection_status != ArchiveInspectionStatus.COMPLETE
        for item in ordered
    ):
        raise ContractError(
            "ARCHIVE_INSPECTION_INCOMPLETE",
            "Partial or blocked archive inspection cannot become Dataset membership.",
        )
    archive_checksums = [item.archive_checksum for item in ordered if item.archive_checksum]
    if len(archive_checksums) != len(set(archive_checksums)):
        raise ContractError(
            "ARCHIVE_SET_DUPLICATE_CHECKSUM",
            "Duplicate archive content cannot become Dataset membership.",
        )

    members = tuple(member for item in ordered for member in item.members)
    supported = tuple(
        member for member in members if member.support_status == ArchiveMemberSupport.SUPPORTED
    )
    checksums = [member.content_sha256 for member in supported if member.content_sha256]
    duplicate_checksums = len(checksums) - len(set(checksums))
    duplicate_identities = len(members) - len(
        {member.normalized_relative_identity for member in members}
    )
    unsupported_extensions = tuple(
        sorted(
            {
                member.extension or "<none>"
                for member in members
                if member.support_status != ArchiveMemberSupport.SUPPORTED
            }
        )
    )
    return DatasetInventory(
        authority_id=authority_id,
        candidate_id=candidate_id,
        source_alias=source_alias,
        purpose=purpose,
        discovered_file_count=len(members),
        supported_item_count=len(supported),
        unsupported_file_count=len(members) - len(supported),
        total_size_bytes=sum(member.uncompressed_size for member in members),
        unsupported_extensions=unsupported_extensions,
        duplicate_relative_identity_count=duplicate_identities,
        duplicate_checksum_count=duplicate_checksums,
        missing_checksum_count=sum(member.content_sha256 is None for member in supported),
        items=tuple(
            InventoryItem(
                sample_id=member.member_logical_id,
                source_key=member.normalized_relative_identity,
                media_type=member.media_type or "application/octet-stream",
                size_bytes=member.uncompressed_size,
                checksum=member.content_sha256,
                provenance=member.provenance_identity,
            )
            for member in supported
        ),
    )


def inspect_archive_set_summary(
    inspector: ArchiveInspector,
    sources: Iterable[ArchiveSource],
    *,
    candidate_id: str,
    mode: ArchiveInspectionMode = ArchiveInspectionMode.DISCOVERY,
    expected_archive_ids: frozenset[str] | None = None,
) -> ArchiveSetInspectionSummary:
    """Inspect one archive at a time and retain only safe aggregate counters."""

    ordered = tuple(sorted(sources, key=lambda item: item.archive_logical_id))
    reasons: list[str] = []
    identities = [source.archive_logical_id for source in ordered]
    if any(source.candidate_id != candidate_id for source in ordered):
        reasons.append("ARCHIVE_SET_CANDIDATE_MISMATCH")
    if len(identities) != len(set(identities)):
        reasons.append("ARCHIVE_SET_DUPLICATE_IDENTITY")
    if expected_archive_ids is not None and set(identities) != expected_archive_ids:
        reasons.append("ARCHIVE_SET_EXPECTED_IDENTITY_MISMATCH")

    counters = {
        "inspected": 0,
        "bytes": 0,
        "members": 0,
        "supported": 0,
        "unsupported": 0,
        "encrypted": 0,
        "nested": 0,
        "unsafe": 0,
        "corrupt": 0,
    }
    checksums: list[str] = []
    extensions: Counter[str] = Counter()
    media_types: Counter[str] = Counter()
    all_complete = bool(ordered)
    all_membership_known = bool(ordered)
    all_paths_safe = bool(ordered)
    for source in ordered:
        result = inspector.inspect(source, mode=mode)
        counters["bytes"] += result.archive_size_bytes
        counters["members"] += result.member_count
        counters["supported"] += result.supported_member_count
        counters["unsupported"] += result.unsupported_member_count
        counters["encrypted"] += result.encrypted_member_count
        counters["nested"] += result.nested_archive_count
        counters["unsafe"] += result.unsafe_member_count
        if result.inspection_status == ArchiveInspectionStatus.FAILED:
            counters["corrupt"] += 1
        else:
            counters["inspected"] += 1
        all_complete = all_complete and result.inspection_complete
        all_membership_known = all_membership_known and result.membership_known
        all_paths_safe = all_paths_safe and result.path_safety_pass
        reasons.extend(result.blocking_reasons)
        extensions.update(member.extension or "<none>" for member in result.members)
        media_types.update(member.media_type or "unsupported" for member in result.members)
        if result.archive_checksum is not None:
            checksums.append(result.archive_checksum)

    if len(checksums) != len(set(checksums)):
        reasons.append("ARCHIVE_SET_DUPLICATE_CHECKSUM")
    reasons = list(dict.fromkeys(reasons))
    return ArchiveSetInspectionSummary(
        candidate_id=candidate_id,
        archive_count=len(ordered),
        inspected_archive_count=counters["inspected"],
        aggregate_archive_bytes=counters["bytes"],
        member_count=counters["members"],
        supported_member_count=counters["supported"],
        unsupported_member_count=counters["unsupported"],
        encrypted_member_count=counters["encrypted"],
        nested_archive_count=counters["nested"],
        unsafe_member_count=counters["unsafe"],
        corrupt_archive_count=counters["corrupt"],
        extension_counts=dict(sorted(extensions.items())),
        media_type_counts=dict(sorted(media_types.items())),
        archive_inspection_complete=all_complete,
        archive_membership_known=all_membership_known,
        archive_path_safety_pass=all_paths_safe,
        blocking_reasons=tuple(reasons),
    )
