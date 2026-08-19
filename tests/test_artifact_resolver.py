from __future__ import annotations

import pytest

from dohaaudio.artifacts import InMemoryArtifactResolver
from dohaaudio.errors import ConflictError


def test_artifact_resolver_keeps_internal_reference_behind_identity_boundary() -> None:
    resolver = InMemoryArtifactResolver()
    resolver.register("artifact-test", "temporary-test-reference")
    resolved = resolver.resolve("artifact-test")
    assert resolved.artifact_id == "artifact-test"
    assert resolved.storage_reference == "temporary-test-reference"
    with pytest.raises(ConflictError):
        resolver.register("artifact-test", "different-reference")
