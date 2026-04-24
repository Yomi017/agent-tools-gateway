# WebCapture Integration Home

This directory holds the local runtime home for the Browserless-backed
`webcapture` backend used by Agent Tools Gateway.

## Contents

```text
tools/WebCapture/
  README.md
  work/
    output/     # allowed output root
    tmp/        # temp root
```

## Notes

- Browserless stays external to this repo and runs as a separate container.
- Runtime files under `work/` are gitignored.
- The gateway backend key is `webcapture`, while the user-facing integration
  home stays at `tools/WebCapture`.
- `GET /health` only proves that the gateway can reach Browserless. It does not
  prove that public web capture is usable.
- Real smoke testing should call `POST /v1/webcapture/check` for a public URL,
  such as `https://example.com`, and confirm that the response includes
  `planned_output_path` instead of `resolution_failed`. A full runtime smoke
  should also call `POST /v1/webcapture/capture`, because health and check
  requests do not prove Chromium can navigate and write an artifact.
- `toolhub-api` and `toolhub-mcp` can inherit
  `TOOLHUB_OUTBOUND_HTTP_PROXY`, `TOOLHUB_OUTBOUND_HTTPS_PROXY`, and
  `TOOLHUB_OUTBOUND_NO_PROXY` when the gateway itself needs a host proxy.
- `browserless` intentionally stays in direct-egress mode by default. This
  avoids Chromium startup/navigation failures such as
  `net::ERR_PROXY_CONNECTION_FAILED` when the host bridge proxy is only meant
  for the API/MCP containers.
- `browserless` also intentionally does not receive `host.docker.internal`.
  The browser container is meant to capture public webpages directly, not to
  reach host-only services or proxy bridges.
- Public web capture can also use container-scoped DNS instead of the host's
  current WSL DNS path. Compose reads
  `TOOLHUB_WEBCAPTURE_DNS_PRIMARY` and `TOOLHUB_WEBCAPTURE_DNS_SECONDARY`,
  defaulting to `223.5.5.5` and `119.29.29.29`.
- `browserless`, `toolhub-api`, and `toolhub-mcp` also declare
  `dns_search: []` so public-domain resolution prefers the container-scoped
  nameservers over the host's current DNS path.
- Browserless and Python Playwright must stay on the same minor version for
  `chromium.connect()` to work. This repo currently aligns
  `ghcr.io/browserless/chromium:v2.38.2` with Python Playwright `1.56.x`.
- If Browserless is upgraded later, re-check the matching Python Playwright
  version before rebuilding `toolhub-api` or `toolhub-mcp`.
- Browserless also needs a job timeout that is at least as long as the gateway
  browser timeout. This compose stack pins `TIMEOUT=120000` so slower public
  pages and full-page screenshots do not get cut off at Browserless's shorter
  default.
- This DNS override is public-web-first. It does not guarantee `*.ts.net` or
  other private/internal domains inside the WebCapture path.
- Browser contexts block Service Workers and validate WebSocket URLs with the
  same public-network policy as normal requests. This closes common SSRF
  bypass paths that request routing alone does not cover.
- WebCapture also applies conservative output limits by default:
  `max_capture_bytes=67108864` and `max_full_page_height_px=20000`. Oversized
  captures fail with `capture_limit_exceeded` instead of writing partial files.
