# autodo-kit

autodo-kit 是 AOK 的官方事务内容库，仓库主体仅保留两类内容：

- autodokit/affairs：官方预置事务与图节点事务
- autodokit/tools：供事务复用的工具函数

运行时调度、任务数据库、流程图执行与 CLI 已拆分到 autodo-engine。本仓库不再提供独立 CLI 入口。

## 安装关系

建议与 autodo-engine 一起安装：

```powershell
uv pip install -e ../autodo-engine
uv pip install -e .
```

安装后：

- 使用 autodoengine.main 运行流程
- 使用 autodokit.run_affair(...) 或 autodoengine.api.run_affair(...) 直调事务
- 使用 scripts/generate_affair_manual.py 重新生成事务总手册

## 仓库结构

```text
autodokit/
  affairs/   官方事务实现
  tools/     事务侧工具
scripts/
  generate_affair_manual.py
  aob_tools/  承接 AOB 迁移过来的执行入口
```

## AOB 迁移承接入口

为收敛 AOB 的执行型入口，AOK 现承接以下脚本型能力：

- `scripts/aob_tools/aoc.py`
- `scripts/aob_tools/deploy.py`
- `scripts/aob_tools/library.py`
- `scripts/aob_tools/regression_opencode_deploy_check.py`
- `scripts/run_items_sync.py`
- `scripts/run_external_templates_import.py`
- `scripts/run_workflow_deploy.py`

说明：

- `autodo-lib/tools/*.py` 与 `autodo-lib/scripts/run_*.py` 已保留为兼容壳；
- 历史命令仍可继续使用，但新的规范主入口位于 `autodo-kit/scripts/` 与 `autodo-kit/scripts/aob_tools/`。

## 工具导出管理

AOK 工具采用“函数直调 + 集中导出”方式：

- 用户公开工具：`from autodokit.tools import <tool_name>`
- 用户工具清单：`autodokit.tools.list_user_tools()`
- 开发者工具清单：`autodokit.tools.list_developer_tools()`
- 按名称取工具：`autodokit.tools.get_tool(name, scope='user'|'developer'|'all')`

说明：

- 公开/非公开由 `autodokit/tools/__init__.py` 的分组清单统一管理。
- 工具参数与返回保持自然函数签名，便于 IDE 形参提示与自动补全。

## 常用操作

生成事务手册：

```powershell
python scripts/generate_affair_manual.py
```

直调事务：

```python
from pathlib import Path
import autodokit as aok

outputs = aok.run_affair(
    "Word转LaTeX",
    config={"input_docx": "input/demo.docx", "output_dir": "output/demo"},
    workspace_root=Path.cwd(),
)
print(outputs)
```

直调工具（示例）：

```python
from autodokit.tools import parse_reference_text

result = parse_reference_text("Smith, 2024. Example Title.")
print(result)
```

demos 脚本（可直接运行）：

```powershell
python demos/scripts/demo_tool_user_import_call.py
python demos/scripts/demo_tool_developer_get_tool_call.py
python demos/scripts/demo_tool_cli_call.py
```

## 边界说明

- 本仓库不再承载 core、flow_graph、scheduling、taskdb、utils 等引擎实现。
- 事务中的路径预处理仍由 autodo-engine 的统一能力完成，事务本体尽量不内嵌路径转换逻辑。
- docs/AOK预置事务手册.md 由脚本生成，变更事务后应同步刷新。
