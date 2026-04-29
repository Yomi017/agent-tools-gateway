from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from ...config import DoclingRuntimeSettings
from ...errors import ConversionTimeoutError, UpstreamError


SUCCESS_STATES = {"success", "succeeded", "completed", "done"}
FAILURE_STATES = {"failure", "failed", "error", "cancelled"}
CONTENT_KEYS = {
    "md": "md_content",
    "json": "json_content",
    "html": "html_content",
    "text": "text_content",
    "doctags": "doctags_content",
    "vtt": "vtt_content",
}


class DoclingClient:
    def __init__(
        self,
        settings: DoclingRuntimeSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.settings.api_key:
            headers["X-API-Key"] = self.settings.api_key
        return headers

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.settings.request_timeout_seconds,
            connect=self.settings.connect_timeout_seconds,
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.base_url.rstrip("/"),
            headers=self._headers(),
            timeout=self._timeout(),
            transport=self._transport,
        )

    async def health(self) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.get("/health")
        except httpx.HTTPError as exc:
            return {
                "reachable": False,
                "base_url": self.settings.base_url,
                "error": str(exc),
            }

        result: dict[str, Any] = {
            "reachable": 200 <= response.status_code < 300,
            "base_url": self.settings.base_url,
            "status_code": response.status_code,
        }

        parsed = self._maybe_json_dict(response)
        if parsed is not None:
            result["health"] = parsed
        else:
            result["body_preview"] = response.text[:500]

        if not result["reachable"]:
            return result

        try:
            async with self._client() as client:
                version_response = await client.get("/version")
        except httpx.HTTPError as exc:
            result["version_error"] = str(exc)
            return result

        version_payload = self._maybe_json_dict(version_response)
        if 200 <= version_response.status_code < 300 and version_payload is not None:
            result["version"] = version_payload
            return result

        result["version_status_code"] = version_response.status_code
        result["version_body_preview"] = self._response_preview(
            version_response,
            parsed_payload=version_payload,
        )
        return result

    async def convert_file(
        self,
        input_path: Path,
        *,
        output_format: str,
        do_ocr: bool | None = None,
        force_ocr: bool | None = None,
        ocr_engine: str | None = None,
        pdf_backend: str | None = None,
        table_mode: str | None = None,
        image_export_mode: str | None = None,
        include_images: bool | None = None,
    ) -> tuple[str, bytes, int]:
        start = time.perf_counter()
        async with self._client() as client:
            task_id = await self._submit_convert(
                client,
                input_path=input_path,
                output_format=output_format,
                do_ocr=do_ocr,
                force_ocr=force_ocr,
                ocr_engine=ocr_engine,
                pdf_backend=pdf_backend,
                table_mode=table_mode,
                image_export_mode=image_export_mode,
                include_images=include_images,
            )
            await self._wait_until_done(client, task_id)
            content = await self._fetch_result(client, task_id, output_format=output_format)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return task_id, content, duration_ms

    async def _submit_convert(
        self,
        client: httpx.AsyncClient,
        *,
        input_path: Path,
        output_format: str,
        do_ocr: bool | None,
        force_ocr: bool | None,
        ocr_engine: str | None,
        pdf_backend: str | None,
        table_mode: str | None,
        image_export_mode: str | None,
        include_images: bool | None,
    ) -> str:
        files: list[tuple[str, tuple[str | None, Any, str | None]]] = [
            ("to_formats", (None, output_format, None))
        ]
        for key, value in (
            ("do_ocr", do_ocr),
            ("force_ocr", force_ocr),
            ("ocr_engine", ocr_engine),
            ("pdf_backend", pdf_backend),
            ("table_mode", table_mode),
            ("image_export_mode", image_export_mode),
            ("include_images", include_images),
        ):
            if value is None:
                continue
            if isinstance(value, bool):
                files.append((key, (None, "true" if value else "false", None)))
            else:
                files.append((key, (None, str(value), None)))

        with input_path.open("rb") as handle:
            files.append(("files", (input_path.name, handle, "application/octet-stream")))
            response = await client.post(
                "/v1/convert/file/async",
                files=files,
            )
        payload = self._json_response(response, "submit Docling conversion")
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise UpstreamError(
                "Docling did not return a task_id.",
                details={"payload": payload},
            )
        return task_id

    async def _wait_until_done(self, client: httpx.AsyncClient, task_id: str) -> None:
        deadline = time.monotonic() + self.settings.conversion_timeout_seconds
        while True:
            response = await client.get(f"/v1/status/poll/{task_id}")
            payload = self._json_response(response, "poll Docling task status")
            raw_status = payload.get("task_status") or payload.get("status")
            status = str(raw_status or "").strip().lower()
            if status in SUCCESS_STATES:
                return
            if status in FAILURE_STATES:
                raise UpstreamError(
                    "Docling task failed.",
                    details={"task_id": task_id, "task_status": raw_status, "payload": payload},
                )
            if time.monotonic() >= deadline:
                raise ConversionTimeoutError(
                    "Timed out waiting for Docling conversion.",
                    details={"task_id": task_id, "task_status": raw_status},
                )
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _fetch_result(
        self,
        client: httpx.AsyncClient,
        task_id: str,
        *,
        output_format: str,
    ) -> bytes:
        response = await client.get(f"/v1/result/{task_id}")
        content_type = response.headers.get("content-type", "").lower()
        if "zip" in content_type:
            raise UpstreamError(
                "Docling returned a multi-file archive, which this gateway does not support.",
                details={"task_id": task_id, "content_type": content_type},
            )

        payload = self._json_response(response, "fetch Docling conversion result")
        document = self._extract_document(payload)
        return self._extract_content(document, output_format=output_format, task_id=task_id)

    @staticmethod
    def _extract_document(payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload.get("document"), dict):
            return payload["document"]
        result = payload.get("result")
        if isinstance(result, dict) and isinstance(result.get("document"), dict):
            return result["document"]
        if any(key in payload for key in CONTENT_KEYS.values()):
            return payload
        raise UpstreamError(
            "Docling result did not include a document payload.",
            details={"payload": payload},
        )

    @staticmethod
    def _extract_content(document: dict[str, Any], *, output_format: str, task_id: str) -> bytes:
        if any(key in document for key in ("documents", "files", "archive")):
            raise UpstreamError(
                "Docling returned a multi-file result, which this gateway does not support.",
                details={"task_id": task_id, "document_keys": sorted(document)},
            )

        key = CONTENT_KEYS[output_format]
        if key not in document or document[key] is None:
            raise UpstreamError(
                "Docling result did not include the requested output format.",
                details={
                    "task_id": task_id,
                    "output_format": output_format,
                    "document_keys": sorted(document),
                },
            )

        value = document[key]
        if output_format == "json":
            return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if not isinstance(value, str):
            raise UpstreamError(
                "Docling returned an unexpected result type.",
                details={
                    "task_id": task_id,
                    "output_format": output_format,
                    "value_type": type(value).__name__,
                },
            )
        return value.encode("utf-8")

    @staticmethod
    def _json_response(response: httpx.Response, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise UpstreamError(
                f"Docling failed to {action}.",
                details={"status_code": response.status_code, "body_preview": response.text[:500]},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                f"Docling returned non-JSON while trying to {action}.",
                details={"status_code": response.status_code, "body_preview": response.text[:500]},
            ) from exc
        if not isinstance(payload, dict):
            raise UpstreamError(
                f"Docling returned an unexpected JSON payload while trying to {action}.",
                details={"status_code": response.status_code, "payload_type": type(payload).__name__},
            )
        return payload

    @staticmethod
    def _maybe_json_dict(response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _response_preview(
        response: httpx.Response,
        *,
        parsed_payload: dict[str, Any] | None = None,
    ) -> str:
        if parsed_payload is not None:
            return json.dumps(parsed_payload, ensure_ascii=False)[:500]
        return response.text[:500]
