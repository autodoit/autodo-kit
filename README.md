# autodo-kit

autodo-kit 是 AOK 的官方事务与工具仓库，当前承担两类职责：

- autodokit/affairs：官方预置事务与图节点事务
- autodokit/tools：事务侧复用工具，以及 AOB 历史执行能力的统一 API

autodo-kit 现已内置最小运行时，可在未安装 autodo-engine 时直接执行官方事务（`autodokit.run_affair(...)`）。
若安装 autodo-engine，可继续复用其完整调度与工作流能力。

## 安装关系

最小安装（仅使用 autodo-kit 内置事务运行时）：

```powershell
uv pip install -e .
```

可选增强安装（需要引擎调度能力时）：

```powershell
uv pip install -e ../autodo-engine
uv pip install -e .
```

安装后可使用：

- autodokit.run_affair(...) 直调事务
- autodoengine.main 运行流程（可选）
- autodokit.tools 中的统一工具 API

## 仓库结构

```text
autodokit/
  affairs/   官方事务实现
  tools/     事务侧工具与 AOB 迁移 API
scripts/
  generate_affair_manual.py
  aob_tools/ AOB CLI 薄入口
  run_*.py   常用一键运行薄入口
```

## AOB 迁移承接入口

AOB 历史执行能力已经统一收敛到 autodokit.tools，并通过以下脚本作为薄入口暴露：

- scripts/aob_tools/aoc.py
- scripts/aob_tools/deploy.py
- scripts/aob_tools/library.py
- scripts/aob_tools/regression_opencode_deploy_check.py
- scripts/run_items_sync.py
- scripts/run_external_templates_import.py
- scripts/run_workflow_deploy.py

对应的推荐调用方式：

- Python 直调：from autodokit.tools import run_aob_deploy 等 API
- CLI 调用：使用本仓库 scripts 下的薄入口脚本

autodo-lib 已切换为静态内容仓，不再保留可执行兼容壳。

## 工具导出管理

AOK 工具采用“函数直调 + 集中导出”方式：

- 用户公开工具：from autodokit.tools import <tool_name>
- 用户工具清单：autodokit.tools.list_user_tools()
- 开发者工具清单：autodokit.tools.list_developer_tools()
- 按名称取工具：autodokit.tools.get_tool(name, scope='user'|'developer'|'all')

公开/非公开由 autodokit/tools/__init__.py 的分组清单统一管理。

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

直调 AOB 迁移工具：

```python
from autodokit.tools import run_aob_workflow_deploy

exit_code = run_aob_workflow_deploy(
    workflow_id="academic",
    engine_ids=["claude"],
    target_dir=r"D:\ProjectS",
    dry_run=True,
)
print(exit_code)
```

## 边界说明

- 本仓库不承载 core、flow_graph、scheduling、taskdb、utils 等引擎实现。
- 事务中的路径预处理仍由 autodo-engine 的统一能力完成，事务本体尽量不内嵌路径转换逻辑。
- docs/AOK预置事务手册.md 由脚本生成，变更事务后应同步刷新。
