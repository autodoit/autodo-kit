"""CNKI 专项技能规划引擎。"""

from __future__ import annotations

from typing import Any, Literal

from autodokit.affairs.检索治理 import default_retrieval_handler

from .models import (
    CnkiAccessContract,
    CnkiInterruptReason,
    CnkiIssueArticle,
    CnkiIssueToc,
    CnkiJournalProfile,
    CnkiPaperDetailRecord,
    CnkiSearchCandidate,
    CnkiSkillPlan,
)

SortMode = Literal["relevance", "date", "citations", "downloads"]
NavigateAction = Literal["next", "previous", "page", "sort"]
ExportMode = Literal["zotero", "ris", "gb"]
DownloadFormat = Literal["pdf", "caj", "auto"]


class CnkiWorkflowPlanner:
    """CNKI 专项技能规划器。

    当前阶段不直接执行浏览器自动化，而是为 OpenCode 侧提供：

    1. 统一的规范化请求结构。
    2. 与检索治理对齐的授权判定结果。
    3. 面向后续页面执行器的结构化占位结果。
    """

    def build_search_plan(
        self,
        query: str,
        page: int = 1,
        sort_by: SortMode = "relevance",
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成基础检索计划。

        Args:
            query: 检索关键词。
            page: 页码。
            sort_by: 排序方式。
            access_type: 访问类型。
            metadata: 扩展元数据。

        Returns:
            结构化技能计划。
        """

        normalized_request = {
            "query": query.strip(),
            "page": max(page, 1),
            "sort_by": sort_by,
            "site": "cnki",
            "operation": "search",
        }
        placeholder = CnkiSearchCandidate(
            rank=1,
            title="",
            authors=(),
            journal="",
            date="",
            citations="",
            downloads="",
            result_url="",
            detail_url="",
            export_id="",
            availability_status="metadata_only",
        )
        plan = CnkiSkillPlan(
            mode="cnki-search",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=query,
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="search",
                access_type=access_type,
                downstream_node="cnki-paper-detail",
                structured_output_fields=(
                    "query",
                    "total",
                    "page",
                    "results",
                    "results[].title",
                    "results[].authors",
                    "results[].journal",
                    "results[].detail_url",
                    "results[].export_id",
                ),
            ),
            placeholder_result={
                "query": normalized_request["query"],
                "total": 0,
                "page": normalized_request["page"],
                "sort_by": sort_by,
                "results": [placeholder.to_dict()],
            },
        )
        return plan.to_dict()

    def build_advanced_search_plan(
        self,
        query: str,
        author: str = "",
        journal: str = "",
        start_year: str = "",
        end_year: str = "",
        source_types: list[str] | None = None,
        field_type: str = "SU",
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成高级检索计划。"""

        normalized_request = {
            "query": query.strip(),
            "author": author.strip(),
            "journal": journal.strip(),
            "start_year": start_year.strip(),
            "end_year": end_year.strip(),
            "source_types": tuple(source_types or ()),
            "field_type": field_type,
            "site": "cnki",
            "operation": "advanced-search",
        }
        plan = CnkiSkillPlan(
            mode="cnki-advanced-search",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=query,
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="advanced-search",
                access_type=access_type,
                downstream_node="cnki-parse-results",
                structured_output_fields=(
                    "query",
                    "field_type",
                    "author",
                    "journal",
                    "start_year",
                    "end_year",
                    "source_types",
                    "total",
                    "page",
                    "results",
                ),
            ),
            placeholder_result={
                "query": normalized_request["query"],
                "filters": {
                    "author": normalized_request["author"],
                    "journal": normalized_request["journal"],
                    "start_year": normalized_request["start_year"],
                    "end_year": normalized_request["end_year"],
                    "source_types": list(normalized_request["source_types"]),
                    "field_type": normalized_request["field_type"],
                },
                "total": 0,
                "page": 1,
                "results": [],
            },
        )
        return plan.to_dict()

    def build_parse_results_plan(
        self,
        page_url: str,
        current_page: int = 1,
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成结果页重解析计划。"""

        normalized_request = {
            "page_url": page_url.strip(),
            "current_page": max(current_page, 1),
            "site": "cnki",
            "operation": "parse-results",
        }
        plan = CnkiSkillPlan(
            mode="cnki-parse-results",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=page_url or "cnki-results-page",
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="parse-results",
                access_type=access_type,
                downstream_node="cnki-navigate-pages",
                structured_output_fields=(
                    "page_url",
                    "current_page",
                    "total",
                    "results",
                    "results[].detail_url",
                    "results[].export_id",
                ),
            ),
            placeholder_result={
                "page_url": normalized_request["page_url"],
                "current_page": normalized_request["current_page"],
                "total": 0,
                "results": [],
            },
        )
        return plan.to_dict()

    def build_navigate_pages_plan(
        self,
        action: NavigateAction,
        current_page: int = 1,
        target_page: int | None = None,
        sort_by: SortMode = "relevance",
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成翻页与排序计划。"""

        normalized_request = {
            "action": action,
            "current_page": max(current_page, 1),
            "target_page": max(target_page, 1) if target_page else None,
            "sort_by": sort_by,
            "site": "cnki",
            "operation": "navigate-pages",
        }
        plan = CnkiSkillPlan(
            mode="cnki-navigate-pages",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=f"cnki-navigation-{action}",
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="navigate-pages",
                access_type=access_type,
                downstream_node="cnki-parse-results",
                structured_output_fields=(
                    "action",
                    "current_page",
                    "target_page",
                    "sort_by",
                    "next_page_hint",
                ),
            ),
            placeholder_result={
                "action": action,
                "current_page": normalized_request["current_page"],
                "target_page": normalized_request["target_page"],
                "sort_by": sort_by,
                "next_page_hint": self._resolve_next_page_hint(
                    action=action,
                    current_page=normalized_request["current_page"],
                    target_page=normalized_request["target_page"],
                ),
            },
        )
        return plan.to_dict()

    def build_paper_detail_plan(
        self,
        detail_url: str,
        title_hint: str = "",
        export_id: str = "",
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成论文详情抽取计划。"""

        normalized_request = {
            "detail_url": detail_url.strip(),
            "title_hint": title_hint.strip(),
            "export_id": export_id.strip(),
            "site": "cnki",
            "operation": "paper-detail",
        }
        placeholder = CnkiPaperDetailRecord(
            title=normalized_request["title_hint"],
            authors=(),
            author_organizations=(),
            journal="",
            date="",
            abstract="",
            keywords=(),
            fund="",
            classification="",
            doi="",
            detail_url=normalized_request["detail_url"],
            export_id=normalized_request["export_id"],
        )
        plan = CnkiSkillPlan(
            mode="cnki-paper-detail",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=title_hint or detail_url or "cnki-paper-detail",
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="paper-detail",
                access_type=access_type,
                downstream_node="local-reference-ingestion",
                structured_output_fields=(
                    "title",
                    "authors",
                    "author_organizations",
                    "journal",
                    "date",
                    "abstract",
                    "keywords",
                    "fund",
                    "classification",
                    "doi",
                    "detail_url",
                    "export_id",
                ),
            ),
            placeholder_result=placeholder.to_dict(),
        )
        return plan.to_dict()

    def build_journal_search_plan(
        self,
        journal_query: str,
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成期刊检索计划。"""

        normalized_request = {
            "journal_query": journal_query.strip(),
            "site": "cnki",
            "operation": "journal-search",
        }
        placeholder = CnkiJournalProfile(
            journal_name_cn=normalized_request["journal_query"],
            journal_name_en="",
            issn="",
            cn_number="",
            sponsor="",
            frequency="",
            indexed_in=(),
            impact_composite="",
            impact_comprehensive="",
            detail_url="",
            toc_url="",
        )
        plan = CnkiSkillPlan(
            mode="cnki-journal-search",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=journal_query,
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="journal-search",
                access_type=access_type,
                downstream_node="cnki-journal-index",
                structured_output_fields=(
                    "journal_query",
                    "results",
                    "results[].journal_name_cn",
                    "results[].issn",
                    "results[].detail_url",
                ),
            ),
            placeholder_result={
                "journal_query": normalized_request["journal_query"],
                "results": [placeholder.to_dict()],
            },
        )
        return plan.to_dict()

    def build_journal_index_plan(
        self,
        journal_name: str,
        detail_url: str = "",
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成期刊收录与评价计划。"""

        normalized_request = {
            "journal_name": journal_name.strip(),
            "detail_url": detail_url.strip(),
            "site": "cnki",
            "operation": "journal-index",
        }
        placeholder = CnkiJournalProfile(
            journal_name_cn=normalized_request["journal_name"],
            journal_name_en="",
            issn="",
            cn_number="",
            sponsor="",
            frequency="",
            indexed_in=("北大核心", "CSSCI", "CSCD"),
            impact_composite="",
            impact_comprehensive="",
            detail_url=normalized_request["detail_url"],
            toc_url="",
        )
        plan = CnkiSkillPlan(
            mode="cnki-journal-index",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=journal_name or detail_url or "cnki-journal-index",
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="journal-index",
                access_type=access_type,
                downstream_node="knowledge-prescreen",
                structured_output_fields=(
                    "journal_name_cn",
                    "journal_name_en",
                    "issn",
                    "cn_number",
                    "sponsor",
                    "frequency",
                    "indexed_in",
                    "impact_composite",
                    "impact_comprehensive",
                    "detail_url",
                    "toc_url",
                ),
            ),
            placeholder_result=placeholder.to_dict(),
        )
        return plan.to_dict()

    def build_journal_toc_plan(
        self,
        journal_name: str,
        year: str,
        issue: str,
        download_original: bool = False,
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成刊期目录计划。"""

        normalized_request = {
            "journal_name": journal_name.strip(),
            "year": year.strip(),
            "issue": issue.strip(),
            "download_original": download_original,
            "site": "cnki",
            "operation": "journal-toc",
        }
        placeholder = CnkiIssueToc(
            journal_name=normalized_request["journal_name"],
            year=normalized_request["year"],
            issue=normalized_request["issue"],
            issue_label=f"{normalized_request['year']}年{normalized_request['issue']}",
            toc_url="",
            original_pdf_url="",
            articles=(
                CnkiIssueArticle(rank=1, title="", authors=(), pages="", detail_url=""),
            ),
        )
        plan = CnkiSkillPlan(
            mode="cnki-journal-toc",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=f"{journal_name} {year} {issue}".strip(),
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="journal-toc",
                access_type=access_type,
                downstream_node="cnki-paper-detail",
                structured_output_fields=(
                    "journal_name",
                    "year",
                    "issue",
                    "issue_label",
                    "toc_url",
                    "original_pdf_url",
                    "articles",
                    "articles[].title",
                    "articles[].detail_url",
                ),
                include_download_interrupts=download_original,
            ),
            placeholder_result=placeholder.to_dict(),
        )
        return plan.to_dict()

    def build_download_plan(
        self,
        detail_url: str,
        preferred_format: DownloadFormat = "auto",
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成全文下载计划。"""

        normalized_request = {
            "detail_url": detail_url.strip(),
            "preferred_format": preferred_format,
            "site": "cnki",
            "operation": "download",
        }
        plan = CnkiSkillPlan(
            mode="cnki-download",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=detail_url or "cnki-download",
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="download",
                access_type=access_type,
                downstream_node="cn-subscribed-literature-access",
                structured_output_fields=(
                    "detail_url",
                    "preferred_format",
                    "download_started",
                    "download_format",
                    "access_note",
                ),
                include_download_interrupts=True,
            ),
            placeholder_result={
                "detail_url": normalized_request["detail_url"],
                "preferred_format": preferred_format,
                "download_started": False,
                "download_format": "",
                "access_note": "当前为结构化占位计划，待后续页面执行器接入。",
            },
        )
        return plan.to_dict()

    def build_export_plan(
        self,
        mode: ExportMode = "ris",
        detail_url: str = "",
        export_id: str = "",
        batch_items: list[dict[str, Any]] | None = None,
        access_type: str = "closed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成导出计划。"""

        normalized_request = {
            "mode": mode,
            "detail_url": detail_url.strip(),
            "export_id": export_id.strip(),
            "batch_size": len(batch_items or []),
            "site": "cnki",
            "operation": "export",
        }
        plan = CnkiSkillPlan(
            mode="cnki-export",
            normalized_request=normalized_request,
            governance_result=self._governance(
                query=detail_url or export_id or f"cnki-export-{mode}",
                access_type=access_type,
                metadata=self._merge_metadata(metadata, normalized_request),
            ),
            access_contract=self._contract(
                operation="export",
                access_type=access_type,
                downstream_node="local-reference-ingestion",
                structured_output_fields=(
                    "mode",
                    "detail_url",
                    "export_id",
                    "batch_size",
                    "artifact_path",
                    "gb_citation",
                    "zotero_status",
                ),
                include_download_interrupts=True,
            ),
            placeholder_result={
                "mode": mode,
                "detail_url": normalized_request["detail_url"],
                "export_id": normalized_request["export_id"],
                "batch_size": normalized_request["batch_size"],
                "artifact_path": "",
                "gb_citation": "",
                "zotero_status": "pending",
            },
        )
        return plan.to_dict()

    def _governance(
        self,
        query: str,
        access_type: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """执行统一检索治理。"""

        return default_retrieval_handler(
            {
                "query": query,
                "object_type": "literature",
                "source_type": "online",
                "region_type": "domestic",
                "access_type": access_type,
                "metadata": metadata,
            }
        )

    def _contract(
        self,
        operation: str,
        access_type: str,
        downstream_node: str,
        structured_output_fields: tuple[str, ...],
        include_download_interrupts: bool = False,
    ) -> CnkiAccessContract:
        """构造访问契约。"""

        interrupts: list[CnkiInterruptReason] = ["captcha_required", "manual_confirmation_required"]
        requires_manual_authorization = access_type == "closed"
        if requires_manual_authorization:
            interrupts.append("institution_auth_required")
        if include_download_interrupts:
            interrupts.extend(["login_required", "download_permission_required"])
        return CnkiAccessContract(
            site="CNKI",
            operation=operation,
            requires_browser_session=True,
            requires_manual_authorization=requires_manual_authorization,
            interrupt_reasons=tuple(dict.fromkeys(interrupts)),
            downstream_node=downstream_node,
            structured_output_fields=structured_output_fields,
            notes=(
                "当前阶段以 OpenCode 侧页面执行 + ARK 侧结构化接收为主。",
                "如未获得合法授权，只保留题录与检索线索，不抓取受限全文。",
            ),
        )

    def _merge_metadata(
        self,
        metadata: dict[str, Any] | None,
        normalized_request: dict[str, Any],
    ) -> dict[str, Any]:
        """合并元数据。"""

        merged = dict(metadata or {})
        merged.update({"site": "cnki", "normalized_request": normalized_request})
        return merged

    def _resolve_next_page_hint(
        self,
        action: NavigateAction,
        current_page: int,
        target_page: int | None,
    ) -> int:
        """推导下一个目标页码。"""

        if action == "previous":
            return max(current_page - 1, 1)
        if action == "page" and target_page is not None:
            return target_page
        return current_page + 1