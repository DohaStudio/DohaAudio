from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from dohaaudio.admission import DatasetAuthorityResolver
from dohaaudio.errors import ContractError


@pytest.fixture
def authority_root() -> Path:
    sandbox = Path("tmp") / "pytest-authority" / uuid4().hex
    root = sandbox / "authority"
    root.mkdir(parents=True)
    yield root
    shutil.rmtree(sandbox)


def test_configured_authority_inventory_is_deterministic_and_path_free(
    authority_root: Path,
) -> None:
    scope = authority_root / "candidate"
    scope.mkdir()
    (scope / "b.wav").write_bytes(b"wave-b")
    (scope / "a.mp3").write_bytes(b"mpeg-a")
    (scope / "notes.txt").write_text("metadata", encoding="utf-8")
    resolver = DatasetAuthorityResolver()
    authority = resolver.from_environment({"DOHAAUDIO_DATASET_ROOT": str(authority_root)})

    first = resolver.inventory(
        authority,
        "candidate",
        candidate_id="candidate-a",
        source_alias="local-authority/candidate-a",
        purpose="admission",
        include_checksums=True,
    )
    second = resolver.inventory(
        authority,
        "candidate",
        candidate_id="candidate-a",
        source_alias="local-authority/candidate-a",
        purpose="admission",
        include_checksums=True,
    )

    assert first == second
    assert first.discovered_file_count == 3
    assert first.supported_item_count == 2
    assert first.unsupported_extensions == (".txt",)
    assert first.missing_checksum_count == 0
    assert str(authority_root) not in first.model_dump_json()
    assert all("/" not in item.source_key and "\\" not in item.source_key for item in first.items)


def test_inventory_detects_duplicate_checksum_and_missing_checksum(
    authority_root: Path,
) -> None:
    scope = authority_root / "candidate"
    scope.mkdir()
    (scope / "first.wav").write_bytes(b"same")
    (scope / "second.wav").write_bytes(b"same")
    resolver = DatasetAuthorityResolver()
    authority = resolver.resolve(authority_root)

    without_hashes = resolver.inventory(
        authority,
        "candidate",
        candidate_id="candidate-a",
        source_alias="local-authority/candidate-a",
        purpose="admission",
    )
    with_hashes = resolver.inventory(
        authority,
        "candidate",
        candidate_id="candidate-a",
        source_alias="local-authority/candidate-a",
        purpose="admission",
        include_checksums=True,
    )

    assert without_hashes.missing_checksum_count == 2
    assert with_hashes.missing_checksum_count == 0
    assert with_hashes.duplicate_checksum_count == 1


def test_inventory_is_read_only(authority_root: Path) -> None:
    scope = authority_root / "candidate"
    scope.mkdir()
    sample = scope / "sample.wav"
    sample.write_bytes(b"immutable")
    before = (sample.read_bytes(), sample.stat().st_mtime_ns)
    resolver = DatasetAuthorityResolver()
    authority = resolver.resolve(authority_root)
    resolver.inventory(
        authority,
        "candidate",
        candidate_id="candidate-a",
        source_alias="local-authority/candidate-a",
        purpose="admission",
        include_checksums=True,
    )
    assert (sample.read_bytes(), sample.stat().st_mtime_ns) == before


def test_authority_resolver_rejects_missing_and_non_directory_roots(
    authority_root: Path,
) -> None:
    resolver = DatasetAuthorityResolver()
    with pytest.raises(ContractError) as missing_configuration:
        resolver.from_environment({})
    assert missing_configuration.value.error_code == "DATASET_AUTHORITY_ROOT_MISSING"
    with pytest.raises(ContractError) as missing:
        resolver.resolve(authority_root / "missing")
    assert missing.value.error_code == "DATASET_AUTHORITY_ROOT_MISSING"
    file_root = authority_root / "file-root"
    file_root.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ContractError) as not_directory:
        resolver.resolve(file_root)
    assert not_directory.value.error_code == "DATASET_AUTHORITY_ROOT_NOT_DIRECTORY"


@pytest.mark.parametrize("scope", ["../escape", "..\\escape"])
def test_authority_resolver_rejects_path_traversal(authority_root: Path, scope: str) -> None:
    resolver = DatasetAuthorityResolver()
    authority = resolver.resolve(authority_root)
    with pytest.raises(ContractError) as exc_info:
        resolver.inventory(
            authority,
            scope,
            candidate_id="candidate-a",
            source_alias="local-authority/candidate-a",
            purpose="admission",
        )
    assert exc_info.value.error_code == "DATASET_AUTHORITY_ROOT_ESCAPE"


def test_authority_resolver_rejects_symlink_or_junction_escape(
    authority_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = authority_root / "candidate"
    outside = authority_root.parent / "outside"
    scope.mkdir()
    outside.mkdir()
    link = scope / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        link.mkdir()
    resolver = DatasetAuthorityResolver()
    if not link.is_symlink():
        original = resolver._is_reparse_point
        monkeypatch.setattr(
            resolver,
            "_is_reparse_point",
            lambda path: path.name == "escape" or original(path),
        )
    authority = resolver.resolve(authority_root)
    with pytest.raises(ContractError) as exc_info:
        resolver.inventory(
            authority,
            "candidate",
            candidate_id="candidate-a",
            source_alias="local-authority/candidate-a",
            purpose="admission",
        )
    assert exc_info.value.error_code == "DATASET_AUTHORITY_ROOT_ESCAPE"
