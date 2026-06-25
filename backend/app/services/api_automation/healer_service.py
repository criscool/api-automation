"""
HealerService - 交互式诊断 + 修复闭环的核心编排服务

Phase 1（诊断）：只读 + 不落盘
- 读 DB（TestScript / ScriptExecutionResult / TestCase）
- 读 Allure 结果目录
- 调用 TestAnalysisAgent / TestHealerAgent
- 返回 diff 与诊断报告（不写脚本文件、不写 DB）

Phase 2（应用 + 验证）：apply_patch
- 备份 TestScript.content → content_backup
- 替换方法体（TestHealerAgent._replace_method_in_source）
- 写回 DB.content + 落盘
- 触发 pytest 重跑该单条 nodeid
- PASS：标记 VERIFIED_PASS；FAIL：回滚 content，标记 ROLLED_BACK，熔断计数 +1

会话状态保存在进程内存中，30 分钟过期。
"""
import ast
import asyncio
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

from loguru import logger

from app.agents.factory import agent_factory, AgentPlatform
from app.core.types import AgentTypes
from app.services.api_automation.healer_evidence import (
    collect_evidence,
    FailureEvidence,
)


_SESSION_TTL_SECONDS = 30 * 60
_STREAM_QUEUE_MAX = 128
_DIAGNOSE_TIMEOUT = 360
_HEAL_CIRCUIT_LIMIT = 3  # 连续失败次数熔断阈值
_RERUN_TIMEOUT = 180


