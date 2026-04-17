# Agent Tools Gateway 命令速查

仓库目录：

```bash
cd /home/shinku/data/service/tool/agent-tools-gateway
```

输入目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input
```

输出目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output
```

## 启动

启动全部服务：

```bash
docker compose up -d convertx toolhub-api toolhub-mcp
```

首次构建或更新后启动：

```bash
docker compose up -d --build convertx toolhub-api toolhub-mcp
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
docker compose logs -f toolhub-api
docker compose logs -f toolhub-mcp
```

健康检查：

```bash
curl http://127.0.0.1:3000/healthcheck
curl http://127.0.0.1:8765/health
```

## 手动转换

先把文件放到输入目录：

```bash
cp /path/to/example.png /home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/
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

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/convertx/convert \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/example.png",
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
      "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/a.png",
      "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/b.png"
    ],
    "output_format": "jpg",
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
```

## OpenClaw

```bash
openclaw mcp set toolhub '{"url":"http://127.0.0.1:8766/mcp","transport":"streamable-http","connectionTimeout":10000}'
```

## 开机脚本

```bash
/home/shinku/data/setup.sh
```
