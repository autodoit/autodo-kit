# -*- coding: utf-8 -*-
"""
A090 - 标准文献笔记持续生成事务

职责（与 A070 对齐）：
- 持续消费 A080 在 content.db 文献主表标记的笔记生成队列
- 按 note_generation_priority DESC 顺序逐条处理
- 自动跳过已完成条目
- 重启后从上次中断位置继续（含失败重试、中断恢复）
- 支持 max_items_per_cycle 限制每轮处理量

执行模式：continuous_generation
"""
from .affair import execute

__all__ = ["execute"]
