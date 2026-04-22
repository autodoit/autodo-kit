# 54yyyu-bridge

对接 `54yyyu/zotero-mcp` 的 AOK 基础程序。

## 依赖前置

1. `third_party/zotero-mcp-54yyyu` 已下载。
2. 已通过 `zotero-mcp serve` 启动 MCP 服务（推荐 `streamable-http`）。

示例启动命令（在 54yyyu 仓库目录）：

```bash
zotero-mcp serve --transport streamable-http --host 127.0.0.1 --port 8000
```

## 文件说明

- `config.template.json`: 配置模板。
- `mcp_http_client.py`: 最小 HTTP MCP 客户端。
- `service_probe.py`: 服务探活与工具列表探测。
- `pull_from_zotero.py`: 拉取示例。
- `push_to_zotero.py`: 写入示例。
