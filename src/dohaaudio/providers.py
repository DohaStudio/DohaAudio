"""Capability interface and deterministic fake provider."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from dohaaudio.contracts import (
    PROVIDER_ID,
    ArtifactMetadata,
    Capability,
    JobRecord,
    ModelManifest,
    RetentionStatus,
)
from dohaaudio.errors import ContractError, NotFoundError
from dohaaudio.manifests import JsonModelManifestLoader

FAKE_MANIFEST_ID = "fake/audio/runtime-foundation-manifest/v1"


@dataclass(frozen=True)
class ProviderExecution:
    artifacts: tuple[ArtifactMetadata, ...]
    result_metadata: dict[str, Any]


class AudioProvider(ABC):
    provider_id: str

    @abstractmethod
    def capabilities(self) -> tuple[Capability, ...]: ...

    @abstractmethod
    def input_formats(self) -> tuple[str, ...]: ...

    @abstractmethod
    def output_formats(self) -> tuple[str, ...]: ...

    @abstractmethod
    def health(self) -> bool: ...

    @abstractmethod
    def readiness(self) -> bool: ...

    @abstractmethod
    def execute(self, job: JobRecord) -> ProviderExecution: ...


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AudioProvider] = {}

    def register(self, provider: AudioProvider) -> None:
        if provider.provider_id in self._providers:
            raise ContractError(
                "PROVIDER_CONFLICT", "Provider ID가 중복되었습니다.", status_code=409
            )
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> AudioProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise NotFoundError("Provider") from exc


class CapabilityRegistry:
    def __init__(self, provider_registry: ProviderRegistry) -> None:
        self._providers = provider_registry

    def supports(self, provider_id: str, capability: Capability) -> bool:
        return capability in self._providers.get(provider_id).capabilities()


class FakeAudioProvider(AudioProvider):
    """A deterministic contract fixture. It does not load or invoke an AI model."""

    provider_id = PROVIDER_ID

    def __init__(self, *, healthy: bool = True, ready: bool = True) -> None:
        self._healthy = healthy
        self._ready = ready

    def capabilities(self) -> tuple[Capability, ...]:
        return tuple(Capability)

    def input_formats(self) -> tuple[str, ...]:
        return ("application/json", "audio/wav")

    def output_formats(self) -> tuple[str, ...]:
        return ("application/json", "audio/wav")

    def health(self) -> bool:
        return self._healthy

    def readiness(self) -> bool:
        return self._healthy and self._ready

    def execute(self, job: JobRecord) -> ProviderExecution:
        if not self.readiness():
            raise ContractError(
                "PROVIDER_NOT_READY",
                "Provider가 새 Job을 수락할 준비가 되지 않았습니다.",
                status_code=503,
            )
        if job.capability == Capability.MUSIC_GENERATION:
            return self._music_generation(job)
        if job.capability == Capability.STEM_SEPARATION:
            return self._stem_separation(job)
        if job.capability == Capability.AUDIO_ANALYSIS:
            return self._audio_analysis(job)
        raise ContractError("CAPABILITY_UNSUPPORTED", "지원하지 않는 capability입니다.")

    def _music_generation(self, job: JobRecord) -> ProviderExecution:
        artifact = self._artifact(job, "generation", "audio", "audio/wav")
        return ProviderExecution((artifact,), {"fixture": "fake_music_generation_v1"})

    def _stem_separation(self, job: JobRecord) -> ProviderExecution:
        vocals = self._artifact(job, "vocals", "stem", "audio/wav")
        instrumental = self._artifact(job, "instrumental", "stem", "audio/wav")
        return ProviderExecution(
            (vocals, instrumental),
            {"fixture": "fake_stem_separation_v1", "stems": ["vocals", "instrumental"]},
        )

    def _audio_analysis(self, job: JobRecord) -> ProviderExecution:
        analysis = {
            "fixture": "fake_audio_analysis_v1",
            "bpm": 120,
            "key": "C_MAJOR",
            "structure": ["intro", "verse", "chorus", "outro"],
            "quality_metadata": {"status": "test_fixture", "score": None},
        }
        serialized = json.dumps(analysis, sort_keys=True, separators=(",", ":")).encode()
        artifact = self._artifact(
            job,
            "analysis",
            "analysis",
            "application/json",
            payload=serialized,
        )
        return ProviderExecution((artifact,), analysis)

    def _artifact(
        self,
        job: JobRecord,
        name: str,
        kind: str,
        media_type: str,
        *,
        payload: bytes | None = None,
    ) -> ArtifactMetadata:
        content = payload or f"fake:{job.request_fingerprint}:{name}".encode()
        checksum = hashlib.sha256(content).hexdigest()
        artifact_id = f"fake/audio/{job.request_fingerprint[:20]}/{name}"
        return ArtifactMetadata(
            artifact_id=artifact_id,
            artifact_kind=kind,
            media_type=media_type,
            size_bytes=len(content),
            checksum_algorithm="sha256",
            artifact_checksum=checksum,
            producer_type="provider",
            producer_id=self.provider_id,
            run_id=job.job_id,
            created_at=job.created_at,
            retention_status=RetentionStatus.ACTIVE,
            logical_uri=f"artifact://audio/{artifact_id}",
            source_artifact_ids=job.input_artifact_ids,
        )


def fake_model_manifest() -> ModelManifest:
    return JsonModelManifestLoader().load_package_fixture("fake-model-manifest.json")
