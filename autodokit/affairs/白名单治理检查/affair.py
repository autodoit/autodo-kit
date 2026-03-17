"""白名单治理检查事务。"""

from __future__ import annotations

from pathlib import Path

from autodokit.tools import load_json_or_py, write_affair_json_result


def check_whitelist(requested_scopes: list[str], approved_scopes: list[str], operator: str, change_reason: str) -> dict:
    """检查申请范围是否越权。"""

    if not operator.strip():
        raise ValueError("operator 不能为空")
    if not change_reason.strip():
        raise ValueError("change_reason 不能为空")
    requested = {scope.strip() for scope in requested_scopes if scope.strip()}
    approved = {scope.strip() for scope in approved_scopes if scope.strip()}
    overreach = sorted(requested - approved)
    retained = sorted(requested & approved)
    return {
        "status": "PASS" if not overreach else "BLOCKED",
        "mode": "whitelist-governance-check",
        "result": {
            "operator": operator,
            "change_reason": change_reason,
            "requested_scopes": sorted(requested),
            "approved_scopes": sorted(approved),
            "retained_scopes": retained,
            "overreach_scopes": overreach,
            "release_decision": "allow" if not overreach else "deny",
            "rollback_suggestion": "恢复至上一个已签发白名单版本并重新提交审批。" if overreach else "无需回滚。"
        }
    }


def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = check_whitelist(
        requested_scopes=list(raw_cfg.get("requested_scopes") or []),
        approved_scopes=list(raw_cfg.get("approved_scopes") or []),
        operator=str(raw_cfg.get("operator") or ""),
        change_reason=str(raw_cfg.get("change_reason") or ""),
    )
    return write_affair_json_result(raw_cfg, config_path, "whitelist_governance_check_result.json", result)
