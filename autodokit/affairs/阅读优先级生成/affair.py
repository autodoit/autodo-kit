# -*- coding: utf-8 -*-
"""
A080 阅读优先级生成 - 主事务入口

与 A060 的设计对齐（幂等 / 续跑）：
- 扫描 content.db 文献主表中所有 解析状态='已完成' 的文献
- 跳过 note_generation_status='已完成' 的条目（A090 已成功处理）
- 对未入队 / 未完成条目计算优先级并标记 pending_note_generation=1
- 支持 refresh_queue：刷新已在队列中但未完成条目的优先级
- 支持 retry_failed：将 '失败' 条目重置回队列允许 A090 重试
- '在运行' 条目视为上次 A090 中断遗留，保留在队列中由 A090 自动恢复
"""
import json
import csv
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import sqlite3

from .priority_scorer import batch_calculate_priorities

logger = logging.getLogger(__name__)


def execute(config: Dict) -> Dict:
    """
    A080 事务执行入口。

    幂等/续跑行为（与 A060 对齐）：
    - 已完成（note_generation_status='已完成'）→ 跳过
    - 失败（note_generation_status='失败'）→ 当 retry_failed=true 时重置回队列
    - 在运行（note_generation_status='在运行'）→ 视为上次 A090 中断，保留在队列
    - 未完成/未入队 → 计算优先级并标记 pending_note_generation=1

    Args:
        config: 配置字典，关键字段：
            - research_topic: 研究主题
            - topic_terms: 主题词列表
            - priority_rules: 优先级权重规则
            - batch_size: 数据库批量更新大小
            - refresh_queue: 是否刷新已在队列中条目的优先级
            - retry_failed: 是否将失败条目重置回队列

    Returns:
        执行结果字典
    """
    workspace_root = Path(config.get("工作区根路径") or config.get("workspace_root", "workspace"))
    content_db_path = Path(config.get("内容数据库路径") or config.get("content_db",
        workspace_root / "database" / "content" / "content.db"))
    output_dir = Path(config.get("输出目录") or config.get("output_dir",
        workspace_root / "tasks" / "A085_note_priority"))

    research_topic = config.get("research_topic", "")
    topic_terms = config.get("topic_terms", [])
    priority_rules = config.get("priority_rules", {})
    batch_size = config.get("batch_size", 50)
    refresh_queue = config.get("refresh_queue", False)
    retry_failed = config.get("retry_failed", False)
    dry_run = config.get("是否仅预演") or config.get("dry_run", False)

    logger.info(f"A080 开始执行 - 工作区: {workspace_root}")
    logger.info(f"研究主题: {research_topic}")
    logger.info(f"主题词数量: {len(topic_terms)}")
    logger.info(f"refresh_queue={refresh_queue}, retry_failed={retry_failed}")

    output_dir.mkdir(parents=True, exist_ok=True)

    conn = None
    try:
        logger.info(f"连接数据库: {content_db_path}")
        conn = sqlite3.connect(str(content_db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # ── 1. 统计全库笔记生成状态 ──────────────────────────────────
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN 解析状态 = '已完成' THEN 1 ELSE 0 END) as parsed,
                SUM(CASE WHEN note_generation_status = '已完成' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN note_generation_status = '失败' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN note_generation_status = '在运行' THEN 1 ELSE 0 END) as running,
                SUM(CASE WHEN pending_note_generation = 1
                         AND (note_generation_status IS NULL
                              OR note_generation_status != '已完成') THEN 1 ELSE 0 END) as pending
            FROM 文献主表
        """)
        db_stats = dict(cursor.fetchone())
        logger.info(
            f"全库状态 - 总:{db_stats['total']} 已解析:{db_stats['parsed']} "
            f"笔记已完成:{db_stats['done']} 失败:{db_stats['failed']} "
            f"运行中:{db_stats['running']} 待处理队列:{db_stats['pending']}")

        # ── 2. 查询需要处理的文献 ────────────────────────────────────
        # 条件：解析状态='已完成'
        #   排除 note_generation_status='已完成'（A090 已成功处理）
        #   如果 retry_failed=false，也排除 '失败'（保留给人工处理）
        where_clause = "解析状态 = '已完成'"
        where_clause += " AND (note_generation_status IS NULL OR note_generation_status != '已完成')"
        if not retry_failed:
            where_clause += " AND (note_generation_status IS NULL OR note_generation_status != '失败')"

        query = f"""
            SELECT
                uid_文献, cite_key, bib_title, bib_abstract, bib_keywords,
                bib_year, bib_collaborator, bib_journal,
                解析状态, 结构化文本长度, 结构化参考文献数,
                标题译文, 摘要译文, 关键词译文,
                pending_note_generation, note_generation_status,
                note_generation_priority, note_generation_fail_reason
            FROM 文献主表
            WHERE {where_clause}
            ORDER BY uid_文献
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        logger.info(f"找到 {len(rows)} 篇待处理文献")

        if not rows:
            logger.info("没有待处理文献，退出")
            return {
                "status": "success",
                "message": "没有待处理文献",
                "processed_count": 0,
                "db_stats": db_stats,
                "output_dir": str(output_dir)
            }

        # ── 3. 分类：新增 / 刷新 / 中断恢复 ─────────────────────────
        new_items = []       # 未入队 (pending_note_generation=0 或 NULL)
        refresh_items = []   # 已入队但未完成 (需要刷新优先级)
        resume_items = []    # '在运行' (A090 中断遗留)
        retry_items = []     # '失败' (retry_failed=true 时重置)

        for row in rows:
            item = dict(row)
            prev_status = item.get("note_generation_status") or ""
            is_pending = item.get("pending_note_generation", 0)

            if prev_status == "在运行":
                resume_items.append(item)
            elif prev_status == "失败" and retry_failed:
                retry_items.append(item)
            elif is_pending and prev_status in ("未完成", ""):
                if refresh_queue:
                    refresh_items.append(item)
                # 不刷新就跳过，保留原有优先级
            else:
                new_items.append(item)

        logger.info(f"分类统计 - 新增:{len(new_items)} 刷新:{len(refresh_items)} "
                     f"中断恢复:{len(resume_items)} 失败重试:{len(retry_items)}")

        # ── 4. 对需要计算优先级的文献批量评分 ───────────────────────
        to_score = new_items + refresh_items + retry_items
        scored = []
        if to_score:
            logger.info(f"计算 {len(to_score)} 篇文献的优先级分数...")
            scored = batch_calculate_priorities(
                literatures=to_score,
                topic_terms=topic_terms,
                weights=priority_rules
            )

        # 过滤质量不达标的文献
        qualified = [lit for lit in scored if lit["note_generation_priority"] > 0]
        logger.info(f"合格文献数量: {len(qualified)} / {len(to_score)}")

        # ── 5. 更新数据库 ───────────────────────────────────────────
        stats = {
            "new_enqueued": 0,
            "refreshed": 0,
            "resumed": 0,
            "retry_reset": 0,
            "filtered_out": len(to_score) - len(qualified),
        }

        if not dry_run:
            now = datetime.now().isoformat()

            # 5a. 新增入队 + 刷新 + 重试 → 写入优先级
            if qualified:
                update_count = _update_database(cursor, qualified, batch_size, now)
                conn.commit()
                # 区分新增和刷新
                new_uids = {lit["uid_文献"] for lit in new_items}
                retry_uids = {lit["uid_文献"] for lit in retry_items}
                for lit in qualified:
                    uid = lit["uid_文献"]
                    if uid in new_uids:
                        stats["new_enqueued"] += 1
                    elif uid in retry_uids:
                        stats["retry_reset"] += 1
                    else:
                        stats["refreshed"] += 1
                logger.info(f"成功更新 {update_count} 条记录")

            # 5b. 失败重试项：清除失败原因
            if retry_items:
                retry_uids_list = [lit["uid_文献"] for lit in retry_items]
                for uid in retry_uids_list:
                    cursor.execute("""
                        UPDATE 文献主表
                        SET note_generation_fail_reason = NULL
                        WHERE uid_文献 = ?
                    """, (uid,))
                conn.commit()
                logger.info(f"已清除 {len(retry_uids_list)} 条失败原因")

            # 5c. 中断恢复项：保留在队列中（A090 会自动恢复 '在运行' 条目）
            stats["resumed"] = len(resume_items)
        else:
            logger.info("预演模式，跳过数据库更新")
            stats["new_enqueued"] = len(new_items)
            stats["refreshed"] = len(refresh_items)
            stats["resumed"] = len(resume_items)
            stats["retry_reset"] = len(retry_items)

        # ── 6. 生成优先级报告 CSV ───────────────────────────────────
        all_queue_items = qualified + resume_items  # 合格新入队 + 中断恢复
        if all_queue_items:
            csv_path = output_dir / "note_generation_priority_candidates.csv"
            _generate_csv_report(all_queue_items, csv_path)
            logger.info(f"优先级报告已生成: {csv_path}")
        else:
            csv_path = None

        # ── 7. 汇总结果 ────────────────────────────────────────────
        total_affected = (stats["new_enqueued"] + stats["refreshed"]
                          + stats["resumed"] + stats["retry_reset"])

        result = {
            "status": "success",
            "message": (f"新增入队:{stats['new_enqueued']} "
                        f"刷新:{stats['refreshed']} "
                        f"中断恢复:{stats['resumed']} "
                        f"失败重试:{stats['retry_reset']} "
                        f"质量过滤:{stats['filtered_out']}"),
            "processed_count": total_affected,
            "statistics": stats,
            "db_stats": db_stats,
            "output_dir": str(output_dir),
            "csv_report": str(csv_path) if csv_path else None,
            "dry_run": dry_run,
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"A080 执行完成: {result['message']}")
        return result

    except Exception as e:
        logger.error(f"A080 执行失败: {e}", exc_info=True)
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


def _update_database(
    cursor: sqlite3.Cursor,
    literatures: List[Dict],
    batch_size: int,
    now: str,
) -> int:
    """
    批量更新数据库中的优先级和标记。

    Args:
        cursor: 数据库游标
        literatures: 文献列表（包含优先级分数）
        batch_size: 批次大小
        now: 当前时间 ISO 字符串

    Returns:
        更新的记录数
    """
    update_count = 0

    for i in range(0, len(literatures), batch_size):
        batch = literatures[i:i + batch_size]

        for lit in batch:
            uid = lit["uid_文献"]
            priority = lit["note_generation_priority"]

            cursor.execute("""
                UPDATE 文献主表
                SET pending_note_generation = 1,
                    note_generation_priority = ?,
                    note_generation_status = '未完成',
                    note_generation_time = ?
                WHERE uid_文献 = ?
            """, (priority, now, uid))

            update_count += 1

        logger.info(f"已处理批次 {i // batch_size + 1}: {len(batch)} 条记录")

    return update_count


def _generate_csv_report(literatures: List[Dict], csv_path: Path):
    """
    生成优先级报告 CSV。

    Args:
        literatures: 文献列表
        csv_path: CSV 文件路径
    """
    if not literatures:
        return

    fieldnames = [
        "uid_文献",
        "cite_key",
        "标题",
        "作者",
        "年份",
        "期刊",
        "优先级分数",
        "解析状态",
        "结构化文本长度"
    ]

    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for lit in literatures:
            writer.writerow({
                "uid_文献": lit.get("uid_文献", ""),
                "cite_key": lit.get("cite_key", ""),
                "标题": lit.get("bib_title") or lit.get("标题译文", ""),
                "作者": lit.get("bib_collaborator", ""),
                "年份": lit.get("bib_year", ""),
                "期刊": lit.get("bib_journal", ""),
                "优先级分数": f"{lit.get('note_generation_priority', 0):.4f}",
                "解析状态": lit.get("解析状态", ""),
                "结构化文本长度": lit.get("结构化文本长度", 0)
            })
