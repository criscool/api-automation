"""
UI 自动化执行会话自愈服务(阶段三 P3-06)

职责:
- 后端进程启动时,把 ui_script_executions 中 status='running' 或 status='pending' 的"上次未完结"
  执行记录批量改为 'interrupted',避免前端永远转圈
- 同时把 ui_recording_sessions 中 status in (launching, recording, postprocessing) 的僵尸录制
  批量改为 'interrupted',避免录制列表卡死
- 不杀真实子进程(进程已随后端重启而死),只修 DB

零回归:
- 仅在 settings.UI_AUTOMATION_ENABLED=True 时被 lifespan 调用
- 只 UPDATE 一张 ui_ 前缀表,不触碰 API 自动化业务表
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger


async def heal_dangling_executions() -> int:
    """把所有 running/pending 的执行记录改为 interrupted,返回受影响行数。

    场景:后端进程崩溃 / 重启时,正在跑的执行会"挂"在 running 状态。
    启动时一次性扫描修正,避免前端列表里永远显示"运行中"。
    """
    try:
        from app.models.ui_automation import UiScriptExecution
    except Exception as e:
        logger.warning(f"加载 UiScriptExecution 失败,跳过自愈: {e}")
        return 0

    try:
        dangling_qs = UiScriptExecution.filter(status__in=["running", "pending"])
        ids = [row.execution_id for row in await dangling_qs.only("execution_id").all()]
        if not ids:
            return 0

        now = datetime.now()
        affected = await UiScriptExecution.filter(execution_id__in=ids).update(
            status="interrupted",
            end_time=now,
            error_message="后端重启时检测到未完结执行,自动标记为 interrupted",
        )
        logger.info(
            f"UI 执行自愈完成: {affected} 条 running/pending 记录改为 interrupted"
        )
        return affected
    except Exception as e:
        logger.error(f"UI 执行自愈失败: {e}")
        return 0


async def heal_dangling_recordings() -> int:
    """把所有 launching/recording/postprocessing 的录制会话改为 interrupted,返回受影响行数。

    场景:后端重启时正在录制、或者本地 daemon 断开导致录制永远不结束,
    ui_recording_sessions 会"挂"在运行中状态,前端点取消都取消不了(因为 codegen 子进程已经不在)。
    """
    try:
        from app.models.ui_automation import UiRecordingSession
    except Exception as e:
        logger.warning(f"加载 UiRecordingSession 失败,跳过录制自愈: {e}")
        return 0

    try:
        dangling_qs = UiRecordingSession.filter(
            status__in=["launching", "recording", "postprocessing"]
        )
        ids = [row.session_id for row in await dangling_qs.only("session_id").all()]
        if not ids:
            return 0

        now = datetime.now()
        affected = await UiRecordingSession.filter(session_id__in=ids).update(
            status="interrupted",
            end_time=now,
            error_message="后端重启时检测到未完结录制,自动标记为 interrupted",
        )
        logger.info(
            f"UI 录制自愈完成: {affected} 条 launching/recording/postprocessing 记录改为 interrupted"
        )
        return affected
    except Exception as e:
        logger.error(f"UI 录制自愈失败: {e}")
        return 0


__all__ = ["heal_dangling_executions", "heal_dangling_recordings"]
