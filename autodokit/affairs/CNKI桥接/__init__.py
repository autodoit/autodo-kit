"""CNKI 专项检索协议与规划模块。"""

from .affair import execute
from .engine import DownloadFormat, ExportMode, NavigateAction, SortMode, CnkiWorkflowPlanner
from .runtime import CnkiBrowserConfig, CnkiManualInterventionRequired, CnkiPlaywrightRuntime
from .models import (
    CnkiAccessContract,
    CnkiIssueArticle,
    CnkiIssueToc,
    CnkiJournalProfile,
    CnkiPaperDetailRecord,
    CnkiSearchCandidate,
    CnkiSkillPlan,
)

__all__ = [
    "CnkiAccessContract",
    "CnkiBrowserConfig",
    "CnkiIssueArticle",
    "CnkiIssueToc",
    "CnkiJournalProfile",
    "CnkiManualInterventionRequired",
    "CnkiPaperDetailRecord",
    "CnkiPlaywrightRuntime",
    "CnkiSearchCandidate",
    "CnkiSkillPlan",
    "CnkiWorkflowPlanner",
    "DownloadFormat",
    "ExportMode",
    "NavigateAction",
    "SortMode",
    "execute",
]