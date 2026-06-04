# -*- coding: utf-8 -*-
"""
A080 - 阅读优先级生成事务

职责：
- 扫描 content.db 中所有已完成预处理的文献
- 根据研究主题、关键词匹配度、文献类型等因素计算优先级分数
- 将符合条件的文献标记为 pending_note_generation=1 并写入优先级队列
- 生成优先级报告 CSV 供人工审核

执行模式：priority_only
"""
from .affair import execute

__all__ = ["execute"]
