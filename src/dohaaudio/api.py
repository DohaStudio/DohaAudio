"""FastAPI transport for the DohaMusic Provider REST mapping."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from dohaaudio.bootstrap import AudioRuntime, bootstrap_runtime
from dohaaudio.contracts import CreateJobRequest, RetryJobRequest
from dohaaudio.errors import ConflictError, ContractError


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or f"req_{uuid4().hex}"


def _envelope(data: Any, request: Request) -> dict[str, Any]:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return {"data": data, "request_id": _request_id(request)}


def create_app(runtime: AudioRuntime | None = None) -> FastAPI:
    app = FastAPI(
        title="DohaAudio Provider Runtime",
        version="0.1.0",
        description="Pre-training contract foundation backed by deterministic fake capabilities.",
    )
    app.state.runtime = runtime or bootstrap_runtime()

    @app.exception_handler(ContractError)
    async def contract_error_handler(request: Request, exc: ContractError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "retryable": exc.status_code >= 500,
                    "stage": "request",
                    "details_id": None,
                },
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, _: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "error_code": "REQUEST_VALIDATION_FAILED",
                    "message": "요청 payload가 Provider 계약과 일치하지 않습니다.",
                    "retryable": False,
                    "stage": "request_validation",
                    "details_id": None,
                },
                "request_id": _request_id(request),
            },
        )

    prefix = "/api/v1/providers/{provider_id}"

    @app.get(f"{prefix}/capabilities")
    def capabilities(provider_id: str, request: Request) -> dict[str, Any]:
        return _envelope(app.state.runtime.get_capabilities(provider_id), request)

    @app.post(f"{prefix}/jobs", status_code=202)
    def create_job(
        provider_id: str,
        payload: CreateJobRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if provider_id != payload.provider_id:
            raise ConflictError("PROVIDER_MISMATCH", "경로와 payload의 Provider가 다릅니다.")
        if idempotency_key is not None and idempotency_key != payload.idempotency_key:
            raise ConflictError(
                "IDEMPOTENCY_KEY_MISMATCH",
                "header와 payload의 idempotency key가 다릅니다.",
            )
        return _envelope(app.state.runtime.create_job(payload), request)

    @app.get(f"{prefix}/jobs/{{job_id}}")
    def get_job(provider_id: str, job_id: str, request: Request) -> dict[str, Any]:
        app.state.runtime.providers.get(provider_id)
        return _envelope(app.state.runtime.get_job(job_id), request)

    @app.post(f"{prefix}/jobs/{{job_id}}/cancel")
    def cancel_job(provider_id: str, job_id: str, request: Request) -> dict[str, Any]:
        app.state.runtime.providers.get(provider_id)
        return _envelope(app.state.runtime.cancel_job(job_id), request)

    @app.post(f"{prefix}/jobs/{{job_id}}/retry", status_code=202)
    def retry_job(
        provider_id: str,
        job_id: str,
        payload: RetryJobRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        app.state.runtime.providers.get(provider_id)
        if idempotency_key is not None and idempotency_key != payload.idempotency_key:
            raise ConflictError(
                "IDEMPOTENCY_KEY_MISMATCH",
                "header와 payload의 idempotency key가 다릅니다.",
            )
        return _envelope(app.state.runtime.retry_job(job_id, payload), request)

    @app.get(f"{prefix}/jobs/{{job_id}}/result")
    def get_result(provider_id: str, job_id: str, request: Request) -> dict[str, Any]:
        app.state.runtime.providers.get(provider_id)
        return _envelope(app.state.runtime.get_result(job_id), request)

    @app.get(f"{prefix}/model-manifests/{{manifest_id:path}}")
    def get_manifest(provider_id: str, manifest_id: str, request: Request) -> dict[str, Any]:
        app.state.runtime.providers.get(provider_id)
        return _envelope(app.state.runtime.get_manifest(manifest_id), request)

    @app.get(f"{prefix}/health")
    def health(provider_id: str, request: Request) -> dict[str, Any]:
        return _envelope(app.state.runtime.health(provider_id), request)

    @app.get(f"{prefix}/readiness")
    def readiness(provider_id: str, request: Request) -> dict[str, Any]:
        return _envelope(app.state.runtime.readiness(provider_id), request)

    return app


app = create_app()
