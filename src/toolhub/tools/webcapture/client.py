from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from ...config import WebCaptureRuntimeSettings
from ...errors import UpstreamError, UrlNotAllowedError
from ...security import Resolver, resolve_host_addresses, validate_web_url
from .models import normalize_capture_format, normalize_wait_until


DEFAULT_WAIT_UNTIL = "networkidle"


@dataclass(frozen=True)
class CaptureArtifact:
    content: bytes
    final_url: str
    title: str | None
    navigation_status: dict[str, Any]


@dataclass(frozen=True)
class BlockedRequest:
    url: str
    resource_type: str | None
    reason: str


class PlaywrightCaptureSession:
    def __init__(self, settings: WebCaptureRuntimeSettings, resolver: Resolver) -> None:
        self.settings = settings
        self.resolver = resolver
        self.blocked_requests: list[BlockedRequest] = []
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    async def __aenter__(self) -> PlaywrightCaptureSession:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect(
            self._ws_endpoint(),
            timeout=int(self.settings.connect_timeout_seconds * 1000),
        )
        self._context = await self._browser.new_context(
            viewport={
                "width": self.settings.viewport_width,
                "height": self.settings.viewport_height,
            }
        )
        await self._context.route("**/*", self._route_request)
        self._page = await self._context.new_page()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            with suppress(Exception):
                await self._context.close()
        if self._browser is not None:
            with suppress(Exception):
                await self._browser.close()
        if self._playwright is not None:
            with suppress(Exception):
                await self._playwright.stop()

    def _ws_endpoint(self) -> str:
        parts = urlsplit(self.settings.base_url.rstrip("/"))
        scheme = parts.scheme.lower()
        if scheme == "http":
            ws_scheme = "ws"
        elif scheme == "https":
            ws_scheme = "wss"
        elif scheme in {"ws", "wss"}:
            ws_scheme = scheme
        else:
            raise UpstreamError(
                "webcapture base_url must use http, https, ws, or wss.",
                details={"base_url": self.settings.base_url},
            )

        query = list(parse_qsl(parts.query, keep_blank_values=True))
        if self.settings.token:
            query.append(("token", self.settings.token))
        path = f"{parts.path.rstrip('/')}/chromium/playwright" if parts.path else "/chromium/playwright"
        return urlunsplit((ws_scheme, parts.netloc, path, urlencode(query), ""))

    async def _route_request(self, route: Any) -> None:
        request = route.request
        try:
            validate_web_url(
                request.url,
                block_private_networks=self.settings.block_private_networks,
                resolver=self.resolver,
            )
        except Exception as exc:
            reason = str(exc)
            if isinstance(exc, UrlNotAllowedError):
                reason = str(exc.details.get("reason") or reason)
            self.blocked_requests.append(
                BlockedRequest(
                    url=request.url,
                    resource_type=getattr(request, "resource_type", None),
                    reason=reason,
                )
            )
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def capture(
        self,
        *,
        url: str,
        output_format: str,
        wait_until: str | None = None,
        full_page: bool | None = None,
    ) -> CaptureArtifact:
        navigation_wait = normalize_wait_until(wait_until or DEFAULT_WAIT_UNTIL)
        capture_format = normalize_capture_format(output_format)

        try:
            response = await self._page.goto(
                url,
                wait_until=navigation_wait,
                timeout=int(self.settings.browser_timeout_seconds * 1000),
            )
            if self.settings.post_load_wait_ms > 0:
                await self._page.wait_for_timeout(self.settings.post_load_wait_ms)
        except Exception as exc:
            if self.blocked_requests:
                raise UrlNotAllowedError(
                    "Browser navigation was blocked by the web capture network policy.",
                    details={"blocked_requests": [item.__dict__ for item in self.blocked_requests]},
                ) from exc
            raise UpstreamError(
                "Browserless failed to load the requested page.",
                details={"url": url, "error": str(exc)},
            ) from exc

        final_url = validate_web_url(
            self._page.url,
            block_private_networks=self.settings.block_private_networks,
            resolver=self.resolver,
        ).normalized_url
        title = await self._page.title() or None

        if capture_format == "pdf":
            content = await self._page.pdf(
                format=self.settings.pdf_format,
                print_background=True,
                prefer_css_page_size=True,
            )
        elif capture_format == "png":
            content = await self._page.screenshot(
                type="png",
                full_page=True if full_page is None else full_page,
            )
        else:
            html = await self._page.content()
            content = _render_markdown(
                html=html,
                source_url=final_url,
                title=title,
            ).encode("utf-8")

        return CaptureArtifact(
            content=content,
            final_url=final_url,
            title=title,
            navigation_status={
                "status": getattr(response, "status", None) if response is not None else None,
                "ok": getattr(response, "ok", None) if response is not None else None,
                "url": getattr(response, "url", None) if response is not None else final_url,
            },
        )


class WebCaptureClient:
    def __init__(
        self,
        settings: WebCaptureRuntimeSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        session_factory: Callable[
            [WebCaptureRuntimeSettings, Resolver], PlaywrightCaptureSession
        ]
        | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._session_factory = session_factory or PlaywrightCaptureSession
        self._resolver = resolver

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.base_url.rstrip("/"),
            timeout=httpx.Timeout(
                self.settings.request_timeout_seconds,
                connect=self.settings.connect_timeout_seconds,
            ),
            transport=self._transport,
        )

    def _token_params(self) -> dict[str, str]:
        if not self.settings.token:
            return {}
        return {"token": self.settings.token}

    async def health(self) -> dict[str, Any]:
        try:
            async with self._http_client() as client:
                response = await client.get("/pressure", params=self._token_params())
        except httpx.HTTPError as exc:
            return {
                "reachable": False,
                "base_url": self.settings.base_url,
                "error": str(exc),
            }

        payload: dict[str, Any] = {
            "reachable": 200 <= response.status_code < 300,
            "base_url": self.settings.base_url,
            "status_code": response.status_code,
        }
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            for key in ("isAvailable", "queued", "running", "recent", "paused"):
                if key in data:
                    payload[key] = data[key]
        else:
            payload["body_preview"] = response.text[:500]
        return payload

    async def capture(
        self,
        *,
        url: str,
        output_format: str,
        wait_until: str | None = None,
        full_page: bool | None = None,
    ) -> tuple[CaptureArtifact, int]:
        start = time.perf_counter()
        async with self._session_factory(
            self.settings,
            self._resolver or resolve_host_addresses,
        ) as session:
            artifact = await session.capture(
                url=url,
                output_format=output_format,
                wait_until=wait_until,
                full_page=full_page,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        return artifact, duration_ms


def _render_markdown(*, html: str, source_url: str, title: str | None) -> str:
    from lxml import html as lxml_html
    from markdownify import markdownify
    from readability import Document

    readable = Document(html)
    summary_html = readable.summary(html_partial=True)
    readable_title = readable.short_title() or readable.title()
    summary_text = " ".join(summary_html.split())
    if len(summary_text) < 80:
        parsed = lxml_html.fromstring(html)
        body = parsed.find(".//body")
        summary_html = (
            lxml_html.tostring(body, encoding="unicode", method="html")
            if body is not None
            else html
        )

    effective_title = title or readable_title
    markdown = markdownify(summary_html, heading_style="ATX").strip()
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    header = [
        f"# {effective_title or 'Captured Page'}",
        "",
        f"Source URL: {source_url}",
        f"Captured At: {captured_at}",
        f"Title: {effective_title or ''}",
        "",
        "---",
        "",
        markdown,
    ]
    return "\n".join(header).rstrip() + "\n"
