"""
UI 页面分析智能体（门面 + 内部 GroupChat）

设计：
- 对外只暴露一个 Agent（UI_PAGE_ANALYZER 主题订阅），上游服务 publish PageAnalysisInput 即可
- 内部按 analysis_type 走不同分支：
    * image  → 元素识别(豆包视觉) → 测试用例设计
    * text   → 直接进入交互流程分析 → 测试用例设计
    * hybrid → 元素识别(图+文) → 交互流程分析(文字补充) → 测试用例设计
- 三个子 AssistantAgent 不单独注册主题，仅作为内部协作单元
- 所有 LLM 走 get_model_client("doubao_vision" / "deepseek")，失败时降级到本地兜底
"""
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import (
    ModelClientStreamingChunkEvent,
    MultiModalMessage,
    TextMessage,
)
from autogen_core import Image as AGImage
from autogen_core import MessageContext, TopicId, message_handler, type_subscription
from loguru import logger
from PIL import Image

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.agents.llms import get_model_client
from app.core.types import AgentTypes, MessageRegion, TopicTypes

from .schemas import (
    AnalysisType,
    ElementRecognitionResult,
    InteractionAnalysisResult,
    InteractionStep,
    LocatorSuggestion,
    PageAnalysisInput,
    PageAnalysisOutput,
    TestCaseDesignResult,
    UiAgentPrompts,
    UiElement,
    UiElementCategory,
)


