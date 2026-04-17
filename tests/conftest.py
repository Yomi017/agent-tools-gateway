from __future__ import annotations

from pathlib import Path

import pytest

from toolhub.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    temp_root = tmp_path / "tmp"
    input_root.mkdir()
    output_root.mkdir()
    temp_root.mkdir()
    return Settings(
        convertx_base_url="http://convertx.test",
        allowed_input_roots=[input_root],
        allowed_output_roots=[output_root],
        temp_root=temp_root,
        poll_interval_seconds=0.001,
        conversion_timeout_seconds=0.1,
    )
