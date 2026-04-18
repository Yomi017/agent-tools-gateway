# Agent Tools Gateway 命令速查

仓库目录：

```bash
cd /home/shinku/data/service/tool/agent-tools-gateway
```

输入目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input
```

输出目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/output
```

网页落地输出目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output
```

如果要同时保护 REST 和 MCP：

```bash
export TOOLHUB_AUTH_TOKEN="change-me-local-token"
```

Docker Compose 会把这个值传给 `toolhub-api` 和 `toolhub-mcp`。

Browserless token：

```bash
export BROWSERLESS_TOKEN="change-me-browserless-token"
```

## 启动

启动全部服务：

```bash
docker compose up -d convertx browserless toolhub-api toolhub-mcp
```

首次构建或更新后启动：

```bash
docker compose up -d --build convertx browserless toolhub-api toolhub-mcp
```

停止：

```bash
docker compose stop
```

删除容器：

```bash
docker compose down
```

## 查看状态

```bash
docker compose ps
docker compose logs -f convertx
docker compose logs -f browserless
docker compose logs -f toolhub-api
docker compose logs -f toolhub-mcp
```

健康检查：

```bash
curl http://127.0.0.1:3000/healthcheck
curl "http://127.0.0.1:3001/pressure?token=$BROWSERLESS_TOKEN"
curl http://127.0.0.1:8765/health
```

启用 token 后：

```bash
curl -H "Authorization: Bearer $TOOLHUB_AUTH_TOKEN" http://127.0.0.1:8765/health
```

## 手动转换

先把文件放到输入目录：

```bash
cp /path/to/example.png /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/
```

查询某种格式支持转什么：

```bash
curl "http://127.0.0.1:8765/v1/convertx/targets?input_format=png"
```

只看目标格式名：

```bash
curl -sS "http://127.0.0.1:8765/v1/convertx/targets?input_format=png" | jq '.targets[] | .target' | sort -u
```

单文件转换：

短命令：

```bash
uv run tool-call convertx png \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/example.png \
  jpg \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/output \
  true
```

`tool-call` 默认输出 JSON。启用 `TOOLHUB_AUTH_TOKEN` 时，它会自动带上 Bearer token。

只检查路径和格式是否可转换，不实际生成文件：

```bash
uv run tool-call convertx --check png \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/example.png \
  jpg \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/output \
  false
```

如果 `input_path` 是一个目录，`tool-call` 会批量转换该目录下所有匹配 `input_format` 的文件：

```bash
uv run tool-call convertx webp \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/shinku \
  jpg \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/output/shinku \
  true
```

目录批量模式目前只扫描目录第一层文件，不递归子目录。

如果要指定转换器、API 地址或超时时间：

```bash
uv run tool-call convertx --converter imagemagick --api-url http://127.0.0.1:8765 --timeout 660 \
  png \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/example.png \
  jpg \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/output \
  true
```

传统 curl：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/convertx/convert \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/example.png",
    "output_format": "jpg",
    "overwrite": true
  }'
```

批量转换：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/convertx/convert-batch \
  -H 'Content-Type: application/json' \
  -d '{
    "input_paths": [
      "/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/a.png",
      "/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input/b.png"
    ],
    "output_format": "jpg",
    "overwrite": true
  }'
```

## 网页落地

只检查网页落地参数，不实际生成文件：

```bash
uv run tool-call webcapture --check \
  https://example.com \
  pdf \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output \
  false
```

保存网页为 PDF：

```bash
uv run tool-call webcapture \
  https://example.com \
  pdf \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output \
  true
```

保存网页为 PNG：

```bash
uv run tool-call webcapture --name example-home --full-page true \
  https://example.com \
  png \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output \
  true
```

保存网页为 Markdown：

```bash
uv run tool-call webcapture --wait-until networkidle \
  https://example.com \
  md \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output \
  true
```

REST 检查：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/webcapture/check \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com",
    "output_format": "pdf",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output"
  }'
```

REST 生成：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/webcapture/capture \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com",
    "output_format": "md",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tools/WebCapture/work/output",
    "filename_stem": "example-md",
    "overwrite": true
  }'
```

## Hermes

添加 MCP：

```bash
hermes mcp add toolhub --url http://127.0.0.1:8766/mcp
hermes mcp test toolhub
hermes mcp list
```

如果启用了 token，Hermes 配置里加：

```yaml
mcp_servers:
  toolhub:
    url: "http://127.0.0.1:8766/mcp"
    headers:
      Authorization: "Bearer ${TOOLHUB_AUTH_TOKEN}"
```

重载：

```text
/reload-mcp
```

Hermes 里可用工具名：

```text
mcp_toolhub_toolhub_health
mcp_toolhub_list_conversion_targets
mcp_toolhub_convert_file
mcp_toolhub_convert_batch
mcp_toolhub_convertx_health
mcp_toolhub_convertx_list_targets
mcp_toolhub_convertx_convert_file
mcp_toolhub_convertx_convert_batch
mcp_toolhub_webcapture_health
mcp_toolhub_webcapture_check_url
mcp_toolhub_webcapture_capture_url
mcp_toolhub_check_webpage_capture
mcp_toolhub_capture_webpage
```

## OpenClaw

```bash
openclaw mcp set toolhub '{"url":"http://127.0.0.1:8766/mcp","transport":"streamable-http","connectionTimeout":10000}'
```

启用 token 后：

```bash
openclaw mcp set toolhub "{\"url\":\"http://127.0.0.1:8766/mcp\",\"transport\":\"streamable-http\",\"connectionTimeout\":10000,\"headers\":{\"Authorization\":\"Bearer ${TOOLHUB_AUTH_TOKEN}\"}}"
```

## 开机脚本

```bash
/home/shinku/data/setup.sh
```
