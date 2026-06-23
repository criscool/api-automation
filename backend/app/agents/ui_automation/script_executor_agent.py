"""
UI 脚本执行智能体（阶段三）

职责:
1. 接收 UiScriptExecutionInput → 静态安全扫描 → 子进程执行 → 解析报告与产物
2. 把执行进度按行投递到 stream_response topic(走基类 _send_message),供前端 SSE 实时显示
3. 执行完成后,组装 UiExecutionDoneMessage 发布到 TopicTypes.UI_DATA_PERSISTENCE,
   由 UiDataPersistenceAgent 落库

约束:
- 不调 LLM(执行就是执行,没有"智能"环节)
- 不直接读写 DB(交给 UiDataPersistenceAgent)
- 不暴露给 API 自动化主题,严格订阅 UI_SCRIPT_EXECUTOR

零回归:settings.UI_AUTOMATION_ENABLED=False 时 orchestrator 不注册本 Agent,根本不会被实例化。
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from autogen_core import MessageContext, TopicId, message_handler, type_subscription
from loguru import logger

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.types import AgentTypes, MessageRegion, TopicTypes
from app.services.ui_automation import execution_service, report_service, script_safety_service
from app.settings.config import settings

from .schemas import (
    UiExecutionArtifactInfo,
    UiExecutionDoneMessage,
    UiScriptExecutionInput,
)


# 进度推送节流:超过 N 行只推汇总,避免 SSE 通道被 Playwright 的逐帧日志洪水冲垮
_PROGRESS_LINE_LIMIT = 200


@type_subscription(topic_type=TopicTypes.UI_SCRIPT_EXECUTOR.value)
class UiScriptExecutorAgent(BaseApiAutomationAgent):
    """UI 脚本执行智能体"""

    def __init__(self, model_client_instance=None, **kwargs):
        super().__init__(
            agent_type=AgentTypes.UI_SCRIPT_EXECUTOR,
            model_client_instance=model_client_instance,
            **kwargs,
        )
        logger.info(f"UI 脚本执行智能体初始化完成: {self.agent_name}")

    # ------------------------------------------------------------------
    # 消息入口
    # ------------------------------------------------------------------

    @message_handler
    async def handle_execute(
        self, message: UiScriptExecutionInput, ctx: MessageContext
    ) -> None:
        started_at = datetime.now()
        execution_id = message.execution_id
        session_id = message.session_id
        script_id = message.script_id

        await self._send_message(
            f"准备执行脚本 (execution_id={execution_id[:8]}, script={message.script_relative_path})",
            message_type="info",
            region=MessageRegion.PROCESS,
        )

        # --- 1. 静态安全扫描 -------------------------------------------------
        abs_script_path = (Path(settings.UI_AUTOMATION_WORKSPACE) / message.script_relative_path).resolve()
        scan = script_safety_service.scan_file(abs_script_path)
        if not scan.ok:
            await self._send_message(
                f"安全扫描拒绝执行: {scan.reason()}",
                message_type="error",
                region=MessageRegion.ERROR,
            )
            await self._publish_done(
                started_at=started_at,
                message=message,
                status="safety_blocked",
                exit_code=None,
                duration_ms=0,
                stdout="",
                stderr="",
                error_message=f"脚本命中安全黑名单: {scan.reason()}",
                workspace_dir="",
                html_report_dir="",
                json_report_file="",
                log_file="",
                workspace_relative="",
                report_summary={"parse_error": "safety_blocked"},
                artifacts=[],
            )
            return

        # --- 2. 推子进程 ---------------------------------------------------
        # 节流计数:running 阶段超过限额后只推每 50 行一条摘要
        running_line_count = 0

        async def _on_progress(progress: execution_service.ExecutionProgress) -> None:
            nonlocal running_line_count
            if progress.phase == "queued":
                await self._send_message(
                    "已进入执行队列",
                    message_type="info",
                    region=MessageRegion.PROCESS,
                )
                return
            if progress.phase == "preparing":
                await self._send_message(
                    "正在准备工作区",
                    message_type="info",
                    region=MessageRegion.PROCESS,
                )
                return
            if progress.phase == "finishing":
                await self._send_message(
                    "执行结束,正在归档产物",
                    message_type="info",
                    region=MessageRegion.PROCESS,
                )
                return
            # running 阶段:每行回调
            if progress.phase == "running" and progress.line:
                running_line_count += 1
                if running_line_count <= _PROGRESS_LINE_LIMIT or running_line_count % 50 == 0:
                    region = MessageRegion.ERROR if progress.stream == "stderr" else MessageRegion.PROCESS
                    msg_type = "warning" if progress.stream == "stderr" else "info"
                    # 截断单行,避免单条 SSE 太长
                    line_payload = progress.line[:500]
                    await self._send_message(
                        f"[{progress.stream}] {line_payload}",
                        message_type=msg_type,
                        region=region,
                    )

        try:
            result = await execution_service.run_playwright_script(
                execution_id=execution_id,
                script_relative_path=message.script_relative_path,
                timeout_seconds=message.timeout_seconds,
                extra_env=message.extra_env or None,
                progress_callback=_on_progress,
            )
        except asyncio.CancelledError:
            await self._send_message(
                "执行被外部取消(可能是后端重启)",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            await self._publish_done(
                started_at=started_at,
                message=message,
                status="cancelled",
                exit_code=None,
                duration_ms=int((datetime.now() - started_at).total_seconds() * 1000),
                stdout="",
                stderr="",
                error_message="执行被取消",
                workspace_dir="",
                html_report_dir="",
                json_report_file="",
                log_file="",
                workspace_relative="",
                report_summary={"parse_error": "cancelled"},
                artifacts=[],
            )
            raise
        except Exception as e:
            import traceback as _tb
            tb_text = _tb.format_exc()
            logger.exception(f"[exec {execution_id}] 执行服务抛异常")
            err_type = type(e).__name__
            err_repr = repr(e) if str(e) == "" else str(e)
            full_msg = f"执行服务异常 [{err_type}]: {err_repr}"
            await self._send_message(
                full_msg,
                message_type="error",
                region=MessageRegion.ERROR,
            )
            await self._publish_done(
                started_at=started_at,
                message=message,
                status="error",
                exit_code=None,
                duration_ms=int((datetime.now() - started_at).total_seconds() * 1000),
                stdout="",
                stderr=tb_text,
                error_message=full_msg,
                workspace_dir="",
                html_report_dir="",
                json_report_file="",
                log_file="",
                workspace_relative="",
                report_summary={"parse_error": "exception"},
                artifacts=[],
            )
            return

        # --- 3. 解析报告 + 收集产物 ----------------------------------------
        summary = report_service.parse_playwright_json(result.json_report_file)
        artifact_records = report_service.collect_artifacts(
            result.workspace_dir,
            max_video_size_mb=settings.UI_MAX_VIDEO_SIZE_MB,
        )
        artifacts = [
            UiExecutionArtifactInfo(
                artifact_type=ar.artifact_type,
                file_path=ar.file_path,
                relative_path=ar.relative_path,
                file_size=ar.file_size,
            )
            for ar in artifact_records
        ]

        # --- 4. 终态汇总文案 -----------------------------------------------
        if result.status == "success" and summary.is_all_passed:
            await self._send_message(
                f"执行成功 (用例 {summary.total} / 通过 {summary.passed} / 耗时 {result.duration_ms}ms)",
                message_type="success",
                region=MessageRegion.SUCCESS,
            )
        elif result.status == "timeout":
            await self._send_message(
                f"执行超时 (耗时 {result.duration_ms}ms): {result.error_message}",
                message_type="error",
                region=MessageRegion.ERROR,
            )
        else:
            await self._send_message(
                f"执行结束 status={result.status} 用例 {summary.total} / 通过 {summary.passed} / "
                f"失败 {summary.failed} / 超时 {summary.timed_out}",
                message_type="warning" if summary.failed or summary.timed_out else "info",
                region=MessageRegion.WARNING if summary.failed or summary.timed_out else MessageRegion.PROCESS,
            )

        # --- 5. 投递 DONE 给 Persistence -----------------------------------
        await self._publish_done(
            started_at=started_at,
            message=message,
            status=result.status,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            error_message=result.error_message or summary.parse_error,
            workspace_dir=result.workspace_dir,
            html_report_dir=result.html_report_dir,
            json_report_file=result.json_report_file,
            log_file=result.log_file,
            workspace_relative=result.workspace_relative,
            report_summary=summary.to_dict(),
            artifacts=artifacts,
        )

    # ------------------------------------------------------------------
    # DONE 投递
    # ------------------------------------------------------------------

    async def _publish_done(
        self,
        *,
        started_at: datetime,
        message: UiScriptExecutionInput,
        status: str,
        exit_code: Optional[int],
        duration_ms: int,
        stdout: str,
        stderr: str,
        error_message: str,
        workspace_dir: str,
        html_report_dir: str,
        json_report_file: str,
        log_file: str,
        workspace_relative: str,
        report_summary: dict,
        artifacts: list,
    ) -> None:
        done = UiExecutionDoneMessage(
            execution_id=message.execution_id,
            session_id=message.session_id,
            script_id=message.script_id,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=datetime.now(),
            stdout=stdout[:200_000],  # 防止单条消息超过 SQLite blob 限制
            stderr=stderr[:100_000],
            error_message=error_message,
            workspace_dir=workspace_dir,
            html_report_dir=html_report_dir,
            json_report_file=json_report_file,
            log_file=log_file,
            workspace_relative=workspace_relative,
            report_summary=report_summary,
            artifacts=artifacts,
            triggered_by=message.triggered_by,
            execution_config={
                "script_relative_path": message.script_relative_path,
                "timeout_seconds": message.timeout_seconds,
                "extra_env_keys": list((message.extra_env or {}).keys()),
                "headless": settings.UI_HEADLESS,
            },
        )

        try:
            await self.runtime.publish_message(
                done,
                topic_id=TopicId(type=TopicTypes.UI_DATA_PERSISTENCE.value, source=self.agent_name),
            )
        except Exception as e:
            # 投递失败不影响 SSE 已经推过的进度;落库会缺,需要靠"启动自愈"补
            logger.error(f"[exec {message.execution_id}] 投递 UI_DATA_PERSISTENCE 失败: {e}")


__all__ = ["UiScriptExecutorAgent"]
