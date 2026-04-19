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
  `planned_output_path` instead of `resolution_failed`.
- If containers need to reach the public web through a host proxy, pass
  `TOOLHUB_OUTBOUND_HTTP_PROXY`, `TOOLHUB_OUTBOUND_HTTPS_PROXY`, and
  `TOOLHUB_OUTBOUND_NO_PROXY` into compose. Otherwise the stack runs in direct
  mode by default.
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
- This DNS override is public-web-first. It does not guarantee `*.ts.net` or
  other private/internal domains inside the WebCapture path.
