"""Internal Artifact resolution boundary with no path-bearing public contract."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from dohaaudio.errors import ConflictError, NotFoundError


@dataclass(frozen=True)
class ResolvedArtifact:
    artifact_id: str
    storage_reference: str


class ArtifactResolver(Protocol):
    def resolve(self, artifact_id: str) -> ResolvedArtifact: ...


class InMemoryArtifactResolver:
    """Test/foundation resolver; storage_reference never crosses the API boundary."""

    def __init__(self) -> None:
        self._references: dict[str, str] = {}
        self._lock = RLock()

    def register(self, artifact_id: str, storage_reference: str) -> None:
        with self._lock:
            existing = self._references.get(artifact_id)
            if existing is not None and existing != storage_reference:
                raise ConflictError(
                    "ARTIFACT_RESOLUTION_CONFLICT",
                    "Artifact storage reference를 제자리에서 변경할 수 없습니다.",
                )
            self._references[artifact_id] = storage_reference

    def resolve(self, artifact_id: str) -> ResolvedArtifact:
        with self._lock:
            try:
                return ResolvedArtifact(artifact_id, self._references[artifact_id])
            except KeyError as exc:
                raise NotFoundError("Artifact storage reference") from exc
