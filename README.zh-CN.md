# Agent Tools Gateway 命令速查

仓库目录：

```bash
cd /home/shinku/data/service/tool/agent-tools-gateway
```

输入目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/input
```

Docling 输入目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/input
```

SearXNG 配置目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/SearXNG/config
```

输出目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/ConvertX/work/output
```

Docling 输出目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/output
```

SearXNG 缓存目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tools/SearXNG/data
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

如果 gateway 侧容器需要通过宿主机代理出网，可以显式传入 outbound proxy 环境变量：

```bash
export TOOLHUB_OUTBOUND_HTTP_PROXY="http://host.docker.internal:17990"
export TOOLHUB_OUTBOUND_HTTPS_PROXY="http://host.docker.internal:17990"
export TOOLHUB_OUTBOUND_NO_PROXY="localhost,127.0.0.1,convertx,docling,browserless,toolhub-api,toolhub-mcp,host.docker.internal"
```

这组 `TOOLHUB_OUTBOUND_*` 现在只给 `toolhub-api` 和 `toolhub-mcp` 使用。
`browserless` 默认保持直连公网，不继承这组代理，避免 Chromium 在抓网页时出现
`net::ERR_PROXY_CONNECTION_FAILED`。
同时 `browserless` 也不会再拿到 `host.docker.internal` 映射；浏览器容器默认不应该直连宿主机服务或代理桥。

当前这台机器推荐直接用 `17990`。它是 WSL 到 Windows 代理的桥：

```text
0.0.0.0:17990 -> 127.0.0.1:7890
```

`/home/shinku/data/setup.sh` 会自动给 `agent-tools-gateway` 导出这组 `TOOLHUB_OUTBOUND_*` 变量，所以正常情况下不需要每次手工设置；compose 会确保 `browserless` 不继承它们。

如果只想优先恢复 WebCapture 的公网域名解析，而不依赖宿主机当前的 DNS 链路，可以给 `browserless`、`toolhub-api`、`toolhub-mcp` 显式传入独立 DNS：

```bash
export TOOLHUB_WEBCAPTURE_DNS_PRIMARY="223.5.5.5"
export TOOLHUB_WEBCAPTURE_DNS_SECONDARY="119.29.29.29"
```

当前 compose 默认就会使用这两个值，并且对这三个容器显式配置 `dns_search: []`，优先让公网域名解析走独立 nameserver。

这套 DNS 只优先保证公网网页抓取，不保证解析 `*.ts.net` 或其他内网域名。

另外要注意：Browserless 镜像和 Python Playwright 必须保持同一 minor 版本，`chromium.connect()` 才能正常工作。当前仓库按 `ghcr.io/browserless/chromium:v2.38.2 -> Playwright 1.56.x` 对齐；如果后面升级 Browserless，需要同步重新评估 Python 侧 Playwright 版本。
同时 Browserless 的 job timeout 也要不小于 gateway 侧的浏览器超时；当前 compose 已显式固定 `TIMEOUT=120000`，避免慢页面或整页截图在 Browserless 默认 30 秒处被提前杀掉。
Docling 的 CPU 基础镜像当前也没有发布 `1.16.1` 这种显式 tag，所以这里直接跟官方 `ghcr.io/docling-project/docling-serve-cpu:latest`，而不是写一个实际上拉不下来的版本号。
另外，Docling Serve 在启动时会把空的 `DOCLING_SERVE_API_KEY` 视为非法值，所以仓库里的 compose 会在变量为空时自动 `unset`，默认仍然保持“可不配 API key”。
同时基础 compose 默认不会把 raw Docling 发布到宿主机；正常使用只通过 gateway 访问 `docling` backend。只有你显式叠加 `docker-compose.debug.yml` 时，`127.0.0.1:5001` 才会重新开放出来。

## 启动

启动全部服务：

```bash
docker compose up -d convertx docling searxng browserless toolhub-api toolhub-mcp
```

首次构建或更新后启动：

```bash
docker compose up -d --build convertx docling searxng browserless toolhub-api toolhub-mcp
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
docker compose logs -f docling
docker compose logs -f searxng
docker compose logs -f browserless
docker compose logs -f toolhub-api
docker compose logs -f toolhub-mcp
```

健康检查：

```bash
curl http://127.0.0.1:3000/healthcheck
curl http://127.0.0.1:8080/healthz
curl "http://127.0.0.1:8080/search?q=example&format=json"
curl "http://127.0.0.1:3001/pressure?token=$BROWSERLESS_TOKEN"
curl http://127.0.0.1:8765/health
```

这里要注意：

- `http://127.0.0.1:3001/pressure` 只表示 Browserless 容器活着。
- `http://127.0.0.1:8765/health` 会聚合 gateway 当前能否连到 ConvertX、Docling、Browserless。
- 这两个检查都不代表“公网网页抓取已可用”。
- `webcapture/check` 更适合作为可选的入口 smoke，不应该作为每次启动脚本的硬失败条件；真实可用性还需要跑一次 `webcapture/capture`，确认 Chromium 能导航并写出产物。
- WebCapture 现在默认走容器独立 DNS，不再依赖宿主机当前的 WSL DNS 是否可用。
- WebCapture 真正抓网页时，`browserless` 默认直连公网；`TOOLHUB_OUTBOUND_*` 只影响 `toolhub-api` / `toolhub-mcp`。
- WebCapture 的浏览器上下文会固定禁用 Service Worker，并对 WebSocket URL 继续套用同一套公网校验，避免绕过现有 SSRF 防护。
- WebCapture 默认还有两条保守资源限制：`max_capture_bytes=67108864`、`max_full_page_height_px=20000`。超限时会直接返回 `capture_limit_exceeded`，不会写出部分产物。

