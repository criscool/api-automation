"""
测试失败分析智能体 (TestAnalysisAgent)

职责：根据失败上下文（脚本源码、pytest 输出、Allure 附件、接口文档）
     判定失败原因属于「脚本错误」还是「产品 Bug」，并给出可读的诊断报告。

输入：FailureEvidence（来自 healer_evidence.collect_evidence）
输出：{verdict, confidence, summary, report_md, evidence}

Phase 1 关键约束：
- 只读，绝对不修改任何文件
- LLM 调用失败时降级返回 verdict=UNCERTAIN 的报告
- evidence 字段必须引用证据原文，禁止模型自由发挥编造来源
"""
from typing import Any, Dict, List, Optional

from loguru import logger

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.healer_patterns import (
    KNOWN_ANTIPATTERNS,
    find_matching_patterns,
    render_digest,
)
from app.core.types import AgentTypes
from app.services.api_automation.healer_evidence import (
    FailureEvidence,
    summarize_for_prompt,
)


class TestAnalysisAgent(BaseApiAutomationAgent):
    """测试失败分析智能体"""

    def __init__(self, **kwargs):
        super().__init__(
            agent_type=AgentTypes.TEST_ANALYSIS,
            **kwargs,
        )

    async def analyze(
        self,
        evidence: FailureEvidence,
        interface_doc: Optional[Dict[str, Any]] = None,
        stream: bool = True,
    ) -> Dict[str, Any]:
        """
        核心方法：分析失败原因并出报告

        Returns:
            {
                "verdict": "SCRIPT_FIX" | "PRODUCT_BUG" | "UNCERTAIN",
                "confidence": 0.0-1.0,
                "summary": "一句话结论",
                "report_md": "Markdown 报告全文",
                "evidence": [{"source": "stderr/stdout/doc/script", "quote": "..."}],
                "matched_patterns": ["snake_camel_mix_situation", ...],
                "from_fallback": bool
            }
        """
        try:
            await self._send_message("正在分析失败原因...", "info")

            if not evidence.has_useful_signal:
                logger.warning("evidence 无有效信号，直接走 fallback")
                return self._fallback_report(evidence, reason="没有可用的失败证据")

            matched = find_matching_patterns(
                endpoint_path=self._guess_endpoint(evidence),
                module_hint=self._guess_module(evidence),
                error_text=self._collect_error_text(evidence),
            )

            prompt = self._build_prompt(evidence, interface_doc, matched)
            result_content = await self._run_assistant_agent(prompt, stream=stream)

            if not result_content:
                logger.warning("LLM 返回空内容，使用 fallback 报告")
                return self._fallback_report(evidence, reason="LLM 返回空")

            parsed = self._extract_json_from_content(result_content)
            if not parsed or "verdict" not in parsed:
                logger.warning("LLM 返回格式异常，使用 fallback 报告")
                return self._fallback_report(evidence, reason="LLM 输出格式异常")

            parsed.setdefault("evidence", [])
            parsed.setdefault("matched_patterns", [m["id"] for m in matched])
            parsed.setdefault("from_fallback", False)

            verdict = parsed.get("verdict", "UNCERTAIN")
            await self._send_message(
                f"诊断完成：{verdict} (置信度 {parsed.get('confidence', 0)})",
                "success",
            )
            return parsed

        except Exception as e:
            logger.error(f"分析失败: {e}", exc_info=True)
            return self._fallback_report(evidence, reason=f"分析异常: {e}")

    def _build_prompt(
        self,
        evidence: FailureEvidence,
        interface_doc: Optional[Dict[str, Any]],
        matched: List[Dict[str, str]],
    ) -> str:
        ev_text = summarize_for_prompt(evidence, max_chars=16000)
        patterns_digest = render_digest()

        doc_text = ""
        if interface_doc:
            doc_text = f"\n## 接口文档片段\n```json\n{interface_doc}\n```"

        matched_hint = ""
        if matched:
            matched_hint = "\n## 可能命中的反模式\n" + "\n".join(
                f"- [{m['id']}] {m['rule']}" for m in matched
            )

        return f"""你是一位资深 API 测试架构师，负责诊断 pytest 自动化测试用例的失败原因。

## 你的判定原则
1. **SCRIPT_FIX**: 失败原因可通过修改测试脚本解决（如 payload 字段名错误、断言写法不兼容、缺必填项、**Java 反序列化 `Null <xxx>` 错误**）
2. **PRODUCT_BUG**: 失败原因是后端逻辑/数据问题（如 500 错误、数据库异常、业务规则违反）
3. **UNCERTAIN**: 证据不足以判定

## 重要：保守判定
- 如果不确定，输出 UNCERTAIN，不要为了"看起来有结论"而强判产品 Bug
- evidence 数组中的 quote 必须从下方"失败现场"原文摘录，不准编造
- 4xx 通常是脚本问题；5xx 才可能是产品 Bug；但要看具体错误信息再判定

{patterns_digest}

## 失败现场
{ev_text}

{doc_text}

{matched_hint}

## 输出格式（严格 JSON）
```json
{{
  "verdict": "SCRIPT_FIX | PRODUCT_BUG | UNCERTAIN",
  "confidence": 0.85,
  "summary": "一句话结论，描述根本原因",
  "report_md": "## 诊断报告\\n\\n### 失败现象\\n...\\n\\n### 根本原因\\n...\\n\\n### 修复建议\\n...",
  "evidence": [
    {{"source": "stderr", "quote": "原文摘录，例如 'Null streamIds'"}},
    {{"source": "script", "quote": "原文摘录"}}
  ],
  "matched_patterns": ["命中的反模式 id"]
}}
```

只输出 JSON，不要在 JSON 外添加任何文字。
"""

    def _fallback_report(self, evidence: FailureEvidence, reason: str) -> Dict[str, Any]:
        """LLM 不可用时的兜底报告：把已有证据原样呈现，让人来判"""
        tc = evidence.get("test_case") or {}
        err = (
            evidence.get("error_message")
            or evidence.get("stderr_tail", "")[-500:]
            or evidence.get("stdout_tail", "")[-500:]
            or "（无可用错误信息）"
        )

        report = f"""## 诊断报告（兜底模式）

> AI 服务暂不可用（{reason}），以下为原始失败信息汇总，请人工判定。

### 失败用例
- 名称: {tc.get('name', '未知')}
- nodeid: {tc.get('nodeid', '未知')}

### 错误信息
```
{err}
```

### 建议
请结合接口文档和上方错误信息人工排查。如怀疑为脚本问题，可参考反模式列表
（共 {len(KNOWN_ANTIPATTERNS)} 条已知陷阱）。
"""

        return {
            "verdict": "UNCERTAIN",
            "confidence": 0.0,
            "summary": f"AI 诊断不可用（{reason}），已转人工",
            "report_md": report,
            "evidence": [{"source": "fallback", "quote": err[:500]}],
            "matched_patterns": [],
            "from_fallback": True,
        }

    def _guess_endpoint(self, evidence: FailureEvidence) -> str:
        script_path = evidence.get("script_path", "")
        return script_path

    def _guess_module(self, evidence: FailureEvidence) -> str:
        path = (evidence.get("script_path") or "").lower()
        for keyword in ["asset", "alarm", "login", "manage", "module", "risk"]:
            if keyword in path:
                return keyword
        return ""

    def _collect_error_text(self, evidence: FailureEvidence) -> str:
        return "\n".join([
            evidence.get("error_message", ""),
            evidence.get("stderr_tail", ""),
            evidence.get("failure_snippet", ""),
        ])
