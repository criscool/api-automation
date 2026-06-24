"""
测试脚本修复智能体 (TestHealerAgent)

职责：在分析结论为 SCRIPT_FIX 时，生成对失败用例的修复补丁（unified diff）。

Phase 1 关键约束：
- 只生成 diff，绝对不写文件、不动 DB
- 补丁仅允许覆盖单个测试方法；其它改动统一返回失败
- LLM 异常时返回 from_fallback=True 的空 patch，由前端引导人工修复
"""
import difflib
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.healer_patterns import find_matching_patterns, render_digest
from app.core.types import AgentTypes
from app.services.api_automation.healer_evidence import (
    FailureEvidence,
    summarize_for_prompt,
)


class TestHealerAgent(BaseApiAutomationAgent):
    """测试脚本修复智能体（Phase 1：只出 diff 不应用）"""

    def __init__(self, **kwargs):
        super().__init__(
            agent_type=AgentTypes.TEST_HEALER,
            **kwargs,
        )

    async def propose_patch(
        self,
        evidence: FailureEvidence,
        analysis: Dict[str, Any],
        stream: bool = True,
    ) -> Dict[str, Any]:
        """
        生成补丁建议

        Args:
            evidence: 失败证据
            analysis: TestAnalysisAgent.analyze 的输出
            stream: 流式推送

        Returns:
            {
                "patch_format": "unified",
                "patch": "<unified diff 文本>",
                "fixed_method": "test_xxx",
                "rationale": "为什么这么改",
                "risk_tags": ["touches_assert", "introduces_import", ...],
                "from_fallback": bool
            }
        """
        try:
            await self._send_message("正在生成修复补丁...", "info")

            method_name = (evidence.get("test_case") or {}).get("method_name", "")
            if not method_name:
                logger.warning("缺少 method_name，无法定位修复目标")
                return self._fallback_patch(
                    evidence,
                    reason="缺少测试方法定位信息（class_name / method_name 为空）",
                )

            original_method_src = self._extract_method_source(
                evidence.get("script_content", ""), method_name
            )
            if not original_method_src:
                return self._fallback_patch(
                    evidence,
                    reason=f"无法在脚本中定位方法 {method_name}",
                )

            matched = find_matching_patterns(
                endpoint_path=evidence.get("script_path", ""),
                error_text=evidence.get("failure_snippet", ""),
            )

            prompt = self._build_prompt(
                evidence, analysis, original_method_src, method_name, matched
            )
            result_content = await self._run_assistant_agent(prompt, stream=stream)

            if not result_content:
                return self._fallback_patch(evidence, reason="LLM 返回空")

            parsed = self._extract_json_from_content(result_content)
            if not parsed or "fixed_method_code" not in parsed:
                return self._fallback_patch(
                    evidence, reason="LLM 输出格式异常，未含 fixed_method_code"
                )

            new_method_src = parsed["fixed_method_code"].strip("\n")

            method_name_in_new = self._first_def_name(new_method_src)
            if method_name_in_new and method_name_in_new != method_name:
                return self._fallback_patch(
                    evidence,
                    reason=f"LLM 试图替换为不同名方法（{method_name_in_new}），已拒绝",
                )

            full_new_content = self._replace_method_in_source(
                evidence.get("script_content", ""), method_name, new_method_src
            )
            if not full_new_content:
                return self._fallback_patch(
                    evidence, reason="无法将新方法回填到原脚本（缩进不匹配？）"
                )

            patch_text = self._make_unified_diff(
                evidence.get("script_content", ""),
                full_new_content,
                file_label=evidence.get("script_path", "script.py"),
            )

            risk_tags = self._collect_risk_tags(original_method_src, new_method_src)

            await self._send_message("补丁已生成", "success")
            return {
                "patch_format": "unified",
                "patch": patch_text,
                "fixed_method": method_name,
                "fixed_method_code": new_method_src,
                "rationale": parsed.get("rationale", ""),
                "risk_tags": risk_tags,
                "from_fallback": False,
            }

        except Exception as e:
            logger.error(f"生成补丁失败: {e}", exc_info=True)
            return self._fallback_patch(evidence, reason=f"生成补丁异常: {e}")

    def _build_prompt(
        self,
        evidence: FailureEvidence,
        analysis: Dict[str, Any],
        original_method_src: str,
        method_name: str,
        matched: List[Dict[str, str]],
    ) -> str:
        ev_text = summarize_for_prompt(evidence, max_chars=12000)
        patterns_digest = render_digest()

        matched_hint = ""
        if matched:
            matched_hint = "\n## 优先考虑这些已知反模式：\n" + "\n".join(
                f"- [{m['id']}] {m['rule']}（提示：{m['fix_hint']}）" for m in matched
            )

        # 提取同脚本中 api_client.<method> 的调用分布，让 AI 偏好"本脚本主导方法"
        # 而不是 RESTful 教科书风格 —— 修复 405 时最关键
        method_dist = self._extract_method_distribution(
            evidence.get("script_content", "")
        )
        method_hint = ""
        if method_dist:
            dist_str = ", ".join(f"{m.upper()}={c}次" for m, c in method_dist)
            dominant = method_dist[0][0].upper()
            method_hint = (
                f"\n## 本脚本 HTTP 方法分布\n"
                f"{dist_str}\n"
                f"主导方法：**{dominant}**\n"
                f"（如果失败是 4xx Method Not Allowed，优先把方法改成上述主导方法，"
                f"而不是 RESTful 教科书推荐——这个团队的接口约定以本脚本为准）\n"
            )

        return f"""你是一位资深 pytest 接口测试专家。请基于失败信息修复指定测试方法。

## 严格规则（违反任何一条都会被自动拒绝）
1. **只能修改 `{method_name}` 这一个方法**，禁止改动文件其它部分
2. **方法名不能变**：返回的 fixed_method_code 必须以 `def {method_name}` 或 `async def {method_name}` 开头
3. **缩进必须与原方法一致**（保留原始的前导空格）
4. **优先改 payload / header / 参数；尽量不改 assert 语句**（除非断言本身写错）
5. 不允许引入 `requests.delete`、`os.system`、`subprocess`、`shutil.rmtree` 等危险调用
6. **HTTP 方法选择**：见下方"本脚本 HTTP 方法分布"。修 405 错误时**沿用本脚本主导方法**，不要凭 RESTful 直觉随意改成 DELETE/PATCH 等
7. **Java 反序列化 Null 字段**：当服务端返回 `Cannot construct instance...problem: Null <字段名>` 时，payload 通常**不止缺这一个字段**（Java 报错只显示第一个 null）。需要补全该接口所有必填的字符串/数组字段，空字符串 `''` 或空数组 `[]` 即可

## 上一步的分析结论
- verdict: {analysis.get('verdict', '')}
- summary: {analysis.get('summary', '')}

{patterns_digest}

{matched_hint}
{method_hint}
## 失败现场
{ev_text}

## 待修复的方法（原始代码）
```python
{original_method_src}
```

## 输出格式（严格 JSON）
```json
{{
  "fixed_method_code": "完整的方法源码（含 def 行，保留原始缩进）",
  "rationale": "本次修复的核心理由（一句话）"
}}
```

只输出 JSON，不要在 JSON 外添加任何文字。
"""

    @staticmethod
    def _extract_method_distribution(src: str) -> List:
        """统计脚本中 api_client.<method>(...) 调用分布，按次数降序返回 [(method, count), ...]"""
        if not src:
            return []
        pattern = re.compile(r"api_client\.(get|post|put|delete|patch)\s*\(", re.IGNORECASE)
        counts: Dict[str, int] = {}
        for m in pattern.finditer(src):
            method = m.group(1).lower()
            counts[method] = counts.get(method, 0) + 1
        return sorted(counts.items(), key=lambda x: -x[1])

    def _fallback_patch(self, evidence: FailureEvidence, reason: str) -> Dict[str, Any]:
        return {
            "patch_format": "unified",
            "patch": "",
            "fixed_method": (evidence.get("test_case") or {}).get("method_name", ""),
            "fixed_method_code": "",
            "rationale": f"无法生成补丁：{reason}",
            "risk_tags": ["fallback"],
            "from_fallback": True,
        }

    @staticmethod
    def _extract_method_source(src: str, method_name: str) -> str:
        if not src or not method_name:
            return ""
        lines = src.splitlines()
        start = -1
        indent = 0
        for i, line in enumerate(lines):
            m = re.match(rf"(\s*)(async\s+)?def\s+{re.escape(method_name)}\s*\(", line)
            if m:
                start = i
                indent = len(m.group(1))
                break
        if start < 0:
            return ""

        end = len(lines)
        for j in range(start + 1, len(lines)):
            line = lines[j]
            if not line.strip():
                continue
            cur_indent = len(line) - len(line.lstrip())
            if cur_indent <= indent and line.strip():
                end = j
                break

        return "\n".join(lines[start:end])

    @staticmethod
    def _first_def_name(src: str) -> str:
        m = re.search(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", src, re.MULTILINE)
        return m.group(1) if m else ""

    @classmethod
    def _replace_method_in_source(
        cls, src: str, method_name: str, new_method_src: str
    ) -> str:
        original = cls._extract_method_source(src, method_name)
        if not original:
            return ""
        if not new_method_src.strip():
            return ""
        return src.replace(original, new_method_src, 1)

    @staticmethod
    def _make_unified_diff(before: str, after: str, file_label: str) -> str:
        diff_lines = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{file_label}",
            tofile=f"b/{file_label}",
            n=3,
        )
        return "".join(diff_lines)

    @staticmethod
    def _collect_risk_tags(before_method: str, after_method: str) -> List[str]:
        tags: List[str] = []
        before_asserts = re.findall(r"^\s*assert\b.*$", before_method, re.MULTILINE)
        after_asserts = re.findall(r"^\s*assert\b.*$", after_method, re.MULTILINE)
        if before_asserts != after_asserts:
            tags.append("touches_assert")
        new_imports = re.findall(r"^\s*(import |from )", after_method, re.MULTILINE)
        if new_imports:
            tags.append("introduces_local_import")
        if "delete" in after_method.lower() and "delete" not in before_method.lower():
            tags.append("introduces_delete")
        return tags
