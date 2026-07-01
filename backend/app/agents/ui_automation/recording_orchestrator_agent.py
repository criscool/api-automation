"""
UI 录制编排智能体（阶段四）

职责:
1. 接收 StartCodegenInput → 起 Playwright codegen 子进程 → 等用户关浏览器
2. 录完自动调 AI 后处理(LLM 把裸 page.click 改成 aiTap + 注入 fixture import)
3. 落库:
   - ui_recording_sessions 主表(整段生命周期状态机)
   - ui_test_scripts 终态脚本(source_type="recorded")
4. 全程 SSE 推送状态给前端(走基类 _send_message → stream_response topic)

也支持独立的 PostprocessRecordingInput 入口(对已落库的录制重新优化,不重启浏览器)。

约束:
- 录制本身不调 LLM(纯 codegen 子进程),仅在后处理阶段用 LLM
- LLM 失败时降级:把录制原始脚本"原样"包成最小 fixture 模板,保证用户拿得到能跑的脚本
- 不直接读写 DB? 这里采取的妥协:直接写 DB —— 因为录制流程线性、状态机简单,
  不像执行那样有 DataPersistenceAgent 解耦的必要,从 Agent 内部事务化更新更省往返
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from autogen_core import MessageContext, message_handler, type_subscription
from loguru import logger
from tortoise.transactions import in_transaction

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.types import AgentTypes, MessageRegion, TopicTypes
from app.models.ui_automation import UiRecordingSession, UiTestScript
from app.services.ui_automation import codegen_runner
from app.settings.config import settings

from .schemas import (
    PostprocessRecordingInput,
    RecordingDoneMessage,
    StartCodegenInput,
    UiAgentPrompts,
)


# 文件名安全字符:只允许 ASCII 字母 / 数字 / 下划线 / 短横线
# Why: Playwright Test CLI 把脚本路径当正则处理,Windows PowerShell + Node + Playwright
# 链路上一旦含中文字符,任意一环编码不一致就会导致 "No tests found"。
# 中文名保留在 spec.ts 内的 test('中文名', ...) title 和 DB.name 字段,完全够用,
# 文件名不需要承担可读性职责。
_FILENAME_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_\-]")


def _safe_filename_stem(name: str, fallback: str) -> str:
    """把用户输入的名称转成可用作文件名的 stem。

    Why: 用户可能输入"资产管理-添加资产 / 保存成功"这类带斜杠空格的名称,
    直接写盘会踩 Windows 非法字符;另外 uvicorn --reload 不能容忍点号结尾的目录
    (见 project_uvicorn_reload_pyext_trap),所以一并把 . 也清掉。
    """
    cleaned = _FILENAME_SAFE_PATTERN.sub("_", (name or "").strip())
    cleaned = cleaned.strip("_-") or fallback
    return cleaned[:80]


@type_subscription(topic_type=TopicTypes.UI_RECORDING_ORCHESTRATOR.value)
class UiRecordingOrchestratorAgent(BaseApiAutomationAgent):
    """UI 录制编排智能体"""

    def __init__(self, model_client_instance=None, **kwargs):
        super().__init__(
            agent_type=AgentTypes.UI_RECORDING_ORCHESTRATOR,
            model_client_instance=model_client_instance,
            **kwargs,
        )
        logger.info(f"UI 录制编排智能体初始化完成: {self.agent_name}")

    # ==================================================================
    # 入口 1:开始录制(codegen → 后处理 → 落库)
    # ==================================================================

    @message_handler
    async def handle_start_codegen(
        self, message: StartCodegenInput, ctx: MessageContext
    ) -> None:
        await self._ensure_database_connection()
        session_id = message.session_id
        start_dt = datetime.now()

        await self._send_message(
            f"准备启动 Playwright 录制 (session={session_id[:8]}, target={message.target_url})",
            message_type="info",
            region=MessageRegion.PROCESS,
        )

        # --- 1. 更新会话状态 = recording ---------------------------------
        try:
            await UiRecordingSession.filter(session_id=session_id).update(
                status="recording",
                target_url=message.target_url,
                storage_state_path=message.storage_state_relpath
                or settings.UI_RECORDING_DEFAULT_STORAGE_STATE,
            )
        except Exception as e:
            logger.warning(f"[recording {session_id}] 更新 recording 状态失败: {e}")

        # --- 1.5 可选预抓 page_dict(crawl4ai),仅作为 LLM 后处理增强 -----
        # 失败仅 WARN,不阻塞录制
        page_dict: Optional[Dict[str, Any]] = None
        if message.prefetch_page_semantics and getattr(settings, "UI_CRAWL4AI_ENABLED", False):
            page_dict = await self._maybe_prefetch_page_dict(
                session_id=session_id,
                target_url=message.target_url,
                storage_state_relpath=message.storage_state_relpath,
            )

        await self._send_message(
            "浏览器窗口即将弹出,请在浏览器中完成操作后关闭窗口以结束录制",
            message_type="info",
            region=MessageRegion.PROCESS,
        )

        # --- 2. 调子进程录制 -------------------------------------------
        try:
            result = await codegen_runner.run_codegen(
                session_id=session_id,
                target_url=message.target_url,
                storage_state_relpath=message.storage_state_relpath,
                timeout_seconds=message.timeout_seconds,
            )
        except asyncio.CancelledError:
            await self._mark_failed(session_id, "录制被外部取消")
            await self._publish_done(
                session_id=session_id, status="cancelled",
                error_message="录制被外部取消",
                duration_ms=int((datetime.now() - start_dt).total_seconds() * 1000),
            )
            raise
        except Exception as e:
            logger.exception(f"[recording {session_id}] codegen 服务异常")
            await self._mark_failed(session_id, f"录制服务异常: {e}")
            await self._send_message(
                f"录制服务异常: {e}",
                message_type="error",
                region=MessageRegion.ERROR,
            )
            await self._publish_done(
                session_id=session_id, status="failed",
                error_message=str(e),
                duration_ms=int((datetime.now() - start_dt).total_seconds() * 1000),
            )
            return

        # --- 3. 录制终态判断 -------------------------------------------
        if result.status != "success":
            await self._mark_failed(
                session_id,
                result.error_message or f"录制结束 status={result.status}",
                raw_script_path=result.raw_script_path,
                duration_ms=result.duration_ms,
            )
            await self._send_message(
                f"录制未成功完成: status={result.status} reason={result.error_message}",
                message_type="error",
                region=MessageRegion.ERROR,
            )
            await self._publish_done(
                session_id=session_id, status=result.status,
                raw_script_path=result.raw_script_path,
                error_message=result.error_message,
                duration_ms=result.duration_ms,
            )
            return

        await self._send_message(
            f"录制完成,共捕获 {len(result.raw_script_content.splitlines())} 行原始脚本,"
            f"开始 AI 优化(注入 fixture + MidScene 改写)...",
            message_type="success",
            region=MessageRegion.SUCCESS,
        )

        # --- 4. 更新状态 = postprocessing -----------------------------
        try:
            await UiRecordingSession.filter(session_id=session_id).update(
                status="postprocessing",
                raw_script_path=result.raw_script_path,
                duration_ms=result.duration_ms,
            )
        except Exception as e:
            logger.warning(f"[recording {session_id}] 更新 postprocessing 状态失败: {e}")

        # --- 5. 跑 LLM 后处理 + 落库 ----------------------------------
        await self._do_postprocess(
            session_id=session_id,
            raw_script_content=result.raw_script_content,
            raw_script_path=result.raw_script_path,
            target_url=message.target_url,
            name=message.name,
            created_by=message.created_by,
            recorded_duration_ms=result.duration_ms,
            script_style=message.script_style,
            page_dict=page_dict,
        )

    # ==================================================================
    # 入口 2:对已录制的脚本重新优化(不开浏览器)
    # ==================================================================

    @message_handler
    async def handle_postprocess(
        self, message: PostprocessRecordingInput, ctx: MessageContext
    ) -> None:
        await self._ensure_database_connection()
        session_id = message.session_id

        await self._send_message(
            f"重新优化录制脚本 (session={session_id[:8]})",
            message_type="info",
            region=MessageRegion.PROCESS,
        )

        # 读原始脚本
        workspace = Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
        raw_abs = (workspace / message.raw_script_path).resolve()
        try:
            raw_abs.relative_to(workspace)
        except ValueError:
            await self._send_message(
                f"原始脚本路径越界,拒绝读取: {message.raw_script_path}",
                message_type="error",
                region=MessageRegion.ERROR,
            )
            await self._publish_done(
                session_id=session_id, status="failed",
                error_message="原始脚本路径越界",
            )
            return

        if not raw_abs.exists():
            await self._send_message(
                f"原始脚本不存在: {message.raw_script_path}",
                message_type="error",
                region=MessageRegion.ERROR,
            )
            await self._publish_done(
                session_id=session_id, status="failed",
                error_message="原始脚本不存在",
            )
            return

        try:
            raw_content = raw_abs.read_text(encoding="utf-8")
        except OSError as e:
            await self._send_message(
                f"读取原始脚本失败: {e}",
                message_type="error",
                region=MessageRegion.ERROR,
            )
            await self._publish_done(
                session_id=session_id, status="failed",
                error_message=f"读取原始脚本失败: {e}",
            )
            return

        try:
            await UiRecordingSession.filter(session_id=session_id).update(
                status="postprocessing"
            )
        except Exception as e:
            logger.warning(f"[recording {session_id}] 更新 postprocessing 状态失败: {e}")

        # 复用之前 prefetch 的 page_dict(如果有)
        existing_page_dict: Optional[Dict[str, Any]] = None
        try:
            existing_session = await UiRecordingSession.filter(session_id=session_id).first()
            if existing_session and isinstance(existing_session.metadata, dict):
                existing_page_dict = existing_session.metadata.get("page_dict")
        except Exception as e:
            logger.warning(f"[recording {session_id}] 读取 metadata.page_dict 失败: {e}")

        await self._do_postprocess(
            session_id=session_id,
            raw_script_content=raw_content,
            raw_script_path=message.raw_script_path,
            target_url=message.target_url,
            name=message.name,
            created_by=message.created_by,
            recorded_duration_ms=0,
            script_style=message.script_style,
            page_dict=existing_page_dict,
        )

    # ==================================================================
    # 后处理核心(LLM 改写 + 写盘 + 落库)
    # ==================================================================

    async def _do_postprocess(
        self,
        *,
        session_id: str,
        raw_script_content: str,
        raw_script_path: str,
        target_url: str,
        name: str,
        created_by: str,
        recorded_duration_ms: int,
        script_style: str = "playwright",
        page_dict: Optional[Dict[str, Any]] = None,
    ) -> None:
        start_dt = datetime.now()

        # 防御:LLM 偶尔会被传入未知 style,强制收敛到两种合法值
        style = (script_style or "playwright").strip().lower()
        if style not in ("midscene", "playwright"):
            logger.warning(f"[recording {session_id}] 未知 script_style={script_style!r},退回 playwright")
            style = "playwright"

        # 1. 走 LLM 改写;失败走降级模板
        try:
            polished = await asyncio.wait_for(
                self._llm_polish(raw_script_content, target_url, name, style, page_dict=page_dict),
                timeout=settings.UI_RECORDING_POSTPROCESS_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[recording {session_id}] LLM 后处理超时,走降级")
            polished = None
        except Exception as e:
            logger.warning(f"[recording {session_id}] LLM 后处理异常,走降级: {e}")
            polished = None

        if not polished or not polished.get("script_content"):
            await self._send_message(
                "LLM 后处理失败或超时,使用降级模板(原始脚本套上 fixture 头)",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            final_content = self._fallback_wrap(raw_script_content, name, style, target_url)
            notes = f"降级模板({style}):仅清洗 import + 去 test.use + 删冗余 goto,未做 AI 改写"
        else:
            final_content = polished["script_content"]
            notes = polished.get("notes") or ""
            await self._send_message(
                f"LLM 后处理完成: {notes[:200]}",
                message_type="success",
                region=MessageRegion.SUCCESS,
            )

        # 2. 写入 scripts/<safe_name>.spec.ts
        safe_stem = _safe_filename_stem(name, fallback=f"recording_{session_id[:8]}")
        file_name = f"{safe_stem}.spec.ts"
        scripts_dir = Path(settings.UI_AUTOMATION_WORKSPACE) / "scripts"
        try:
            await asyncio.to_thread(scripts_dir.mkdir, parents=True, exist_ok=True)
            file_abs = scripts_dir / file_name
            await asyncio.to_thread(file_abs.write_text, final_content, "utf-8")
            file_rel = f"scripts/{file_name}"
        except OSError as e:
            logger.error(f"[recording {session_id}] 写最终脚本失败: {e}")
            await self._mark_failed(session_id, f"写最终脚本失败: {e}",
                                    raw_script_path=raw_script_path,
                                    duration_ms=recorded_duration_ms)
            await self._publish_done(
                session_id=session_id, status="failed",
                raw_script_path=raw_script_path,
                error_message=f"写最终脚本失败: {e}",
                duration_ms=recorded_duration_ms,
            )
            return

        # 3. 落库:ui_test_scripts + 反向关联 ui_recording_sessions
        # 同一个 recording_session 反复 repolish 时,必须 UPDATE 已关联的 script,
        # 不能每次 INSERT 新行——否则前端列表会出现同名脚本堆积,且 file_path 全指向同一文件,
        # 旧 DB 行的 content 是过期快照,与磁盘文件不一致。
        try:
            async with in_transaction():
                # 查这个会话之前是否已经关联过 script,若是则复用 script_id 走 UPDATE
                existing_session = await UiRecordingSession.filter(session_id=session_id).first()
                existing_script_id = (
                    existing_session.final_script_id if existing_session else ""
                )
                existing_script = None
                if existing_script_id:
                    existing_script = await UiTestScript.filter(
                        script_id=existing_script_id
                    ).first()

                description = f"Playwright codegen 录制生成 ({notes[:120]})"
                if existing_script:
                    # repolish 路径:UPDATE 同一行,script_id/created_at/created_by 保留
                    script_id = existing_script_id
                    await UiTestScript.filter(script_id=script_id).update(
                        name=name,
                        description=description,
                        script_type="playwright",
                        source_type="recorded",
                        content=final_content,
                        file_path=file_rel,
                        tags=["recorded"],
                        status="active",
                        base_url=target_url,
                    )
                else:
                    # 首次录制:INSERT 并把 final_script_id 写回 session
                    script_id = uuid.uuid4().hex
                    await UiTestScript.create(
                        script_id=script_id,
                        analysis_id="",
                        name=name,
                        description=description,
                        script_type="playwright",
                        source_type="recorded",
                        content=final_content,
                        file_path=file_rel,
                        tags=["recorded"],
                        status="active",
                        base_url=target_url,
                        created_by=created_by or "recording_pipeline",
                    )
                total_duration = recorded_duration_ms + int(
                    (datetime.now() - start_dt).total_seconds() * 1000
                )
                await UiRecordingSession.filter(session_id=session_id).update(
                    status="ready",
                    raw_script_path=raw_script_path,
                    final_script_id=script_id,
                    duration_ms=total_duration,
                    error_message="",
                )
        except Exception as e:
            logger.exception(f"[recording {session_id}] 落库失败")
            await self._mark_failed(session_id, f"落库失败: {e}",
                                    raw_script_path=raw_script_path,
                                    duration_ms=recorded_duration_ms)
            await self._publish_done(
                session_id=session_id, status="failed",
                raw_script_path=raw_script_path,
                error_message=f"落库失败: {e}",
                duration_ms=recorded_duration_ms,
            )
            return

        await self._send_message(
            f"录制脚本已入库: script_id={script_id[:8]} file={file_rel}",
            message_type="success",
            region=MessageRegion.SUCCESS,
        )
        await self._publish_done(
            session_id=session_id, status="ready",
            raw_script_path=raw_script_path,
            final_script_id=script_id,
            final_script_path=file_rel,
            duration_ms=recorded_duration_ms + int(
                (datetime.now() - start_dt).total_seconds() * 1000
            ),
        )

    # ==================================================================
    # LLM 改写
    # ==================================================================

    async def _llm_polish(
        self,
        raw_script: str,
        target_url: str,
        name: str,
        script_style: str = "playwright",
        page_dict: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """让 LLM 把 codegen 原始脚本改成目标风格。

        script_style:
          - playwright: 保留 getByRole 等原生 selector,只清洗 test.use / goto(默认,推荐)
          - midscene  : 改写为 ./fixture + aiTap/aiInput 等 MidScene 调用(仅 codegen 完全没录到 role 时考虑)

        page_dict:
          可选的真实 DOM 元素字典(由 crawl4ai 预抓产出),作为额外 context 注入 LLM,
          帮助 LLM 把 codegen 录到的不稳定 selector 替换成稳定 selector(id/aria/text)。

        失败/超时 → 返回 None,调用方走降级。
        """
        style = (script_style or "playwright").strip().lower()
        if style == "playwright":
            system_prompt = UiAgentPrompts.RECORDING_POSTPROCESS_PLAYWRIGHT_SYSTEM
        else:
            system_prompt = UiAgentPrompts.RECORDING_POSTPROCESS_SYSTEM

        page_dict_section = ""
        if page_dict and isinstance(page_dict, dict):
            elements = page_dict.get("elements") or []
            if elements:
                # 只取前 80 个,避免 prompt 太长把 LLM 撑爆
                trimmed = elements[:80]
                page_dict_section = (
                    "\n\n【真实 DOM 元素字典(crawl4ai 抓取,优先采用其中的稳定 selector 改写录制脚本)】\n"
                    + json.dumps(
                        {
                            "page_title": page_dict.get("page_title", ""),
                            "elements": trimmed,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )

        prompt = (
            system_prompt
            + "\n\n【目标 URL】\n"
            + (target_url or "(未指定,baseURL 由 playwright.config 注入)")
            + "\n\n【用例名称】\n"
            + name
            + page_dict_section
            + "\n\n【原始脚本(Playwright codegen 输出)】\n```\n"
            + raw_script
            + "\n```\n\n请按要求输出严格 JSON。"
        )

        content = await self._run_assistant_agent(prompt, stream=False)
        if not content:
            return None

        parsed = self._extract_json_from_content(content)
        if not parsed:
            logger.warning(f"LLM 输出无法解析为 JSON,前 200 字符: {content[:200]}")
            return None

        script_content = parsed.get("script_content")
        if not isinstance(script_content, str) or not script_content.strip():
            logger.warning("LLM JSON 缺少 script_content 字段")
            return None

        # 兜底:LLM 偶尔会把 ```ts 包裹带回来,清一下
        script_content = self._strip_md_fences(script_content).strip()
        # 兜底:强制剥离 test.use({...}) 块 —— LLM 会自作主张把 storageState 写死绝对路径,
        # playwright.config.ts 已全局配好,这里再写就是污染
        script_content = self._strip_test_use_block(script_content)
        # 再保险:LLM 偶尔会忘记/写错 import 头
        if style == "midscene":
            if "./fixture" not in script_content and "from \"./fixture\"" not in script_content:
                script_content = self._ensure_fixture_import(script_content)
        else:
            # playwright 风格:确保 import { test, expect } from "@playwright/test",
            # 且严禁 ./fixture / aiTap 之类残留(LLM 偶尔会跨界)
            script_content = self._ensure_playwright_import(script_content)

        # 兜底:LLM 偶尔会漏掉首句 page.goto("/"),浏览器停在 about:blank 全脚本翻车。
        # 即使 prompt 里强制要求了,也必须用确定性规则保险(fallback 路径同样调这个方法)。
        # target_url 带子路径时(如 /asset/network),goto 也跟着跳到该子路径。
        script_content = self._ensure_canonical_goto(script_content, target_url)

        # 兜底:LLM 软约束不可靠,deterministic 改写 getByText().nth(N) anti-pattern
        # (优先级 2.5 prompt 规则的最后一道安全网)
        script_content = self._rewrite_text_nth_anti_pattern(script_content)

        # 兜底:复制资源默认名带时间戳，精确匹配注定跨次失败
        # 提取 _copy_ 前的稳定前缀，改写为 hasText 包含匹配
        script_content = self._rewrite_copy_timestamp_pattern(script_content)

        # 兜底:搜索按钮 click 改写为最近 fill 输入框的 press('Enter')
        # (feedback_search_prefer_enter：搜索/筛选一律用回车，click 易超时)
        script_content = self._rewrite_search_click_to_press_enter(script_content)

        # 兜底:表格行内 checkbox 深层 CSS 定位 → 业务文案 xpath 定位
        # (含状态 class 的链式 CSS 跨环境失败率高，改写为 xpath 用业务文案锚定行)
        script_content = self._rewrite_table_checkbox_to_xpath(script_content)

        # 兜底:prompt 第 9 条 + 硬禁令 F 段 DeepSeek 不一定听,deterministic 保证至少有一句 expect
        # (feedback_ui_script_must_have_assertion 反复强调的"假新闻"反模式必须封死)
        script_content = self._ensure_trailing_assertion(script_content)

        return {
            "script_content": script_content,
            "notes": parsed.get("notes", "") or "",
        }

    @staticmethod
    def _strip_md_fences(text: str) -> str:
        """去掉首尾的 ``` 块,LLM 经常画蛇添足。"""
        stripped = text.strip()
        if stripped.startswith("```"):
            # 去掉第一行 ```lang
            stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        if stripped.endswith("```"):
            stripped = stripped.rsplit("```", 1)[0]
        return stripped.rstrip()

    @staticmethod
    def _strip_test_use_block(text: str) -> str:
        """强制剥离 test.use({...}); 块。

        Why: LLM 经常在录制脚本顶部加 test.use({ storageState: '<绝对路径>' }),
        这会:
          1. 把 storageState 硬编码成开发机绝对路径,换机器立刻失效
          2. 覆盖 playwright.config.ts 里的全局 storageState 配置
          3. 污染 ignoreHTTPSErrors / baseURL 等全局配置项

        解析方式:简单括号配平,不依赖 AST。test.use({ ... }) 这种深层嵌套
        最多一层 {},正则就够;但保险起见用括号栈处理。
        """
        result = []
        i = 0
        n = len(text)
        while i < n:
            # 找下一个 test.use(
            idx = text.find("test.use(", i)
            if idx < 0:
                result.append(text[i:])
                break
            result.append(text[i:idx])
            # 从 ( 开始括号配平
            depth = 0
            j = idx + len("test.use")
            while j < n:
                ch = text[j]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1  # 跳过 ')'
                        # 可选吞掉随后的 ; 和换行
                        while j < n and text[j] in ";\r\n\t ":
                            if text[j] == "\n":
                                j += 1
                                break
                            j += 1
                        break
                j += 1
            i = j
        return "".join(result)

    @staticmethod
    def _ensure_fixture_import(content: str) -> str:
        """LLM 输出缺 fixture import 时补上头部。"""
        header = (
            'import { expect } from "@playwright/test";\n'
            'import { test } from "./fixture";\n\n'
        )
        # 如果 content 已有 import 行,把它替换/合并;否则直接前置
        lines = content.splitlines()
        new_lines = []
        skipped_test_import = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import") and "@playwright/test" in stripped:
                skipped_test_import = True
                continue
            new_lines.append(line)
        body = "\n".join(new_lines).lstrip()
        return header + body

    @staticmethod
    def _ensure_playwright_import(content: str) -> str:
        """纯 Playwright 风格:确保 import 头是 `{ test, expect } from "@playwright/test"`,
        并删除任何 `./fixture` 残留。

        Why: LLM 偶尔跨界 —— 选了 playwright 风格但仍引 `./fixture`,跑起来会 mismatch fixture 签名。
        """
        header = 'import { test, expect } from "@playwright/test";\n\n'
        new_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            # 跳过所有 @playwright/test 和 ./fixture 的 import,统一由 header 重写
            if stripped.startswith("import") and (
                "@playwright/test" in stripped or "./fixture" in stripped
            ):
                continue
            new_lines.append(line)
        body = "\n".join(new_lines).lstrip()
        return header + body

    # ==================================================================
    # deterministic 净化:把 codegen 的 getByText().nth(N) 强制改写
    # ==================================================================

    # 匹配 page.getByText('X') 或 page.getByText("X")
    # 可选 { exact: true } / { exact: false } 等 options 块
    # 紧跟 .nth(N) —— 这是 codegen 录制下拉选项时的标志性 anti-pattern
    _TEXT_NTH_PATTERN = re.compile(
        r"""page\.getByText\(\s*
            (?P<q>['"])(?P<text>[^'"]+)(?P=q)        # 'X' 或 "X"
            (?:\s*,\s*\{[^}]*\})?                     # 可选 { exact: true } 等
            \s*\)\.nth\(\s*\d+\s*\)                   # .nth(N)
        """,
        re.VERBOSE,
    )

    # 匹配 getByRole('<role>', { name: '<prefix>_copy_<14位数字><后续可能有IP/编号/域名等动态内容>' })
    # copy 操作会自动带时间戳 → 每次运行都不同 → 精确 name 匹配注定失败
    # 提取 _copy_ 前的稳定前缀，改写为 hasText 包含匹配
    _COPY_TIMESTAMP_NAME_PATTERN = re.compile(
        r"""getByRole\(\s*
            (?P<q1>['"])(?P<role>[a-zA-Z]+)(?P=q1)\s*,\s*
            \{\s*name:\s*
            (?P<q2>['"])(?P<prefix>[^'"]*?_copy_)\d{8,14}[^'"]*(?P=q2)
            (?:\s*,\s*[^}]*)?                          # 可选 exact: true 等
            \s*\}\s*
        \)""",
        re.VERBOSE,
    )

    # 【搜索按钮识别】覆盖两种常见 codegen 产物：
    # 1) 显式按钮 name：getByRole('button', { name: '搜索'|'查询'|'Search'|'search' })
    # 2) ant-design 搜索输入框自带的搜索按钮：.ant-input-search-button
    # 3) 业务侧常见 class：.search-btn
    _SEARCH_BUTTON_CLICK_PATTERN = re.compile(
        r"""await\s+page\.(?:
            getByRole\(\s*['"]button['"]\s*,\s*\{\s*name:\s*
              ['"](?:搜索|查询|检索|Search|SEARCH|search)['"]
              (?:\s*,\s*[^}]*)?
            \s*\}\s*\)
            |
            locator\(\s*['"](?:\.ant-input-search-button|\.search-btn)['"]\s*\)
        )\.click\(\s*\)\s*;?""",
        re.VERBOSE,
    )

    # 【fill 定位记忆】识别形如 `await page.<selector>.fill('xxx');`
    # 抓取 selector 部分（不含 .fill(...)），用于把后续搜索按钮 click 改写为该 selector.press('Enter')
    _FILL_SELECTOR_PATTERN = re.compile(
        r"""await\s+(?P<sel>page\..+?)\.fill\(""",
        re.VERBOSE,
    )

    # 【业务关键字捕获】用于把表格 checkbox 点击改写为 xpath 业务定位
    # 匹配几种 codegen 常见带业务文案的调用：
    #   .fill('X')                              — 搜索框输入
    #   getByText('X')  / getByTitle('X')       — 文本定位
    #   { hasText: 'X' } / { hasText: /X/ }     — filter 链
    #   getByRole('...', { name: 'X' })         — role name
    _BIZ_TEXT_CAPTURE_PATTERN = re.compile(
        r"""(?:
            \.fill\(\s*(?P<q1>['"])(?P<txt1>[^'"]+)(?P=q1)
            |
            getByText\(\s*(?P<q2>['"])(?P<txt2>[^'"]+)(?P=q2)
            |
            getByTitle\(\s*(?P<q3>['"])(?P<txt3>[^'"]+)(?P=q3)
            |
            hasText\s*:\s*(?:
                (?P<q4>['"])(?P<txt4>[^'"]+)(?P=q4)
                |
                /(?P<txt5>[^/]+)/[a-z]*
            )
            |
            getByRole\(\s*['"][a-zA-Z]+['"]\s*,\s*\{\s*name:\s*
              (?P<q6>['"])(?P<txt6>[^'"]+)(?P=q6)
        )""",
        re.VERBOSE,
    )

    # 【表格复选框识别】链式 CSS 含 ant 表格选择列关键 class
    # codegen 录 checkbox 点击时几乎必带 .ant-checkbox-inner 或 .ant-checkbox-wrapper
    # 且路径里含 .ant-table-row 或 .ant-table-selection-column 才能确认是"表格行内"复选框
    # （避免误改表单里的独立 checkbox）
    _TABLE_CHECKBOX_CLICK_PATTERN = re.compile(
        r"""await\s+page\.locator\(\s*
            (?P<q>['"`])(?P<sel>[^'"`]*
                (?:\.ant-table-row|\.ant-table-selection-column)
                [^'"`]*
                \.ant-checkbox(?:-inner|-wrapper)?
                [^'"`]*
            )(?P=q)
        \s*\)\.(?:click|check)\(\s*\)\s*;?""",
        re.VERBOSE,
    )

    @staticmethod
    def _escape_js_regex_literal(s: str) -> str:
        """转义 JS 正则字面量里的元字符。

        中文文案通常无需,但用户文案可能含 () . * 等。
        """
        return re.sub(r"([/\\^$.*+?()\[\]{}|])", r"\\\1", s)

    @classmethod
    def _rewrite_text_nth_anti_pattern(cls, content: str) -> str:
        """把 page.getByText('X').nth(N) 改写成 class + hasText 全字正则联合。

        Why:
          codegen 默认录 getByText("X").nth(N) —— 索引随排序漂移,跨环境必翻车。
          prompt 里已加优先级 2.5 强约束,但 deepseek 不一定遵守,LLM 软约束不可靠。
          这里用确定性正则做最后一道安全网,跟 _ensure_canonical_goto 同款思路:
          无论 LLM 路径还是 fallback 路径,最终入库的脚本不含此 anti-pattern。

        默认改写目标:ant-select 下拉选项内容容器 `.ant-select-item-option-content`。
        ant-cascader / ant-tree-select 等其他容器需用户手动微调,但起码不会再因索引漂移失败。
        相关记忆:feedback_dropdown_class_hastext_over_nth
        """

        def _replace(m: re.Match) -> str:
            text = m.group("text")
            text_re = cls._escape_js_regex_literal(text)
            return (
                f"page.locator('.ant-select-item-option-content')"
                f".filter({{ hasText: /^{text_re}$/ }}).first()"
            )

        return cls._TEXT_NTH_PATTERN.sub(_replace, content)

    @classmethod
    def _rewrite_copy_timestamp_pattern(cls, content: str) -> str:
        """把 codegen 录到的 name 带时间戳的 getByRole 精确匹配改写为 hasText 包含匹配。

        Why:
          业务里"复制"一份资源时，默认命名通常是 `<原名>_copy_YYYYMMDDHHMMSS`，
          codegen 录制时 name 会带上这个时间戳，name 后面往往还跟着 IP/主机名/编号等动态内容。
          精确 name 匹配 → 下次运行时间戳不同 → 定位失败超时。

          规则：提取到 `_copy_` 为止的稳定前缀，改写为 `hasText` 包含匹配 + `.first()` 兜底
          多行同名场景。

        改写示例：
            getByRole('row', { name: '策略中心-进程白名单_copy_20260701104912 5 默认 ...' })
              → getByRole('row').filter({ hasText: '策略中心-进程白名单_copy_' }).first()
        """

        def _replace(m: re.Match) -> str:
            role = m.group("role")
            stable_prefix = m.group("prefix")
            # JS 单引号字符串转义（原文里出现的 \ 和 ' 都要处理，
            # 中文/常见符号不受影响，防止 prefix 里出现 ' 破坏语法）
            escaped = stable_prefix.replace("\\", "\\\\").replace("'", "\\'")
            return f"getByRole('{role}').filter({{ hasText: '{escaped}' }}).first()"

        return cls._COPY_TIMESTAMP_NAME_PATTERN.sub(_replace, content)

    @classmethod
    def _rewrite_search_click_to_press_enter(cls, content: str) -> str:
        """把搜索按钮的 click 改写为最近一次 fill 定位到的输入框上的 press('Enter')。

        Why:
          codegen 默认录 `fill(...)` + `getByRole('button', { name: '搜索' }).click()`，
          但 ant-design 搜索按钮的 click 在数据量大 / 网络慢时经常超时（disabled 态、加载 spinner 覆盖等）。
          业务侧统一约定 —— 搜索/筛选一律用回车提交，等价语义 + 更稳。
          相关约定：feedback_search_prefer_enter

        改写策略：
          - 逐行扫描
          - 遇到 `await <SEL>.fill(...)` 记住 <SEL>
          - 遇到"搜索按钮 click"行 → 改写为 `await <记忆的 SEL>.press('Enter')`
          - 没有找到前置 fill 的 → 保留原样（避免误改）

        识别范围（`_SEARCH_BUTTON_CLICK_PATTERN`）：
          - `getByRole('button', { name: '搜索'|'查询'|'检索'|'Search' })`
          - `.ant-input-search-button` / `.search-btn`

        为什么不涉及 getByText('搜索')？
          - 页面里 "搜索" 二字可能是菜单/图标 tooltip/占位文字，误伤面大
          - 如果 codegen 录出这种，交给 LLM prompt 里的优先级 2.5 铁律去改
        """
        lines = content.splitlines(keepends=True)
        last_fill_selector: Optional[str] = None
        for i, line in enumerate(lines):
            fill_match = cls._FILL_SELECTOR_PATTERN.search(line)
            if fill_match:
                last_fill_selector = fill_match.group("sel").strip()
                continue

            if cls._SEARCH_BUTTON_CLICK_PATTERN.search(line) and last_fill_selector:
                indent_match = re.match(r"^\s*", line)
                indent = indent_match.group() if indent_match else ""
                # 保留原行末尾的换行符
                newline = "\n" if line.endswith("\n") else ""
                lines[i] = f"{indent}await {last_fill_selector}.press('Enter');{newline}"

        return "".join(lines)

    @classmethod
    def _rewrite_table_checkbox_to_xpath(cls, content: str) -> str:
        """把 ant-table 行内复选框的深层 CSS 定位改写为业务文案的 xpath 定位。

        Why:
          codegen 录制表格勾选时会产出类似：
            page.locator('.ant-table-row.GreyRowColor > .ant-table-cell.ant-table-selection-column
                         > .ant-checkbox-wrapper > .ant-checkbox > .ant-checkbox-inner').click()
          这种链式 CSS 有两个致命问题：
            1. 含状态 class（`.GreyRowColor` / hover 类），行状态一变就命中不到
            2. 不含业务信息，跨环境/数据变化必翻车

          业务侧稳定写法是"用行内业务文案锚定，找该行的复选框"：
            page.locator("xpath=//tr[.//text()[contains(., '业务名')]]//input[@type='checkbox']").check()

        改写策略（逐行扫描 + 上下文回溯）：
          - 记忆最近的业务文案（来自 fill/getByText/hasText/getByRole name）
          - 匹配到表格 checkbox click 时，用最近记忆的业务文案组装 xpath
          - **找不到业务文案 → 保留原样**（不做启发式猜测，避免误改）
          - .click() 和 .check() 都改写为 .check()（复选框语义更明确）
        """
        lines = content.splitlines(keepends=True)
        last_biz_text: Optional[str] = None

        for i, line in enumerate(lines):
            # 先尝试识别为表格 checkbox click（可能这一行既是 click 又提到文本，先判 click）
            table_match = cls._TABLE_CHECKBOX_CLICK_PATTERN.search(line)
            if table_match and last_biz_text:
                indent_match = re.match(r"^\s*", line)
                indent = indent_match.group() if indent_match else ""
                newline = "\n" if line.endswith("\n") else ""

                # 组装 xpath：转义单引号（业务文案里出现 ' 概率极低，兜底处理）
                escaped_text = last_biz_text.replace("\\", "\\\\").replace("'", "\\'")
                # 用双引号包 JS 字符串，xpath 内层用单引号，避免转义混乱
                xpath = (
                    f"xpath=//tr[.//text()[contains(., '{escaped_text}')]]"
                    f"//input[@type=\"checkbox\"]"
                )
                lines[i] = (
                    f"{indent}await page.locator(\"{xpath}\").check();{newline}"
                )
                continue

            # 非 click 行，尝试记忆业务文案
            biz_match = cls._BIZ_TEXT_CAPTURE_PATTERN.search(line)
            if biz_match:
                # 取第一个非空的捕获组作为业务文案
                for key in ("txt1", "txt2", "txt3", "txt4", "txt5", "txt6"):
                    val = biz_match.group(key)
                    if val:
                        last_biz_text = val.strip()
                        break

        return "".join(lines)

    # 检测 test 体内是否已经存在 expect(...) 调用
    # 注释里出现 "expect" 字样不算 —— 我们要求真实调用,所以匹配带 `(` 的形态
    _HAS_EXPECT_PATTERN = re.compile(r"\bexpect\s*\(")

    @classmethod
    def _ensure_trailing_assertion(cls, content: str) -> str:
        """Deterministic 兜底:test 体内若无任何 expect() 调用,在最后一个 }); 之前注入通用断言。

        Why:
          prompt 第 9 条 + 硬禁令 F 段都明确要求"末尾必须有终态断言",但 DeepSeek-V4-pro
          在长 prompt 下选择性合规,实测 2026-06-18 录制的两条脚本仍然裸 click 收尾。
          没断言的 Playwright 用例报告全绿,但实际可能点错按钮、点没生效都看不出来——
          属于 feedback_ui_script_must_have_assertion 明确的"假新闻级别"反模式。
          这里用确定性兜底确保磁盘上不存在零断言脚本(LLM 路径 + fallback 路径都过这一层)。

        策略:
          1. 已经有任意 `expect(` 调用 → 不动
          2. 没有 → 在最后一个 `});` 前注入消息提示通用断言,并带 ⚠️ 注释明确标注为兜底,
             方便人工 review 时识别并改写为业务断言。

        timeout 用 3s 而不是 5s/10s:兜底断言不该慢慢拖,失败要快暴露出来让用户去补真断言。
        """
        if cls._HAS_EXPECT_PATTERN.search(content):
            return content

        # 找最后一个 });  —— 它是 test() 块的收尾
        # rfind 而不是正则:行末可能跟 ; 或注释,但 `});` 三字符序列足够定位
        last_close = content.rfind("});")
        if last_close < 0:
            # 没有 test 收尾 —— 文件可能已经损坏,不强行注入
            return content

        # 注入的断言块。缩进对齐 2 空格(与现有 test 体内缩进一致)
        indent = "  "
        assertion_block = (
            f"\n{indent}// ⚠️ LLM 未生成业务断言,本条为 deterministic 兜底通用断言;\n"
            f"{indent}// 如失败请手动改为业务断言(如表格行内容 / 详情页字段 / 跳转后页面标题等)\n"
            f"{indent}await expect(\n"
            f"{indent}  page.locator('.ant-message, .ant-notification, .ant-modal-confirm, .el-message').first()\n"
            f"{indent}).toBeVisible({{ timeout: 3000 }});\n"
        )

        return content[:last_close] + assertion_block + content[last_close:]

    # ==================================================================
    # 降级模板(LLM 失败时把录制原文包成最小可跑结构)
    # ==================================================================

    @staticmethod
    def _fallback_wrap(raw_script: str, name: str, script_style: str = "playwright", target_url: str = "") -> str:
        """最小侵入降级:仅替换 import 头,test 块体原样保留。

        这样用户至少拿得到一个能跑(假设录制时元素选择器都能用)的脚本,
        他们可以自己再走"AI 修复"或手动改裸 selector → ai*。

        script_style:
          - playwright → 顶部注入 `import { test, expect } from "@playwright/test"`(默认,推荐)
          - midscene  → 顶部注入 `import { test } from "./fixture"`(MidScene fixture)
        """
        style = (script_style or "playwright").strip().lower()
        # 把所有 @playwright/test 和 ./fixture 的 import 全部清掉,后面 header 统一重写
        lines = raw_script.splitlines()
        if style == "playwright":
            out_lines = [
                'import { test, expect } from "@playwright/test";',
            ]
        else:
            out_lines = [
                'import { expect } from "@playwright/test";',
                'import { test } from "./fixture";',
            ]
        body_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import") and (
                "@playwright/test" in stripped or "./fixture" in stripped
            ):
                continue
            body_lines.append(line)

        # 把 test('xxx', ... 的标题统一改成用户填的中文 name(只替第一处)
        body_text = "\n".join(body_lines).lstrip()
        replaced = False

        def _replace_first_test_title(match: re.Match) -> str:
            nonlocal replaced
            if replaced:
                return match.group(0)
            replaced = True
            safe_name = name.replace('"', '\\"')
            return f'test("{safe_name}",'

        body_text = re.sub(
            r"test\(\s*['\"][^'\"]*['\"]\s*,",
            _replace_first_test_title,
            body_text,
            count=1,
        )

        # 兜底 1:剥离 test.use({...}) 块(LLM 路径绕过来,fallback 路径也要做)
        body_text = UiRecordingOrchestratorAgent._strip_test_use_block(body_text)

        # 兜底 2+3 合并:删冗余 https goto + 补标准 page.goto(landing) 首句,
        # landing 由 target_url 解析(无路径走 "/",带子路径就跟过去)
        body_text = UiRecordingOrchestratorAgent._ensure_canonical_goto(body_text, target_url)

        # 兜底 4:fallback 路径也要净化 getByText().nth(N) anti-pattern
        body_text = UiRecordingOrchestratorAgent._rewrite_text_nth_anti_pattern(body_text)

        # 兜底 4.5:fallback 路径同样识别 copy 时间戳并改写为 hasText 匹配
        body_text = UiRecordingOrchestratorAgent._rewrite_copy_timestamp_pattern(body_text)

        # 兜底 4.6:fallback 路径同样处理搜索按钮 click → press('Enter')
        body_text = UiRecordingOrchestratorAgent._rewrite_search_click_to_press_enter(body_text)

        # 兜底 4.7:fallback 路径同样把表格 checkbox 深层 CSS → xpath 业务定位
        body_text = UiRecordingOrchestratorAgent._rewrite_table_checkbox_to_xpath(body_text)

        # 兜底 5:fallback 路径同样必须保证有 expect 断言(LLM 都失败了,原始 codegen 更不可能带)
        body_text = UiRecordingOrchestratorAgent._ensure_trailing_assertion(body_text)

        return "\n".join(out_lines) + "\n\n" + body_text + "\n"

    # ==================================================================
    # 统一的"page.goto 规范化"
    # ==================================================================

    @staticmethod
    def _resolve_landing_path(target_url: str) -> str:
        """从录制 target_url 解析出 page.goto 应该用的相对路径。

        规则(对齐用户口语):
          - 只有 IP / 主机(无路径或路径仅 "/") → 返回 "/"
          - 带具体子路径 → 返回 "/path?query#hash" 形态(保留 query/hash,
            录制时填的 ?tab=xxx 也得跟过去)
          - 非法/空 → 返回 "/"

        why 不直接 goto 完整 URL: playwright.config.ts 已把 baseURL 设为
        UI_BASE_URL,page.goto("/sub") 会自动拼成 origin + 相对路径,
        切环境只需要改 .env / 脚本的 base_url,不用动脚本体。
        """
        if not target_url:
            return "/"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(target_url.strip())
        except Exception:
            return "/"
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        # 保留 query / fragment
        if parsed.query:
            path += f"?{parsed.query}"
        if parsed.fragment:
            path += f"#{parsed.fragment}"
        return path or "/"

    @staticmethod
    def _ensure_canonical_goto(body_text: str, target_url: str = "") -> str:
        """规范化 test 体内的 page.goto:
        1. 删掉所有 `page.goto("http(s)://...")` 整行 —— 这些是 codegen 录到的浏览器自动跳转
           或 SPA 路由产物,执行时会被 storageState + click 触发的真实 navigation 自动重现,
           显式 goto 反而会绕开登录态重定向。
        2. 如果 test 体内首句已经是 `page.goto("<landing>", ...)` (LLM 听话了),直接返回不重复插入。
        3. 否则在 `test("xxx", async ({ page }) => {` 之后注入标准首句,landing 由 target_url 决定:
           - target_url 仅域名/IP → page.goto("/")
           - target_url 带子路径 → page.goto("/asset/network")

        Why: 漏了首句 goto,浏览器停在 about:blank,所有后续操作 30s 超时(失败截图
        看起来像"白屏",其实是空白起始页)。这是最常见的录制脚本翻车点。
        修复历史:旧实现的注入正则 `test\([^)]*\)\s*,\s*async...` 在
        `test("xxx", async ({ page }) => {` 上无法匹配 —— `[^)]*` 贪婪吃过头到
        `({ page })` 的第一个 `)`,后续期望 `,` 但实际是 `=>`,导致兜底完全没生效。
        """
        # 0. 计算落地路径(默认 "/",有子路径就跟用户输入的 target_url)
        landing = UiRecordingOrchestratorAgent._resolve_landing_path(target_url)

        # 1. 删冗余 https goto
        cleaned_lines = []
        for line in body_text.splitlines():
            if re.search(r"page\.goto\(\s*['\"]https?://", line):
                continue
            cleaned_lines.append(line)
        body_text = "\n".join(cleaned_lines)

        # 2. 幂等检查:test 体内前 400 字符任一处已有 page.goto("<任意路径>" 就跳过
        #    (LLM 自己写过 / 之前已经注入过,不重复插)
        test_match = re.search(
            r"test\(\s*['\"][^'\"]*['\"]\s*,\s*async\s*\(\s*\{[^}]*\}\s*\)\s*=>\s*\{",
            body_text,
        )
        if test_match:
            head = body_text[test_match.end(): test_match.end() + 400]
            if re.search(r"page\.goto\(\s*['\"][^'\"]+['\"]", head):
                return body_text

        # 3. 注入标准首句(修复后的正则:明确匹配标题字符串 + async ({...}) => {)
        # 注意:替换串用普通字符串(不是 raw)。raw string 里 `\"` 是两个字符
        # `\` + `"`,而 re.sub 替换语义里 `\"` 不是特殊序列,会原样写入,导致文件出现
        # `await page.goto(\"/\", ...)` 这种字面反斜杠 —— TS 解析器直接 No tests found。
        # 同时 landing 里可能含正则元字符 / 反斜杠,统一通过 \g<1> 引用 + 拼接,不走 \1 占位
        replacement = (
            "\\g<1>\n"
            f'  await page.goto("{landing}", {{ waitUntil: "domcontentloaded" }});\n'
            "  await page.waitForTimeout(1000);"
        )
        body_text = re.sub(
            r"(test\(\s*['\"][^'\"]*['\"]\s*,\s*async\s*\(\s*\{[^}]*\}\s*\)\s*=>\s*\{)",
            replacement,
            body_text,
            count=1,
        )
        return body_text

    # ==================================================================
    # 失败状态机更新
    # ==================================================================

    async def _mark_failed(
        self,
        session_id: str,
        error_message: str,
        *,
        raw_script_path: str = "",
        duration_ms: int = 0,
    ) -> None:
        try:
            payload: Dict[str, Any] = {
                "status": "failed",
                "error_message": error_message[:500],
            }
            if raw_script_path:
                payload["raw_script_path"] = raw_script_path
            if duration_ms:
                payload["duration_ms"] = duration_ms
            await UiRecordingSession.filter(session_id=session_id).update(**payload)
        except Exception as e:
            logger.warning(f"[recording {session_id}] mark_failed 落库失败: {e}")

    # ==================================================================
    # 录制前可选预抓 page_dict(crawl4ai)
    # ==================================================================

    async def _maybe_prefetch_page_dict(
        self,
        *,
        session_id: str,
        target_url: str,
        storage_state_relpath: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """录制启动前用 crawl4ai 抓一次 DOM,产出 page_dict 给后续 LLM 后处理用。

        失败路径(均返回 None,不阻塞录制):
          - crawl4ai 未安装 / lazy import 失败
          - 抓取超时 / 网络异常
          - storage_state 文件不存在(直接以未登录态抓)

        成功路径:
          - 写入 UiRecordingSession.metadata.page_dict(供 repolish 时复用)
          - 返回 dict 给 _do_postprocess 透传到 _llm_polish
        """
        from app.services.ui_automation import crawl4ai_service

        if not target_url or not target_url.strip():
            return None

        storage_state_abs: Optional[str] = None
        if storage_state_relpath:
            workspace = getattr(settings, "UI_AUTOMATION_WORKSPACE", "")
            if workspace:
                candidate = Path(workspace) / storage_state_relpath
                if candidate.is_file():
                    storage_state_abs = str(candidate)
                else:
                    logger.warning(
                        f"[recording {session_id}] prefetch storage_state 不存在 {candidate},"
                        f"将以未登录态抓取"
                    )

        await self._send_message(
            f"正在用 crawl4ai 预抓页面语义({target_url})...",
            message_type="info",
            region=MessageRegion.PROCESS,
        )

        try:
            page_dict = await crawl4ai_service.prefetch_page_dict(
                url=target_url,
                storage_state_path=storage_state_abs,
                timeout=getattr(settings, "UI_CRAWL4AI_TIMEOUT", 60),
                persist_dir=getattr(settings, "UI_CRAWL4AI_PAGE_DICT_DIR", None),
                session_id=session_id,
            )
        except Exception as e:
            logger.warning(f"[recording {session_id}] prefetch 异常,忽略: {e}")
            await self._send_message(
                f"⚠ 预抓页面语义失败,降级为不带 page_dict 录制: {type(e).__name__}: {str(e)[:200]}",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return None

        if not page_dict:
            await self._send_message(
                "⚠ 预抓页面语义失败(crawl4ai 不可用或抓取超时),将以无 page_dict 模式继续录制",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return None

        # 登录态判定:被重定向到登录页 → 拿到的元素是登录页元素,对录制后处理有害,直接丢弃
        if page_dict.get("login_required"):
            final_url = page_dict.get("final_url") or ""
            await self._send_message(
                f"⚠ 预抓被重定向到登录页({final_url}),storage_state 未生效。"
                f"已丢弃预抓结果,继续以无 page_dict 模式录制(建议先刷新登录态)",
                message_type="warning",
                region=MessageRegion.WARNING,
            )
            return None

        elements_count = len(page_dict.get("elements") or [])
        file_path = page_dict.get("file_path") or ""
        await self._send_message(
            f"预抓完成:识别 {elements_count} 个 DOM 元素"
            + (f",已落盘 {file_path}" if file_path else ""),
            message_type="success",
            region=MessageRegion.SUCCESS,
        )

        # 写入 session.metadata.page_dict,供 repolish 复用
        # NOTE: 只存 elements + page_title 这种纯字典,不存 file_path 之外的大字段
        try:
            existing = await UiRecordingSession.filter(session_id=session_id).first()
            base_metadata: Dict[str, Any] = {}
            if existing and isinstance(existing.metadata, dict):
                base_metadata = dict(existing.metadata)
            base_metadata["page_dict"] = {
                "page_title": page_dict.get("page_title", ""),
                "elements": page_dict.get("elements") or [],
                "file_path": file_path,
            }
            await UiRecordingSession.filter(session_id=session_id).update(
                metadata=base_metadata
            )
        except Exception as e:
            logger.warning(f"[recording {session_id}] 写 metadata.page_dict 失败,忽略: {e}")

        return page_dict

    # ==================================================================
    # DONE 消息(供前端订阅 SSE 时识别终态)
    # ==================================================================

    async def _publish_done(
        self,
        *,
        session_id: str,
        status: str,
        raw_script_path: str = "",
        final_script_id: str = "",
        final_script_path: str = "",
        duration_ms: int = 0,
        error_message: str = "",
    ) -> None:
        done = RecordingDoneMessage(
            session_id=session_id,
            status=status,
            raw_script_path=raw_script_path,
            final_script_id=final_script_id,
            final_script_path=final_script_path,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        # 录制流程没有独立的 persistence agent,直接复用 _send_message 把 result 带过去,
        # 前端订阅 SSE 看 is_final + result.status 即可识别终态。
        await self._send_message(
            content=f"录制流程结束: status={status}",
            message_type="success" if status == "ready" else "warning",
            region=MessageRegion.SUCCESS if status == "ready" else MessageRegion.WARNING,
            is_final=True,
            result=done.model_dump(),
        )


__all__ = ["UiRecordingOrchestratorAgent"]
