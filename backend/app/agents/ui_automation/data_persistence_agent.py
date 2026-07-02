"""
UI 数据持久化智能体（阶段三）

订阅 TopicTypes.UI_DATA_PERSISTENCE,接收 UiExecutionDoneMessage,事务化落库:
  1. 更新 ui_script_executions 的执行终态(status / start_time / end_time / 退出码 / 日志 / 配置 / 产物汇总)
  2. 写 ui_test_reports(执行成功且 HTML 报告存在时),report_url 走 StaticFiles 路径约定
  3. 批量写 ui_execution_artifacts,带 expires_at(用于 P3-09 清理任务过滤)

零回归:
- 表全是 ui_ 前缀,与 API 自动化表物理隔离
- 整段事务,失败回滚,不破坏 ui_script_executions 的 pending 行
- API 层在调度执行前已经创建 ui_script_executions(execution_id=..., status='pending'),
  本 Agent 只 update;若 API 层缺失,这里兜底 create。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from autogen_core import MessageContext, message_handler, type_subscription
from loguru import logger
from tortoise.transactions import in_transaction

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.types import AgentTypes, MessageRegion, TopicTypes
from app.models.ui_automation import (
    UiBatchExecution,
    UiExecutionArtifact,
    UiScriptExecution,
    UiTestReport,
    UiTestScript,
)
from app.settings.config import settings

from .schemas import UiBatchExecutionDoneMessage, UiExecutionDoneMessage


# StaticFiles 在 P3-06 里挂载到 /static/ui-reports/,所有 file_url / report_url 都按此前缀拼
_STATIC_PREFIX = "/static/ui-reports"


@type_subscription(topic_type=TopicTypes.UI_DATA_PERSISTENCE.value)
class UiDataPersistenceAgent(BaseApiAutomationAgent):
    """UI 自动化执行结果落库"""

    def __init__(self, model_client_instance=None, **kwargs):
        super().__init__(
            agent_type=AgentTypes.UI_DATA_PERSISTENCE,
            model_client_instance=model_client_instance,
            **kwargs,
        )
        logger.info(f"UI 数据持久化智能体初始化完成: {self.agent_name}")

    # ------------------------------------------------------------------
    # 消息入口
    # ------------------------------------------------------------------

    @message_handler
    async def handle_persistence(
        self, message: UiExecutionDoneMessage, ctx: MessageContext
    ) -> None:
        await self._ensure_database_connection()

        try:
            async with in_transaction():
                await self._upsert_execution(message)
                await self._save_report_if_any(message)
                await self._save_artifacts(message)
        except Exception as e:
            logger.exception(
                f"[exec {message.execution_id}] UI 执行落库失败: {e}"
            )
            await self._send_message(
                f"执行落库失败: {e}",
                message_type="error",
                region=MessageRegion.ERROR,
            )
            return

        await self._send_message(
            f"执行结果已入库 (execution_id={message.execution_id[:8]}, status={message.status}, "
            f"产物 {len(message.artifacts)} 件)",
            message_type="success",
            region=MessageRegion.SUCCESS,
        )

    @message_handler
    async def handle_batch_persistence(
        self, message: UiBatchExecutionDoneMessage, ctx: MessageContext
    ) -> None:
        """批次执行终态落库"""
        defaults = {
            "status": message.status,
            "start_time": message.started_at,
            "end_time": message.finished_at,
            "duration_ms": message.duration_ms,
            "total_scripts": message.total_scripts,
            "success_count": message.success_count,
            "failed_count": message.failed_count,
            "timeout_count": message.timeout_count,
            "cancelled_count": message.cancelled_count,
            "safety_blocked_count": message.safety_blocked_count,
        }
        batch, created = await UiBatchExecution.get_or_create(
            batch_id=message.batch_id,
            defaults=defaults,
        )
        if not created:
            await UiBatchExecution.filter(batch_id=message.batch_id).update(**defaults)
        logger.info(
            f"批次终态落库 batch={message.batch_id} status={message.status} "
            f"ok={message.success_count}/{message.total_scripts}"
        )

    # ------------------------------------------------------------------
    # 数据落库分步
    # ------------------------------------------------------------------

    async def _upsert_execution(self, message: UiExecutionDoneMessage) -> None:
        """更新或创建 ui_script_executions。

        API 层在触发执行时应已写入 status='pending' 的行;本方法 update 终态字段。
        若该行不存在(异常/启动自愈场景),create 一条带终态的记录兜底。
        """
        # 按 type 统计产物
        artifact_counter: Counter[str] = Counter()
        artifact_size_total = 0
        for a in message.artifacts:
            artifact_counter[a.artifact_type] += 1
            artifact_size_total += a.file_size

        artifact_summary: Dict[str, Any] = {
            "by_type": dict(artifact_counter),
            "total_count": len(message.artifacts),
            "total_size": artifact_size_total,
            "workspace_relative": message.workspace_relative,
            "html_report_dir": message.html_report_dir,
            "log_file": message.log_file,
        }

        defaults = {
            "script_id": message.script_id,
            "status": message.status,
            "start_time": message.started_at,
            "end_time": message.finished_at,
            "duration_ms": message.duration_ms,
            "exit_code": message.exit_code,
            "stdout": message.stdout,
            "stderr": message.stderr,
            "error_message": message.error_message[:500] if message.error_message else "",
            "execution_config": message.execution_config or {},
            "artifact_summary": artifact_summary,
            "triggered_by": message.triggered_by,
        }

        execution, created = await UiScriptExecution.get_or_create(
            execution_id=message.execution_id,
            defaults=defaults,
        )
        if not created:
            await UiScriptExecution.filter(execution_id=message.execution_id).update(**defaults)
            logger.debug(f"[exec {message.execution_id}] ui_script_executions 已更新")
        else:
            logger.info(
                f"[exec {message.execution_id}] ui_script_executions 兜底 create"
                f"(API 层未预建 pending 行?)"
            )

        # 同步更新脚本的"最近执行"字段（脚本管理列表展示用）
        # 只在终态才更新，避免中间态覆盖
        if message.status in ("success", "failed", "timeout", "error", "interrupted", "cancelled"):
            try:
                await UiTestScript.filter(script_id=message.script_id).update(
                    last_execution_status=message.status,
                    last_execution_time=defaults.get("end_time"),
                    last_execution_id=message.execution_id,
                )
            except Exception as e:
                # 更新失败不影响主流程（脚本可能已删）
                logger.warning(
                    f"[exec {message.execution_id}] 更新脚本 last_execution 失败: {e}"
                )

    async def _save_report_if_any(self, message: UiExecutionDoneMessage) -> None:
        """如果 HTML 报告主页存在,落 ui_test_reports 一条。"""
        if not message.html_report_dir:
            return
        index_html = Path(message.html_report_dir) / "index.html"
        if not index_html.exists():
            logger.debug(
                f"[exec {message.execution_id}] 跳过 ui_test_reports:HTML 报告 index.html 缺失"
            )
            return

        summary = message.report_summary or {}
        report_url = self._build_static_url(message.workspace_relative, "html/index.html")

        defaults = {
            "execution_id": message.execution_id,
            "script_id": message.script_id,
            "report_type": "playwright",
            "report_url": report_url,
            "report_path": str(index_html.resolve()),
            "summary": summary,
            "passed": int(summary.get("passed", 0) or 0),
            "failed": int(summary.get("failed", 0) or 0),
            "skipped": int(summary.get("skipped", 0) or 0),
        }

        # report_id = report:<execution_id>(单执行单报告,幂等)
        report_id = f"report_{message.execution_id}"
        report, created = await UiTestReport.get_or_create(
            report_id=report_id,
            defaults=defaults,
        )
        if not created:
            await UiTestReport.filter(report_id=report_id).update(**defaults)

        # 自动生成 Allure 报告（异步，不阻塞执行完成事件）
        # UI_AUTO_GENERATE_ALLURE=False 时不触发；等前端按钮
        if settings.UI_AUTO_GENERATE_ALLURE:
            try:
                from app.services.ui_automation.allure_service import (
                    trigger_single_generate_task,
                )
                await trigger_single_generate_task(
                    execution_id=message.execution_id,
                    script_id=message.script_id,
                )
            except Exception as e:
                # 自动生成的触发失败不能影响执行完成事件本身
                logger.warning(
                    f"[exec {message.execution_id}] 触发 Allure 自动生成失败（不影响主流程）: {e}"
                )

    async def _save_artifacts(self, message: UiExecutionDoneMessage) -> None:
        """批量写 ui_execution_artifacts(先清掉同执行的旧记录,重跑场景幂等)。"""
        if not message.artifacts:
            return

        retention_days = int(settings.UI_ARTIFACT_RETENTION_DAYS or 7)
        expires_at = datetime.now() + timedelta(days=retention_days)

        # 同 execution_id 旧记录清掉(理论上 execution_id 是 uuid 不会重复;
        # 但启动自愈兜底 + 重试场景下可能产生重复,保险起见删掉再写)
        await UiExecutionArtifact.filter(execution_id=message.execution_id).delete()

        rows = []
        for idx, a in enumerate(message.artifacts):
            # artifact_id = <execution_id>_<idx>_<artifact_type>(全表 unique)
            artifact_id = f"{message.execution_id}_{idx}_{a.artifact_type}"
            rows.append(UiExecutionArtifact(
                artifact_id=artifact_id,
                execution_id=message.execution_id,
                artifact_type=a.artifact_type,
                file_path=a.file_path,
                file_url=self._build_static_url(message.workspace_relative, a.relative_path),
                file_size=a.file_size,
                expires_at=expires_at,
            ))

        await UiExecutionArtifact.bulk_create(rows, batch_size=100)
        logger.debug(
            f"[exec {message.execution_id}] 入库 {len(rows)} 件产物,expires_at={expires_at}"
        )

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _build_static_url(workspace_relative: str, relative_path: str) -> str:
        """拼 StaticFiles URL,统一用正斜杠并去掉头尾多余 /。"""
        if not workspace_relative:
            return ""
        ws = workspace_relative.strip("/").replace("\\", "/")
        rel = (relative_path or "").lstrip("/").replace("\\", "/")
        if not rel:
            return f"{_STATIC_PREFIX}/{ws}"
        return f"{_STATIC_PREFIX}/{ws}/{rel}"


__all__ = ["UiDataPersistenceAgent"]
