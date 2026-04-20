# Agent Tools Gateway

Local HTTP and MCP gateway for agent-callable tools. The current backends wrap a
self-hosted ConvertX service and a Browserless-powered webpage capture flow
without vendoring either upstream service.

Chinese guide: [README.zh-CN.md](README.zh-CN.md)

## Layout

```text
src/toolhub/
  api.py                  # FastAPI REST API
  mcp_server.py           # FastMCP tools
  config.py               # config.yaml + TOOLHUB_* env
  registry.py             # backend registry
  security.py             # path / URL policy and safe tar extraction
  tools/convertx/         # ConvertX backend package
  tools/docling/          # Docling backend package
  tools/webcapture/       # Browserless web capture backend package
tools/
  ConvertX/
    README.md             # integration home
    data/                 # runtime data, gitignored
    work/                 # input/output/tmp, gitignored
  Docling/
    README.md             # integration home
    work/                 # input/output/tmp, gitignored
  WebCapture/
    README.md             # integration home
    work/                 # output/tmp, gitignored
```

## Local Setup

```bash
cd /home/shinku/data/service/tool/agent-tools-gateway
uv sync --extra dev
cp config.example.yaml config.yaml
```

Run ConvertX, Docling, and Browserless separately:

```bash
docker compose up -d convertx docling browserless
```

Docling stays on the internal compose network by default. Raw host access to
`127.0.0.1:5001` is only enabled with the debug override file.

Run the REST API:

```bash
uv run toolhub-api
```

Run the MCP server over HTTP:

```bash
uv run toolhub-mcp-http
```

The defaults bind to localhost:

- REST: `http://127.0.0.1:8765`
- MCP: `http://127.0.0.1:8766/mcp`
- ConvertX: `http://127.0.0.1:3000`
- Browserless: `http://127.0.0.1:3001`

Docling is internal-only by default and is reached through the gateway via the
compose service name `docling:5001`.

## Docker Compose

To run ConvertX, Docling, Browserless, REST, and MCP together:

```bash
docker compose up -d --build
```

The compose setup keeps all public ports bound to `127.0.0.1`. ConvertX
v0.17.0 is patched at container startup to listen on `0.0.0.0` inside Docker,
so Docker port publishing and other compose services can reach it.

The compose file pins ConvertX to:

```text
ghcr.io/c4illin/convertx:v0.17.0
```

Docling Serve to:

```text
ghcr.io/docling-project/docling-serve-cpu:latest
```

Docling's upstream CPU base image currently publishes convenience tags such as
`latest` and `main` rather than a `1.16.1` image tag, so this compose stack
tracks the official `latest` CPU image instead of a nonexistent version tag.
The compose service also unsets `DOCLING_SERVE_API_KEY` when it is blank,
because Docling Serve treats an empty value as invalid at startup.
The base compose file does not publish raw Docling to the host; use
`docker-compose.debug.yml` only when you explicitly need direct debugging.

and Browserless to:

```text
ghcr.io/browserless/chromium:v2.38.2
```

ConvertX input and output files are restricted to:

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input
/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/output
```

Docling input and output files are restricted to:

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/input
/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/output
```

Web capture outputs are restricted to:

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output
```

Optional shared Bearer token for both REST and MCP:

```bash
export TOOLHUB_AUTH_TOKEN="change-me-local-token"
```

Docker Compose passes this value into both `toolhub-api` and `toolhub-mcp`.

Browserless uses its own token:

```bash
export BROWSERLESS_TOKEN="change-me-browserless-token"
```

## REST

```bash
curl http://127.0.0.1:8765/health
curl "http://127.0.0.1:8765/v1/convertx/targets?input_format=png"
curl -X POST http://127.0.0.1:8765/v1/webcapture/check \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com",
    "output_format": "pdf",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output"
  }'
```

```bash
curl -X POST http://127.0.0.1:8765/v1/docling/check \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/input/example.pdf",
    "output_format": "md",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/output",
    "overwrite": false
  }'
