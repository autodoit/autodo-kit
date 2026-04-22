# zotero-tools

本目录用于承载 AOK 对接 Zotero MCP 的基础程序。

## 目录结构

- `cookjohn-bridge/`: 对接 `third_party/zotero-mcp-cookjohn` 的基础程序（HTTP MCP）。
- `54yyyu-bridge/`: 对接 `third_party/zotero-mcp-54yyyu` 的基础程序（MCP 服务探活 + HTTP 调用骨架）。

## 设计原则

1. 仅放最小对接层，不直接承载事务编排逻辑。
2. 所有路径输入优先使用绝对路径。
3. 对外返回统一 `ok/error/data` 风格字典，便于后续并入 AOK facade。
