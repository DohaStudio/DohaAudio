"""Model Manifest loading boundary."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Protocol

from dohaaudio.contracts import ModelManifest


class ModelManifestLoader(Protocol):
    def load_mapping(self, payload: dict[str, Any]) -> ModelManifest: ...


class JsonModelManifestLoader:
    def load_mapping(self, payload: dict[str, Any]) -> ModelManifest:
        return ModelManifest.model_validate(payload)

    def load_json(self, payload: str) -> ModelManifest:
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise ValueError("Model Manifest JSON root must be an object")
        return self.load_mapping(parsed)

    def load_package_fixture(self, name: str) -> ModelManifest:
        fixture = resources.files("dohaaudio.fixtures").joinpath(name)
        return self.load_json(fixture.read_text(encoding="utf-8"))
