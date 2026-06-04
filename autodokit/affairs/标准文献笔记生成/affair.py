# -*- coding: utf-8 -*-
"""
A090 标准文献笔记持续生成 - 主事务入口

与 A070 的设计对齐：
- 从 content.db 文献主表消费 A080 标记的笔记生成队列
- 按 note_generation_priority DESC 顺序处理（高优先级优先）
- 幂等/续跑：
  * 跳过 note_generation_status='已完成' 的条目
  * '失败' 的条目自动重试（可通过 max_retry_count 限制）
  * '在运行' 的条目视为上次中断，自动恢复
- 支持 max_items_per_cycle 控制每轮处理上限
- 单条失败不中断整批，记录原因后继续下一条
"""
import json
import logging
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import sqlite3

from .note_generator import generate_standard_note

logger = logging.getLogger(__name__)


def execute(config: Dict) -> Dict:
    """
    A090 事务执行入口

    Args:
        config: 配置字典，关键字段：
            - max_items_per_cycle: 每轮最大处理数
            - max_retry_count: 单条文献最大重试次数（0=无限）
            - llm_config: LLM 模型配置
            - note_template: 笔记模板配置
            - dry_run: 预演模式

    Returns:
        执行结果字典
    """
    workspace_root = Path(config.get("工作区根路径") or config.get("workspace_root", "workspace"))
    content_db_path = Path(
        config.get("内容数据库路径") or config.get("content_db",
            workspace_root / "database" / "content" / "content.db"))
    output_dir = Path(
        config.get("输出目录") or config.get("output_dir",
            workspace_root / "tasks" / "A090_note_generation"))
    knowledge_dir = Path(
        config.get("knowledge_output_dir",
            workspace_root / "knowledge" / "notes"))
    structured_dir = Path(
        config.get("structured_dir",
            workspace_root / "references" / "structured_monkeyocr_full"))

    max_items = config.get("max_items_per_cycle", 5)
    max_retry_count = config.get("max_retry_count", 3)
    llm_config = config.get("llm_config", {})
    note_template = config.get("note_template", {})
    research_topic = config.get("research_topic", "")
    topic_terms = config.get("topic_terms", [])
    dry_run = config.get("是否仅预演") or config.get("dry_run", False)

    logger.info(f"A090 开始执行 - 工作区: {workspace_root}")
    logger.info(f"每轮最大处理数: {max_items}")

    output_dir.mkdir(parents=True, exist_ok=True)
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    conn = None
    results = {"success": [], "failed": [], "skipped": []}

    try:
        conn = sqlite3.connect(str(content_db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # ── 统计全库状态 ──────────────────────────────────────────────
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN note_generation_status = '已完成' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN note_generation_status = '失败' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN note_generation_status = '在运行' THEN 1 ELSE 0 END) as running,
                SUM(CASE WHEN pending_note_generation = 1 
                         AND note_generation_status != '已完成' THEN 1 ELSE 0 END) as pending
            FROM 文献主表
        """)
        db_stats = dict(cursor.fetchone())
        logger.info(f"全库笔记状态 - 已完成:{db_stats['done']} "
                    f"失败:{db_stats['failed']} 运行中:{db_stats['running']} "
                    f"待处理队列:{db_stats['pending']}")

        if db_stats["pending"] == 0:
            logger.info("笔记生成队列为空，无需处理")
            return {
                "status": "success",
                "message": "队列为空，无需处理",
                "success_count": 0,
                "failed_count": 0,
                "db_stats": db_stats,
                "output_dir": str(output_dir),
                "timestamp": datetime.now().isoformat()
            }

        # ── 获取待处理队列（按优先级降序）───────────────────────────
        # 包含：未完成 + 失败（重试） + 在运行（中断恢复）
        cursor.execute("""
            SELECT uid_文献, cite_key, bib_title, bib_year,
                   note_generation_priority, note_generation_status,
                   note_generation_fail_reason, 解析状态,
                   uid_当前解析资产, 当前解析路径
            FROM 文献主表
            WHERE pending_note_generation = 1
              AND (note_generation_status IS NULL
                   OR note_generation_status != '已完成')
            ORDER BY note_generation_priority DESC
            LIMIT ?
        """, (max_items,))

        queue = [dict(row) for row in cursor.fetchall()]
        logger.info(f"本轮处理队列: {len(queue)} 条")

        # ── 逐条处理 ─────────────────────────────────────────────────
        for idx, item in enumerate(queue, 1):
            uid = item["uid_文献"]
            cite_key = item.get("cite_key", uid)
            title = item.get("bib_title", "未知标题")
            priority = item.get("note_generation_priority", 0)
            prev_status = item.get("note_generation_status", "")
            prev_reason = item.get("note_generation_fail_reason", "")

            logger.info(f"[{idx}/{len(queue)}] uid={uid} cite_key={cite_key} "
                        f"priority={priority:.4f} 原状态={prev_status or '未处理'}")

            # 失败次数检查
            if prev_status == "失败" and max_retry_count > 0:
                # 检查是否超过最大重试（简单方式：看历史失败原因计数）
                # 这里用 fail_reason 中记录的重试次数来判断
                retry_marker = prev_reason or ""
                retry_count = retry_marker.count("[重试]") if retry_marker else 0
                if retry_count >= max_retry_count:
                    logger.warning(f"  跳过：已达最大重试次数 ({max_retry_count})")
                    results["skipped"].append({"uid": uid, "cite_key": cite_key,
                                               "reason": "max_retry_exceeded"})
                    continue

            if dry_run:
                logger.info(f"  [预演] 将处理此条目，跳过实际执行")
                results["success"].append({"uid": uid, "cite_key": cite_key,
                                           "dry_run": True})
                continue

            # 标记为"在运行"（检测中断）
            cursor.execute("""
                UPDATE 文献主表
                SET note_generation_status = '在运行',
                    note_generation_time = ?
                WHERE uid_文献 = ?
            """, (datetime.now().isoformat(), uid))
            conn.commit()

            try:
                # 调用笔记生成
                note_result = generate_standard_note(
                    item=item,
                    structured_dir=structured_dir,
                    knowledge_dir=knowledge_dir,
                    llm_config=llm_config,
                    note_template=note_template,
                    research_topic=research_topic,
                    topic_terms=topic_terms,
                    workspace_root=workspace_root,
                )

                if note_result.get("status") == "success":
                    cursor.execute("""
                        UPDATE 文献主表
                        SET note_generation_status = '已完成',
                            note_generation_time = ?,
                            note_generation_fail_reason = NULL,
                            pending_note_generation = 0
                        WHERE uid_文献 = ?
                    """, (datetime.now().isoformat(), uid))
                    conn.commit()
                    logger.info(f"  ✓ 笔记生成成功: {note_result.get('note_path', '')}")
                    results["success"].append({
                        "uid": uid, "cite_key": cite_key,
                        "note_path": note_result.get("note_path", "")
                    })
                else:
                    raise RuntimeError(note_result.get("message", "未知错误"))

            except Exception as item_err:
                err_msg = str(item_err)
                retry_note = "[重试]" if prev_status == "失败" else ""
                full_reason = f"{retry_note}{err_msg}" if retry_note else err_msg
                logger.error(f"  ✗ 笔记生成失败: {err_msg}")

                cursor.execute("""
                    UPDATE 文献主表
                    SET note_generation_status = '失败',
                        note_generation_time = ?,
                        note_generation_fail_reason = ?
                    WHERE uid_文献 = ?
                """, (datetime.now().isoformat(), full_reason, uid))
                conn.commit()
                results["failed"].append({"uid": uid, "cite_key": cite_key,
                                          "reason": err_msg})

        # ── 汇总 ──────────────────────────────────────────────────────
        success_count = len(results["success"])
        failed_count = len(results["failed"])
        skipped_count = len(results["skipped"])

        result = {
            "status": "success" if failed_count == 0 else "partial",
            "message": f"完成 {success_count} 条，失败 {failed_count} 条，跳过 {skipped_count} 条",
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "success_items": results["success"],
            "failed_items": results["failed"],
            "skipped_items": results["skipped"],
            "db_stats": db_stats,
            "output_dir": str(output_dir),
            "dry_run": dry_run,
            "timestamp": datetime.now().isoformat()
        }
        logger.info(f"A090 执行完成: {result['message']}")
        return result

    except Exception as e:
        logger.error(f"A090 执行失败: {e}", exc_info=True)
        if conn is not None:
            conn.rollback()
        return {
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }
    finally:
        if conn is not None:
            conn.close()
