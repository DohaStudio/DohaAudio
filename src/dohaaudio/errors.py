"""Safe errors exposed by the provider contract."""

from __future__ import annotations


class ContractError(Exception):
    """An expected contract failure with no private diagnostic payload."""

    def __init__(self, error_code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


class ConflictError(ContractError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(error_code, message, status_code=409)


class NotFoundError(ContractError):
    def __init__(self, resource: str) -> None:
        super().__init__(
            "RESOURCE_NOT_FOUND", f"{resource}을(를) 찾을 수 없습니다.", status_code=404
        )
