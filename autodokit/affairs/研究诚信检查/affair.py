"""研究诚信检查事务。

执行最小可复用的文本扫描规则，识别疑似密钥硬编码与私钥片段。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List

from autodokit.tools import load_json_or_py

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("疑似 API Key", re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[\"'][^\"']+[\"']")),
    ("疑似私钥片段", re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----")),
)
_DEFAULT_EXTENSIONS: tuple[str, ...] = (".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt")


@dataclass(slots=True, frozen=True)
class IntegrityCheckFinding:
    """诚信检查命中项。

    Args:
        rule: 命中规则名。
        file: 文件路径。
        snippet: 命中片段。
    """

    rule: str
    file: str
    snippet: str


@dataclass(slots=True, frozen=True)
class IntegrityCheckResult:
    """诚信检查结果。

    Args:
        project_root: 扫描根目录。
        scanned_files: 已扫描文件数。
        finding_count: 命中总数。
        findings: 命中明细。
    """

    project_root: str
    scanned_files: int
    finding_count: int
    findings: tuple[IntegrityCheckFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        """导出为可序列化字典。

        Returns:
            可序列化结果。
        """

        return {
            "project_root": self.project_root,
            "scanned_files": self.scanned_files,
            "finding_count": self.finding_count,
            "findings": [asdict(item) for item in self.findings],
        }


class IntegrityCheckEngine:
    """研究诚信检查引擎。"""

    def run(
        self,
        project_root: str | Path,
        strict: bool = False,
        include_extensions: list[str] | None = None,
    ) -> tuple[str, IntegrityCheckResult]:
        """执行研究诚信检查。

        Args:
            project_root: 待扫描根目录。
            strict: 严格模式下有命中则阻断。
            include_extensions: 可选扫描后缀列表。

        Returns:
            `(status, result)` 元组。

        Raises:
            FileNotFoundError: 根目录不存在时抛出。
        """

        root = Path(project_root).resolve()
        if not root.exists():
            raise FileNotFoundError(f"项目根目录不存在: {root}")

        extensions = tuple((item if item.startswith(".") else f".{item}").lower() for item in (include_extensions or list(_DEFAULT_EXTENSIONS)))
        findings: list[IntegrityCheckFinding] = []
        scanned = 0

        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in extensions:
                continue
            scanned += 1
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for rule_name, pattern in _SECRET_PATTERNS:
                for match in pattern.finditer(content):
                    findings.append(
                        IntegrityCheckFinding(
                            rule=rule_name,
                            file=str(file_path),
                            snippet=match.group(0)[:120],
                        )
                    )

        result = IntegrityCheckResult(
            project_root=str(root),
            scanned_files=scanned,
            finding_count=len(findings),
            findings=tuple(findings),
        )
        status = "BLOCKED" if strict and findings else "PASS"
        return status, result


def execute(config_path: Path) -> List[Path]:
    """事务执行入口。

    Args:
        config_path: 事务配置路径。

    Returns:
        输出文件路径列表。
    """

    raw_cfg = load_json_or_py(config_path)
    status, result = IntegrityCheckEngine().run(
        project_root=str(raw_cfg.get("project_root") or "."),
        strict=bool(raw_cfg.get("strict") or False),
        include_extensions=raw_cfg.get("include_extensions"),
    )

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "integrity_check_result.json"
    out_path.write_text(
        json.dumps({"status": status, "result": result.to_dict()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return [out_path]
