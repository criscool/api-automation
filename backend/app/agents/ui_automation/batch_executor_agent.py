"""
UI 批次执行智能体（阶段五）

职责:
1. 接收 UiBatchExecutionInput → 直接投递所有子脚本到 UI_SCRIPT_EXECUTOR
2. 后台轮询 DB 检查所有子执行是否完成
3. 全部完成后发布 UiBatchExecutionDoneMessage → UI_DATA_PERSISTENCE 落库

约束:
- 不调 LLM
- 复用 UiScriptExecutorAgent 完整单脚本链路 (安全扫描 → 子进程 → 报告)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from autogen_core import MessageContext, TopicId, message_handler, type_subscription
from loguru import logger

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.types import AgentTypes, TopicTypes
from app.models.ui_automation import UiBatchExecution, UiScriptExecution, UiTestScript
from app.settings.config import settings

from .schemas import (
    UiBatchCancelCommand,
    UiBatchExecutionDoneMessage,
    UiBatchExecutionInput,
    UiScriptExecutionInput,
    UiSubExecutionCompleted,
)


POLL_INTERVAL = 3  # 秒


@type_subscription(topic_type=TopicTypes.UI_BATCH_EXECUTOR.value)
class UiBatchExecutorAgent(BaseApiAutomationAgent):
    """UI 批次执行智能体"""

    def __init__(self, model_client_instance=None, **kwargs):
        super().__init__(
            agent_type=AgentTypes.UI_BATCH_EXECUTOR,
            model_client_instance=model_client_instance,
            **kwargs,
        )
        self._batch_cancel_flags: Dict[str, bool] = {}
        logger.info(f"UI 批次执行智能体初始化完成: {self.agent_name}")

    @message_handler
    async def handle_batch_start(
        self, message: UiBatchExecutionInput, ctx: MessageContext
    ) -> None:
        await self._start_batch(message)

    @message_handler
    async def handle_cancel(
        self, message: UiBatchCancelCommand, ctx: MessageContext
    ) -> None:
        self._batch_cancel_flags[message.batch_id] = True
        logger.info(f"批次取消命令已处理 batch={message.batch_id}")

    async def _start_batch(self, msg: UiBatchExecutionInput) -> None:
        total = len(msg.script_ids)
        execution_ids: Dict[str, str] = {}  # script_id → execution_id
        self._batch_cancel_flags[msg.batch_id] = False

        logger.info(f"批次启动 batch={msg.batch_id} scripts={total}")

        # 逐个投递
        for script_id in msg.script_ids:
            if self._batch_cancel_flags.get(msg.batch_id):
                break
            eid = await self._fire_one(msg, script_id)
            if eid:
                execution_ids[script_id] = eid

        if not execution_ids:
            await UiBatchExecution.filter(batch_id=msg.batch_id).update(
                status="completed", total_scripts=0, end_time=datetime.now()
            )
            return

        # 后台轮询等待全部完成
        asyncio.create_task(self._poll_until_done(msg, execution_ids))

    async def _fire_one(self, msg: UiBatchExecutionInput, script_id: str) -> Optional[str]:
        execution_id = uuid.uuid4().hex

        script = await UiTestScript.filter(script_id=script_id).first()
        if not script or not script.file_path:
            await UiScriptExecution.create(
                execution_id=execution_id, script_id=script_id,
                status="error", batch_id=msg.batch_id,
                error_message=f"脚本无效: {'不存在' if not script else '无 file_path'}"[:500],
                triggered_by=msg.triggered_by,
            )
            logger.warning(f"跳过无效脚本 batch={msg.batch_id} script={script_id}")
            return None

        # 校验文件实际存在
        from pathlib import Path
        script_abs = (Path(settings.UI_AUTOMATION_WORKSPACE) / script.file_path).resolve()
        if not script_abs.exists():
            await UiScriptExecution.create(
                execution_id=execution_id, script_id=script_id,
                status="error", batch_id=msg.batch_id,
                error_message=f"脚本文件不存在: {script.file_path}"[:500],
                triggered_by=msg.triggered_by,
            )
            logger.warning(f"脚本文件缺失 batch={msg.batch_id} script={script_id} path={script.file_path}")
            return None

        sub_session_id = f"ui_exec_{uuid.uuid4().hex[:12]}"
        extra_env = dict(msg.extra_env or {})
        if script.base_url:
            extra_env.setdefault("UI_BASE_URL", script.base_url)
            extra_env.setdefault("UI_LOGIN_URL", script.base_url + "/")

        try:
            await UiScriptExecution.create(
                execution_id=execution_id, script_id=script_id,
                status="pending", batch_id=msg.batch_id,
                execution_config={
                    "script_relative_path": script.file_path,
                    "timeout_seconds": msg.timeout_seconds,
                    "extra_env": extra_env,
                    "session_id": sub_session_id,
                },
                triggered_by=msg.triggered_by,
            )
        except Exception as e:
            logger.exception(f"创建执行记录失败 script={script_id}: {e}")
            return None

        exec_input = UiScriptExecutionInput(
            execution_id=execution_id,
            session_id=sub_session_id,
            script_id=script_id,
            script_relative_path=script.file_path,
            triggered_by=msg.triggered_by,
            timeout_seconds=msg.timeout_seconds,
            extra_env=extra_env,
        )

        try:
            await self.runtime.publish_message(
                exec_input,
                topic_id=TopicId(
                    type=TopicTypes.UI_SCRIPT_EXECUTOR.value,
                    source=self.agent_name,
                ),
            )
            logger.info(f"已投递子执行 batch={msg.batch_id} script={script_id} exec={execution_id[:8]}")
            return execution_id
        except Exception as e:
            logger.exception(f"投递子执行失败 script={script_id}: {e}")
            await UiScriptExecution.filter(execution_id=execution_id).update(
                status="error", error_message=f"投递失败: {e}"[:500]
            )
            return None

    async def _poll_until_done(
        self, msg: UiBatchExecutionInput, execution_ids: Dict[str, str]
    ) -> None:
        """轮询 DB 检查所有子执行是否完成"""
        total = len(execution_ids)
        batch_timeout = total * settings.UI_PLAYWRIGHT_SUBPROCESS_TIMEOUT * 2
        started = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - started
            if elapsed > batch_timeout:
                logger.error(f"批次总超时 batch={msg.batch_id}")
                break
            if self._batch_cancel_flags.get(msg.batch_id):
                logger.info(f"批次被取消 batch={msg.batch_id}")
                break

            await asyncio.sleep(POLL_INTERVAL)

            # 查所有子执行状态
            done_count = 0
            success_count = 0
            failed_count = 0
            timeout_count = 0
            cancelled_count = 0

            for eid in execution_ids.values():
                row = await UiScriptExecution.filter(execution_id=eid).first()
                if not row:
                    done_count += 1  # 不存在视为完成
                    continue
                if row.status in ("success",):
                    done_count += 1
                    success_count += 1
                elif row.status in ("failed", "error"):
                    done_count += 1
                    failed_count += 1
                elif row.status in ("timeout",):
                    done_count += 1
                    timeout_count += 1
                elif row.status in ("cancelled",):
                    done_count += 1
                    cancelled_count += 1
                elif row.status in ("safety_blocked",):
                    done_count += 1
                    failed_count += 1

            logger.debug(
                f"批次轮询 batch={msg.batch_id} done={done_count}/{total}"
            )

            if done_count >= total:
                status = "completed"
                if failed_count > 0 or timeout_count > 0:
                    status = "partial_failed"
                if cancelled_count > 0:
                    status = "cancelled"

                done = UiBatchExecutionDoneMessage(
                    batch_id=msg.batch_id,
                    session_id="",
                    status=status,
                    total_scripts=total,
                    success_count=success_count,
                    failed_count=failed_count,
                    timeout_count=timeout_count,
                    cancelled_count=cancelled_count,
                    safety_blocked_count=0,
                    started_at=datetime.now(),
                    duration_ms=int(elapsed * 1000),
                    triggered_by=msg.triggered_by,
                )
                try:
                    await self.runtime.publish_message(
                        done,
                        topic_id=TopicId(
                            type=TopicTypes.UI_DATA_PERSISTENCE.value,
                            source=self.agent_name,
                        ),
                    )
                    logger.info(
                        f"批次完成 batch={msg.batch_id} status={status} "
                        f"ok={success_count} fail={failed_count} total={total}"
                    )
                except Exception as e:
                    logger.error(f"批次落库投递失败 batch={msg.batch_id}: {e}")
                break

        self._batch_cancel_flags.pop(msg.batch_id, None)


__all__ = ["UiBatchExecutorAgent"]
