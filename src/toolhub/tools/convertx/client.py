from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

import httpx

from ...config import ConvertXRuntimeSettings
from ...errors import ConversionTimeoutError, FormatNotSupportedError, UpstreamError
from .models import TargetCandidate


def normalize_format(value: str) -> str:
    return value.strip().lower().lstrip(".")


class _TargetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.targets: list[TargetCandidate] = []
        self._optgroup: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value for key, value in attrs}
        if tag == "optgroup":
            self._optgroup = attr.get("label")
            return
        if tag == "button":
            target = attr.get("data-target")
            converter = attr.get("data-converter")
            value = attr.get("data-value")
            if target and converter:
                self.targets.append(
                    TargetCandidate(
                        target=target,
                        converter=converter,
                        value=value or f"{target},{converter}",
                    )
                )
            return
        if tag == "option" and self._optgroup:
            value = attr.get("value")
            if value and "," in value:
                target, converter = value.split(",", 1)
                self.targets.append(
                    TargetCandidate(target=target, converter=converter, value=value)
                )

    def handle_endtag(self, tag: str) -> None:
        if tag == "optgroup":
            self._optgroup = None


@dataclass(frozen=True)
class Progress:
    value: int
    maximum: int

    @property
    def done(self) -> bool:
        return self.maximum > 0 and self.value >= self.maximum


class _ProgressParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.progress: Progress | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "progress":
            return
        attr = {key: value for key, value in attrs}
        try:
            maximum = int(float(attr.get("max") or "0"))
            value = int(float(attr.get("value") or "0"))
        except ValueError:
            maximum = 0
            value = 0
        self.progress = Progress(value=value, maximum=maximum)


def parse_targets(html: str) -> list[TargetCandidate]:
    parser = _TargetParser()
    parser.feed(html)
    seen: set[tuple[str, str]] = set()
    targets: list[TargetCandidate] = []
    for candidate in parser.targets:
        key = (normalize_format(candidate.target), candidate.converter)
        if key in seen:
            continue
        seen.add(key)
        targets.append(candidate)
    return targets


def parse_progress(html: str) -> Progress:
    parser = _ProgressParser()
    parser.feed(html)
    return parser.progress or Progress(value=0, maximum=0)


def _job_id_from_location(location: str) -> str | None:
    match = re.search(r"/results/([^/?#]+)", location)
    return match.group(1) if match else None


