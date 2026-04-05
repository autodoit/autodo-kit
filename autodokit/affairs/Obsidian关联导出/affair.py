"""事务：Obsidian 关联导出。

该事务用于把主笔记及其关联笔记/附件打包导出，支持 dry-run 预览。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autodokit.tools import load_json_or_py
from autodokit.tools.obsidian_exporter import export_obsidian_note_with_links


@dataclass
class ObsidianExportConfig:
    """Obsidian 关联导出事务配置。

    Attributes:
        vault_root_dir: Obsidian Vault 根目录绝对路径。
        main_note_file: 主笔记绝对路径。
        output_dir: 导出目录绝对路径。
        dry_run: 是否仅输出导出计划。
        overwrite: 导出目标存在时是否覆盖。
        fail_on_missing: 遇到未解析链接是否直接失败。
        output_manifest: 导出清单 JSON 路径（可选）。
        output_log: 事务日志路径（可选）。
    """

    vault_root_dir: str
    main_note_file: str
    output_dir: str
    dry_run: bool = True
    overwrite: bool = False
    fail_on_missing: bool = False
    output_manifest: str | None = None
    output_log: str | None = None


def _require_abs(path_text: str, *, field_name: str, must_exist: bool, expect_dir: bool | None = None) -> Path:
    """校验绝对路径。

    Args:
        path_text: 路径字符串。
        field_name: 字段名。
        must_exist: 是否要求存在。
        expect_dir: 是否要求为目录，None 表示不校验类型。

    Returns:
        Path: 解析后的绝对路径。

    Raises:
        ValueError: 路径非法或类型不匹配。
    """

    if not isinstance(path_text, str) or not path_text.strip():
        raise ValueError(f"{field_name} 为空")
    path_obj = Path(path_text)
    if not path_obj.is_absolute():
        raise ValueError(f"{field_name} 必须是绝对路径：{path_text!r}")
    resolved_path = path_obj.resolve()

    if must_exist and not resolved_path.exists():
        raise ValueError(f"{field_name} 不存在：{resolved_path}")

    if expect_dir is True and resolved_path.exists() and not resolved_path.is_dir():
        raise ValueError(f"{field_name} 必须是目录：{resolved_path}")
    if expect_dir is False and resolved_path.exists() and not resolved_path.is_file():
        raise ValueError(f"{field_name} 必须是文件：{resolved_path}")

    return resolved_path


def execute(config_path: Path) -> List[Path]:
    """事务入口。

    Args:
        config_path: 配置文件路径（json/py）。

    Returns:
        List[Path]: 产物路径列表（manifest 与可选日志）。

    Raises:
        ValueError: 配置非法。
        RuntimeError: 导出执行失败。
    """

    raw_cfg: Dict[str, Any] = dict(load_json_or_py(config_path))
    cfg = ObsidianExportConfig(
        vault_root_dir=str(raw_cfg.get("vault_root_dir") or ""),
        main_note_file=str(raw_cfg.get("main_note_file") or ""),
        output_dir=str(raw_cfg.get("output_dir") or ""),
        dry_run=bool(raw_cfg.get("dry_run", True)),
        overwrite=bool(raw_cfg.get("overwrite", False)),
        fail_on_missing=bool(raw_cfg.get("fail_on_missing", False)),
        output_manifest=str(raw_cfg.get("output_manifest") or "").strip() or None,
        output_log=str(raw_cfg.get("output_log") or "").strip() or None,
    )

    vault_root = _require_abs(cfg.vault_root_dir, field_name="vault_root_dir", must_exist=True, expect_dir=True)
    main_note = _require_abs(cfg.main_note_file, field_name="main_note_file", must_exist=True, expect_dir=False)
    output_dir = _require_abs(cfg.output_dir, field_name="output_dir", must_exist=False, expect_dir=None)

    output_log_path: Path | None = None
    if cfg.output_log:
        output_log_path = _require_abs(cfg.output_log, field_name="output_log", must_exist=False, expect_dir=None)
        output_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(line: str) -> None:
        print(line)
        if output_log_path is not None:
            with output_log_path.open("a", encoding="utf-8") as writer:
                writer.write(line.rstrip("\n") + "\n")

    _log(f"dry_run={cfg.dry_run}")
    _log(f"vault_root_dir={vault_root}")
    _log(f"main_note_file={main_note}")
    _log(f"output_dir={output_dir}")
    _log(f"overwrite={cfg.overwrite}")
    _log(f"fail_on_missing={cfg.fail_on_missing}")

    result = export_obsidian_note_with_links(
        vault_root=vault_root,
        main_note_file=main_note,
        output_dir=output_dir,
        dry_run=cfg.dry_run,
        overwrite=cfg.overwrite,
        fail_on_missing=cfg.fail_on_missing,
    )

    _log(f"planned_files={len(result.planned_files)}")
    _log(f"missing_targets={len(result.missing_targets)}")
    if not cfg.dry_run:
        _log(f"copied_files={len(result.copied_files)}")

    manifest_path = (
        _require_abs(cfg.output_manifest, field_name="output_manifest", must_exist=False, expect_dir=None)
        if cfg.output_manifest
        else (output_dir / "obsidian_export_manifest.json").resolve()
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    outputs: List[Path] = [manifest_path]
    if output_log_path is not None:
        outputs.append(output_log_path)
    return outputs


def main() -> None:
    """命令行入口。

    Returns:
        None
    """

    import sys

    if len(sys.argv) < 2:
        raise SystemExit("用法：python Obsidian关联导出.py <config_path>")
    for output_path in execute(Path(sys.argv[1])):
        print(output_path)


if __name__ == "__main__":
    main()

