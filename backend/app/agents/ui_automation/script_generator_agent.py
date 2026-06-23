"""
UI 脚本生成智能体（三模板路由）

- playwright_classic   : 纯 Playwright（page.locator + click/fill/expect）
- playwright_midscene  : MidScene + Playwright 集成（aiTap/aiInput/aiAssert + fixture.ts 附属文件）
- yaml_midscene        : MidScene YAML（web + tasks.flow）

输入 ScriptGenerationInput.page_analysis 由编排器装填；Agent 自身无状态。
LLM 失败时走兜底模板（基于 testcase_design.steps 直生成）。
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage
from autogen_core import MessageContext, message_handler, type_subscription
from loguru import logger

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.types import AgentTypes, MessageRegion, TopicTypes

from .schemas import (
    InteractionStep,
    PageAnalysisOutput,
    ScriptGenerationInput,
    ScriptGenerationOutput,
    ScriptSource,
    ScriptType,
    UiAgentPrompts,
    UiElement,
)


@type_subscription(topic_type=TopicTypes.UI_SCRIPT_GENERATOR.value)
class UiScriptGeneratorAgent(BaseApiAutomationAgent):
    """UI 脚本生成智能体（三模板）"""

    # MidScene + Playwright 集成的标准 fixture.ts（官方推荐）
    _STANDARD_FIXTURE_TS = (
        'import { test as base } from "@playwright/test";\n'
        'import type { PlayWrightAiFixtureType } from "@midscene/web/playwright";\n'
        'import { PlaywrightAiFixture } from "@midscene/web/playwright";\n'
        'import "dotenv/config";\n\n'
        "export const test = base.extend<PlayWrightAiFixtureType>(PlaywrightAiFixture({\n"
        "  waitForNetworkIdleTimeout: 2000,\n"
        "}));\n"
    )

    def __init__(self, model_client_instance=None, **kwargs):
        super().__init__(
            agent_type=AgentTypes.UI_SCRIPT_GENERATOR,
            model_client_instance=model_client_instance,
            **kwargs,
        )
        self._assistants: Dict[ScriptType, AssistantAgent] = {}
        logger.info(f"UI 脚本生成智能体初始化完成: {self.agent_name}")

    # ------------------------------------------------------------------
    # 内部 AssistantAgent（按 script_type 缓存）
    # ------------------------------------------------------------------

    def _get_assistant(self, script_type: ScriptType) -> AssistantAgent:
        if script_type in self._assistants:
            return self._assistants[script_type]

        system_message = {
            ScriptType.PLAYWRIGHT_CLASSIC: UiAgentPrompts.SCRIPT_PLAYWRIGHT_CLASSIC_SYSTEM,
            ScriptType.PLAYWRIGHT_MIDSCENE: UiAgentPrompts.SCRIPT_PLAYWRIGHT_MIDSCENE_SYSTEM,
            ScriptType.YAML_MIDSCENE: UiAgentPrompts.SCRIPT_YAML_MIDSCENE_SYSTEM,
        }[script_type]

        assistant = AssistantAgent(
            name=f"ui_script_{script_type.value}",
            model_client=self.model_client,
            system_message=system_message,
            model_client_stream=False,
        )
        self._assistants[script_type] = assistant
        return assistant

    # ------------------------------------------------------------------
    # 消息处理入口
    # ------------------------------------------------------------------

    @message_handler
    async def handle_script_generation(
        self, message: ScriptGenerationInput, ctx: MessageContext
    ) -> None:
        start = datetime.now()
        try:
            await self._send_message(
                f"开始生成脚本：{message.script_name}（模板={message.script_type.value}）",
                message_type="info",
                region=MessageRegion.PROCESS,
            )

            page_analysis = message.page_analysis
            if page_analysis is None:
                logger.warning(
                    f"ScriptGenerationInput.page_analysis 为空（page_analysis_id={message.page_analysis_id}），"
                    f"将完全依赖 LLM 通用模板兜底"
                )
                await self._send_message(
                    "未携带页面分析结果,生成质量将下降(走通用模板)",
                    message_type="warning",
                    region=MessageRegion.WARNING,
                )

            output = await self._generate(message, page_analysis)

            elapsed = (datetime.now() - start).total_seconds()
            await self._send_message(
                f"脚本生成完成（耗时 {elapsed:.1f}s, 模板={message.script_type.value}, "
                f"兜底={output.is_fallback}）",
                message_type="success",
                is_final=True,
                region=MessageRegion.SUCCESS,
                result={
                    "script_id": output.script_id,
                    "script_type": output.script_type.value,
                    "file_name": output.file_name,
                    "is_fallback": output.is_fallback,
                    "output": output.model_dump(mode="json"),
                },
            )

        except Exception as e:
            logger.exception(f"UI 脚本生成失败: {e}")
            await self._send_message(
                f"脚本生成异常：{e}",
                message_type="error",
                is_final=True,
                region=MessageRegion.ERROR,
            )

    # ------------------------------------------------------------------
    # 主调度
    # ------------------------------------------------------------------

    async def _generate(
        self,
        message: ScriptGenerationInput,
        page_analysis: Optional[PageAnalysisOutput],
    ) -> ScriptGenerationOutput:
        # 登录态由 auth.setup.ts + storageState 接管,Playwright baseURL 由
        # playwright.config.ts 从 UI_BASE_URL 注入,业务脚本无需也不应该感知 URL。
        # 仅 YAML 模板因为是独立 midscene CLI 跑、没有 baseURL 概念,需要一个绝对 URL,
        # 优先用用户在弹窗里显式填写的 target_url,其次用 UI_BASE_URL,都没有才退出。
        from app.settings.config import settings as _settings
        yaml_url = (message.target_url or _settings.UI_BASE_URL or "").strip()

        # 0) 降级演练开关:直接走兜底模板,不调 LLM(QA 验证用)
        if getattr(_settings, "UI_AUTOMATION_FORCE_FALLBACK", False):
            await self._send_message(
                "已开启 UI_AUTOMATION_FORCE_FALLBACK,直接走本地模板",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return self._fallback_generate(message, page_analysis, yaml_url)

        # 1) 尝试 LLM 生成
        try:
            task_text = self._build_task_prompt(message, page_analysis)
            assistant = self._get_assistant(message.script_type)
            content = await self._run_agent_collect(
                assistant, TextMessage(content=task_text, source="user")
            )
            parsed = self._extract_llm_payload(content or "", message.script_type)
            if parsed:
                return self._build_output_from_parsed(message, parsed)
        except Exception as e:
            logger.error(f"LLM 生成失败,走兜底: {e}")

        # 2) 兜底模板
        await self._send_message(
            "LLM 不可用,使用本地模板生成脚本",
            message_type="warning",
            region=MessageRegion.WARNING,
        )
        return self._fallback_generate(message, page_analysis, yaml_url)

    def _build_task_prompt(
        self,
        message: ScriptGenerationInput,
        page_analysis: Optional[PageAnalysisOutput],
    ) -> str:
        analysis_block = (
            json.dumps(page_analysis.model_dump(mode="json"), ensure_ascii=False, indent=2)
            if page_analysis
            else "(无,可仅根据用户意图生成最小可用脚本)"
        )
        return (
            f"脚本名称: {message.script_name}\n"
            f"模板类型: {message.script_type.value}\n"
            f"用户补充意图:\n{message.user_intent or '(无)'}\n\n"
            f"页面分析结果(含元素清单/交互流程/测试用例):\n{analysis_block}\n\n"
            f"⚠️ 重要约束:\n"
            f"- 脚本启动即处于已登录态(auth.setup.ts + storageState 已加载)\n"
            f"- Playwright 模板使用 page.goto('/') 走 baseURL,严禁 hardcode 任何完整 URL\n"
            f"- 业务页通过菜单导航进入,不要直接 goto 业务页 URL\n\n"
            f"请严格按系统提示词中的 JSON 格式输出。"
        )

    def _extract_llm_payload(
        self, content: str, script_type: ScriptType
    ) -> Optional[Dict[str, Any]]:
        """解析 LLM 输出,允许:
        - 严格 JSON
        - markdown 包裹的 JSON
        - 退化为裸代码块时,提取代码块作为 script_content
        """
        parsed = self._extract_json_from_content(content)
        if parsed and ("script_content" in parsed or "file_name" in parsed):
            return parsed

        # 兜底:从 markdown 代码块提取内容
        code_blocks = re.findall(r"```(?:typescript|ts|yaml|yml|javascript|js)?\s*\n(.*?)```", content, re.DOTALL)
        if code_blocks:
            script_content = code_blocks[0].strip()
            return {
                "file_name": self._default_file_name(script_type),
                "script_content": script_content,
            }
        return None

    def _default_file_name(self, script_type: ScriptType) -> str:
        suffix = "yaml" if script_type == ScriptType.YAML_MIDSCENE else "spec.ts"
        return f"ui_test_{uuid.uuid4().hex[:8]}.{suffix}"

    def _build_output_from_parsed(
        self, message: ScriptGenerationInput, parsed: Dict[str, Any]
    ) -> ScriptGenerationOutput:
        file_name = parsed.get("file_name") or self._default_file_name(message.script_type)
        script_content = parsed.get("script_content") or ""
        auxiliary_files: Dict[str, str] = parsed.get("auxiliary_files") or {}

        # playwright_midscene 必须带 fixture.ts;LLM 没给就补上
        if message.script_type == ScriptType.PLAYWRIGHT_MIDSCENE and "fixture.ts" not in auxiliary_files:
            auxiliary_files["fixture.ts"] = self._STANDARD_FIXTURE_TS

        return ScriptGenerationOutput(
            session_id=message.session_id,
            script_id=None,
            script_type=message.script_type,
            script_name=message.script_name,
            file_name=file_name,
            script_content=script_content,
            auxiliary_files=auxiliary_files,
            source=ScriptSource.AI,
            is_fallback=False,
            generated_at=datetime.now(),
        )

    # ------------------------------------------------------------------
    # 兜底模板（LLM 不可用时基于 testcase_design 步骤本地拼接）
    # ------------------------------------------------------------------

    def _fallback_generate(
        self,
        message: ScriptGenerationInput,
        page_analysis: Optional[PageAnalysisOutput],
        yaml_url: str,
    ) -> ScriptGenerationOutput:
        steps, elements = self._extract_steps_and_elements(page_analysis)
        case_name = (
            page_analysis.testcase_design.case_name
            if page_analysis and page_analysis.testcase_design
            else message.script_name
        )

        if message.script_type == ScriptType.PLAYWRIGHT_CLASSIC:
            content = self._render_playwright_classic(case_name, steps, elements)
            file_name = f"{self._sanitize_filename(message.script_name)}.spec.ts"
            aux: Dict[str, str] = {}
        elif message.script_type == ScriptType.PLAYWRIGHT_MIDSCENE:
            content = self._render_playwright_midscene(case_name, steps, elements)
            file_name = f"{self._sanitize_filename(message.script_name)}.spec.ts"
            aux = {"fixture.ts": self._STANDARD_FIXTURE_TS}
        else:  # YAML_MIDSCENE
            # YAML 是 midscene CLI 独立执行,没有 Playwright baseURL 概念,
            # url 留空会让 CLI 启动就报错,所以这里必须有兜底
            content = self._render_yaml_midscene(case_name, yaml_url or "about:blank", steps, elements)
            file_name = f"{self._sanitize_filename(message.script_name)}.yaml"
            aux = {}

        return ScriptGenerationOutput(
            session_id=message.session_id,
            script_id=None,
            script_type=message.script_type,
            script_name=message.script_name,
            file_name=file_name,
            script_content=content,
            auxiliary_files=aux,
            source=ScriptSource.AI,
            is_fallback=True,
            generated_at=datetime.now(),
        )

    def _extract_steps_and_elements(
        self, page_analysis: Optional[PageAnalysisOutput]
    ) -> tuple[List[InteractionStep], Dict[str, UiElement]]:
        steps: List[InteractionStep] = []
        elements: Dict[str, UiElement] = {}
        if not page_analysis:
            return steps, elements
        if page_analysis.testcase_design and page_analysis.testcase_design.steps:
            steps = page_analysis.testcase_design.steps
        elif page_analysis.interaction_analysis:
            steps = page_analysis.interaction_analysis.steps
        if page_analysis.element_recognition:
            for el in page_analysis.element_recognition.elements:
                elements[el.element_id] = el
        return steps, elements

    def _sanitize_filename(self, name: str) -> str:
        safe = re.sub(r"[^\w\-]+", "_", name).strip("_")
        return safe or f"ui_test_{uuid.uuid4().hex[:8]}"

    # -- playwright_classic 渲染 --
    def _render_playwright_classic(
        self,
        case_name: str,
        steps: List[InteractionStep],
        elements: Dict[str, UiElement],
    ) -> str:
        lines = [
            'import { test, expect } from "@playwright/test";',
            "",
            f'test("{self._escape_js(case_name)}", async ({{ page }}) => {{',
            '  // baseURL 由 playwright.config.ts 从 UI_BASE_URL 注入;登录态由 auth.setup.ts 提供',
            '  await page.goto("/");',
        ]
        for idx, s in enumerate(steps):
            el = elements.get(s.target_element_id or "")
            locator = self._build_pw_locator(el, s.target_description)
            if s.action == "navigate":
                # 业务用例不再 hardcode 业务页 URL;step 显式给了 value(站内相对路径)才二次 goto
                if s.value and (s.value.startswith("/") or s.value.startswith("#")):
                    lines.append(f'  await page.goto("{s.value}");')
            elif s.action == "input":
                value = (s.value or "test").replace('"', '\\"')
                lines.append(f'  await {locator}.fill("{value}");')
            elif s.action == "click":
                # 启发式:"前一步 input + 本步 click 搜索按钮"的组合,改为 input.press("Enter")
                # 避免 Naive UI 搜索按钮被表头吸顶遮挡/icon-only 命名不稳导致 Click 30s 超时
                prev = steps[idx - 1] if idx > 0 else None
                target_text = (s.target_description or "") + " " + ((el.text_content or "") if el else "")
                is_search_btn = any(k in target_text for k in ("搜索", "查询", "查找", "Search", "search"))
                if prev and prev.action == "input" and is_search_btn:
                    prev_el = elements.get(prev.target_element_id or "")
                    prev_locator = self._build_pw_locator(prev_el, prev.target_description)
                    lines.append(f'  await {prev_locator}.press("Enter");')
                else:
                    lines.append(f"  await {locator}.click();")
            elif s.action == "select":
                value = (s.value or "").replace('"', '\\"')
                lines.append(f'  await {locator}.selectOption("{value}");')
            elif s.action == "hover":
                lines.append(f"  await {locator}.hover();")
            elif s.action == "scroll":
                lines.append("  await page.mouse.wheel(0, 500);")
            elif s.action == "wait":
                lines.append("  await page.waitForTimeout(1000);")
            elif s.action == "assert":
                expected = self._escape_js(s.expected or s.target_description or "页面正常")
                lines.append(f'  await expect(page.locator("body")).toContainText("{expected}");')
        lines.append("});")
        lines.append("")
        return "\n".join(lines)

    # 裸 tag 黑名单:命中后退化为 getByText / getByRole,避免 page.locator("table") 这类
    # 撞 ant-table-measure-row(aria-hidden=true) 的可见性陷阱
    _BARE_TAG_BLACKLIST = {
        "table", "thead", "tbody", "tr", "td", "th",
        "div", "span", "ul", "ol", "li", "section", "article",
        "input", "form", "button", "a", "img",
    }

    def _build_pw_locator(self, el: Optional[UiElement], fallback: str) -> str:
        """根据 UiElement.locator_suggestions 构造 Playwright 定位代码片段"""
        if el and el.locator_suggestions:
            top = sorted(el.locator_suggestions, key=lambda x: x.confidence, reverse=True)[0]
            expr = self._escape_js(top.expression)
            strategy = top.strategy
            if strategy == "text":
                return f'page.getByText("{expr}")'
            if strategy == "role":
                # expression 可能形如 'button[name="登录"]' 也可能就是 role 名
                role_match = re.match(r"^(\w+)(?:\[name=['\"](.+?)['\"]\])?$", top.expression)
                if role_match:
                    role = role_match.group(1)
                    name = role_match.group(2)
                    if name:
                        return f'page.getByRole("{role}", {{ name: "{self._escape_js(name)}" }})'
                    return f'page.getByRole("{role}")'
                return f'page.getByText("{expr}")'
            if strategy == "test_id":
                return f'page.getByTestId("{expr}")'
            if strategy == "xpath":
                return f'page.locator("xpath={expr}")'
            # 裸 tag 兜底:strategy=css 但 expression 是 "table" / "div" / "tr" 这种单 tag,
            # 转成 getByRole(语义),否则会撞辅助行 aria-hidden 的可见性问题
            if top.expression.strip().lower() in self._BARE_TAG_BLACKLIST:
                role_map = {"table": "table", "tr": "row", "td": "cell", "th": "columnheader",
                            "button": "button", "a": "link", "input": "textbox", "img": "img",
                            "form": "form", "ul": "list", "ol": "list", "li": "listitem"}
                role = role_map.get(top.expression.strip().lower())
                if role:
                    return f'page.getByRole("{role}")'
                # 没有合适 role 映射(div/span 等),退化到业务文本
                text = self._escape_js((el.text_content if el else None) or fallback or "元素")
                return f'page.getByText("{text}")'
            return f'page.locator("{expr}")'

        # 没有 locator_suggestions 时退化:用 description / fallback 走 getByText
        text = self._escape_js((el.text_content if el else None) or fallback or "元素")
        return f'page.getByText("{text}")'

    def _escape_js(self, s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')

    # -- playwright_midscene 渲染 --
    def _render_playwright_midscene(
        self,
        case_name: str,
        steps: List[InteractionStep],
        elements: Dict[str, UiElement],
    ) -> str:
        lines = [
            'import { expect } from "@playwright/test";',
            'import { test } from "./fixture";',
            "",
            "// baseURL 由 playwright.config.ts 从 UI_BASE_URL 注入;登录态由 auth.setup.ts 提供",
            "test.beforeEach(async ({ page }) => {",
            '  await page.goto("/");',
            '  await page.waitForLoadState("networkidle");',
            "});",
            "",
            f'test("{self._escape_js(case_name)}", async ({{ aiTap, aiInput, aiAssert, aiWaitFor }}) => {{',
        ]
        for s in steps:
            el = elements.get(s.target_element_id or "")
            target_desc = self._escape_js((el.description if el else None) or s.target_description or s.target_element_id or "元素")
            if s.action == "input":
                value = self._escape_js(s.value or "test")
                lines.append(f'  await aiInput("{value}", "{target_desc}");')
            elif s.action == "click":
                lines.append(f'  await aiTap("{target_desc}");')
            elif s.action == "hover":
                lines.append(f'  await aiHover("{target_desc}");')
            elif s.action == "wait":
                expected = self._escape_js(s.expected or "页面加载完成")
                lines.append(f'  await aiWaitFor("{expected}");')
            elif s.action == "assert":
                expected = self._escape_js(s.expected or s.target_description or "页面正常")
                lines.append(f'  await aiAssert("{expected}");')
            elif s.action == "navigate":
                # MidScene+Playwright 由 beforeEach 已处理首次 navigate;额外的 navigate 不渲染
                continue
            elif s.action == "select":
                value = self._escape_js(s.value or "")
                lines.append(f'  await aiTap("{target_desc}");')
                lines.append(f'  await aiTap("{value}");')
        lines.append("});")
        lines.append("")
        return "\n".join(lines)

    # -- yaml_midscene 渲染 --
    def _render_yaml_midscene(
        self,
        case_name: str,
        yaml_url: str,
        steps: List[InteractionStep],
        elements: Dict[str, UiElement],
    ) -> str:
        lines = [
            "web:",
            f'  url: "{yaml_url}"',
            "  viewportWidth: 1280",
            "  viewportHeight: 800",
            "  waitForNetworkIdle:",
            "    timeout: 2000",
            "    continueOnNetworkIdleError: true",
            "",
            "tasks:",
            f'  - name: "{self._escape_yaml(case_name)}"',
            "    flow:",
        ]
        for s in steps:
            el = elements.get(s.target_element_id or "")
            target_desc = self._escape_yaml((el.description if el else None) or s.target_description or s.target_element_id or "元素")
            if s.action == "input":
                value = self._escape_yaml(s.value or "test")
                lines.append(f'      - aiInput: "{value}"')
                lines.append(f'        locate: "{target_desc}"')
            elif s.action == "click":
                lines.append(f'      - aiTap: "{target_desc}"')
            elif s.action == "hover":
                lines.append(f'      - aiHover: "{target_desc}"')
            elif s.action == "wait":
                expected = self._escape_yaml(s.expected or "页面加载完成")
                lines.append(f'      - aiWaitFor: "{expected}"')
                lines.append(f"        timeout: 10000")
            elif s.action == "assert":
                expected = self._escape_yaml(s.expected or s.target_description or "页面正常")
                lines.append(f'      - aiAssert: "{expected}"')
            elif s.action == "select":
                value = self._escape_yaml(s.value or "")
                lines.append(f'      - aiTap: "{target_desc}"')
                lines.append(f'      - aiTap: "{value}"')
            elif s.action == "scroll":
                lines.append("      - aiScroll:")
                lines.append('          direction: "down"')
                lines.append('          scrollType: "once"')
                lines.append("          distance: 400")
            elif s.action == "navigate":
                # YAML 首屏 url 已含;额外 navigate 用 javascript 节点(相对路径需自行拼)
                if s.value:
                    lines.append(f'      - javascript: "window.location.href = \\"{self._escape_yaml(s.value)}\\""')
        lines.append("")
        return "\n".join(lines)

    def _escape_yaml(self, s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')

    # ------------------------------------------------------------------
    # 共用工具
    # ------------------------------------------------------------------

    async def _run_agent_collect(self, agent: AssistantAgent, task: TextMessage) -> str:
        """运行 AssistantAgent 并收集最终文本输出。

        包 asyncio.wait_for 超时：单次 LLM 调用超过 UI_LLM_CALL_TIMEOUT 秒视为失败，
        返回空串让外层走兜底模板，避免脚本生成门面卡死。
        """
        from app.settings.config import settings
        timeout = max(5, int(getattr(settings, "UI_LLM_CALL_TIMEOUT", 60)))
        try:
            result = await asyncio.wait_for(agent.run(task=task), timeout=timeout)
            if result and result.messages:
                last = result.messages[-1]
                if hasattr(last, "content"):
                    content = last.content
                    if isinstance(content, list):
                        return "\n".join(str(c) for c in content if isinstance(c, str))
                    return str(content)
            return ""
        except asyncio.TimeoutError:
            logger.warning(f"AssistantAgent 运行超时（>{timeout}s），走兜底模板")
            return ""
        except Exception as e:
            logger.error(f"AssistantAgent 运行失败: {e}")
            return ""
