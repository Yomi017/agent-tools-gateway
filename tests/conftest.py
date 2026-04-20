from __future__ import annotations

from pathlib import Path

import pytest

from toolhub.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    convertx_work_root = tmp_path / "tools" / "ConvertX" / "work"
    input_root = convertx_work_root / "input"
    output_root = convertx_work_root / "output"
    temp_root = convertx_work_root / "tmp"
    docling_work_root = tmp_path / "tools" / "Docling" / "work"
    docling_input_root = docling_work_root / "input"
    docling_output_root = docling_work_root / "output"
    docling_temp_root = docling_work_root / "tmp"
    webcapture_work_root = tmp_path / "tools" / "WebCapture" / "work"
    webcapture_output_root = webcapture_work_root / "output"
    webcapture_temp_root = webcapture_work_root / "tmp"
    input_root.mkdir(parents=True)
    output_root.mkdir(parents=True)
    temp_root.mkdir(parents=True)
    docling_input_root.mkdir(parents=True)
    docling_output_root.mkdir(parents=True)
    docling_temp_root.mkdir(parents=True)
    webcapture_output_root.mkdir(parents=True)
    webcapture_temp_root.mkdir(parents=True)
    return Settings(
        backends={
            "convertx": {
                "base_url": "http://convertx.test",
                "work_root": convertx_work_root,
                "allowed_input_roots": [input_root],
                "allowed_output_roots": [output_root],
                "temp_root": temp_root,
            },
            "docling": {
                "enabled": False,
                "base_url": "http://docling.test",
                "api_key": "docling-token",
                "work_root": docling_work_root,
                "allowed_input_roots": [docling_input_root],
                "allowed_output_roots": [docling_output_root],
                "temp_root": docling_temp_root,
            },
            "webcapture": {
                "enabled": False,
                "base_url": "http://browserless.test",
                "token": "browserless-token",
                "work_root": webcapture_work_root,
                "allowed_output_roots": [webcapture_output_root],
                "temp_root": webcapture_temp_root,
            },
        },
        poll_interval_seconds=0.001,
        conversion_timeout_seconds=0.1,
    )


@pytest.fixture
def docling_settings(settings: Settings) -> Settings:
    convertx = settings.convertx()
    docling = settings.docling()
    return Settings(
        backends={
            "convertx": {
                "base_url": convertx.base_url,
                "work_root": convertx.work_root,
                "allowed_input_roots": convertx.allowed_input_roots,
                "allowed_output_roots": convertx.allowed_output_roots,
                "temp_root": convertx.temp_root,
            },
            "docling": {
                "enabled": True,
                "base_url": docling.base_url,
                "api_key": docling.api_key,
                "work_root": docling.work_root,
                "allowed_input_roots": docling.allowed_input_roots,
                "allowed_output_roots": docling.allowed_output_roots,
                "temp_root": docling.temp_root,
            },
        },
        request_timeout_seconds=settings.request_timeout_seconds,
        connect_timeout_seconds=settings.connect_timeout_seconds,
        poll_interval_seconds=settings.poll_interval_seconds,
        conversion_timeout_seconds=settings.conversion_timeout_seconds,
        max_file_bytes=settings.max_file_bytes,
    )


@pytest.fixture
def webcapture_settings(settings: Settings) -> Settings:
    convertx = settings.convertx()
    webcapture = settings.webcapture()
    return Settings(
        backends={
            "convertx": {
                "base_url": convertx.base_url,
                "work_root": convertx.work_root,
                "allowed_input_roots": convertx.allowed_input_roots,
                "allowed_output_roots": convertx.allowed_output_roots,
                "temp_root": convertx.temp_root,
            },
            "docling": {
                "base_url": settings.docling().base_url,
                "api_key": settings.docling().api_key,
                "work_root": settings.docling().work_root,
                "allowed_input_roots": settings.docling().allowed_input_roots,
                "allowed_output_roots": settings.docling().allowed_output_roots,
                "temp_root": settings.docling().temp_root,
            },
            "webcapture": {
                "enabled": True,
                "base_url": webcapture.base_url,
                "token": webcapture.token,
                "work_root": webcapture.work_root,
                "allowed_output_roots": webcapture.allowed_output_roots,
                "temp_root": webcapture.temp_root,
            },
        },
        request_timeout_seconds=settings.request_timeout_seconds,
        connect_timeout_seconds=settings.connect_timeout_seconds,
        poll_interval_seconds=settings.poll_interval_seconds,
        conversion_timeout_seconds=settings.conversion_timeout_seconds,
        max_file_bytes=settings.max_file_bytes,
    )
