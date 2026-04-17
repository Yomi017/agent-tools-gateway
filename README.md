# Agent Tools Gateway

Local HTTP and MCP gateway for agent-callable tools. The first backend wraps a
self-hosted ConvertX service without vendoring or modifying ConvertX.

Chinese guide: [README.zh-CN.md](README.zh-CN.md)

## Layout

```text
src/toolhub/
  api.py                  # FastAPI REST API
  mcp_server.py           # FastMCP tools
  config.py               # config.yaml + TOOLHUB_* env
  security.py             # path whitelist and safe tar extraction
  backends/convertx.py    # ConvertX web/form workflow
```

## Local Setup

```bash
cd /home/shinku/data/service/tool/agent-tools-gateway
uv sync --extra dev
cp config.example.yaml config.yaml
```

Run ConvertX separately:

```bash
docker compose up -d convertx
```

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

## Docker Compose

To run ConvertX, REST, and MCP together:

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

Input and output files are restricted to:

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output
```

## REST

```bash
curl http://127.0.0.1:8765/health
curl "http://127.0.0.1:8765/v1/convertx/targets?input_format=png"
```

```bash
curl -X POST http://127.0.0.1:8765/v1/convertx/convert \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/example.png",
    "output_format": "jpg",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output",
    "overwrite": false
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
      resources: false
      prompts: false
```

OpenClaw config:

```bash
openclaw mcp set toolhub '{"url":"http://127.0.0.1:8766/mcp","transport":"streamable-http","connectionTimeout":10000}'
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
- Keep the service bound to `127.0.0.1` unless you also add transport-level
  authentication and network controls.

## Tests

```bash
uv run pytest
```
