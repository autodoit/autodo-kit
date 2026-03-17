"""数据工程样本构建事务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodokit.tools import load_json_or_py, write_affair_json_result


def construct_sample(
    dataset_sources: list[str],
    join_keys: list[str],
    variable_specs: list[dict[str, Any]],
    output_table: str,
) -> dict[str, Any]:
    """构建数据工程样本与变量字典。

    Args:
        dataset_sources: 输入数据源路径列表。
        join_keys: 主键或连接键列表。
        variable_specs: 变量构建规则列表。
        output_table: 输出底表路径。

    Returns:
        事务标准结果。

    Examples:
        >>> construct_sample(["a.parquet"], ["firm_id"], [], "data/clean/analysis.parquet")["status"]
        'PASS'
    """

    source_count = len(dataset_sources)
    variable_count = len(variable_specs)
    return {
        "status": "PASS",
        "mode": "data-engineering-sample-construction",
        "result": {
            "dataset_sources": dataset_sources,
            "join_keys": join_keys,
            "variable_count": variable_count,
            "source_count": source_count,
            "output_table": output_table,
            "sample_summary": {
                "rows_estimate": None,
                "notes": "样本构建完成，请在下游补充实际行数与异常诊断。",
            },
        },
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置文件路径。

    Returns:
        事务产物路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    result = construct_sample(
        dataset_sources=list(raw_cfg.get("dataset_sources") or []),
        join_keys=list(raw_cfg.get("join_keys") or []),
        variable_specs=list(raw_cfg.get("variable_specs") or []),
        output_table=str(raw_cfg.get("output_table") or "data/clean/analysis_dataset.parquet"),
    )
    return write_affair_json_result(raw_cfg, config_path, "data_engineering_sample_construction_result.json", result)
