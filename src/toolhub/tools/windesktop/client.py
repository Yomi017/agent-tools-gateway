from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from ...config import WinDesktopRuntimeSettings
from ...errors import UpstreamError


@dataclass(frozen=True)
class ScreenshotArtifact:
    filename: str
    width: int | None
    height: int | None
    content_type: str
    size_bytes: int
    duration_ms: int


class WinDesktopClient:
    def __init__(
        self,
        settings: WinDesktopRuntimeSettings,
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

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.base_url.rstrip("/"),
            headers=self._headers(),
            timeout=self._timeout(),
            transport=self._transport,
            trust_env=False,
        )

    async def health(self) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.get("/health", params={"compact": True})
        except httpx.HTTPError as exc:
            return {
                "reachable": False,
                "base_url": self.settings.base_url,
                "error": str(exc),
            }

        payload = self._maybe_json_dict(response)
        result: dict[str, Any] = {
            "reachable": 200 <= response.status_code < 300,
            "base_url": self.settings.base_url,
            "status_code": response.status_code,
        }
        if payload is not None:
            result.update(payload)
        else:
            result["body_preview"] = response.text[:500]
        return result

    async def list_windows(
        self,
        *,
        include_hidden: bool = False,
        include_titles: bool = True,
    ) -> tuple[dict[str, Any], int]:
        start = time.perf_counter()
        async with self._client() as client:
            response = await client.get(
                "/windows",
                params={
                    "include_hidden": include_hidden,
                    "include_titles": include_titles,
                },
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        return self._json_response(response, "list Windows desktop windows"), duration_ms

    async def screenshot(
        self,
        *,
        filename_stem: str | None = None,
        overwrite: bool = True,
    ) -> ScreenshotArtifact:
        start = time.perf_counter()
        params: dict[str, Any] = {"overwrite": overwrite}
        if filename_stem is not None:
            params["filename_stem"] = filename_stem
        async with self._client() as client:
            response = await client.get(
                "/screenshot",
                params=params,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        if response.status_code >= 400:
            raise UpstreamError(
                "WinDesktop bridge failed to capture screenshot.",
                details={
                    "status_code": response.status_code,
                    "body_preview": response.text[:500],
                },
            )
        payload = self._json_response(response, "capture Windows desktop screenshot")
        filename = payload.get("filename")
        if not isinstance(filename, str) or not filename:
            raise UpstreamError(
                "WinDesktop bridge screenshot response did not include a filename.",
                details={"payload": payload},
            )
        content_type = str(payload.get("content_type") or "")
        if content_type.lower() != "image/png":
            raise UpstreamError(
                "WinDesktop bridge reported a non-PNG screenshot payload.",
                details={"content_type": content_type, "payload": payload},
            )
        return ScreenshotArtifact(
            filename=filename,
            width=self._optional_int(payload.get("width")),
            height=self._optional_int(payload.get("height")),
            content_type=content_type,
            size_bytes=self._required_int(payload.get("size_bytes"), "size_bytes"),
            duration_ms=duration_ms,
        )

    async def focus_window(self, *, handle: int) -> tuple[dict[str, Any], int]:
        return await self._post_json(
            "/focus-window",
            {"handle": handle},
            "focus a Windows desktop window",
        )

    async def click(
        self,
        *,
        x: int,
        y: int,
        button: str = "left",
        double: bool = False,
    ) -> tuple[dict[str, Any], int]:
        return await self._post_json(
            "/click",
            {"x": x, "y": y, "button": button, "double": double},
            "click the Windows desktop",
        )

    async def type_text(self, *, text: str, mode: str = "paste") -> tuple[dict[str, Any], int]:
        return await self._post_json(
            "/type",
            {"text": text, "mode": mode},
            "type into the Windows desktop",
        )

    async def hotkey(self, *, keys: list[str]) -> tuple[dict[str, Any], int]:
        return await self._post_json(
            "/hotkey",
            {"keys": keys},
            "send a Windows desktop hotkey",
        )

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        action: str,
    ) -> tuple[dict[str, Any], int]:
        start = time.perf_counter()
        async with self._client() as client:
            response = await client.post(path, json=payload)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return self._json_response(response, action), duration_ms

    @staticmethod
    def _maybe_json_dict(response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _json_response(response: httpx.Response, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise UpstreamError(
                f"WinDesktop bridge failed to {action}.",
                details={"status_code": response.status_code, "body_preview": response.text[:500]},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                f"WinDesktop bridge returned non-JSON while trying to {action}.",
                details={"status_code": response.status_code, "body_preview": response.text[:500]},
            ) from exc
        if not isinstance(payload, dict):
            raise UpstreamError(
                f"WinDesktop bridge returned an unexpected JSON payload while trying to {action}.",
                details={"status_code": response.status_code, "payload_type": type(payload).__name__},
            )
        return payload

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _required_int(cls, value: Any, field_name: str) -> int:
        normalized = cls._optional_int(value)
        if normalized is None:
            raise UpstreamError(
                "WinDesktop bridge screenshot response included an invalid integer field.",
                details={"field": field_name, "value": value},
            )
        return normalized
