from __future__ import annotations

import os
from pathlib import Path

import pytest

from toolhub.errors import FileTooLargeError, PathNotAllowedError
from toolhub.security import PathPolicy


def test_input_file_allowed(settings) -> None:
    path = settings.allowed_input_roots[0] / "sample.txt"
    path.write_text("ok", encoding="utf-8")

    assert PathPolicy(settings).validate_input_file(path) == path.resolve()


def test_input_file_rejects_outside_root(settings, tmp_path: Path) -> None:
    path = tmp_path / "outside.txt"
    path.write_text("no", encoding="utf-8")

    with pytest.raises(PathNotAllowedError):
        PathPolicy(settings).validate_input_file(path)


def test_input_file_rejects_symlink_escape(settings, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    link = settings.allowed_input_roots[0] / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not supported on this filesystem")

    with pytest.raises(PathNotAllowedError):
        PathPolicy(settings).validate_input_file(link)


def test_output_dir_rejects_parent_escape(settings) -> None:
    escaped = settings.allowed_output_roots[0] / ".." / "elsewhere"

    with pytest.raises(PathNotAllowedError):
        PathPolicy(settings).validate_output_dir(escaped)


def test_input_file_size_limit(settings) -> None:
    path = settings.allowed_input_roots[0] / "large.bin"
    path.write_bytes(b"abcd")
    limited = settings.model_copy(update={"max_file_bytes": 3})

    with pytest.raises(FileTooLargeError):
        PathPolicy(limited).validate_input_file(path)
