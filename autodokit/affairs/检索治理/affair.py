"""检索治理事务。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from autodokit.tools import load_json_or_py
from autodokit.tools.atomic.task_aok.post_affair_git_commit import affair_auto_git_commit

ObjectType = Literal["literature", "dataset"]
SourceType = Literal["offline", "online"]
RegionType = Literal["domestic", "global"]
AccessType = Literal["open", "closed"]
PermissionStatus = Literal["approved", "manual_required", "blocked"]


@dataclass(slots=True, frozen=True)
class RetrievalRequest:
    """检索请求。"""

    request_uid: str
    object_type: ObjectType
    source_type: SourceType
    region_type: RegionType
    access_type: AccessType
    query: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RetrievalBundle:
    """检索 bundle。"""

    bundle_id: str
    object_type: ObjectType
    source_type: SourceType
    file_paths: tuple[str, ...]
    manifest_patch: dict[str, Any]
    permission_status: PermissionStatus
    result_code: str


@dataclass(slots=True)
class RetrievalGovernanceEngine:
    """检索治理引擎。"""

    def process_request(self, request: RetrievalRequest) -> RetrievalBundle:
        """按统一状态机处理检索请求。"""

        permission_status = self.evaluate_permission(request=request)
        result_code: str = "PASS"
        if permission_status in {"manual_required", "blocked"}:
            result_code = "BLOCKED"

        file_paths: tuple[str, ...] = tuple(request.metadata.get("file_paths", []))
        manifest_patch = {
            "request_uid": request.request_uid,
            "query": request.query,
            "object_type": request.object_type,
            "source_type": request.source_type,
            "region_type": request.region_type,
            "access_type": request.access_type,
        }
        return RetrievalBundle(
            bundle_id=f"bundle-{uuid4().hex}",
            object_type=request.object_type,
            source_type=request.source_type,
            file_paths=file_paths,
            manifest_patch=manifest_patch,
            permission_status=permission_status,
            result_code=result_code,
        )

    def evaluate_permission(self, request: RetrievalRequest) -> PermissionStatus:
        """评估授权状态。"""

        if request.access_type == "closed":
            return "manual_required"
        if request.metadata.get("deny", False):
            return "blocked"
        return "approved"


@dataclass(slots=True)
class RetrievalRouter:
    """检索结果路由器。"""

    def route_bundle(self, bundle: RetrievalBundle) -> str:
        """根据 bundle 决定后续流向。"""

        if bundle.result_code == "BLOCKED":
            return "manual_review_queue"
        if bundle.object_type == "literature":
            return "reference_ingestion"
        return "dataset_ingestion"


def default_retrieval_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """默认检索处理器。"""

    request = RetrievalRequest(
        request_uid=str(payload.get("request_uid") or f"request-{uuid4().hex}"),
        object_type=payload.get("object_type", "literature"),
        source_type=payload.get("source_type", "online"),
        region_type=payload.get("region_type", "global"),
        access_type=payload.get("access_type", "open"),
        query=str(payload.get("query") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )
    engine = RetrievalGovernanceEngine()
    router = RetrievalRouter()
    bundle = engine.process_request(request=request)
    return {
        "bundle": asdict(bundle),
        "next_node": router.route_bundle(bundle=bundle),
    }


@affair_auto_git_commit("A040")
def execute(config_path: Path) -> list[Path]:
    """事务执行入口。"""

    raw_cfg = load_json_or_py(config_path)
    result = default_retrieval_handler(
        {
            "request_uid": str(raw_cfg.get("request_uid") or f"request-{uuid4().hex}"),
            "query": str(raw_cfg.get("query") or ""),
            "object_type": raw_cfg.get("object_type", "literature"),
            "source_type": raw_cfg.get("source_type", "online"),
            "region_type": raw_cfg.get("region_type", "global"),
            "access_type": raw_cfg.get("access_type", "open"),
            "metadata": dict(raw_cfg.get("metadata") or {}),
        }
    )

    output_dir = Path(str(raw_cfg.get("output_dir") or config_path.parent))
    if not output_dir.is_absolute():
        raise ValueError(
            "output_dir 必须为绝对路径：请确认已在 tools 层完成统一路径预处理，"
            f"当前值={str(raw_cfg.get('output_dir') or '')!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "retrieval_governance_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return [out_path]
