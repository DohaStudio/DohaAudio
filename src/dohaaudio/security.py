"""Shared metadata guard for path and secret-free public contracts."""

from __future__ import annotations

import re
from typing import Any

from dohaaudio.errors import ContractError

WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
SENSITIVE_SETTING_KEYS = frozenset(
    {"api_key", "apikey", "authorization", "credential", "password", "secret", "token"}
)
SENSITIVE_SETTING_SUFFIXES = ("_api_key", "_credential", "_password", "_secret", "_token")


def _is_sensitive_setting_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    return normalized in SENSITIVE_SETTING_KEYS or normalized.endswith(SENSITIVE_SETTING_SUFFIXES)


def assert_safe_metadata(value: Any, *, key: str | None = None) -> None:
    if key is not None and _is_sensitive_setting_key(key):
        raise ContractError("UNSAFE_REQUEST_METADATA", "비밀정보 필드는 요청할 수 없습니다.")
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            assert_safe_metadata(child_value, key=str(child_key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            assert_safe_metadata(child)
    elif isinstance(value, str) and (
        WINDOWS_ABSOLUTE_PATH.match(value)
        or value.startswith(("/", "~/", "~\\", "\\\\"))
        or value.casefold().startswith("file:")
    ):
        raise ContractError(
            "ABSOLUTE_PATH_FORBIDDEN", "절대 경로는 공개 계약에 사용할 수 없습니다."
        )