class ConvertXClient:
    def __init__(
        self,
        settings: ConvertXRuntimeSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.settings.request_timeout_seconds,
            connect=self.settings.connect_timeout_seconds,
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.base_url.rstrip("/"),
            follow_redirects=False,
            timeout=self._timeout(),
            transport=self._transport,
        )

    async def health(self) -> dict[str, str | bool]:
        try:
            async with self._client() as client:
                response = await client.get("/healthcheck")
                reachable = response.status_code < 500
        except httpx.HTTPError as exc:
            return {
                "reachable": False,
                "base_url": self.settings.base_url,
                "error": str(exc),
            }
        return {"reachable": reachable, "base_url": self.settings.base_url}

    async def list_targets(self, input_format: str | None = None) -> list[TargetCandidate]:
        async with self._client() as client:
            root_html, _job_id = await self._open_job(client)
            if input_format:
                response = await client.post(
                    "/conversions",
                    json={"fileType": normalize_format(input_format)},
                    headers={"Accept": "text/html"},
                )
                self._raise_bad_response(response, "list conversion targets")
                return parse_targets(response.text)
            return parse_targets(root_html)

    async def convert_files(
        self,
        input_paths: Iterable[Path],
        *,
        output_format: str,
        converter: str | None = None,
    ) -> tuple[str, bytes, int]:
        paths = list(input_paths)
        if not paths:
            raise FormatNotSupportedError("No input files were provided.")

        input_formats = {normalize_format(path.suffix) for path in paths}
        if len(input_formats) != 1:
            raise FormatNotSupportedError(
                "ConvertX batch conversion requires all files to share one extension.",
                details={"input_formats": sorted(input_formats)},
            )
        input_format = next(iter(input_formats))

        start = time.perf_counter()
        async with self._client() as client:
            _root_html, job_id = await self._open_job(client)
            candidates = await self._targets_for_format(client, input_format)
            selected = self._select_target(
                candidates,
                output_format=output_format,
                converter=converter,
                input_format=input_format,
            )

            for path in paths:
                await self._upload_file(client, path)

            job_id = await self._submit_convert(
                client,
                job_id=job_id,
                file_names=[path.name for path in paths],
                selected=selected,
            )
            await self._wait_until_done(client, job_id)
            archive = await self._download_archive(client, job_id)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return job_id, archive, duration_ms

    async def _open_job(self, client: httpx.AsyncClient) -> tuple[str, str]:
        response = await client.get("/")
        self._raise_bad_response(response, "open ConvertX session")
        job_id = client.cookies.get("jobId")
        if not job_id:
            raise UpstreamError(
                "ConvertX did not set a jobId cookie.",
                details={"status_code": response.status_code},
            )
        return response.text, job_id

    async def _targets_for_format(
        self,
        client: httpx.AsyncClient,
        input_format: str,
    ) -> list[TargetCandidate]:
        response = await client.post(
            "/conversions",
            json={"fileType": normalize_format(input_format)},
            headers={"Accept": "text/html"},
        )
        self._raise_bad_response(response, "choose converter")
        return parse_targets(response.text)

    def _select_target(
        self,
        candidates: list[TargetCandidate],
        *,
        output_format: str,
        converter: str | None,
        input_format: str,
    ) -> TargetCandidate:
        wanted_format = normalize_format(output_format)
        wanted_converter = converter.lower() if converter else None
        matches = [
            item
            for item in candidates
            if normalize_format(item.target) == wanted_format
            and (wanted_converter is None or item.converter.lower() == wanted_converter)
        ]
        if matches:
            return matches[0]
        raise FormatNotSupportedError(
            f"ConvertX does not list a conversion from {input_format} to {wanted_format}.",
            details={
                "input_format": input_format,
                "output_format": wanted_format,
                "converter": converter,
                "available": [item.model_dump() for item in candidates],
            },
        )

    async def _upload_file(self, client: httpx.AsyncClient, path: Path) -> None:
        with path.open("rb") as handle:
            response = await client.post(
                "/upload",
                files={"file": (path.name, handle, "application/octet-stream")},
            )
        self._raise_bad_response(response, f"upload {path.name}")

    async def _submit_convert(
        self,
        client: httpx.AsyncClient,
        *,
        job_id: str,
        file_names: list[str],
        selected: TargetCandidate,
    ) -> str:
        response = await client.post(
            "/convert",
            data={
                "convert_to": selected.value,
                "file_names": json.dumps(file_names),
            },
        )
        if response.status_code not in {200, 302, 303}:
            self._raise_bad_response(response, "submit conversion")
        return _job_id_from_location(response.headers.get("location", "")) or job_id

    async def _wait_until_done(self, client: httpx.AsyncClient, job_id: str) -> None:
        deadline = time.monotonic() + self.settings.conversion_timeout_seconds
        while time.monotonic() < deadline:
            response = await client.post(f"/progress/{job_id}")
            self._raise_bad_response(response, "poll conversion progress")
            progress = parse_progress(response.text)
            if progress.done:
                return
            await asyncio.sleep(self.settings.poll_interval_seconds)
        raise ConversionTimeoutError(
            "ConvertX job did not finish before timeout.",
            details={"job_id": job_id, "timeout_seconds": self.settings.conversion_timeout_seconds},
        )

    async def _download_archive(self, client: httpx.AsyncClient, job_id: str) -> bytes:
        response = await client.get(f"/archive/{job_id}")
        self._raise_bad_response(response, "download converted archive")
        if not response.content:
            raise UpstreamError(
                "ConvertX returned an empty archive.",
                details={"job_id": job_id},
            )
        return response.content

    @staticmethod
    def _raise_bad_response(response: httpx.Response, action: str) -> None:
        if response.status_code < 400:
            return
        raise UpstreamError(
            f"ConvertX failed to {action}.",
            details={
                "status_code": response.status_code,
                "body_preview": response.text[:500],
            },
        )
