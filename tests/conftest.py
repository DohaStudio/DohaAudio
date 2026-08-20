from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from dohaaudio.bootstrap import AudioRuntime, bootstrap_runtime
from dohaaudio.contracts import Capability, CreateJobRequest
from dohaaudio.providers import FAKE_MANIFEST_ID


@pytest.fixture
def database_path() -> Path:
    root = Path("tmp") / "pytest-sqlite"
    root.mkdir(parents=True, exist_ok=True)
    database = root / f"{uuid4().hex}.sqlite3"
    yield database
    database.unlink(missing_ok=True)


@pytest.fixture
def runtime() -> AudioRuntime:
    return bootstrap_runtime()


@pytest.fixture
def make_request() -> Callable[..., CreateJobRequest]:
    def factory(**overrides: object) -> CreateJobRequest:
        values: dict[str, object] = {
            "job_id": "job_test_001",
            "provider_id": "audio",
            "capability": Capability.MUSIC_GENERATION,
            "api_contract_version": "1.0",
            "idempotency_key": "idem-test-001",
            "project_id": "project-test",
            "input_asset_version_ids": ("asset-version-test",),
            "input_artifact_ids": (),
            "model_manifest_id": FAKE_MANIFEST_ID,
            "settings_snapshot": {"seed": 1234, "duration_seconds": 10},
            "requested_by": "actor-test",
        }
        values.update(overrides)
        return CreateJobRequest(**values)

    return factory
