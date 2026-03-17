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
```

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

## 边界说明

- 本仓库不再承载 core、flow_graph、scheduling、taskdb、utils 等引擎实现。
- 事务中的路径预处理仍由 autodo-engine 的统一能力完成，事务本体尽量不内嵌路径转换逻辑。
- docs/AOK预置事务手册.md 由脚本生成，变更事务后应同步刷新。
