"""Metadata-only future Evaluation linkage contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from dohaaudio.contracts import FrozenModel


class EvaluationRequest(FrozenModel):
    evaluation_request_id: str = Field(min_length=1)
    training_run_id: str = Field(min_length=1)
    model_manifest_id: str = Field(min_length=1)
    dataset_manifest_id: str = Field(min_length=1)
    evaluation_split: str = "test"
    created_at: datetime


class EvaluationResultMetadata(FrozenModel):
    evaluation_result_id: str = Field(min_length=1)
    evaluation_request_id: str = Field(min_length=1)
    training_run_id: str = Field(min_length=1)
    model_manifest_id: str = Field(min_length=1)
    dataset_manifest_id: str = Field(min_length=1)
    metrics_artifact_id: str | None = None
    completed_at: datetime | None = None
