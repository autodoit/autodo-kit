# 快速开始

## 安装文档依赖

```powershell
uv pip install --python .venv/Scripts/python.exe -r docs/sphinx/requirements.txt
```

## 生成预置事务手册

```powershell
~/CoreFiles/ProjectsFile/autodo-kit/.venv/Scripts/python.exe scripts/generate_affair_manual.py
```

## 生成预置事务手册

```powershell
~/CoreFiles/ProjectsFile/autodo-kit/.venv/Scripts/python.exe scripts/generate_affair_manual.py
```

## 通过 Python 直调事务

```python
from pathlib import Path
import autodokit as aok

aok.run_affair(
	"Word转LaTeX",
	config={"input_docx": "data/demo.docx", "output_dir": "output/demo"},
	workspace_root=Path.cwd(),
)
```

## 构建 Sphinx HTML

```powershell
~/CoreFiles/ProjectsFile/autodo-kit/.venv/Scripts/python.exe -m sphinx -b html docs/sphinx docs/sphinx/_build/html
```
