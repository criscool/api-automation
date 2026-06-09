"""
失败证据提取器
为 AI 诊断准备结构化的「失败现场」上下文。

数据来源优先级：
1. ScriptExecutionResult.stdout/stderr （已存末 5000 字，包含 pytest FAILED 详情）
2. backend/reports/{execution_id}/allure-results/*.json （如果存在，含 attachment）
3. TestScript.content + TestCase 元数据（脚本源码与定位）
4. TestResult.error_message （兜底）
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from app.models.api_automation import (
    ScriptExecutionResult,
    TestCase,
    TestResult,
    TestScript,
)


# 项目内 backend/ 根目录（reports 与之同级）
_BACKEND_DIR = Path(__file__).resolve().parents[3]
_REPORTS_ROOT = _BACKEND_DIR / "reports"


class FailureEvidence(dict):
    """便于在 prompt 构造中作为 dict 直接 .format 使用"""

    @property
    def has_useful_signal(self) -> bool:
        """是否包含至少一种有用证据"""
        return bool(
            self.get("stderr_tail")
            or self.get("stdout_tail")
            or self.get("allure_attachments")
            or self.get("error_message")
            or self.get("failure_snippet")
        )


async def collect_evidence(
    script_id: str,
    test_case_id: Optional[str] = None,
) -> FailureEvidence:
    """
    收集指定脚本（可选指定 testcase）最近一次失败的证据。

    Args:
        script_id: TestScript.script_id
        test_case_id: 可选，TestCase.test_id，用于精准定位失败方法

    Returns:
        FailureEvidence dict，含字段：
        - script_id / script_name / script_path / script_content
        - test_case: {test_id, name, class_name, method_name, nodeid}
        - last_execution: {execution_id, status, start_time, duration}
        - stdout_tail / stderr_tail / error_message
        - allure_attachments: List[{name, source, content_preview}]
        - failure_snippet: pytest 输出中本方法的失败片段（如能提取）
    """
    evidence = FailureEvidence(
        script_id=script_id,
        test_case_id=test_case_id,
    )

    script = await TestScript.filter(script_id=script_id).first()
    if not script:
        logger.warning(f"collect_evidence: 找不到脚本 {script_id}")
        return evidence

    evidence["script_name"] = script.name
    evidence["script_path"] = script.file_path or script.file_name
    evidence["script_content"] = script.content or ""

    if test_case_id:
        tc = await TestCase.filter(test_id=test_case_id).first()
        if tc:
            evidence["test_case"] = {
                "test_id": tc.test_id,
                "name": tc.name,
                "class_name": tc.class_name,
                "method_name": tc.method_name,
                "nodeid": _build_nodeid(tc),
            }

    last_exec = None
    try:
        last_exec = (
            await ScriptExecutionResult
            .filter(script=script, status="FAILED")
            .order_by("-created_at")
            .first()
        )
    except Exception as e:
        logger.warning(f"加载 ScriptExecutionResult 失败 script_id={script_id}: {e}")

    if last_exec:
        try:
            await last_exec.fetch_related("execution")
            execution_id = last_exec.execution.execution_id if last_exec.execution else None
        except Exception as e:
            logger.warning(f"fetch_related execution 失败: {e}")
            execution_id = None
        evidence["last_execution"] = {
            "execution_id": execution_id,
            "status": last_exec.status,
            "start_time": last_exec.start_time.isoformat() if last_exec.start_time else None,
            "duration": last_exec.duration,
            "exit_code": last_exec.exit_code,
        }
        evidence["stdout_tail"] = last_exec.stdout or ""
        evidence["stderr_tail"] = last_exec.stderr or ""
        evidence["error_message"] = last_exec.error_message or ""
        evidence["failure_reason"] = last_exec.failure_reason or ""

        method_name = (evidence.get("test_case") or {}).get("method_name")
        if method_name:
            evidence["failure_snippet"] = _extract_method_failure(
                last_exec.stdout, method_name
            )

        if execution_id:
            evidence["allure_attachments"] = _collect_allure_failures(
                execution_id, method_name
            )

    if not evidence.get("error_message") and test_case_id:
        try:
            tr = (
                await TestResult
                .filter(test_case__test_id=test_case_id, status="failed")
                .order_by("-start_time")
                .first()
            )
            if tr and tr.error_message:
                evidence["error_message"] = tr.error_message
        except Exception as e:
            logger.warning(f"加载 TestResult 失败 test_case_id={test_case_id}: {e}")

    return evidence


def _build_nodeid(tc: TestCase) -> str:
    parts = [tc.script_file_path or ""]
    if tc.class_name:
        parts.append(tc.class_name)
    if tc.method_name:
        parts.append(tc.method_name)
    return "::".join(p for p in parts if p)


def _extract_method_failure(stdout: str, method_name: str) -> str:
    """从 pytest stdout 中提取目标方法的失败块"""
    if not stdout or not method_name:
        return ""
    pattern = re.compile(
        rf"_+\s+{re.escape(method_name)}\b.*?(?=\n_+\s+\w+|\n=+\sshort test summary|\Z)",
        re.DOTALL,
    )
    m = pattern.search(stdout)
    if m:
        text = m.group(0)
        return text[-3000:] if len(text) > 3000 else text
    return ""


def _collect_allure_failures(
    execution_id: str,
    method_name: Optional[str],
) -> List[Dict[str, Any]]:
    """从 Allure 结果目录读 attachment 摘要"""
    results_dir = _REPORTS_ROOT / execution_id / "allure-results"
    if not results_dir.exists():
        return []

    attachments: List[Dict[str, Any]] = []
    for result_file in results_dir.glob("*-result.json"):
        try:
            data = json.loads(result_file.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            logger.debug(f"解析 Allure 结果失败 {result_file}: {e}")
            continue

        name = data.get("name") or data.get("fullName") or ""
        if method_name and method_name not in name and method_name not in data.get("fullName", ""):
            continue
        if data.get("status") not in ("failed", "broken"):
            continue

        for att in data.get("attachments", []):
            source_name = att.get("source", "")
            src_path = results_dir / source_name if source_name else None
            preview = ""
            if src_path and src_path.exists() and src_path.stat().st_size < 50_000:
                try:
                    preview = src_path.read_text(encoding="utf-8", errors="replace")[:2000]
                except Exception:
                    preview = ""

            attachments.append({
                "name": att.get("name", ""),
                "type": att.get("type", ""),
                "source": source_name,
                "content_preview": preview,
            })

        steps_summary = []
        for step in data.get("steps", []):
            if step.get("status") in ("failed", "broken"):
                steps_summary.append({
                    "name": step.get("name", ""),
                    "status": step.get("status"),
                    "message": (step.get("statusDetails") or {}).get("message", ""),
                })
        if steps_summary:
            attachments.append({
                "name": "__failed_steps__",
                "type": "summary",
                "source": "",
                "content_preview": json.dumps(steps_summary, ensure_ascii=False)[:2000],
            })

    return attachments


def summarize_for_prompt(evidence: FailureEvidence, max_chars: int = 16000) -> str:
    """
    把 evidence 渲染成压缩的 prompt 片段。
    避免把过长的 stdout/源码全塞进 LLM 上下文。

    对超长源码（如 scenario 类用例的 test_chain）采用"头部 + 失败行邻域 + 尾部"
    分段保留，避免简单截断丢失失败步骤上下文。
    """
    lines: List[str] = []
    tc = evidence.get("test_case") or {}
    if tc:
        lines.append(f"## 失败用例")
        lines.append(f"- 名称: {tc.get('name', '')}")
        lines.append(f"- nodeid: {tc.get('nodeid', '')}")

    last_exec = evidence.get("last_execution") or {}
    if last_exec:
        lines.append(f"\n## 最近一次执行")
        lines.append(f"- execution_id: {last_exec.get('execution_id', '')}")
        lines.append(f"- exit_code: {last_exec.get('exit_code', '')}")
        lines.append(f"- duration: {last_exec.get('duration', '')}s")

    snippet = evidence.get("failure_snippet") or ""
    if snippet:
        lines.append(f"\n## pytest 失败片段")
        lines.append("```")
        lines.append(snippet[:3500])
        lines.append("```")
    else:
        stderr_tail = evidence.get("stderr_tail") or ""
        stdout_tail = evidence.get("stdout_tail") or ""
        if stderr_tail:
            lines.append(f"\n## stderr 末尾")
            lines.append("```")
            lines.append(stderr_tail[-2500:])
            lines.append("```")
        if stdout_tail:
            lines.append(f"\n## stdout 末尾")
            lines.append("```")
            lines.append(stdout_tail[-2500:])
            lines.append("```")

    err_msg = evidence.get("error_message") or ""
    if err_msg and err_msg not in snippet:
        lines.append(f"\n## error_message")
        lines.append("```")
        lines.append(err_msg[-1500:])
        lines.append("```")

    atts = evidence.get("allure_attachments") or []
    if atts:
        lines.append(f"\n## Allure 失败附件 ({len(atts)} 项)")
        for att in atts[:5]:
            lines.append(f"- [{att.get('name', '')}] {att.get('type', '')}")
            if att.get("content_preview"):
                lines.append("  ```")
                lines.append(f"  {att['content_preview'][:800]}")
                lines.append("  ```")

    src = evidence.get("script_content") or ""
    if src:
        method_name = tc.get("method_name")
        rendered = _render_source_block(src, method_name, snippet)
        lines.append(rendered)

    result = "\n".join(lines)
    return result[:max_chars]


def _render_source_block(src: str, method_name: Optional[str], failure_snippet: str) -> str:
    """
    源码块渲染策略：
    1) 短源码（<6000 字符）→ 整段
    2) 能定位到方法 → 取方法体；方法体仍超长则按"头部 + 失败行邻域 + 尾部"分段
    3) 兜底 → 头尾截断
    """
    SHORT_THRESHOLD = 6000
    METHOD_SHORT_THRESHOLD = 6000

    if len(src) <= SHORT_THRESHOLD:
        return "\n## 脚本源码（完整）\n```python\n" + src + "\n```"

    func_snippet = _extract_function_source(src, method_name) if method_name else ""
    if not func_snippet:
        head = src[:2500]
        tail = src[-2500:]
        return (
            "\n## 脚本源码片段（头尾截断）\n```python\n"
            + head + "\n...（中间省略）...\n" + tail + "\n```"
        )

    if len(func_snippet) <= METHOD_SHORT_THRESHOLD:
        return "\n## 失败方法源码（完整）\n```python\n" + func_snippet + "\n```"

    # 长方法（scenario test_chain）：头部 + 失败行邻域 + 尾部
    failure_line = _guess_failure_line(failure_snippet)
    func_lines = func_snippet.splitlines()
    total_lines = len(func_lines)
    head = "\n".join(func_lines[:60])
    tail = "\n".join(func_lines[-80:])

    neighborhood = ""
    if failure_line:
        # 在 func_lines 里找包含 failure_line 关键片段的行号
        target_idx = -1
        key = failure_line.strip()[:80]
        for i, line in enumerate(func_lines):
            if key and key in line:
                target_idx = i
                break
        if target_idx > 0:
            start = max(0, target_idx - 25)
            end = min(total_lines, target_idx + 10)
            neighborhood = "\n".join(func_lines[start:end])

    parts = [
        "\n## 失败方法源码（分段保留：头部 + 失败行邻域 + 尾部）",
        "```python",
        "# === 方法头部（前 60 行）===",
        head,
        "# ...（中间省略，方法总行数 {tot}）...".format(tot=total_lines),
    ]
    if neighborhood:
        parts.append("# === 失败行邻域 ===")
        parts.append(neighborhood)
    parts.append("# === 方法尾部（最后 80 行，含失败断言）===")
    parts.append(tail)
    parts.append("```")
    return "\n".join(parts)


def _guess_failure_line(failure_snippet: str) -> str:
    """从 pytest 失败片段中提取看起来像是失败源码所在那一行的文本。
    pytest 的输出格式典型如：
        >       assert resp.status_code == 200, ...
        E       AssertionError: step 13 ...
    取 `>` 开头的最后一行作为失败行特征。
    """
    if not failure_snippet:
        return ""
    candidate = ""
    for line in failure_snippet.splitlines():
        if line.lstrip().startswith(">"):
            candidate = line.lstrip("> ").rstrip()
    return candidate


def _extract_function_source(src: str, method_name: str) -> str:
    """用简单缩进规则截取函数体（无需 import ast 以降低出错面）"""
    if not src or not method_name:
        return ""
    lines = src.splitlines()
    start = -1
    indent = 0
    for i, line in enumerate(lines):
        m = re.match(rf"(\s*)def\s+{re.escape(method_name)}\s*\(", line)
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