```

When `auth_token` is enabled:

```bash
curl -H "Authorization: Bearer $TOOLHUB_AUTH_TOKEN" http://127.0.0.1:8765/health
```

## Docling Debug Exposure

The normal stack does not publish raw Docling on the host. If you need direct
debug access to upstream Docling Serve, explicitly opt in:

```bash
export DOCLING_SERVE_API_KEY="change-me-docling-debug-key"
docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d docling toolhub-api toolhub-mcp
```

With the debug override enabled:

```bash
curl http://127.0.0.1:5001/version
```

Raw Docling conversion endpoints require the same `X-Api-Key` value:

```bash
curl -X POST http://127.0.0.1:5001/v1/convert/file/async \
  -H "X-Api-Key: $DOCLING_SERVE_API_KEY" \
  -F files=@/path/to/example.pdf \
  -F to_formats=md
```

```bash
curl -X POST http://127.0.0.1:8765/v1/convertx/convert \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/example.png",
    "output_format": "jpg",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/output",
    "overwrite": false
  }'
```

```bash
curl -X POST http://127.0.0.1:8765/v1/webcapture/capture \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com",
    "output_format": "png",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output",
    "filename_stem": "example-home",
    "overwrite": true
  }'
```

```bash
curl -X POST http://127.0.0.1:8765/v1/docling/convert \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/input/example.pdf",
    "output_format": "html",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/output",
    "filename_stem": "example-doc",
    "overwrite": true,
    "do_ocr": true
  }'
```

## MCP

Smoke test:

```bash
uv run fastmcp inspect mcp_server.py:mcp --format fastmcp
uv run fastmcp inspect mcp_server.py:mcp --format mcp
```

Hermes config:

```yaml
mcp_servers:
  toolhub:
    url: "http://127.0.0.1:8766/mcp"
    timeout: 600
    connect_timeout: 60
    tools:
      include:
        - toolhub_health
        - list_conversion_targets
        - convert_file
        - convert_batch
        - docling_check_file
        - docling_convert_file
        - webcapture_check_url
        - webcapture_capture_url
      resources: false
      prompts: false
```

When Bearer auth is enabled, add:

```yaml
headers:
  Authorization: "Bearer ${TOOLHUB_AUTH_TOKEN}"
```

Canonical namespaced MCP tools are also registered:

```text
convertx_health
convertx_list_targets
convertx_convert_file
convertx_convert_batch
docling_health
docling_check_file
docling_convert_file
webcapture_health
webcapture_check_url
webcapture_capture_url
```

OpenClaw config:

```bash
openclaw mcp set toolhub '{"url":"http://127.0.0.1:8766/mcp","transport":"streamable-http","connectionTimeout":10000}'
```

With Bearer auth enabled:

```bash
openclaw mcp set toolhub "{\"url\":\"http://127.0.0.1:8766/mcp\",\"transport\":\"streamable-http\",\"connectionTimeout\":10000,\"headers\":{\"Authorization\":\"Bearer ${TOOLHUB_AUTH_TOKEN}\"}}"
```

If an OpenClaw runtime runs inside Docker, publish MCP beyond host localhost
first, for example by changing the compose port to `"8766:8766"`, then use:

```text
http://host.docker.internal:8766/mcp
```

## Safety

- Input files must resolve under `allowed_input_roots`.
- Output directories must resolve under `allowed_output_roots`.
- Symlink escapes and `..` escapes are rejected.
- ConvertX archives are extracted manually; absolute paths, parent traversal,
  duplicate archive members, and accidental overwrites are rejected.
- Web capture only allows `http` and `https` URLs by default and blocks
  `localhost`, loopback, private-network, link-local, multicast, and similar
  non-public targets.
- Keep the service bound to `127.0.0.1` unless you also add transport-level
  authentication and network controls.

## Tests

```bash
uv run pytest
```
