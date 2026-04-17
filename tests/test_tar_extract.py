from __future__ import annotations

import io
import tarfile

import pytest

from toolhub.errors import UnsafeArchiveError
from toolhub.security import PathPolicy, safe_extract_tar_bytes


def _tar_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def test_safe_extract_tar(settings) -> None:
    policy = PathPolicy(settings.convertx())
    output_dir = policy.validate_output_dir(None)
    outputs = safe_extract_tar_bytes(
        _tar_bytes({"converted.jpg": b"image"}),
        output_dir,
        policy,
    )

    assert outputs[0].filename == "converted.jpg"
    assert (output_dir / "converted.jpg").read_bytes() == b"image"


def test_safe_extract_rejects_parent_traversal(settings) -> None:
    policy = PathPolicy(settings.convertx())
    output_dir = policy.validate_output_dir(None)

    with pytest.raises(UnsafeArchiveError):
        safe_extract_tar_bytes(_tar_bytes({"../evil.txt": b"no"}), output_dir, policy)


def test_safe_extract_rejects_duplicate_member(settings) -> None:
    policy = PathPolicy(settings.convertx())
    output_dir = policy.validate_output_dir(None)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for content in [b"one", b"two"]:
            info = tarfile.TarInfo("same.txt")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

    with pytest.raises(UnsafeArchiveError):
        safe_extract_tar_bytes(buffer.getvalue(), output_dir, policy)


def test_safe_extract_rejects_existing_without_overwrite(settings) -> None:
    policy = PathPolicy(settings.convertx())
    output_dir = policy.validate_output_dir(None)
    (output_dir / "same.txt").write_text("old", encoding="utf-8")

    with pytest.raises(UnsafeArchiveError):
        safe_extract_tar_bytes(_tar_bytes({"same.txt": b"new"}), output_dir, policy)
