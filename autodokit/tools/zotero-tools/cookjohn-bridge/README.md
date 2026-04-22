# cookjohn-bridge

对接 `cookjohn/zotero-mcp`（Zotero 插件内置 MCP HTTP 服务）的 AOK 基础程序。

## 依赖前置

1. 已安装 Zotero 与 `zotero-mcp` 插件。
2. 插件内 MCP 服务已启用（默认 `http://127.0.0.1:23120/mcp`）。

## 文件说明

- `config.template.json`: 配置模板。
- `mcp_http_client.py`: 最小 MCP HTTP 客户端。
- `pull_from_zotero.py`: 从 Zotero MCP 拉取条目/注释示例。
- `push_to_zotero.py`: 向 Zotero MCP 写入标签/元数据示例。
