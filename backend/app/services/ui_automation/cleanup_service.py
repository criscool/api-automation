"""
UI 自动化产物清理服务(阶段三 P3-09)

定期任务,扫描 ui_execution_artifacts 与 UI_ARTIFACT_DIR/exec_<id>/ 目录,执行两条规则:

1. 时间窗口规则:expires_at < now() 的产物记录与对应文件/目录全部删除
2. 报告保留规则:UI_KEEP_LATEST_SUCCESS_REPORTS 之外的 success 报告整目录清理(保留 DB 记录,只删盘上)

路径白名单(BLOCKING):
- 待删目录必须严格位于 UI_ARTIFACT_DIR 内,且必须是 exec_xxx 形态
- 任何 .. / 绝对路径逃逸 / 非 exec_ 前缀目录一律拒绝
- 整体逻辑只删 UI 自动化自己的产物,不碰任何用户上传 / 数据库文件 / git 仓库

零回归:仅在 settings.UI_AUTOMATION_ENABLED=True 时被 register_cleanup_job 注册到 APScheduler。
"""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.settings.config import settings


_EXEC_DIR_PREFIX = "exec_"


def _is_safe_workspace_path(path: Path, artifact_root: Path) -> bool:
    """白名单校验:目录必须在 UI_ARTIFACT_DIR 内,且为 exec_xxx 前缀"""
    try:
        resolved = path.resolve()
        resolved.relative_to(artifact_root.resolve())
    except (ValueError, OSError):
        return False
    if not resolved.name.startswith(_EXEC_DIR_PREFIX):
        return False
    return True


def _delete_workspace(path: Path) -> bool:
    """同步删除整个 exec_<id> 目录,失败返回 False"""
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
        return True
    except Exception as e:
        logger.warning(f"清理 UI 产物目录失败 path={path} err={e}")
        return False


async def cleanup_expired_artifacts() -> Tuple[int, int]:
    """按 expires_at 清理已过期的产物记录与磁盘文件。

    Returns:
        (expired_artifact_rows_deleted, exec_dirs_removed)
    """
    try:
        from app.models.ui_automation import (
            UiExecutionArtifact,
            UiScriptExecution,
        )
    except Exception as e:
        logger.warning(f"加载 UI 模型失败,跳过清理: {e}")
        return 0, 0

    artifact_root = Path(settings.UI_ARTIFACT_DIR)
    if not artifact_root.exists():
        return 0, 0

    now = datetime.now()
    expired_rows = await UiExecutionArtifact.filter(expires_at__lt=now).all()
    execution_ids = {row.execution_id for row in expired_rows}

    # 删 DB 行
    deleted_rows = 0
    if execution_ids:
        deleted_rows = await UiExecutionArtifact.filter(execution_id__in=list(execution_ids)).delete()

    # 删盘目录(走白名单校验)
    dirs_removed = 0
    for exec_id in execution_ids:
        execution = await UiScriptExecution.filter(execution_id=exec_id).first()
        # 优先用 DB 里保存的 workspace 信息,缺失则按命名约定推
        artifact_summary = (execution.artifact_summary if execution else None) or {}
        rel = artifact_summary.get("workspace_relative", "")
        candidate = (artifact_root / rel) if rel else (artifact_root / f"exec_{exec_id}")
        if _is_safe_workspace_path(candidate, artifact_root):
            if await asyncio.to_thread(_delete_workspace, candidate):
                dirs_removed += 1
        else:
            logger.warning(f"跳过非白名单路径(可能逃逸): {candidate}")

    if deleted_rows or dirs_removed:
        logger.info(
            f"UI 产物清理:DB 删除 {deleted_rows} 行,磁盘清理 {dirs_removed} 个 exec 目录"
        )
    return deleted_rows, dirs_removed


async def cleanup_success_reports_overflow() -> int:
    """保留最近 UI_KEEP_LATEST_SUCCESS_REPORTS 条 success 报告的盘文件,其余清磁盘。

    DB 记录保留(用作历史摘要),仅释放磁盘空间。
    """
    try:
        from app.models.ui_automation import UiScriptExecution, UiTestReport
    except Exception as e:
        logger.warning(f"加载 UI 模型失败,跳过 success 报告裁剪: {e}")
        return 0

    artifact_root = Path(settings.UI_ARTIFACT_DIR)
    if not artifact_root.exists():
        return 0

    keep = max(1, int(settings.UI_KEEP_LATEST_SUCCESS_REPORTS or 20))
    success_reports = (
        await UiTestReport.all().order_by("-id").offset(keep).all()
    )
    if not success_reports:
        return 0

    overflow_exec_ids = [r.execution_id for r in success_reports]
    success_execs = await UiScriptExecution.filter(
        execution_id__in=overflow_exec_ids, status="success"
    ).all()

    dirs_removed = 0
    for execution in success_execs:
        rel = (execution.artifact_summary or {}).get("workspace_relative", "")
        candidate = (artifact_root / rel) if rel else (artifact_root / f"exec_{execution.execution_id}")
        if _is_safe_workspace_path(candidate, artifact_root):
            if await asyncio.to_thread(_delete_workspace, candidate):
                dirs_removed += 1

    if dirs_removed:
        logger.info(f"UI 报告盘文件裁剪:删除 {dirs_removed} 个超出保留数的 success 目录")
    return dirs_removed


async def _run_cleanup_round() -> None:
    """单次清理回合(APScheduler 调用入口)。"""
    try:
        await cleanup_expired_artifacts()
        await cleanup_success_reports_overflow()
    except Exception as e:
        logger.exception(f"UI 产物清理回合异常: {e}")


def register_cleanup_job(scheduler: AsyncIOScheduler) -> None:
    """把清理任务注册到现有 APScheduler 实例(每天凌晨 3:17 跑一次)。

    Why 3:17 而不是 3:00:避开整点拥堵 + 与定时任务调度高峰错开。
    """
    try:
        scheduler.add_job(
            _run_cleanup_round,
            trigger=CronTrigger(hour=3, minute=17),
            id="ui_artifact_cleanup",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("UI 产物清理任务已注册:每日 03:17 触发")
    except Exception as e:
        logger.error(f"注册 UI 产物清理任务失败: {e}")


__all__ = [
    "cleanup_expired_artifacts",
    "cleanup_success_reports_overflow",
    "register_cleanup_job",
]