class HealerSession:
    """单次诊断会话的运行时状态"""

    def __init__(self, session_id: str, script_id: str, test_case_id: Optional[str]):
        self.session_id = session_id
        self.script_id = script_id
        self.test_case_id = test_case_id
        self.created_at = time.time()
        self.finished_at: Optional[float] = None
        self.status: str = "PENDING"  # PENDING / RUNNING / DONE / ERROR
        self.error: Optional[str] = None
        self.result: Dict[str, Any] = {}
        self.events: asyncio.Queue = asyncio.Queue(maxsize=_STREAM_QUEUE_MAX)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "script_id": self.script_id,
            "test_case_id": self.test_case_id,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class HealerService:
    """Phase 1 诊断服务（单例，进程内）"""

    def __init__(self):
        self._sessions: Dict[str, HealerSession] = {}
        self._lock = asyncio.Lock()

    async def diagnose_async(
        self,
        script_id: str,
        test_case_id: Optional[str] = None,
    ) -> HealerSession:
        """
        启动一次诊断（不阻塞返回 session_id）。
        实际诊断任务在后台 asyncio.Task 中跑，进度通过 session.events 推送。
        """
        session_id = str(uuid.uuid4())
        session = HealerSession(session_id, script_id, test_case_id)
        async with self._lock:
            self._sessions[session_id] = session
            self._cleanup_expired_locked()

        asyncio.create_task(self._run_session(session))
        return session

    async def get_session(self, session_id: str) -> Optional[HealerSession]:
        return self._sessions.get(session_id)

    async def stream_events(self, session_id: str) -> AsyncIterator[Dict[str, Any]]:
        """
        SSE 事件流：异步消费 session.events 队列。
        若 session 已结束且队列已空，立刻退出。
        """
        session = self._sessions.get(session_id)
        if not session:
            yield {"event": "error", "data": {"message": "session not found"}}
            return

        yield {
            "event": "diag.connected",
            "data": {"session_id": session_id, "status": session.status},
        }

        while True:
            if session.status in ("DONE", "ERROR") and session.events.empty():
                yield {
                    "event": "diag.closed",
                    "data": {"status": session.status, "error": session.error},
                }
                return

            try:
                evt = await asyncio.wait_for(session.events.get(), timeout=2.0)
                yield evt
                if evt.get("event") in ("heal.done", "diag.error"):
                    return
            except asyncio.TimeoutError:
                yield {"event": "diag.heartbeat", "data": {"ts": time.time()}}

    # ---------- 内部 ----------

    async def _run_session(self, session: HealerSession) -> None:
        try:
            await asyncio.wait_for(self._do_diagnose(session), timeout=_DIAGNOSE_TIMEOUT)
        except asyncio.TimeoutError:
            session.status = "ERROR"
            session.error = f"诊断超时（{_DIAGNOSE_TIMEOUT}秒）"
            await self._push(session, "diag.error", {"message": session.error})
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"诊断会话异常 {session.session_id}: {e}\n{tb}")
            session.status = "ERROR"
            session.error = f"{e}\n--- traceback ---\n{tb[-1500:]}"
            await self._push(session, "diag.error", {"message": session.error})
        finally:
            session.finished_at = time.time()

    async def _do_diagnose(self, session: HealerSession) -> None:
        session.status = "RUNNING"
        await self._push(session, "diag.started", {"session_id": session.session_id})

        stage_started = time.time()
        # 1. 提取证据
        await self._push(session, "diag.evidence_collecting", {})
        evidence: FailureEvidence = await collect_evidence(
            session.script_id, session.test_case_id
        )
        evidence_elapsed = time.time() - stage_started
        if not evidence.get("script_content"):
            raise RuntimeError(f"找不到脚本 {session.script_id} 或内容为空")
        await self._push(
            session,
            "diag.evidence_collected",
            {
                "has_useful_signal": evidence.has_useful_signal,
                "has_allure": bool(evidence.get("allure_attachments")),
                "test_case_name": (evidence.get("test_case") or {}).get("name", ""),
                "elapsed_sec": round(evidence_elapsed, 1),
            },
        )
        logger.info(f"诊断阶段[evidence] session={session.session_id} 耗时 {evidence_elapsed:.1f}s")

        # 2. 分析
        await self._push(session, "diag.analyzing", {})
        stage_started = time.time()

        # 硬编码预处理：Java 反序列化 Null → 直接判 SCRIPT_FIX，跳过 LLM
        error_text = "\n".join(filter(None, [
            evidence.get("stdout_tail", ""),
            evidence.get("stderr_tail", ""),
            evidence.get("error_message", ""),
            evidence.get("failure_snippet", ""),
        ]))
        if "cannot construct instance" in error_text.lower() and "null" in error_text.lower():
            analysis_result = {
                "verdict": "SCRIPT_FIX",
                "confidence": 0.95,
                "summary": f"Java 反序列化报 Null 字段缺失: {error_text[:200]}",
                "report_md": f"## 诊断报告\n\n### 失败现象\nJava 后端反序列化请求体时发现必填字段为 null。\n\n### 根本原因\n测试脚本的 payload 缺少一个或多个必填字段。\n\n### 错误信息\n```\n{error_text[:500]}\n```\n\n### 修复方向\n补全 payload 中所有必填字段。",
                "evidence": [{"source": "response_body", "quote": error_text[:300]}],
                "matched_patterns": ["strategy_add_required_fields"],
                "from_fallback": True,
            }
        else:
            analysis_agent = await agent_factory.create_agent(
                AgentTypes.TEST_ANALYSIS.value,
                platform=AgentPlatform.API_AUTOMATION,
            )
            analysis_result = await analysis_agent.analyze(evidence, stream=False)
        analyze_elapsed = time.time() - stage_started
        logger.info(f"诊断阶段[analyze] session={session.session_id} 耗时 {analyze_elapsed:.1f}s verdict={analysis_result.get('verdict')}")
        await self._push(
            session,
            "diag.verdict",
            {
                "verdict": analysis_result.get("verdict"),
                "confidence": analysis_result.get("confidence"),
                "summary": analysis_result.get("summary"),
                "from_fallback": analysis_result.get("from_fallback", False),
                "elapsed_sec": round(analyze_elapsed, 1),
            },
        )

        verdict = analysis_result.get("verdict", "UNCERTAIN")
        patch_result: Dict[str, Any] = {}

        # 3. 仅 SCRIPT_FIX 才生成补丁
        if verdict == "SCRIPT_FIX":
            await self._push(session, "heal.proposing_patch", {})
            stage_started = time.time()
            healer_agent = await agent_factory.create_agent(
                AgentTypes.TEST_HEALER.value,
                platform=AgentPlatform.API_AUTOMATION,
            )
            patch_result = await healer_agent.propose_patch(
                evidence, analysis_result, stream=False
            )
            patch_elapsed = time.time() - stage_started
            logger.info(
                f"诊断阶段[propose_patch] session={session.session_id} 耗时 {patch_elapsed:.1f}s "
                f"has_patch={bool(patch_result.get('patch'))} fallback={patch_result.get('from_fallback', False)}"
            )
            await self._push(
                session,
                "heal.patch_ready",
                {
                    "has_patch": bool(patch_result.get("patch")),
                    "fixed_method": patch_result.get("fixed_method"),
                    "risk_tags": patch_result.get("risk_tags", []),
                    "from_fallback": patch_result.get("from_fallback", False),
                    "elapsed_sec": round(patch_elapsed, 1),
                },
            )

        session.result = {
            "verdict": verdict,
            "analysis": analysis_result,
            "patch": patch_result,
            "evidence_summary": {
                "test_case": evidence.get("test_case"),
                "script_path": evidence.get("script_path"),
                "has_useful_signal": evidence.has_useful_signal,
            },
        }
        session.status = "DONE"
        await self._push(session, "heal.done", {"verdict": verdict})

    async def _push(self, session: HealerSession, event: str, data: Dict[str, Any]) -> None:
        try:
            await session.events.put({"event": event, "data": data})
        except Exception as e:
            logger.warning(f"推送事件失败 {event}: {e}")

    def _cleanup_expired_locked(self) -> None:
        """调用方持有 _lock"""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if s.finished_at and (now - s.finished_at) > _SESSION_TTL_SECONDS
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

    # ---------- Phase 2：应用补丁 + 重跑验证 ----------

    async def apply_patch(
        self,
        session_id: str,
        rerun: bool = True,
        environment: str = "test",
    ) -> Dict[str, Any]:
        """应用诊断会话的补丁到目标脚本：
        1. 校验 session DONE + verdict=SCRIPT_FIX + 有 fixed_method/fixed_method_code
        2. 熔断检查（heal_failed_count >= 3 拒绝）
        3. 备份当前 content → content_backup
        4. 用 TestHealerAgent._replace_method_in_source 替换方法
        5. 写回 DB + 落盘
        6. rerun=True 时跑 pytest（仅该方法 nodeid），按结果决定 VERIFIED_PASS 或回滚

        返回 dict：{status, applied, verified, passed, failed, message, log_tail, heal_failed_count}
        """
        from datetime import datetime
        from app.models.api_automation import TestScript

        session = self._sessions.get(session_id)
        if not session:
            raise RuntimeError(f"诊断会话不存在或已过期: {session_id}")
        if session.status != "DONE":
            raise RuntimeError(f"诊断会话尚未完成: status={session.status}")
        if (session.result or {}).get("verdict") != "SCRIPT_FIX":
            raise RuntimeError("仅 verdict=SCRIPT_FIX 的会话允许应用补丁")

        patch = (session.result or {}).get("patch") or {}
        fixed_method = patch.get("fixed_method") or ""
        fixed_method_code = patch.get("fixed_method_code") or ""
        if not fixed_method or not fixed_method_code:
            raise RuntimeError("诊断结果未给出可应用的方法补丁（fixed_method/fixed_method_code）")

        script = await TestScript.filter(script_id=session.script_id).select_related("document").first()
        if not script:
            raise RuntimeError(f"找不到脚本 {session.script_id}")

        # 熔断
        if (script.heal_failed_count or 0) >= _HEAL_CIRCUIT_LIMIT:
            return {
                "status": "CIRCUIT_OPEN",
                "applied": False,
                "verified": False,
                "passed": 0,
                "failed": 0,
                "message": f"该脚本累计连续修复失败 {script.heal_failed_count} 次，已达熔断阈值 {_HEAL_CIRCUIT_LIMIT}，请人工介入",
                "heal_failed_count": script.heal_failed_count,
            }

        from app.agents.api_automation.test_healer_agent import TestHealerAgent
        original_content = script.content or ""
        new_content = TestHealerAgent._replace_method_in_source(
            original_content, fixed_method, fixed_method_code
        )
        if not new_content or new_content == original_content:
            raise RuntimeError(f"补丁应用失败：在脚本中未能定位方法 {fixed_method}（或新内容与原内容一致）")

        # 预校验：AI 生成的方法体可能有语法错误，先 ast.parse 一次，避免落盘 + 跑 pytest 才发现
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            script.heal_failed_count = (script.heal_failed_count or 0) + 1
            script.heal_attempts = (script.heal_attempts or 0) + 1
            script.last_heal_at = datetime.now()
            script.last_heal_session_id = session_id
            script.last_heal_status = "PATCH_INVALID"
            await script.save()
            logger.warning(
                f"AI 补丁语法校验失败 session={session_id} script={script.script_id} "
                f"err={e} failed_count={script.heal_failed_count}"
            )
            return {
                "status": "PATCH_INVALID",
                "applied": False,
                "verified": False,
                "passed": 0,
                "failed": 0,
                "message": f"AI 生成的补丁存在语法错误（{e.msg} @ line {e.lineno}），已拒绝应用。建议重新诊断或人工修改。",
                "heal_failed_count": script.heal_failed_count,
            }

        # 备份 + 写回 DB
        script.content_backup = original_content
        script.content = new_content
        script.heal_attempts = (script.heal_attempts or 0) + 1
        script.last_heal_at = datetime.now()
        script.last_heal_session_id = session_id
        script.last_heal_status = "APPLIED"
        await script.save()

        # 落盘
        backend_dir = Path(__file__).resolve().parents[3]
        generated_tests_dir = backend_dir / "generated_tests"
        script_file = generated_tests_dir / (script.file_path or script.file_name)
        try:
            script_file.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text(new_content, encoding="utf-8")
        except Exception as e:
            logger.error(f"写入脚本文件失败 {script_file}: {e}")
            raise RuntimeError(f"写入脚本文件失败: {e}")

        result: Dict[str, Any] = {
            "status": "APPLIED",
            "applied": True,
            "verified": False,
            "passed": 0,
            "failed": 0,
            "message": "补丁已应用到脚本（未重跑验证）",
            "heal_failed_count": script.heal_failed_count or 0,
        }

        if not rerun:
            return result

        # 触发 pytest 重跑（仅该方法 nodeid）
        try:
            rerun_result = await self._rerun_single_test(
                script=script,
                session=session,
                env_name=environment,
                generated_tests_dir=generated_tests_dir,
                backend_dir=backend_dir,
            )
        except Exception as e:
            logger.error(f"应用补丁后重跑异常 session={session_id}: {e}", exc_info=True)
            # 重跑过程异常：保守起见执行回滚
            await self._rollback(script, original_content, script_file, session_id, reason=f"重跑异常: {e}")
            result.update({
                "status": "RERUN_ERROR",
                "verified": False,
                "message": f"重跑异常已回滚: {e}",
                "heal_failed_count": script.heal_failed_count,
            })
            return result

        passed = rerun_result.get("passed", 0)
        failed = rerun_result.get("failed", 0) + rerun_result.get("errors", 0)
        log_tail = (rerun_result.get("stdout") or "")[-2000:]

        if passed > 0 and failed == 0:
            # 验证通过
            script.last_heal_status = "VERIFIED_PASS"
            script.heal_failed_count = 0
            await script.save()
            result.update({
                "status": "VERIFIED_PASS",
                "verified": True,
                "passed": passed,
                "failed": failed,
                "message": "补丁应用并验证通过",
                "log_tail": log_tail,
                "heal_failed_count": 0,
            })
        else:
            # 验证失败：回滚
            await self._rollback(
                script, original_content, script_file, session_id,
                reason=f"重跑 passed={passed} failed={failed}",
            )
            result.update({
                "status": "ROLLED_BACK",
                "verified": False,
                "applied": False,
                "passed": passed,
                "failed": failed,
                "message": f"补丁应用后重跑失败（passed={passed}, failed={failed}），已自动回滚",
                "log_tail": log_tail,
                "heal_failed_count": script.heal_failed_count,
            })

        return result

    async def _rerun_single_test(
        self,
        script,
        session: "HealerSession",
        env_name: str,
        generated_tests_dir: Path,
        backend_dir: Path,
    ) -> Dict[str, Any]:
        """重跑单条 nodeid（如失败信息齐全）或整个脚本（fallback）"""
        from app.api.v1.endpoints.script_management import _run_pytest_for_one_script

        evidence_summary = (session.result or {}).get("evidence_summary") or {}
        tc = evidence_summary.get("test_case") or {}
        class_name = tc.get("class_name") or ""
        method_name = tc.get("method_name") or ""

        nodeids = []
        if class_name and method_name:
            nodeids = [f"{class_name}::{method_name}"]
        elif method_name:
            nodeids = [method_name]

        script_file_path = script.file_path or script.file_name
        # 单脚本临时执行目录
        rerun_dir = backend_dir / "reports" / f"_heal_{session.session_id[:8]}"
        rerun_dir.mkdir(parents=True, exist_ok=True)

        return await _run_pytest_for_one_script(
            script_file_path=script_file_path,
            script_dir=rerun_dir,
            generated_tests_dir=generated_tests_dir,
            env_name=env_name,
            timeout=_RERUN_TIMEOUT,
            nodeids=nodeids or None,
        )

    async def _rollback(
        self,
        script,
        original_content: str,
        script_file: Path,
        session_id: str,
        reason: str = "",
    ) -> None:
        """回滚 content 与文件，递增熔断计数"""
        try:
            script.content = original_content
            script.heal_failed_count = (script.heal_failed_count or 0) + 1
            script.last_heal_status = "ROLLED_BACK"
            await script.save()
            try:
                script_file.write_text(original_content, encoding="utf-8")
            except Exception as e:
                logger.error(f"回滚文件写入失败 {script_file}: {e}")
            logger.warning(
                f"修复回滚 session={session_id} script={script.script_id} "
                f"failed_count={script.heal_failed_count} reason={reason}"
            )
        except Exception as e:
            logger.error(f"回滚异常 session={session_id}: {e}", exc_info=True)


# 单例
healer_service = HealerService()