## Docling 调试暴露

默认栈不会开放 `127.0.0.1:5001`。如果你需要直接调 raw Docling，再显式叠加调试覆盖文件：

```bash
export DOCLING_SERVE_API_KEY="change-me-docling-debug-key"
docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d docling toolhub-api toolhub-mcp
```

这时可以直接访问版本接口：

```bash
curl http://127.0.0.1:5001/version
```

raw Docling 的转换接口则需要带同一个 `X-Api-Key`：

```bash
curl -X POST http://127.0.0.1:5001/v1/convert/file/async \
  -H "X-Api-Key: $DOCLING_SERVE_API_KEY" \
  -F files=@/path/to/example.pdf \
  -F to_formats=md
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

## 手动搜索

直接访问 raw SearXNG：

```bash
curl "http://127.0.0.1:8080/search?q=OpenAI+GPT-5.5&format=json"
```

走 gateway 的 REST：

```bash
curl -X POST http://127.0.0.1:8765/v1/searxng/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "OpenAI GPT-5.5",
    "limit": 5,
    "language": "auto",
    "safe_search": "moderate"
  }'
```

走 CLI：

```bash
uv run tool-call searxng --limit 5 --safe-search moderate "OpenAI GPT-5.5"
```

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

## 文档转换

只检查 Docling 的输入路径和输出规划，不实际生成文件：

```bash
uv run tool-call docling --check \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/input/example.pdf \
  md \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/output \
  false
```

导出为 Markdown：

```bash
uv run tool-call docling \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/input/example.pdf \
  md \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/output \
  true
```

带 OCR 和图片引用导出为 HTML：

```bash
uv run tool-call docling --name lecture-html --do-ocr true --include-images true \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/input/example.pdf \
  html \
  /home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/output \
  true
```

REST 检查：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/docling/check \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/input/example.pdf",
    "output_format": "md",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tools/Docling/work/output",
    "overwrite": false
  }'
```

REST 生成：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/docling/convert \
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

推荐把这条 `webcapture/check` 当作可选的入口 smoke：

- 如果它成功返回 `planned_output_path`，说明 WebCapture 的入口校验和输出路径都正常。
- 如果它返回 `resolution_failed`，优先检查 `TOOLHUB_WEBCAPTURE_DNS_PRIMARY/SECONDARY` 是否符合当前网络环境，并确认相关容器已经 `up -d --force-recreate`。
- 如果 `check` 成功但 `capture` 失败，优先检查 `browserless` 是否错误继承了 `HTTP_PROXY` / `HTTPS_PROXY`，以及 Chromium 真实导航时的网络链路。

如果调整了这组独立 DNS，推荐这样重建 WebCapture 三容器：

```bash
docker compose up -d --force-recreate browserless toolhub-api toolhub-mcp
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

Hermes gateway 现在以 `systemd --user` 的 `hermes-gateway.service` 为准。  
当前环境里 `hermes gateway status` 可能会误报 “Gateway is not running”，所以日常检查和启动更推荐：

```bash
systemctl --user is-active hermes-gateway.service
systemctl --user status hermes-gateway.service --no-pager
systemctl --user start hermes-gateway.service
```

添加 MCP：

```bash
hermes mcp add toolhub --url http://localhost:8766/mcp
hermes mcp test toolhub
hermes mcp list
```

如果启用了 token，Hermes 配置里加：

```yaml
mcp_servers:
  toolhub:
    url: "http://localhost:8766/mcp"
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
mcp_toolhub_docling_health
mcp_toolhub_docling_check_file
mcp_toolhub_docling_convert_file
mcp_toolhub_searxng_health
mcp_toolhub_searxng_search
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

这个脚本现在只负责 ensure 当前开发环境，不做系统修复。它会：

- 确保 `sub2api_proxy_forward.py` 在跑，提供 `17990 -> 7890` 代理桥
- 按需启动 Docker，但不会再无脑 `restart docker`
- 确保 `sub2api` 和 `agent-tools-gateway` 两个 compose 栈都起来
- 用 `systemd --user` 确保 `hermes-gateway.service` 在跑

它不会再做这些事：

- 不改 `/etc/resolv.conf` 或 `/etc/wsl.conf`
- 不尝试重启 WSL
- 不再启动本地 `tmux clash`
- 不再调用 `hermes gateway install --force`
