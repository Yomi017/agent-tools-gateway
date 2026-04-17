from __future__ import annotations

from pathlib import Path

import pytest

from toolhub.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    work_root = tmp_path / "tools" / "ConvertX" / "work"
    input_root = work_root / "input"
    output_root = work_root / "output"
    temp_root = work_root / "tmp"
    input_root.mkdir(parents=True)
    output_root.mkdir(parents=True)
    temp_root.mkdir(parents=True)
    return Settings(
        backends={
            "convertx": {
                "base_url": "http://convertx.test",
                "work_root": work_root,
                "allowed_input_roots": [input_root],
                "allowed_output_roots": [output_root],
                "temp_root": temp_root,
            }
        },
        poll_interval_seconds=0.001,
        conversion_timeout_seconds=0.1,
    )