@type_subscription(topic_type=TopicTypes.UI_PAGE_ANALYZER.value)
class PageAnalyzerAgent(BaseApiAutomationAgent):
    """页面分析门面 Agent

    内部聚合 3 个 AssistantAgent：
    - element_recognizer: 视觉模型（doubao_vision）做元素识别
    - interaction_analyst: 文本模型（deepseek）做交互流程
    - testcase_designer: 文本模型（deepseek）做最终用例设计

    NOTE: 复用 BaseApiAutomationAgent 是为了拿到 _send_message / _extract_json_from_content；
    它默认会创建 deepseek 客户端给 self.model_client（用于 interaction/testcase 子 Agent）。
    """

    def __init__(self, model_client_instance=None, **kwargs):
        super().__init__(
            agent_type=AgentTypes.UI_PAGE_ANALYZER,
            model_client_instance=model_client_instance,
            **kwargs,
        )

        # 视觉模型客户端（豆包） - 懒加载，失败时为 None
        self._vision_client = None
        # 文本模型客户端（沿用 self.model_client = deepseek）

        # 三个子 AssistantAgent 缓存
        self._element_recognizer: Optional[AssistantAgent] = None
        self._interaction_analyst: Optional[AssistantAgent] = None
        self._testcase_designer: Optional[AssistantAgent] = None

        logger.info(f"UI 页面分析智能体初始化完成: {self.agent_name}")

    # ------------------------------------------------------------------
    # 内部子 Agent 懒加载
    # ------------------------------------------------------------------

    def _get_vision_client(self):
        if self._vision_client is None:
            try:
                self._vision_client = get_model_client("doubao_vision")
                logger.info("视觉模型客户端 (doubao_vision) 创建成功")
            except Exception as e:
                logger.warning(f"豆包视觉模型不可用，将走纯文字降级路径: {e}")
                self._vision_client = None
        return self._vision_client

    def _get_element_recognizer(self) -> Optional[AssistantAgent]:
        if self._element_recognizer is not None:
            return self._element_recognizer
        vision_client = self._get_vision_client()
        if vision_client is None:
            return None
        self._element_recognizer = AssistantAgent(
            name="ui_element_recognizer",
            model_client=vision_client,
            system_message=UiAgentPrompts.ELEMENT_RECOGNIZER_SYSTEM,
            model_client_stream=False,
        )
        return self._element_recognizer

    def _get_interaction_analyst(self) -> AssistantAgent:
        if self._interaction_analyst is None:
            self._interaction_analyst = AssistantAgent(
                name="ui_interaction_analyst",
                model_client=self.model_client,
                system_message=UiAgentPrompts.INTERACTION_ANALYST_SYSTEM,
                model_client_stream=False,
            )
        return self._interaction_analyst

    def _get_testcase_designer(self) -> AssistantAgent:
        if self._testcase_designer is None:
            self._testcase_designer = AssistantAgent(
                name="ui_testcase_designer",
                model_client=self.model_client,
                system_message=UiAgentPrompts.TESTCASE_DESIGNER_SYSTEM,
                model_client_stream=False,
            )
        return self._testcase_designer

    # ------------------------------------------------------------------
    # 消息处理入口
    # ------------------------------------------------------------------

    @message_handler
    async def handle_page_analysis(
        self, message: PageAnalysisInput, ctx: MessageContext
    ) -> None:
        """页面分析主流程"""
        start = datetime.now()
        analysis_id = str(uuid.uuid4())
        session_id = message.session_id
        is_fallback_overall = False

        try:
            await self._send_message(
                f"开始页面分析：{message.page_name}（模式={message.analysis_type.value}）",
                message_type="info",
                region=MessageRegion.PROCESS,
            )

            # 1) 元素识别（image / hybrid 才走视觉模型；text 模式产生空元素列表;live_url 走 crawl4ai 抓真实 DOM）
            if message.analysis_type == AnalysisType.LIVE_URL:
                element_result = await self._run_live_url_analysis(message)
            elif message.analysis_type in (AnalysisType.IMAGE, AnalysisType.HYBRID):
                element_result = await self._run_element_recognition(message)
            else:
                element_result = ElementRecognitionResult(
                    page_title=message.page_name,
                    page_description=message.text_description or "",
                    elements=[],
                    is_fallback=False,
                )
            if element_result.is_fallback:
                is_fallback_overall = True

            await self._send_message(
                f"识别到 {len(element_result.elements)} 个可测试元素",
                message_type="info",
            )

            # 2) 交互流程分析
            interaction_result = await self._run_interaction_analysis(message, element_result)
            if interaction_result.is_fallback:
                is_fallback_overall = True

            await self._send_message(
                f"梳理出 {len(interaction_result.steps)} 个交互步骤",
                message_type="info",
            )

            # 3) 测试用例设计
            testcase_result = await self._run_testcase_design(
                message, element_result, interaction_result
            )
            if testcase_result.is_fallback:
                is_fallback_overall = True

            # 4) 组装输出
            output = PageAnalysisOutput(
                session_id=session_id,
                analysis_id=analysis_id,
                analysis_type=message.analysis_type,
                page_name=message.page_name,
                page_url=message.page_url,
                element_recognition=element_result,
                interaction_analysis=interaction_result,
                testcase_design=testcase_result,
                finished_at=datetime.now(),
                is_fallback=is_fallback_overall,
            )

            elapsed = (datetime.now() - start).total_seconds()
            await self._send_message(
                f"页面分析完成（耗时 {elapsed:.1f}s，是否降级={is_fallback_overall}）",
                message_type="success",
                is_final=True,
                region=MessageRegion.SUCCESS,
                result={
                    "analysis_id": analysis_id,
                    "page_name": message.page_name,
                    "elements_count": len(element_result.elements),
                    "steps_count": len(testcase_result.steps),
                    "is_fallback": is_fallback_overall,
                    "output": output.model_dump(mode="json"),
                },
            )

            # 5) 暂存内存供脚本生成阶段消费（由编排器服务 / API 落库）
            #    Phase 2: 不直接广播给 UiScriptGeneratorAgent，等用户在前端选模板后再发起
            logger.info(
                f"PageAnalysis 完成 session={session_id} analysis_id={analysis_id} "
                f"elements={len(element_result.elements)} steps={len(testcase_result.steps)}"
            )

        except Exception as e:
            logger.exception(f"页面分析失败: {e}")
            await self._send_message(
                f"页面分析异常：{e}",
                message_type="error",
                is_final=True,
                region=MessageRegion.ERROR,
            )

    # ------------------------------------------------------------------
    # 子任务：元素识别
    # ------------------------------------------------------------------

    async def _run_element_recognition(
        self, message: PageAnalysisInput
    ) -> ElementRecognitionResult:
        # 降级演练开关：直接走本地兜底
        from app.settings.config import settings as _settings
        if getattr(_settings, "UI_AUTOMATION_FORCE_FALLBACK", False):
            await self._send_message(
                "已开启 UI_AUTOMATION_FORCE_FALLBACK,元素识别走本地兜底",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_element_recognition(message)

        agent = self._get_element_recognizer()
        if agent is None:
            if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                raise RuntimeError(
                    "视觉模型客户端创建失败(DOUBAO_API_KEY/BASE_URL/MODEL 三件套有问题),"
                    "且 UI_AUTOMATION_DISABLE_FALLBACK=true,拒绝走兜底"
                )
            await self._send_message(
                "视觉模型不可用，跳过元素识别（仅以文字描述驱动后续流程）",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_element_recognition(message)

        try:
            await self._send_message(
                "正在调用视觉模型深度解析页面（耗时约 30-90s）...",
                message_type="info",
            )
            ag_image = self._load_screenshot_as_agimage(message.screenshot_path)
            text_prompt = self._build_element_recognition_text(message)
            mm_msg = MultiModalMessage(content=[text_prompt, ag_image], source="user")

            # 视觉任务给予更高的超时阈值（120s）
            content = await self._run_agent_collect(agent, mm_msg, timeout=120)
            parsed = self._extract_json_from_content(content or "")
            if not parsed:
                preview = (content or "").strip().replace("\n", " ")[:200]
                logger.warning(f"元素识别 LLM 输出无法解析为 JSON,走降级 | 原始输出片段: {preview}")
                if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                    raise ValueError(f"元素识别:视觉模型返回非 JSON,前 200 字: {preview}")
                await self._send_message(
                    f"⚠ 元素识别走降级:视觉模型返回的不是合法 JSON。原始输出片段:{preview}",
                    message_type="warning",
                    region=MessageRegion.WARNING,
                )
                return self._fallback_element_recognition(message)

            return self._build_element_result_from_json(parsed, message)

        except Exception as e:
            logger.exception(f"元素识别失败: {e}")
            if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                raise
            await self._send_message(
                f"⚠ 元素识别走降级:视觉模型调用异常 → {type(e).__name__}: {str(e)[:300]}",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_element_recognition(message)

    def _build_element_recognition_text(self, message: PageAnalysisInput) -> str:
        parts = [
            "你是一个专业的 UI 元素识别专家。请分析截图，提取可测试的交互元素。",
            "要求：",
            "1. 只输出合法且完整的 JSON，不要有任何解释性文字。",
            "2. 包含 elements 数组，每个元素需有 category, name, locator_suggestions, position。",
            f"页面名称: {message.page_name}",
        ]
        if message.page_url:
            parts.append(f"页面 URL: {message.page_url}")
        if message.text_description:
            parts.append(f"上下文参考: {message.text_description}")
        return "\n".join(parts)

    def _load_screenshot_as_agimage(self, screenshot_path: str) -> AGImage:
        path = Path(screenshot_path)
        if not path.exists():
            raise FileNotFoundError(f"截图文件不存在: {screenshot_path}")
        
        pil = Image.open(path)
        # 优化：大图等比缩放至 1280px 宽度，减少推理耗时和 Token 消耗
        max_width = 1280
        if pil.width > max_width:
            ratio = max_width / pil.width
            new_size = (max_width, int(pil.height * ratio))
            pil = pil.resize(new_size, Image.Resampling.LANCZOS)
            logger.info(f"截图过大，已自动缩放至: {new_size}")
            
        return AGImage(pil)

    def _build_element_result_from_json(
        self, parsed: Dict[str, Any], message: PageAnalysisInput
    ) -> ElementRecognitionResult:
        elements: List[UiElement] = []
        raw_elements = parsed.get("elements") or []
        for raw in raw_elements:
            try:
                category_raw = (raw.get("category") or "button").lower()
                category = (
                    UiElementCategory(category_raw)
                    if category_raw in {c.value for c in UiElementCategory}
                    else UiElementCategory.BUTTON
                )
                locators_raw = raw.get("locator_suggestions") or []
                locators: List[LocatorSuggestion] = []
                for loc in locators_raw:
                    if not isinstance(loc, dict):
                        continue
                    try:
                        locators.append(LocatorSuggestion(**loc))
                    except Exception:
                        continue
                position_raw = raw.get("position")
                position = None
                if isinstance(position_raw, dict):
                    from .schemas import ElementPosition

                    try:
                        position = ElementPosition(
                            x=int(position_raw.get("x", 0) or 0),
                            y=int(position_raw.get("y", 0) or 0),
                            width=int(position_raw.get("width", 0) or 0),
                            height=int(position_raw.get("height", 0) or 0),
                        )
                    except Exception:
                        position = None

                elements.append(
                    UiElement(
                        element_id=str(raw.get("element_id") or f"el_{len(elements) + 1}"),
                        name=raw.get("name", "未命名元素"),
                        category=category,
                        element_type=raw.get("element_type", ""),
                        description=raw.get("description", ""),
                        text_content=raw.get("text_content"),
                        position=position,
                        visual_features=raw.get("visual_features") or {},
                        functionality=raw.get("functionality", ""),
                        interaction_state=raw.get("interaction_state", "normal"),
                        testability=float(raw.get("testability", 0.8) or 0.8),
                        locator_suggestions=locators,
                        confidence_score=float(raw.get("confidence_score", 0.8) or 0.8),
                    )
                )
            except Exception as e:
                logger.warning(f"跳过非法元素: {e}")
                continue

        return ElementRecognitionResult(
            page_title=parsed.get("page_title") or message.page_name,
            page_description=parsed.get("page_description") or "",
            elements=elements,
            is_fallback=False,
        )

    def _fallback_element_recognition(
        self, message: PageAnalysisInput
    ) -> ElementRecognitionResult:
        """视觉模型不可用时的兜底：从 text_description 提取关键词造占位元素"""
        text = message.text_description or ""
        placeholders: List[UiElement] = []
        if "登录" in text:
            placeholders.append(
                UiElement(
                    element_id="input_username",
                    name="用户名输入框",
                    category=UiElementCategory.INPUT,
                    description="登录表单中的用户名输入框",
                    locator_suggestions=[LocatorSuggestion(strategy="text", expression="用户名", confidence=0.6)],
                    confidence_score=0.4,
                )
            )
            placeholders.append(
                UiElement(
                    element_id="input_password",
                    name="密码输入框",
                    category=UiElementCategory.INPUT,
                    description="登录表单中的密码输入框",
                    locator_suggestions=[LocatorSuggestion(strategy="text", expression="密码", confidence=0.6)],
                    confidence_score=0.4,
                )
            )
            placeholders.append(
                UiElement(
                    element_id="btn_login",
                    name="登录按钮",
                    category=UiElementCategory.BUTTON,
                    description="登录表单底部的登录提交按钮",
                    locator_suggestions=[LocatorSuggestion(strategy="text", expression="登录", confidence=0.7)],
                    confidence_score=0.4,
                )
            )

        return ElementRecognitionResult(
            page_title=message.page_name,
            page_description=text[:200],
            elements=placeholders,
            is_fallback=True,
        )

    # ------------------------------------------------------------------
    # 子任务:Live URL 元素抓取(crawl4ai,2026-06-17 引入)
    # ------------------------------------------------------------------

    async def _run_live_url_analysis(
        self, message: PageAnalysisInput
    ) -> ElementRecognitionResult:
        """live_url 模式:用 crawl4ai 抓真实 DOM,直接产出 UiElement 列表(无需 VLM)。

        失败路径:
          - UI_CRAWL4AI_ENABLED=False / lazy import 失败 → _fallback_element_recognition
          - 抓取超时 / 网络异常 / JS 执行失败 → _fallback_element_recognition
          - 抓取成功但 0 个可用元素 → 视为失败,走 fallback
        """
        from app.settings.config import settings as _settings
        from app.services.ui_automation import crawl4ai_service

        if getattr(_settings, "UI_AUTOMATION_FORCE_FALLBACK", False):
            await self._send_message(
                "已开启 UI_AUTOMATION_FORCE_FALLBACK,Live URL 走本地兜底",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_element_recognition(message)

        target_url = (message.live_url or "").strip()
        if not target_url:
            return self._fallback_element_recognition(message)

        storage_state_abs: Optional[str] = None
        # 留空时 fallback 到系统默认登录态(与录制管理对齐),业务页未登录基本无意义
        effective_relpath = (
            message.storage_state_relpath
            or getattr(_settings, "UI_RECORDING_DEFAULT_STORAGE_STATE", "")
            or ""
        ).strip()
        if effective_relpath:
            workspace = getattr(_settings, "UI_AUTOMATION_WORKSPACE", "")
            if workspace:
                from pathlib import Path as _P
                candidate = _P(workspace) / effective_relpath
                if candidate.is_file():
                    storage_state_abs = str(candidate)
                else:
                    logger.warning(
                        f"[live_url] storage_state 文件不存在 {candidate},"
                        f"将以未登录态抓取"
                    )
                    await self._send_message(
                        f"⚠ 登录态文件不存在 {effective_relpath},将以未登录态抓取"
                        f"(业务页大概率被踢到登录页)",
                        message_type="warning",
                        region=MessageRegion.WARNING,
                    )

        await self._send_message(
            f"正在用 crawl4ai 抓取 {target_url}(预计 5-30s)...",
            message_type="info",
        )

        try:
            result = await crawl4ai_service.analyze_live_url(
                url=target_url,
                storage_state_path=storage_state_abs,
                timeout=getattr(_settings, "UI_CRAWL4AI_TIMEOUT", 60),
            )
        except Exception as e:
            logger.exception(f"crawl4ai 抓取异常: {e}")
            if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                raise
            await self._send_message(
                f"⚠ Live URL 走降级:crawl4ai 抓取异常 → {type(e).__name__}: {str(e)[:200]}",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_element_recognition(message)

        if result is None:
            if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                raise RuntimeError(
                    "crawl4ai 抓取返回 None(可能未安装/失败/超时),且 UI_AUTOMATION_DISABLE_FALLBACK=true"
                )
            await self._send_message(
                f"⚠ Live URL 走降级:crawl4ai 不可用或抓取失败 url={target_url}",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_element_recognition(message)

        elements = result.get("elements") or []
        page_title = result.get("page_title") or message.page_name

        # 登录态判定:crawl4ai 在 service 层根据 final_url + DOM password 框双重信号判定
        if result.get("login_required"):
            final_url = result.get("final_url") or ""
            login_reason = result.get("login_reason") or ""
            ss_debug = result.get("storage_state_debug") or {}
            ss_issues = ss_debug.get("issues") or []
            debug = result.get("debug") or {}
            # 区分两种触发场景:URL 跳到登录页 vs 业务页弹登录组件(同一 URL)
            if final_url and final_url != target_url:
                redirect_hint = f"被重定向到登录页({final_url})"
            else:
                redirect_hint = "页面在原地弹出了登录组件(URL 未变,实际未登录)"

            ss_path = ss_debug.get("path") or "(未提供)"
            ss_exists = ss_debug.get("exists")
            ss_cookies = ss_debug.get("cookie_count", 0)
            ss_ls_count = ss_debug.get("localstorage_key_count", 0)
            ss_auth_keys = ss_debug.get("auth_like_keys") or []
            ss_summary = (
                f"文件态: path={ss_path} exists={ss_exists} "
                f"cookie={ss_cookies}个 localStorage={ss_ls_count}个键 "
                f"疑似鉴权键={ss_auth_keys[:5]}"
            )

            # 运行态:Playwright 实际在浏览器里挂上的 localStorage,跟文件态做对比
            runtime_ls = debug.get("runtime_ls_count", -1)
            runtime_keys = debug.get("runtime_ls_keys") or []
            runtime_origin = debug.get("runtime_origin", "")
            ls_after_goto_count = debug.get("ls_after_goto_count", -1)
            ls_after_goto_keys = debug.get("ls_after_goto_keys") or []
            injected_origins = debug.get("init_script_injected_origins") or []
            runtime_summary = (
                f"运行态: origin={runtime_origin} "
                f"navigation刚结束时 localStorage={ls_after_goto_count}个键={ls_after_goto_keys[:5]} "
                f"→ 业务JS跑完后 localStorage={runtime_ls}个键={runtime_keys[:5]} "
                f"add_init_script注入origins={injected_origins}"
            )

            # 智能根因判定(三段式:有没有注入 → 注入后被不被清 → 整体方向)
            if ss_ls_count > 0 and ls_after_goto_count <= 0 and runtime_ls == 0:
                root_cause = (
                    "❗根因: 文件里有 localStorage,但 navigation 后浏览器一个键都没有 —— "
                    "可能 origin 文本不匹配,或 Playwright 与 init_script 都没能注入。"
                    "确认 storage_state 里的 origin 跟目标 URL 的 scheme://host:port 完全一致"
                )
            elif ss_ls_count > 0 and ls_after_goto_count > 0 and runtime_ls == 0:
                root_cause = (
                    "❗根因: navigation 刚结束时 localStorage 还在,但业务 JS 跑完后被清空了 —— "
                    "业务前端做了 token 校验(可能调用 /me 接口返回 401),"
                    "判定 sessionId 过期后主动 localStorage.clear(),需要重新登录刷一份 .auth/user.json"
                )
            elif ss_ls_count > 0 and ls_after_goto_count > 0 and runtime_ls > 0:
                root_cause = (
                    "❗根因: localStorage 已经成功注入并保留,但服务端仍然踢回登录页 —— "
                    "服务端鉴权拒绝了这个 sessionId(过期/被踢),需要重新登录"
                )
            elif ss_cookies == 0 and ss_ls_count == 0:
                root_cause = (
                    "❗根因: .auth/user.json 既没 cookie 也没 localStorage —— "
                    "之前就没登录过/录制时漏存了"
                )
            else:
                root_cause = "❗根因待定,看运行态 + 文件态对比"

            issues_text = ("\n  - " + "\n  - ".join(ss_issues)) if ss_issues else "(无显式问题)"

            await self._send_message(
                f"⚠ Live URL 登录态失效:{redirect_hint}\n"
                f"判定原因: {login_reason}\n"
                f"{ss_summary}\n"
                f"{runtime_summary}\n"
                f"{root_cause}\n"
                f"文件问题清单: {issues_text}\n"
                f"修复路径: 用录制管理新建一个会话,登录完成后到处的 storageState 复制到 "
                f"generated_ui_tests/.auth/user.json 即可。",
                message_type="error",
                region=MessageRegion.WARNING,
            )
            if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                raise RuntimeError(
                    f"Live URL 抓到登录页,storage_state 失效。"
                    f"final_url={final_url} 原因={login_reason} "
                    f"ss_debug={ss_debug} runtime_debug={debug}"
                )
            # 登录页元素对业务测试无意义,直接走降级
            return self._fallback_element_recognition(message)

        if not elements:
            await self._send_message(
                f"⚠ Live URL 抓取成功但未识别到可测试元素,可能页面是 SPA/反爬,走降级",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_element_recognition(message)

        return ElementRecognitionResult(
            page_title=page_title,
            page_description=f"crawl4ai 直接抓取自 {target_url}",
            elements=elements,
            is_fallback=False,
        )

    # ------------------------------------------------------------------
    # 子任务：交互流程分析
    # ------------------------------------------------------------------

    async def _run_interaction_analysis(
        self, message: PageAnalysisInput, element_result: ElementRecognitionResult
    ) -> InteractionAnalysisResult:
        from app.settings.config import settings as _settings
        if getattr(_settings, "UI_AUTOMATION_FORCE_FALLBACK", False):
            return self._fallback_interaction(message, element_result)

        agent = self._get_interaction_analyst()
        try:
            await self._send_message("梳理交互流程...", message_type="info")
            user_task = self._build_interaction_task(message, element_result)
            content = await self._run_agent_collect(agent, TextMessage(content=user_task, source="user"))
            parsed = self._extract_json_from_content(content or "")
            if not parsed:
                preview = (content or "").strip().replace("\n", " ")[:200]
                logger.warning(f"交互流程 LLM 输出无法解析,走降级 | 原始输出片段: {preview}")
                if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                    raise ValueError(f"交互流程:文本模型返回非 JSON,前 200 字: {preview}")
                await self._send_message(
                    f"⚠ 交互流程走降级:文本模型返回的不是合法 JSON。原始输出片段:{preview}",
                    message_type="warning",
                    region=MessageRegion.WARNING,
                )
                return self._fallback_interaction(message, element_result)

            steps_raw = parsed.get("steps") or []
            steps = [self._build_step(s, idx + 1) for idx, s in enumerate(steps_raw)]
            return InteractionAnalysisResult(
                scenario_name=parsed.get("scenario_name") or message.page_name,
                scenario_description=parsed.get("scenario_description") or (message.text_description or ""),
                steps=steps,
                is_fallback=False,
            )
        except Exception as e:
            logger.exception(f"交互流程分析失败: {e}")
            if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                raise
            await self._send_message(
                f"⚠ 交互流程走降级:文本模型调用异常 → {type(e).__name__}: {str(e)[:300]}",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_interaction(message, element_result)

    def _build_interaction_task(
        self, message: PageAnalysisInput, element_result: ElementRecognitionResult
    ) -> str:
        elements_brief = [
            {
                "element_id": e.element_id,
                "name": e.name,
                "category": e.category.value,
                "description": e.description,
                "text_content": e.text_content,
            }
            for e in element_result.elements
        ]
        return (
            "请基于以下页面元素清单与用户测试意图，输出交互流程 JSON。\n"
            f"页面名称: {message.page_name}\n"
            f"页面 URL: {message.page_url or ''}\n"
            f"用户意图描述:\n{message.text_description or '（无显式描述，按页面主流程推断）'}\n\n"
            f"元素清单:\n{json.dumps(elements_brief, ensure_ascii=False, indent=2)}"
        )

    def _fallback_interaction(
        self, message: PageAnalysisInput, element_result: ElementRecognitionResult
    ) -> InteractionAnalysisResult:
        steps: List[InteractionStep] = []
        idx = 0
        if message.page_url:
            idx += 1
            steps.append(
                InteractionStep(
                    step=idx,
                    action="navigate",
                    target_description=message.page_url,
                    expected="页面加载完成",
                )
            )

        for el in element_result.elements:
            idx += 1
            if el.category == UiElementCategory.INPUT:
                steps.append(
                    InteractionStep(
                        step=idx,
                        action="input",
                        target_element_id=el.element_id,
                        target_description=el.description or el.name,
                        value=f"<{el.name}的测试值>",
                        expected="输入框显示内容",
                    )
                )
            elif el.category == UiElementCategory.BUTTON:
                steps.append(
                    InteractionStep(
                        step=idx,
                        action="click",
                        target_element_id=el.element_id,
                        target_description=el.description or el.name,
                        expected=f"触发 {el.name} 对应操作",
                    )
                )

        if steps:
            idx += 1
            steps.append(
                InteractionStep(
                    step=idx,
                    action="assert",
                    target_description="页面出现成功提示或跳转",
                    expected="操作生效",
                )
            )

        return InteractionAnalysisResult(
            scenario_name=message.page_name,
            scenario_description=message.text_description or "兜底生成的交互流程",
            steps=steps,
            is_fallback=True,
        )

    # ------------------------------------------------------------------
    # 子任务：测试用例设计
    # ------------------------------------------------------------------

    async def _run_testcase_design(
        self,
        message: PageAnalysisInput,
        element_result: ElementRecognitionResult,
        interaction_result: InteractionAnalysisResult,
    ) -> TestCaseDesignResult:
        from app.settings.config import settings as _settings
        if getattr(_settings, "UI_AUTOMATION_FORCE_FALLBACK", False):
            return self._fallback_testcase(interaction_result)

        agent = self._get_testcase_designer()
        try:
            await self._send_message("设计 MidScene 风格测试用例...", message_type="info")
            task_text = self._build_testcase_task(message, element_result, interaction_result)
            content = await self._run_agent_collect(agent, TextMessage(content=task_text, source="user"))
            parsed = self._extract_json_from_content(content or "")
            if not parsed:
                preview = (content or "").strip().replace("\n", " ")[:200]
                logger.warning(f"测试用例设计 LLM 输出无法解析,走降级 | 原始输出片段: {preview}")
                if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                    raise ValueError(f"测试用例:文本模型返回非 JSON,前 200 字: {preview}")
                await self._send_message(
                    f"⚠ 测试用例走降级:文本模型返回的不是合法 JSON。原始输出片段:{preview}",
                    message_type="warning",
                    region=MessageRegion.WARNING,
                )
                return self._fallback_testcase(interaction_result)

            steps_raw = parsed.get("steps") or []
            steps = [self._build_step(s, idx + 1) for idx, s in enumerate(steps_raw)]
            return TestCaseDesignResult(
                case_name=parsed.get("case_name") or f"{message.page_name}_用例",
                case_description=parsed.get("case_description") or "",
                preconditions=list(parsed.get("preconditions") or []),
                steps=steps,
                assertions=list(parsed.get("assertions") or []),
                is_fallback=False,
            )
        except Exception as e:
            logger.exception(f"测试用例设计失败: {e}")
            if getattr(_settings, "UI_AUTOMATION_DISABLE_FALLBACK", False):
                raise
            await self._send_message(
                f"⚠ 测试用例走降级:文本模型调用异常 → {type(e).__name__}: {str(e)[:300]}",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_testcase(interaction_result)

    def _build_testcase_task(
        self,
        message: PageAnalysisInput,
        element_result: ElementRecognitionResult,
        interaction_result: InteractionAnalysisResult,
    ) -> str:
        return (
            "请基于以下信息设计最终落地的测试用例（MidScene 风格），严格 JSON 输出。\n"
            f"页面名称: {message.page_name}\n"
            f"用户意图: {message.text_description or '（无）'}\n\n"
            f"交互流程:\n{json.dumps(interaction_result.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n\n"
            f"元素清单（供 target_description 优化使用）:\n"
            f"{json.dumps([e.model_dump(mode='json') for e in element_result.elements], ensure_ascii=False, indent=2)}"
        )

    def _fallback_testcase(
        self, interaction_result: InteractionAnalysisResult
    ) -> TestCaseDesignResult:
        return TestCaseDesignResult(
            case_name=interaction_result.scenario_name or "兜底用例",
            case_description=interaction_result.scenario_description or "兜底生成",
            preconditions=["页面可访问"],
            steps=interaction_result.steps,
            assertions=["页面无显式异常"],
            is_fallback=True,
        )

    # ------------------------------------------------------------------
    # 共用工具
    # ------------------------------------------------------------------

    def _build_step(self, raw: Dict[str, Any], default_idx: int) -> InteractionStep:
        action = (raw.get("action") or "click").lower()
        if action not in {"navigate", "click", "input", "select", "hover", "scroll", "wait", "assert"}:
            action = "click"
        return InteractionStep(
            step=int(raw.get("step") or default_idx),
            action=action,  # type: ignore[arg-type]
            target_element_id=raw.get("target_element_id"),
            target_description=raw.get("target_description", ""),
            value=raw.get("value"),
            expected=raw.get("expected"),
        )

    async def _run_agent_collect(self, agent: AssistantAgent, task, timeout: Optional[int] = None) -> str:
        """运行 AssistantAgent 并收集最终文本输出（非流式，避免污染外层 SSE）

        包 asyncio.wait_for 超时：单次 LLM 调用超过 UI_LLM_CALL_TIMEOUT 秒视为失败，
        返回空串让外层走 fallback 路径，避免整条门面链阻塞拖死 SSE。
        """
        from app.settings.config import settings
        if timeout is None:
            timeout = max(5, int(getattr(settings, "UI_LLM_CALL_TIMEOUT", 60)))
        try:
            result = await asyncio.wait_for(agent.run(task=task), timeout=timeout)
            if result and result.messages:
                last = result.messages[-1]
                if hasattr(last, "content"):
                    content = last.content
                    if isinstance(content, list):
                        # MultiModalMessage 返回时取文本部分
                        return "\n".join(str(c) for c in content if isinstance(c, str))
                    return str(content)
            return ""
        except asyncio.TimeoutError:
            logger.warning(f"AssistantAgent 运行超时（>{timeout}s），走 fallback")
            return ""
        except Exception as e:
            logger.error(f"AssistantAgent 运行失败: {e}")
            return ""
