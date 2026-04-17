# Agent Tools Gateway 中文使用说明

`agent-tools-gateway` 是一个本地工具网关。

它把第三方工具或本地部署工具包装成统一接口，供下面两类使用者调用：

- 人：通过 HTTP REST 直接在终端里调用
- Agent：通过 MCP 工具调用

第一版后端是 `ConvertX`，用于文件格式转换。

## 1. 它现在能做什么

当前仓库已经提供三层服务：

- `ConvertX`：实际执行转换
- `toolhub-api`：REST API
- `toolhub-mcp`：MCP 服务

默认地址：

- ConvertX: `http://127.0.0.1:3000`
- REST API: `http://127.0.0.1:8765`
- MCP: `http://127.0.0.1:8766/mcp`

## 2. 启动方式

进入仓库目录：

```bash
cd /home/shinku/data/service/tool/agent-tools-gateway
```

启动全部服务：

```bash
docker compose up -d convertx toolhub-api toolhub-mcp
```

第一次构建或代码更新后，建议：

```bash
docker compose up -d --build convertx toolhub-api toolhub-mcp
```

查看服务状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f convertx
docker compose logs -f toolhub-api
docker compose logs -f toolhub-mcp
```

停止服务：

```bash
docker compose stop
```

删除容器但保留数据：

```bash
docker compose down
```

## 3. 白名单目录

出于安全原因，输入和输出路径只能在固定目录下。

输入目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input
```

输出目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output
```

临时目录：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/tmp
```

如果你传入别的路径，网关会拒绝。

## 4. 最常见的手动用法

### 4.1 先把文件放进输入目录

```bash
cp /path/to/example.png /home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/
```

### 4.2 查询服务是否正常

```bash
curl http://127.0.0.1:8765/health
```

成功响应示例：

```json
{
  "ok": true,
  "service": "agent-tools-gateway",
  "backends": {
    "convertx": {
      "reachable": true,
      "base_url": "http://convertx:3000"
    }
  }
}
```

### 4.3 查询某种输入格式可以转成什么

例如查询 `png`：

```bash
curl "http://127.0.0.1:8765/v1/convertx/targets?input_format=png"
```

如果装了 `jq`，看起来会更清楚：

```bash
curl -sS "http://127.0.0.1:8765/v1/convertx/targets?input_format=png" \
  | jq '.targets[] | .target' \
  | sort -u
```

### 4.4 转换单个文件

把 `example.png` 转成 `jpg`：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/convertx/convert \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/example.png",
    "output_format": "jpg",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output",
    "overwrite": true
  }'
```

成功响应示例：

```json
{
  "ok": true,
  "backend": "convertx",
  "job_id": "3",
  "outputs": [
    {
      "path": "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output/example.jpg",
      "filename": "example.jpg"
    }
  ],
  "duration_ms": 1063
}
```

也就是说输出文件会在：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output/example.jpg
```

### 4.5 批量转换

批量转换要求所有输入文件扩展名相同。

例如把两个 `png` 一起转成 `jpg`：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/convertx/convert-batch \
  -H 'Content-Type: application/json' \
  -d '{
    "input_paths": [
      "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/a.png",
      "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/b.png"
    ],
    "output_format": "jpg",
    "output_dir": "/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output",
    "overwrite": true
  }'
```

## 5. 最短命令套路

如果你只是自己手动转格式，记住这三步就够了：

1. 把文件放进 `tool-work/input`
2. `curl POST /v1/convertx/convert`
3. 去 `tool-work/output` 取结果

## 6. 给 Hermes 用

推荐直接把 `toolhub-mcp` 接到 Hermes。

最简单的配置方式：

```bash
hermes mcp add toolhub --url http://127.0.0.1:8766/mcp
hermes mcp test toolhub
hermes mcp list
```

如果 Hermes gateway 正在运行，可以在对话里执行：

```text
/reload-mcp
```

或者直接重启 Hermes gateway。

接好后，Hermes 会自动发现这些工具：

- `mcp_toolhub_toolhub_health`
- `mcp_toolhub_list_conversion_targets`
- `mcp_toolhub_convert_file`
- `mcp_toolhub_convert_batch`

这时候你就可以直接对 Hermes 说：

```text
把 /home/shinku/data/service/tool/agent-tools-gateway/tool-work/input/example.png 转成 jpg
```

或者：

```text
先看看 png 支持转成什么格式
```

## 7. 给 OpenClaw 用

可以把同一个 MCP 服务挂到 OpenClaw：

```bash
openclaw mcp set toolhub '{"url":"http://127.0.0.1:8766/mcp","transport":"streamable-http","connectionTimeout":10000}'
```

如果 OpenClaw 本身跑在 Docker 里，需要额外处理宿主机访问问题。

## 8. setup.sh 集成

当前 `/home/shinku/data/setup.sh` 已经包含这一段：

```bash
cd /home/shinku/data/service/tool/agent-tools-gateway
docker compose up -d convertx toolhub-api toolhub-mcp
```

所以之后执行：

```bash
/home/shinku/data/setup.sh
```

会自动把整个 Agent Tools Gateway 拉起来。

## 9. 常见报错

### 9.1 `input path is outside allowed roots`

说明输入文件不在白名单目录里。

解决方法：把文件移动或复制到：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/input
```

### 9.2 `output path is outside allowed roots`

说明输出目录不在白名单目录里。

解决方法：把 `output_dir` 改到：

```text
/home/shinku/data/service/tool/agent-tools-gateway/tool-work/output
```

或者直接不传 `output_dir`。

### 9.3 `ConvertX job did not finish before timeout`

说明上游转换超时，通常是：

- 文件太大
- 格式太复杂
- ConvertX 自身卡住

可以先检查 ConvertX 日志：

```bash
docker compose logs -f convertx
```

### 9.4 服务端口不通

先看容器是不是都起来了：

```bash
docker compose ps
```

再测健康检查：

```bash
curl http://127.0.0.1:3000/healthcheck
curl http://127.0.0.1:8765/health
```

## 10. 设计原则

这个仓库的设计目标是：

- 不 vendoring ConvertX 源码
- 固定 ConvertX Docker 镜像版本
- 对 agent 暴露稳定的 MCP / REST 接口
- 把路径白名单、安全解包、上游页面细节都封装在网关里

这样以后即使后端不再是 ConvertX，而换成 FFmpeg、ImageMagick、OCR 或其他本地工具，上层 agent 的调用方式也可以尽量保持不变。
