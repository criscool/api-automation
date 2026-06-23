"""
UI 自动化编排器服务（阶段二）

职责:
1. 启动 / 关闭 独立的 SingleThreadedAgentRuntime（不与 API 自动化共享）
2. 注册 PageAnalyzerAgent + UiScriptGeneratorAgent（受 settings.UI_AUTOMATION_ENABLED 控制）
3. 提供业务入口:
   - analyze_page(input)    → 发布 PageAnalysisInput
   - generate_script(input) → 装填 PageAnalysisOutput 后发布 ScriptGenerationInput
4. 通过 StreamResponseCollector 把进度/结果广播到 stream_response topic,API 层走 SSE 给前端
5. 终态消息持久化:
   - PageAnalysisOutput → ui_page_analysis_results + ui_page_elements
   - ScriptGenerationOutput → ui_test_scripts，同步写文件到 UI_AUTOMATION_WORKSPACE/scripts/

UI_AUTOMATION_ENABLED=False 时,本服务的所有方法均抛 UiAutomationDisabledError,API 层应直接 503,
不创建 runtime、不导入 UI Agent 类,严格零回归。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from autogen_core import (
    ClosureAgent,
    ClosureContext,
    MessageContext,
    SingleThreadedAgentRuntime,
    TopicId,
    TypeSubscription,
)
from loguru import logger

from app.core.agents.collector import StreamResponseCollector
from app.core.config import settings as core_settings
from app.core.messages import StreamMessage
from app.core.types import AgentPlatform, TopicTypes
from app.settings.config import settings


class UiAutomationDisabledError(RuntimeError):
    """UI 自动化模块未启用（settings.UI_AUTOMATION_ENABLED=False）"""


class UiAutomationOrchestrator:
    """UI 自动化编排器（单例）

    NOTE: Agent 类 / Schema 模型都在方法内部 lazy import,避免 settings.UI_AUTOMATION_ENABLED=False
    时整个模块都不加载,确保 kill switch 彻底零回归。
    """

    _instance: Optional["UiAutomationOrchestrator"] = None

    def __new__(cls) -> "UiAutomationOrchestrator":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._runtime: Optional[SingleThreadedAgentRuntime] = None
        self._collector: Optional[StreamResponseCollector] = None

        # 仍保留内存缓存，作为 SSE 之外的同步快速查询路径（DB 是持久化主路径）
        self._analysis_cache: Dict[str, Any] = {}
        self._script_cache: Dict[str, Any] = {}

        # 脚本生成的 session → page_analysis_id 映射（落库时回填 analysis_id 用）
        self._script_session_to_analysis: Dict[str, str] = {}

        # 进度回调（按 session_id 注册）
        self._session_subscribers: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}

        # 幂等性：记录正在运行的任务指纹 → session_id
        self._active_fingerprints: Dict[str, str] = {}
        # session_id → fingerprint 映射（用于清理）
        self._session_to_fingerprint: Dict[str, str] = {}

        # 新增：记录正在生成的 analysis_id -> session_id
        self._active_script_gens: Dict[str, str] = {}
        self._session_to_analysis_gen: Dict[str, str] = {}

        # 批次桥接: execution_id → batch_id 映射
        self._batch_execution_map: Dict[str, str] = {}

        logger.info("UI 自动化编排器实例创建（尚未启动 runtime）")

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def _check_enabled(self) -> None:
        if not settings.UI_AUTOMATION_ENABLED:
            raise UiAutomationDisabledError(
                "UI 自动化模块未启用，请在 .env 设置 UI_AUTOMATION_ENABLED=true"
            )

    async def initialize(self) -> None:
        """启动 runtime 并注册 UI Agent。多次调用幂等。"""
        self._check_enabled()
        if self._runtime is not None:
            return

        logger.info("🚀 启动 UI 自动化编排器 runtime ...")

        # lazy import 防止 kill switch 关闭时仍走 import
        from app.agents.ui_automation.page_analyzer_agent import PageAnalyzerAgent
        from app.agents.ui_automation.script_generator_agent import UiScriptGeneratorAgent
        from app.agents.ui_automation.script_executor_agent import UiScriptExecutorAgent
        from app.agents.ui_automation.data_persistence_agent import UiDataPersistenceAgent
        from app.agents.ui_automation.recording_orchestrator_agent import UiRecordingOrchestratorAgent
        from app.core.types import AgentTypes

        runtime = SingleThreadedAgentRuntime()

        await PageAnalyzerAgent.register(
            runtime,
            type=AgentTypes.UI_PAGE_ANALYZER.value,
            factory=lambda: PageAnalyzerAgent(),
        )
        await UiScriptGeneratorAgent.register(
            runtime,
            type=AgentTypes.UI_SCRIPT_GENERATOR.value,
            factory=lambda: UiScriptGeneratorAgent(),
        )
        await UiScriptExecutorAgent.register(
            runtime,
            type=AgentTypes.UI_SCRIPT_EXECUTOR.value,
            factory=lambda: UiScriptExecutorAgent(),
        )
        await UiDataPersistenceAgent.register(
            runtime,
            type=AgentTypes.UI_DATA_PERSISTENCE.value,
            factory=lambda: UiDataPersistenceAgent(),
        )
        await UiRecordingOrchestratorAgent.register(
            runtime,
            type=AgentTypes.UI_RECORDING_ORCHESTRATOR.value,
            factory=lambda: UiRecordingOrchestratorAgent(),
        )
        # 批次执行编排 Agent
        from app.agents.ui_automation.batch_executor_agent import UiBatchExecutorAgent
        await UiBatchExecutorAgent.register(
            runtime,
            type=AgentTypes.UI_BATCH_EXECUTOR.value,
            factory=lambda: UiBatchExecutorAgent(),
        )

        collector = StreamResponseCollector(platform=AgentPlatform.UI_AUTOMATION)
        orchestrator_self = self

        async def stream_closure(
            ctx: ClosureContext,
            message: StreamMessage,
            msg_ctx: MessageContext,
        ) -> None:
            await orchestrator_self._on_stream_message(message)

        collector.set_callback(stream_closure)
        await ClosureAgent.register_closure(
            runtime,
            "ui_stream_collector",
            stream_closure,
            subscriptions=lambda: [
                TypeSubscription(
                    topic_type="stream_response",
                    agent_type="ui_stream_collector",
                )
            ],
        )

        # 批次桥接收集器 — 监听 UI_DATA_PERSISTENCE,
        # 收到 UiExecutionDoneMessage 时检查是否属于某个活跃批次,是则转发给 BatchExecutorAgent
        async def batch_collector_closure(
            ctx: ClosureContext,
            message: object,
            msg_ctx: MessageContext,
        ) -> None:
            from app.agents.ui_automation.schemas import UiExecutionDoneMessage
            if isinstance(message, UiExecutionDoneMessage):
                await orchestrator_self._on_sub_execution_done(message)

        await ClosureAgent.register_closure(
            runtime,
            "ui_batch_done_collector",
            batch_collector_closure,
            subscriptions=lambda: [
                TypeSubscription(
                    topic_type=TopicTypes.UI_DATA_PERSISTENCE.value,
                    agent_type="ui_batch_done_collector",
                )
            ],
        )

        runtime.start()
        self._runtime = runtime
        self._collector = collector

        logger.info("✅ UI 自动化编排器 runtime 启动完成（已注册 6 个 UI Agent + 2 个收集器）")

    async def shutdown(self) -> None:
        if self._runtime is None:
            return
        try:
            await self._runtime.stop_when_idle()
        except Exception as e:
            logger.warning(f"UI runtime 停止异常: {e}")
        finally:
            self._runtime = None
            self._collector = None
            logger.info("UI 自动化编排器 runtime 已停止")

    @property
    def is_running(self) -> bool:
        return self._runtime is not None

    # ------------------------------------------------------------------
    # 流式回调（StreamResponseCollector → session 订阅者 + 落库）
    # ------------------------------------------------------------------

    async def _on_stream_message(self, message: StreamMessage) -> None:
        """收到 StreamMessage:
        1. 终态消息 → 入内存缓存 + 异步落库（含写文件） + 清理指纹锁
        2. 任何消息 → 分发给对应 session 订阅者（SSE 实时推送）
        """
        try:
            payload: Dict[str, Any] = {
                "content": getattr(message, "content", ""),
                "message_type": getattr(message, "message_type", "info"),
                "is_final": getattr(message, "is_final", False),
                "region": getattr(message, "region", "process"),
                "agent_name": getattr(message, "agent_name", ""),
                "timestamp": datetime.now().isoformat(),
                "result": getattr(message, "result", None),
            }

            result = payload.get("result") or {}
            # 终态消息落库 + 缓存
            if isinstance(result, dict) and "output" in result:
                output = result.get("output") or {}
                if "analysis_id" in result:
                    self._analysis_cache[result["analysis_id"]] = output
                    asyncio.create_task(self._persist_analysis(output))
                elif result.get("script_type"):
                    script_id = result.get("script_id") or str(uuid.uuid4())
                    output["script_id"] = script_id
                    self._script_cache[script_id] = output
                    asyncio.create_task(self._persist_script(output))

            session_id = None
            if isinstance(result, dict):
                session_id = result.get("session_id") or (result.get("output") or {}).get("session_id")
            
            # 清理指纹锁
            if payload.get("is_final") and session_id:
                fp = self._session_to_fingerprint.pop(session_id, None)
                if fp:
                    self._active_fingerprints.pop(fp, None)
                    logger.debug(f"会话结束，清理指纹锁: session={session_id} fingerprint={fp}")
                
                # 清理脚本生成锁
                aid = self._session_to_analysis_gen.pop(session_id, None)
                if aid:
                    self._active_script_gens.pop(aid, None)
                    logger.debug(f"脚本生成会话结束，清理锁: session={session_id} analysis_id={aid}")

            for sid, subs in list(self._session_subscribers.items()):
                if session_id and sid != session_id:
                    continue
                for cb in subs:
                    try:
                        await cb(payload)
                    except Exception as cb_err:
                        logger.warning(f"session={sid} 订阅者回调异常: {cb_err}")
        except Exception as e:
            logger.error(f"_on_stream_message 处理失败: {e}")

    # ------------------------------------------------------------------
    # 落库
    # ------------------------------------------------------------------

    async def _persist_analysis(self, output: Dict[str, Any]) -> None:
        """页面分析终态结果落库:
        - ui_page_analysis_results 主表
        - ui_page_elements 元素行（每元素一行）
        """
        try:
            from app.models.ui_automation import UiPageAnalysisResult, UiPageElement
        except Exception as e:
            logger.warning(f"导入 UI 模型失败,跳过分析落库: {e}")
            return

        try:
            analysis_id = output.get("analysis_id")
            if not analysis_id:
                logger.warning("分析结果缺少 analysis_id,跳过落库")
                return

            er = output.get("element_recognition") or {}
            ia = output.get("interaction_analysis") or {}
            td = output.get("testcase_design") or {}

            elements = er.get("elements") or []
            suggested_steps = td.get("steps") or ia.get("steps") or []

            existing = await UiPageAnalysisResult.filter(analysis_id=analysis_id).first()
            payload = dict(
                session_id=output.get("session_id", "") or "",
                source_type=output.get("analysis_type", "") or "",
                source_path=output.get("page_url", "") or "",
                user_description=output.get("page_name", "") or "",
                page_type=output.get("page_name", "") or "",
                page_summary=er.get("page_description", "") or "",
                raw_response=output,
                elements=elements,
                suggested_steps=suggested_steps,
                from_fallback=bool(output.get("is_fallback")),
                model_name="doubao_vision+deepseek",
                status="success",
                error_message="",
            )
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
                await existing.save()
            else:
                await UiPageAnalysisResult.create(analysis_id=analysis_id, **payload)

            # 元素表：先清掉旧元素，再批量插入（同一 analysis_id 是覆盖式存储）
            await UiPageElement.filter(analysis_id=analysis_id).delete()
            for idx, el in enumerate(elements):
                element_id = el.get("element_id") or f"{analysis_id}_el_{idx}"
                locator_suggestions = el.get("locator_suggestions") or []
                primary_locator = locator_suggestions[0] if locator_suggestions else {}
                fallback_locators = locator_suggestions[1:] if len(locator_suggestions) > 1 else []
                try:
                    await UiPageElement.create(
                        element_id=f"{analysis_id}::{element_id}",
                        analysis_id=analysis_id,
                        element_type=el.get("category", "") or el.get("element_type", "") or "",
                        name=el.get("name", "") or "",
                        selector=primary_locator.get("expression", "") or "",
                        selector_type=primary_locator.get("strategy", "css") or "css",
                        fallback_selectors=fallback_locators,
                        text_content=el.get("text_content", "") or "",
                        attributes=el.get("visual_features") or {},
                        bbox=el.get("position") or {},
                        order_index=idx,
                        confidence=float(el.get("confidence_score") or 1.0),
                        interactive=True,
                    )
                except Exception as el_err:
                    logger.warning(f"元素落库失败 idx={idx} err={el_err}")

            logger.info(f"✅ 页面分析结果已落库: analysis_id={analysis_id} elements={len(elements)}")
        except Exception as e:
            logger.error(f"页面分析落库失败: {e}")

    async def _persist_script(self, output: Dict[str, Any]) -> None:
        """脚本生成终态结果落库 + 写入工作目录"""
        try:
            from app.models.ui_automation import UiTestScript
        except Exception as e:
            logger.warning(f"导入 UI 模型失败,跳过脚本落库: {e}")
            return

        try:
            script_id = output.get("script_id") or str(uuid.uuid4())
            script_type = output.get("script_type", "playwright_classic")
            script_name = output.get("script_name", "未命名脚本")
            file_name = output.get("file_name") or f"{script_id}.txt"
            content = output.get("script_content", "") or ""
            auxiliary_files: Dict[str, str] = output.get("auxiliary_files") or {}

            # 写入工作目录 generated_ui_tests/scripts/
            scripts_dir = os.path.join(settings.UI_AUTOMATION_WORKSPACE, "scripts")
            file_path = ""
            try:
                await asyncio.to_thread(_write_script_files, scripts_dir, file_name, content, auxiliary_files)
                file_path = os.path.join("scripts", file_name)
            except Exception as fs_err:
                logger.warning(f"脚本写文件失败,仅入库: {fs_err}")

            # 入库（覆盖式）
            analysis_id = output.get("page_analysis_id") or self._script_session_to_analysis.get(
                output.get("session_id", "")
            ) or ""
            existing = await UiTestScript.filter(script_id=script_id).first()
            payload = dict(
                analysis_id=analysis_id,
                name=script_name,
                description=output.get("user_intent", "") or "",
                script_type=script_type,
                source_type="ai",
                content=content,
                file_path=file_path,
                tags=[],
                status="active",
                base_url=output.get("target_url", "") or "",
                created_by=output.get("created_by", "") or "ai_pipeline",
            )
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
                await existing.save()
            else:
                await UiTestScript.create(script_id=script_id, **payload)

            logger.info(f"✅ 脚本已落库 + 写盘: script_id={script_id} file={file_path}")
        except Exception as e:
            logger.error(f"脚本落库失败: {e}")

    # ------------------------------------------------------------------
    # 订阅管理
    # ------------------------------------------------------------------

    def subscribe(self, session_id: str, callback: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        self._session_subscribers.setdefault(session_id, []).append(callback)

    def unsubscribe(self, session_id: str, callback: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        subs = self._session_subscribers.get(session_id)
        if not subs:
            return
        try:
            subs.remove(callback)
        except ValueError:
            pass
        if not subs:
            self._session_subscribers.pop(session_id, None)

    # ------------------------------------------------------------------
    # 业务入口
    # ------------------------------------------------------------------

    def get_active_session_by_fingerprint(self, fingerprint: str) -> Optional[str]:
        """根据指纹查询正在运行的会话 ID"""
        return self._active_fingerprints.get(fingerprint)

    def get_active_session_by_analysis(self, analysis_id: str) -> Optional[str]:
        """根据分析 ID 查询正在运行的脚本生成会话"""
        return self._active_script_gens.get(analysis_id)

    def clear_script_gen_lock(self, analysis_id: str) -> bool:
        """主动清掉某个 analysis_id 的脚本生成内存锁。

        触发场景:
        - 用户删除该 analysis_id 关联的脚本(走 DELETE /scripts/{id})
        - generate_script 自愈:DB 已无记录但内存仍锁着,认为是脏锁,清掉
        - 任何"分析记录被删/被重置,后续应当允许重新生成"的入口

        返回是否真的清了。
        """
        cleared = False
        session_id = self._active_script_gens.pop(analysis_id, None)
        if session_id is not None:
            cleared = True
            self._session_to_analysis_gen.pop(session_id, None)
            logger.info(f"主动清理脚本生成内存锁: analysis_id={analysis_id} session={session_id}")
        return cleared

    async def analyze_page(self, analysis_input) -> str:
        self._check_enabled()
        await self.initialize()

        from app.agents.ui_automation.schemas import PageAnalysisInput

        if not isinstance(analysis_input, PageAnalysisInput):
            raise TypeError("analysis_input 必须是 PageAnalysisInput 实例")

        # 记录指纹锁
        if analysis_input.fingerprint:
            self._active_fingerprints[analysis_input.fingerprint] = analysis_input.session_id
            self._session_to_fingerprint[analysis_input.session_id] = analysis_input.fingerprint

        assert self._runtime is not None
        await self._runtime.publish_message(
            analysis_input,
            topic_id=TopicId(
                type=TopicTypes.UI_PAGE_ANALYZER.value,
                source=analysis_input.session_id,
            ),
        )
        logger.info(
            f"已投递页面分析: session={analysis_input.session_id} "
            f"page={analysis_input.page_name} fp={analysis_input.fingerprint}"
        )
        return analysis_input.session_id

    async def generate_script(self, script_input) -> str:
        self._check_enabled()
        await self.initialize()

        from app.agents.ui_automation.schemas import PageAnalysisOutput, ScriptGenerationInput

        if not isinstance(script_input, ScriptGenerationInput):
            raise TypeError("script_input 必须是 ScriptGenerationInput 实例")

        # 记录脚本生成锁
        if script_input.page_analysis_id:
            self._active_script_gens[script_input.page_analysis_id] = script_input.session_id
            self._session_to_analysis_gen[script_input.session_id] = script_input.page_analysis_id

        # 装填 page_analysis：优先内存缓存，回落到 DB
        if script_input.page_analysis is None and script_input.page_analysis_id:
            cached = self._analysis_cache.get(script_input.page_analysis_id)
            if not cached:
                cached = await self._load_analysis_from_db(script_input.page_analysis_id)
            if cached:
                try:
                    script_input.page_analysis = PageAnalysisOutput.model_validate(cached)
                except Exception as e:
                    logger.warning(f"页面分析结果反序列化失败,跳过装填: {e}")
            else:
                logger.warning(
                    f"未找到 page_analysis_id={script_input.page_analysis_id} 的分析结果,"
                    f"Agent 将走通用模板兜底"
                )

        assert self._runtime is not None
        await self._runtime.publish_message(
            script_input,
            topic_id=TopicId(
                type=TopicTypes.UI_SCRIPT_GENERATOR.value,
                source=script_input.session_id,
            ),
        )
        # 记录 session→analysis_id 映射，供终态落库时回填
        if script_input.page_analysis_id:
            self._script_session_to_analysis[script_input.session_id] = script_input.page_analysis_id
        logger.info(
            f"已投递脚本生成: session={script_input.session_id} "
            f"template={script_input.script_type.value} name={script_input.script_name}"
        )
        return script_input.session_id

    async def trigger_execution(self, execution_input) -> str:
        """发布脚本执行请求到 UI_SCRIPT_EXECUTOR topic"""
        self._check_enabled()
        await self.initialize()

        from app.agents.ui_automation.schemas import UiScriptExecutionInput

        if not isinstance(execution_input, UiScriptExecutionInput):
            raise TypeError("execution_input 必须是 UiScriptExecutionInput 实例")

        assert self._runtime is not None
        await self._runtime.publish_message(
            execution_input,
            topic_id=TopicId(
                type=TopicTypes.UI_SCRIPT_EXECUTOR.value,
                source=execution_input.session_id,
            ),
        )
        logger.info(
            f"已投递脚本执行: session={execution_input.session_id} "
            f"execution_id={execution_input.execution_id} script={execution_input.script_id}"
        )
        return execution_input.session_id

    async def trigger_recording(self, recording_input) -> str:
        """发布录制启动请求到 UI_RECORDING_ORCHESTRATOR topic"""
        self._check_enabled()
        await self.initialize()

        from app.agents.ui_automation.schemas import StartCodegenInput

        if not isinstance(recording_input, StartCodegenInput):
            raise TypeError("recording_input 必须是 StartCodegenInput 实例")

        assert self._runtime is not None
        await self._runtime.publish_message(
            recording_input,
            topic_id=TopicId(
                type=TopicTypes.UI_RECORDING_ORCHESTRATOR.value,
                source=recording_input.session_id,
            ),
        )
        logger.info(
            f"已投递录制启动: session={recording_input.session_id} "
            f"name={recording_input.name} target={recording_input.target_url}"
        )
        return recording_input.session_id

    async def trigger_recording_postprocess(self, postprocess_input) -> str:
        """发布录制后处理请求(对已录制原始脚本重新跑 AI 优化)"""
        self._check_enabled()
        await self.initialize()

        from app.agents.ui_automation.schemas import PostprocessRecordingInput

        if not isinstance(postprocess_input, PostprocessRecordingInput):
            raise TypeError("postprocess_input 必须是 PostprocessRecordingInput 实例")

        assert self._runtime is not None
        await self._runtime.publish_message(
            postprocess_input,
            topic_id=TopicId(
                type=TopicTypes.UI_RECORDING_ORCHESTRATOR.value,
                source=postprocess_input.session_id,
            ),
        )
        logger.info(
            f"已投递录制后处理: session={postprocess_input.session_id} "
            f"raw={postprocess_input.raw_script_path}"
        )
        return postprocess_input.session_id

    # ------------------------------------------------------------------
    # 批次执行
    # ------------------------------------------------------------------

    def register_batch_sub_execution(self, batch_id: str, execution_id: str) -> None:
        """BatchExecutorAgent 投递子执行前调用，建立 execution → batch 映射"""
        self._batch_execution_map[execution_id] = batch_id
        logger.debug(f"注册批次子执行: batch={batch_id} execution={execution_id}")

    async def _on_sub_execution_done(self, message) -> None:
        """收到 UiExecutionDoneMessage → 转发给对应 BatchExecutorAgent"""
        execution_id = getattr(message, "execution_id", "")
        batch_id = self._batch_execution_map.pop(execution_id, None)
        if not batch_id:
            return  # 单独执行,不是批次的一部分

        from app.agents.ui_automation.schemas import UiSubExecutionCompleted
        done = UiSubExecutionCompleted(
            batch_id=batch_id,
            execution_id=execution_id,
            script_id=getattr(message, "script_id", ""),
            status=getattr(message, "status", "error"),
            duration_ms=getattr(message, "duration_ms", 0),
            report_summary=getattr(message, "report_summary", {}),
        )
        assert self._runtime is not None
        await self._runtime.publish_message(
            done,
            topic_id=TopicId(
                type=TopicTypes.UI_BATCH_EXECUTOR.value,
                source="orchestrator",
            ),
        )

    async def trigger_batch_execution(self, batch_input) -> str:
        """发布批量执行请求到 UI_BATCH_EXECUTOR topic"""
        self._check_enabled()
        await self.initialize()

        from app.agents.ui_automation.schemas import UiBatchExecutionInput
        if not isinstance(batch_input, UiBatchExecutionInput):
            raise TypeError("batch_input 必须是 UiBatchExecutionInput 实例")

        assert self._runtime is not None
        await self._runtime.publish_message(
            batch_input,
            topic_id=TopicId(
                type=TopicTypes.UI_BATCH_EXECUTOR.value,
                source=batch_input.session_id,
            ),
        )
        logger.info(
            f"已投递批次执行: batch={batch_input.batch_id} "
            f"scripts={len(batch_input.script_ids)}"
        )
        return batch_input.session_id

    async def trigger_batch_cancel(self, batch_id: str, cancel_cmd) -> None:
        """发布取消命令到 UI_BATCH_EXECUTOR topic"""
        self._check_enabled()
        await self.initialize()

        assert self._runtime is not None
        await self._runtime.publish_message(
            cancel_cmd,
            topic_id=TopicId(
                type=TopicTypes.UI_BATCH_EXECUTOR.value,
                source="orchestrator",
            ),
        )
        logger.info(f"已投递批次取消: batch={batch_id}")

    # ------------------------------------------------------------------
    # DB 回退
    # ------------------------------------------------------------------

    async def _load_analysis_from_db(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """从 DB 加载分析结果（raw_response 字段保留完整 PageAnalysisOutput 序列化）"""
        try:
            from app.models.ui_automation import UiPageAnalysisResult
            row = await UiPageAnalysisResult.filter(analysis_id=analysis_id).first()
            if not row:
                return None
            return row.raw_response if isinstance(row.raw_response, dict) else None
        except Exception as e:
            logger.warning(f"从 DB 加载分析结果失败 analysis_id={analysis_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # 同步查询（内存缓存优先；缺失由 API 层走 DB 查询）
    # ------------------------------------------------------------------

    def get_analysis_result(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        return self._analysis_cache.get(analysis_id)

    def get_script_result(self, script_id: str) -> Optional[Dict[str, Any]]:
        return self._script_cache.get(script_id)

    def list_recent_analyses(self, limit: int = 20) -> List[Dict[str, Any]]:
        items = list(self._analysis_cache.values())
        return items[-limit:]

    def list_recent_scripts(self, limit: int = 20) -> List[Dict[str, Any]]:
        items = list(self._script_cache.values())
        return items[-limit:]


def _write_script_files(scripts_dir: str, file_name: str, content: str, auxiliary_files: Dict[str, str]) -> None:
    """同步写脚本主文件 + 附属文件。由 asyncio.to_thread 调用。"""
    os.makedirs(scripts_dir, exist_ok=True)
    main_path = os.path.join(scripts_dir, file_name)
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(content)
    for aux_name, aux_content in (auxiliary_files or {}).items():
        # 限制只允许相对路径下的文件名，防止目录穿越
        safe_name = os.path.basename(aux_name)
        if not safe_name:
            continue
        aux_path = os.path.join(scripts_dir, safe_name)
        with open(aux_path, "w", encoding="utf-8") as f:
            f.write(aux_content)


# 全局单例
ui_orchestrator = UiAutomationOrchestrator()
