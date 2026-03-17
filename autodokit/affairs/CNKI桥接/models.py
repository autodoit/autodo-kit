"""CNKI 专项检索结构化模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CnkiInterruptReason = Literal[
    "captcha_required",
    "login_required",
    "institution_auth_required",
    "download_permission_required",
    "manual_confirmation_required",
]
CnkiAvailabilityStatus = Literal[
    "metadata_only",
    "abstract_only",
    "fulltext_available",
    "fulltext_restricted",
]


@dataclass(slots=True, frozen=True)
class CnkiSearchCandidate:
    """CNKI 检索结果候选项。

    Args:
        rank: 当前页排序序号。
        title: 题名。
        authors: 作者列表。
        journal: 来源期刊。
        date: 发表日期。
        citations: 被引次数。
        downloads: 下载次数。
        result_url: 当前结果页 URL。
        detail_url: 详情页 URL。
        export_id: 导出所需标识。
        availability_status: 可得性状态。
    """

    rank: int
    title: str
    authors: tuple[str, ...]
    journal: str
    date: str
    citations: str
    downloads: str
    result_url: str
    detail_url: str
    export_id: str
    availability_status: CnkiAvailabilityStatus

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。

        Returns:
            可序列化字典。
        """

        return asdict(self)


@dataclass(slots=True, frozen=True)
class CnkiPaperDetailRecord:
    """CNKI 论文详情记录。

    Args:
        title: 题名。
        authors: 作者列表。
        author_organizations: 作者单位列表。
        journal: 来源期刊。
        date: 发表日期。
        abstract: 摘要。
        keywords: 关键词。
        fund: 基金信息。
        classification: 分类号。
        doi: DOI。
        detail_url: 详情页 URL。
        export_id: 导出标识。
    """

    title: str
    authors: tuple[str, ...]
    author_organizations: tuple[str, ...]
    journal: str
    date: str
    abstract: str
    keywords: tuple[str, ...]
    fund: str
    classification: str
    doi: str
    detail_url: str
    export_id: str

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。

        Returns:
            可序列化字典。
        """

        return asdict(self)


@dataclass(slots=True, frozen=True)
class CnkiJournalProfile:
    """CNKI 期刊信息与评价记录。

    Args:
        journal_name_cn: 中文刊名。
        journal_name_en: 英文刊名。
        issn: ISSN。
        cn_number: CN 号。
        sponsor: 主办单位。
        frequency: 出版周期。
        indexed_in: 收录标签。
        impact_composite: 复合影响因子。
        impact_comprehensive: 综合影响因子。
        detail_url: 详情页 URL。
        toc_url: 刊期目录 URL。
    """

    journal_name_cn: str
    journal_name_en: str
    issn: str
    cn_number: str
    sponsor: str
    frequency: str
    indexed_in: tuple[str, ...]
    impact_composite: str
    impact_comprehensive: str
    detail_url: str
    toc_url: str

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。

        Returns:
            可序列化字典。
        """

        return asdict(self)


@dataclass(slots=True, frozen=True)
class CnkiIssueArticle:
    """CNKI 某期目录中的文章条目。

    Args:
        rank: 顺序号。
        title: 题名。
        authors: 作者列表。
        pages: 页码信息。
        detail_url: 详情页 URL。
    """

    rank: int
    title: str
    authors: tuple[str, ...]
    pages: str
    detail_url: str

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。

        Returns:
            可序列化字典。
        """

        return asdict(self)


@dataclass(slots=True, frozen=True)
class CnkiIssueToc:
    """CNKI 刊期目录记录。

    Args:
        journal_name: 期刊名称。
        year: 年份。
        issue: 期号。
        issue_label: 展示标签。
        toc_url: 目录 URL。
        original_pdf_url: 原版目录下载 URL。
        articles: 目录文章集合。
    """

    journal_name: str
    year: str
    issue: str
    issue_label: str
    toc_url: str
    original_pdf_url: str
    articles: tuple[CnkiIssueArticle, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。

        Returns:
            可序列化字典。
        """

        return {
            "journal_name": self.journal_name,
            "year": self.year,
            "issue": self.issue,
            "issue_label": self.issue_label,
            "toc_url": self.toc_url,
            "original_pdf_url": self.original_pdf_url,
            "articles": [article.to_dict() for article in self.articles],
        }


@dataclass(slots=True, frozen=True)
class CnkiAccessContract:
    """CNKI 访问与执行契约。

    Args:
        site: 目标站点。
        operation: 操作名。
        requires_browser_session: 是否需要浏览器会话。
        requires_manual_authorization: 是否需要人工授权。
        interrupt_reasons: 可能的人工中断原因。
        downstream_node: 推荐下游节点。
        structured_output_fields: 约定输出字段。
        notes: 执行备注。
    """

    site: str
    operation: str
    requires_browser_session: bool
    requires_manual_authorization: bool
    interrupt_reasons: tuple[CnkiInterruptReason, ...]
    downstream_node: str
    structured_output_fields: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。

        Returns:
            可序列化字典。
        """

        return asdict(self)


@dataclass(slots=True, frozen=True)
class CnkiSkillPlan:
    """CNKI 技能规划结果。

    Args:
        mode: 技能模式名。
        normalized_request: 规范化请求。
        governance_result: 检索治理结果。
        access_contract: 访问契约。
        placeholder_result: 占位结果结构。
    """

    mode: str
    normalized_request: dict[str, Any]
    governance_result: dict[str, Any]
    access_contract: CnkiAccessContract
    placeholder_result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。

        Returns:
            可序列化字典。
        """

        return {
            "mode": self.mode,
            "normalized_request": self.normalized_request,
            "governance_result": self.governance_result,
            "access_contract": self.access_contract.to_dict(),
            "placeholder_result": self.placeholder_result,
        }