# Zotero RDF → A020 增量导入工具

概述
- 位置: `autodokit/tools/zotero_rdf_to_a020_incremental_import_tools.py`
- 导出函数: `convert_zotero_rdf_to_a020_incremental_package(payload)`（通过 `autodokit.tools` 可直接调用）

目的
- 将 Zotero 导出的 RDF 包预处理为 A020 增量导入可消费的输入包（CSV + manifest + 日志），不直接写入 `content.db`。

主要功能
- 解析 Zotero RDF（metadata + 附件引用）。
- 基于 cite-key / DOI / 标题-年份-作者优先匹配现有 `content.db` 条目，复用 `uid_literature`。若无法匹配则生成稳定的新 UID。
- 解析并解析附件文件路径（支持共享附件、多附件），产生 `literature_files.csv` 关系行，并标注主附件。
- 输出文件清单：
  - `literature_items.csv` — 文献条目（A020 可消费格式）
  - `literature_files.csv` — 附件关系表
  - `literature-manifest.json` — 包元信息与来源映射
  - `run_log.txt` / `run_summary.md` — 运行日志与摘要
  - `unmatched_items.json` — 未匹配或需人工核查的条目

示例用法（Python）
```
from autodokit.tools import convert_zotero_rdf_to_a020_incremental_package

payload = {
    "rdf_path": "path/to/zotero_export.rdf",
    "attachments_root": "path/to/attachments",
    "output_dir": "path/to/output_dir",
}

convert_zotero_rdf_to_a020_incremental_package(payload)
```

测试说明
- 推荐在项目虚拟环境下运行回归测试：
```
cd C:\Users\Ethan\CoreFiles\ProjectsFile\AcademicResearch-auto-workflow
.\.venv\Scripts\python.exe -m pytest tests/test_zotero_rdf_to_a020_incremental_import_tools.py -q
```

注意事项
- 本工具为预处理器，A020 事务（导入实际写入 `content.db`）不在此工具内修改。
- 技能 frontmatter 的 `name` 字段需为 ASCII kebab-case（例如 `zotero-rdf-to-a020-incremental-import-v1`），否则平台验证可能失败；但文档标题与文件路径可以保留中文。

建议
- 如需命令行运行，可为该模块添加一个轻量 CLI wrapper（`scripts/` 下）并在本说明中补充示例。

维护
- 作者: 实现者
- 上次更新: 2026-04-21
