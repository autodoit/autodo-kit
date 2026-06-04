# -*- coding: utf-8 -*-
"""
优先级评分器

根据多个维度计算文献笔记生成的优先级分数。
"""
import math
from datetime import datetime
from typing import Dict, List, Optional


class PriorityScorer:
    """文献笔记生成优先级评分器"""
    
    def __init__(
        self,
        topic_terms: List[str],
        relevance_weight: float = 0.4,
        recency_weight: float = 0.2,
        citation_weight: float = 0.2,
        completeness_weight: float = 0.2,
        min_structured_quality_score: float = 0.7
    ):
        """
        初始化评分器
        
        Args:
            topic_terms: 研究主题词列表
            relevance_weight: 相关性权重
            recency_weight: 时效性权重
            citation_weight: 引用影响力权重
            completeness_weight: 完整性权重
            min_structured_quality_score: 最低结构化质量分数阈值
        """
        self.topic_terms = [term.lower() for term in topic_terms]
        self.relevance_weight = relevance_weight
        self.recency_weight = recency_weight
        self.citation_weight = citation_weight
        self.completeness_weight = completeness_weight
        self.min_quality_score = min_structured_quality_score
    
    def calculate_priority(
        self,
        literature: Dict
    ) -> float:
        """
        计算单篇文献的优先级分数
        
        Args:
            literature: 文献字典，包含标题、摘要、关键词、年份等字段
            
        Returns:
            优先级分数 (0.0 - 1.0)
        """
        # 检查结构化质量
        quality_score = self._check_structured_quality(literature)
        if quality_score < self.min_quality_score:
            return 0.0  # 质量不达标，不参与排序
        
        # 计算各维度分数
        relevance = self._calculate_relevance(literature)
        recency = self._calculate_recency(literature)
        citation = self._calculate_citation(literature)
        completeness = self._calculate_completeness(literature)
        
        # 加权综合
        priority = (
            relevance * self.relevance_weight +
            recency * self.recency_weight +
            citation * self.citation_weight +
            completeness * self.completeness_weight
        )
        
        # 确保在 0-1 范围内
        return max(0.0, min(1.0, priority))
    
    def _check_structured_quality(self, literature: Dict) -> float:
        """
        检查结构化产物质量
        
        Args:
            literature: 文献字典
            
        Returns:
            质量分数 (0.0 - 1.0)
        """
        score = 1.0
        
        # 检查是否有解析状态
        parse_status = literature.get("解析状态", "")
        if parse_status != "已完成":
            return 0.0
        
        # 检查结构化文本长度
        text_length = literature.get("结构化文本长度", 0) or 0
        if text_length < 1000:
            score -= 0.3
        elif text_length < 5000:
            score -= 0.1
        
        # 检查是否有参考文献
        ref_count = literature.get("结构化参考文献数", 0) or 0
        if ref_count == 0:
            score -= 0.2
        
        # 检查是否有摘要
        abstract = literature.get("bib_abstract") or literature.get("摘要译文") or ""
        if not abstract or len(abstract) < 100:
            score -= 0.2
        
        return max(0.0, score)
    
    def _calculate_relevance(self, literature: Dict) -> float:
        """
        计算与研究主题的相关性分数
        
        Args:
            literature: 文献字典
            
        Returns:
            相关性分数 (0.0 - 1.0)
        """
        # 收集所有文本字段
        texts = []
        
        title = literature.get("bib_title") or literature.get("标题译文") or ""
        if title:
            texts.append(title.lower())
        
        abstract = literature.get("bib_abstract") or literature.get("摘要译文") or ""
        if abstract:
            texts.append(abstract.lower())
        
        keywords = literature.get("bib_keywords") or literature.get("关键词译文") or ""
        if keywords:
            texts.append(keywords.lower())
        
        if not texts:
            return 0.0
        
        full_text = " ".join(texts)
        
        # 计算主题词匹配度
        matched_count = 0
        for term in self.topic_terms:
            if term in full_text:
                matched_count += 1
        
        if not self.topic_terms:
            return 0.5  # 没有主题词时给中等分数
        
        # 匹配比例
        match_ratio = matched_count / len(self.topic_terms)
        
        # 使用平方根函数使分数分布更合理（避免极端值）
        return math.sqrt(match_ratio)
    
    def _calculate_recency(self, literature: Dict) -> float:
        """
        计算时效性分数（越近越高）
        
        Args:
            literature: 文献字典
            
        Returns:
            时效性分数 (0.0 - 1.0)
        """
        year = literature.get("bib_year") or literature.get("年份")
        
        if not year:
            return 0.5  # 缺少年份时给中等分数
        
        try:
            pub_year = int(year)
        except (ValueError, TypeError):
            return 0.5
        
        current_year = datetime.now().year
        age = current_year - pub_year
        
        if age < 0:
            return 1.0  # 未来发表（在线优先），最高分
        
        # 20年内的文献线性衰减，超过20年给最低分
        if age <= 20:
            return max(0.0, 1.0 - (age / 20.0))
        else:
            return 0.0
    
    def _calculate_citation(self, literature: Dict) -> float:
        """
        计算引用影响力分数
        
        Args:
            literature: 文献字典
            
        Returns:
            引用影响力分数 (0.0 - 1.0)
        """
        # 当前简化实现：如果有引用次数字段则使用，否则给中等分数
        # TODO: 后续可以从 Crossref 或其他 API 获取真实引用次数
        
        citation_count = literature.get("citation_count") or literature.get("被引次数")
        
        if citation_count is None:
            return 0.5  # 没有引用数据时给中等分数
        
        try:
            count = int(citation_count)
        except (ValueError, TypeError):
            return 0.5
        
        # 使用对数函数归一化到 0-1
        # 假设 100 次引用为满分
        if count <= 0:
            return 0.0
        elif count >= 100:
            return 1.0
        else:
            return math.log1p(count) / math.log1p(100)
    
    def _calculate_completeness(self, literature: Dict) -> float:
        """
        计算文献信息完整性分数
        
        Args:
            literature: 文献字典
            
        Returns:
            完整性分数 (0.0 - 1.0)
        """
        score = 0.0
        max_score = 0.0
        
        # 检查关键字段
        fields_to_check = {
            "标题": ["bib_title", "标题译文"],
            "作者": ["bib_collaborator", "作者"],
            "年份": ["bib_year", "年份"],
            "摘要": ["bib_abstract", "摘要译文"],
            "关键词": ["bib_keywords", "关键词译文"],
            "期刊": ["bib_journal", "期刊"],
        }
        
        for field_name, field_keys in fields_to_check.items():
            max_score += 1.0
            for key in field_keys:
                value = literature.get(key)
                if value and str(value).strip():
                    score += 1.0
                    break  # 找到一个有效值即可
        
        if max_score == 0:
            return 0.0
        
        return score / max_score


def batch_calculate_priorities(
    literatures: List[Dict],
    topic_terms: List[str],
    weights: Optional[Dict[str, float]] = None
) -> List[Dict]:
    """
    批量计算文献优先级
    
    Args:
        literatures: 文献列表
        topic_terms: 主题词列表
        weights: 权重配置字典
        
    Returns:
        包含优先级分数的文献列表（已按优先级降序排序）
    """
    if weights is None:
        weights = {}
    
    scorer = PriorityScorer(
        topic_terms=topic_terms,
        relevance_weight=weights.get("relevance_weight", 0.4),
        recency_weight=weights.get("recency_weight", 0.2),
        citation_weight=weights.get("citation_weight", 0.2),
        completeness_weight=weights.get("completeness_weight", 0.2),
        min_structured_quality_score=weights.get("min_structured_quality_score", 0.7)
    )
    
    results = []
    for lit in literatures:
        priority = scorer.calculate_priority(lit)
        lit_with_priority = lit.copy()
        lit_with_priority["note_generation_priority"] = priority
        results.append(lit_with_priority)
    
    # 按优先级降序排序
    results.sort(key=lambda x: x["note_generation_priority"], reverse=True)
    
    return results
