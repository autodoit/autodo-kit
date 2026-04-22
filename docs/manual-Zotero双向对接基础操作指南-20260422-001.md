---
title: Zotero双向对接基础操作指南
date: 2026-04-22
tags:
  - manual
  - zotero
  - aok
  - mcp
aliases:
  - Zotero 对接操作手册
  - zotero-tools 使用说明
---

# manual-Zotero双向对接基础操作指南-20260422-001

## 目标

这份手册说明如何验证 `autodo-kit/autodokit/tools/zotero-tools` 下的两套桥接程序：

- `cookjohn-bridge`：对接 `cookjohn/zotero-mcp`
- `54yyyu-bridge`：对接 `54yyyu/zotero-mcp`

目标不是一次性完成完整业务集成，而是先把最小联通链路跑通：

1. `cookjohn` 侧能发出 `search_library` / `search_annotations` 调用。
2. `54yyyu` 侧能完成服务探活，并读到 `tools/list` 返回。

## 目录位置

- AOK 工具目录：[`autodo-kit/autodokit/tools/zotero-tools`](../autodokit/tools/zotero-tools)
- cookjohn 桥接目录：[`autodo-kit/autodokit/tools/zotero-tools/cookjohn-bridge`](../autodokit/tools/zotero-tools/cookjohn-bridge)
- 54yyyu 桥接目录：[`autodo-kit/autodokit/tools/zotero-tools/54yyyu-bridge`](../autodokit/tools/zotero-tools/54yyyu-bridge)
- 第三方源码目录：[`autodo-kit/third_party`](../third_party)

## 你可以先做的事

我已经完成的部分：

- 建好两个桥接目录。
- 写好两个最小 HTTP 客户端。
- 写好拉取与推送示例脚本。
- 写好 54yyyu 的服务探活脚本。

你需要手动做的部分：

- 启动 `54yyyu/zotero-mcp` 的 MCP HTTP 服务。
- 确保本机 Zotero 和对应插件/服务配置满足该仓库的启动要求。
- 如需真实读写数据，先在 Zotero 里确认已登录、库可访问、服务端口未被占用。

## cookjohn 联通步骤

### 1. 进入桥接目录

打开 PowerShell，进入目录：

```powershell
Set-Location "c:\Users\Ethan\CoreFiles\ProjectsFile\autodo-kit\autodokit\tools\zotero-tools\cookjohn-bridge"
```

### 2. 修改配置模板

把 `config.template.json` 复制为实际配置文件，例如 `config.json`，然后修改 `endpoint`：

- 默认模板地址是 `http://127.0.0.1:23120/mcp`
- 如果 cookjohn 服务实际端口不同，以你本机实际端口为准

### 3. 在 Zotero 里启用 cookjohn 的服务

`cookjohn/zotero-mcp` 也是插件内置 MCP 服务路线。你需要先在 Zotero 里把插件装好并启用服务：

1. 打开 Zotero。
2. 安装 `zotero-mcp-plugin`。
3. 在 `Preferences -> Zotero MCP Plugin` 里启用 `Enable Server`。
4. 确认端口配置与脚本里的 `endpoint` 一致，默认常见是 `23120`。

如果服务没有启用，`pull_from_zotero.py` 会直接报连接失败，这是正常现象，不是脚本本身的问题。

### 4. 运行拉取脚本

```powershell
python pull_from_zotero.py
```

预期结果：

- 第一段输出是 `search_library` 的返回值。
- 第二段输出是 `search_annotations` 的返回值。
- 如果服务正常但没有命中数据，返回通常也是结构化结果，只是条目为空。

### 5. 需要时运行写入脚本

```powershell
python push_to_zotero.py
```

预期结果：

- 会尝试调用 `write_tag` 和 `write_metadata`。
- 如果当前 cookjohn 服务没有实现这两个工具，会返回明确的错误信息。

## 54yyyu 联通步骤

### 1. 进入桥接目录

```powershell
Set-Location "c:\Users\Ethan\CoreFiles\ProjectsFile\autodo-kit\autodokit\tools\zotero-tools\54yyyu-bridge"
```

### 2. 在 Zotero 里启用插件内置服务

`54yyyu/zotero-mcp` 的当前架构是插件内置 MCP 服务，不需要单独再起一个独立后端进程。你需要做的是：

1. 打开 Zotero。
2. 安装 `zotero-mcp-plugin`。
3. 在 `Preferences -> Zotero MCP Plugin` 里启用 `Enable Server`。
4. 确认端口是 `23120`，或者改成你实际配置的端口。
5. 如插件提供 `Generate Client Configuration`，可先导出客户端配置备用。

如果你当前还没装好插件，那就先按仓库 README 的安装步骤完成安装，再回来执行探活。

### 3. 回到桥接目录执行探活

```powershell
Set-Location "c:\Users\Ethan\CoreFiles\ProjectsFile\autodo-kit\autodokit\tools\zotero-tools\54yyyu-bridge"
python service_probe.py
```

预期结果：

- 返回 `ok: True`
- `tool_count` 大于 0
- 说明服务已经能被桥接层读到 `tools/list`

### 4. 需要时运行拉取与写入示例

```powershell
python pull_from_zotero.py
python push_to_zotero.py
```

预期结果：

- 拉取脚本会尝试调用 `zotero_search_items` 和 `zotero_search_notes`
- 写入脚本会尝试调用 `zotero_add_by_doi` 和 `zotero_update_item`

## 故障判断

### 情况 1：连接失败

常见原因：

- MCP 服务没有启动
- 端口不对
- `endpoint` 配置不匹配
- 防火墙或代理拦截

处理方式：

- 先看服务端控制台是否启动成功
- 再确认 `config.template.json` 里的 `endpoint`
- 必要时把端口改成服务实际监听端口

### 情况 2：返回工具不存在

常见原因：

- 当前仓库没有提供该工具名
- MCP 版本与脚本里使用的工具名不一致

处理方式：

- 先执行 `service_probe.py` 看 `tools/list`
- 根据实际工具名改 `pull_from_zotero.py` 或 `push_to_zotero.py`

### 情况 3：有服务但没有数据

常见原因：

- Zotero 库本身为空
- 查询关键词不匹配
- 权限或索引尚未就绪

处理方式：

- 先用更简单的关键词测试
- 再检查 Zotero 本地库是否能正常搜索

## 后续接入建议

如果这一步联通成功，下一步建议把两套桥接再往上收敛成统一的 AOK facade：

- 统一输入参数结构
- 统一返回结构
- 统一错误码/错误文本
- 统一把 `cookjohn` 与 `54yyyu` 的能力暴露给上层工具
