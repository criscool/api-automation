"""
Playwright JSON 报告解析 + 产物归档

后端 UiScriptExecutorAgent 执行完 subprocess 后,调用本服务:
1. parse_playwright_json: 解析 results.json → 用例级状态/耗时/错误信息
2. collect_artifacts:    扫描产物目录 → 截图/视频/trace 文件清单(供持久化层入库)
3. write_combined_log:   stdout/stderr 合并落盘(run.log 给前端"下载日志"按钮)

Playwright JSON 报告结构(关键字段,基于 1.47 版本):
{
  "config": {...},
  "suites": [
    {
      "title": "test_login.spec.ts",
      "specs": [
        {
          "title": "用户登录",
          "tests": [
            {
              "results": [
                {
                  "status": "passed" | "failed" | "timedOut" | "skipped" | "interrupted",
                  "duration": 12345,
                  "error": { "message": "...", "stack": "..." },
                  "attachments": [
                    {"name":"video", "path":"<abs>", "contentType":"video/webm"},
                    {"name":"trace", "path":"<abs>", "contentType":"application/zip"},
                    {"name":"screenshot", "path":"<abs>", "contentType":"image/png"}
                  ]
                }
              ]
            }
          ]
        }
      ],
      "suites": [...]    // 嵌套子套件
    }
  ],
  "stats": { "expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0, "duration": 12345 }
}

零回归:本模块只读 results.json 和产物目录,不写任何持久化层。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class CaseResult:
    """单条 spec 解析结果"""
    suite: str                          # 文件名 / 顶层套件标题
    title: str                          # spec 标题
    status: str                         # passed / failed / timed_out / skipped / interrupted / unknown
    duration_ms: int = 0
    error_message: str = ""             # 失败时第一条 error.message
    attachments: List[Dict[str, str]] = field(default_factory=list)
    # 每条 attachment: {name, path, content_type}


@dataclass
class ReportSummary:
    """整次执行的汇总"""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    timed_out: int = 0
    interrupted: int = 0
    duration_ms: int = 0
    cases: List[CaseResult] = field(default_factory=list)
    raw_stats: Dict[str, Any] = field(default_factory=dict)
    parse_error: str = ""               # JSON 不存在或解析失败时的原因(非空 = 解析未成功)

    @property
    def is_all_passed(self) -> bool:
        return self.failed == 0 and self.timed_out == 0 and self.interrupted == 0 and self.total > 0

    def to_dict(self) -> Dict[str, Any]:
        """供 ui_test_reports.summary JSONField 入库"""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "timed_out": self.timed_out,
            "interrupted": self.interrupted,
            "duration_ms": self.duration_ms,
            "cases": [
                {
                    "suite": c.suite,
                    "title": c.title,
                    "status": c.status,
                    "duration_ms": c.duration_ms,
                    "error_message": c.error_message,
                }
                for c in self.cases
            ],
            "raw_stats": self.raw_stats,
            "parse_error": self.parse_error,
        }


# ============================================================================
# 解析
# ============================================================================

_PLAYWRIGHT_STATUS_MAP = {
    "passed": "passed",
    "failed": "failed",
    "timedout": "timed_out",
    "timed_out": "timed_out",
    "timeout": "timed_out",
    "skipped": "skipped",
    "interrupted": "interrupted",
}


def _normalize_status(raw: str) -> str:
    if not raw:
        return "unknown"
    key = raw.replace(" ", "").lower()
    return _PLAYWRIGHT_STATUS_MAP.get(key, "unknown")


def _walk_suites(suites: List[Dict[str, Any]], parent_title: str = "") -> List[CaseResult]:
    """递归遍历 suites,把所有 spec 拍平。"""
    results: List[CaseResult] = []
    for suite in suites or []:
        suite_title = suite.get("title") or parent_title or ""
        # 当前层级的 specs
        for spec in suite.get("specs", []) or []:
            spec_title = spec.get("title", "")
            for test in spec.get("tests", []) or []:
                # tests[].results[] —— 多次重试时取最后一次
                test_results = test.get("results", []) or []
                if not test_results:
                    continue
                final = test_results[-1]
                status = _normalize_status(final.get("status", ""))
                duration = int(final.get("duration", 0) or 0)
                error_msg = ""
                err = final.get("error") or {}
                if isinstance(err, dict):
                    error_msg = str(err.get("message", ""))[:2000]
                elif final.get("errors"):
                    first = (final.get("errors") or [{}])[0]
                    error_msg = str(first.get("message", ""))[:2000] if isinstance(first, dict) else ""

                attachments: List[Dict[str, str]] = []
                for att in final.get("attachments", []) or []:
                    if not isinstance(att, dict):
                        continue
                    path = att.get("path") or att.get("body") or ""
                    if not path:
                        continue
                    attachments.append({
                        "name": str(att.get("name", "")),
                        "path": str(path),
                        "content_type": str(att.get("contentType", "")),
                    })

                results.append(CaseResult(
                    suite=suite_title,
                    title=spec_title,
                    status=status,
                    duration_ms=duration,
                    error_message=error_msg,
                    attachments=attachments,
                ))

        # 递归子套件
        nested = suite.get("suites", []) or []
        if nested:
            results.extend(_walk_suites(nested, parent_title=suite_title))

    return results


def parse_playwright_json(json_path: str | Path) -> ReportSummary:
    """解析 Playwright JSON 报告。

    文件不存在 / 解析失败时返回带 parse_error 的空 summary,不抛异常。
    调用方据此判断:
        if summary.parse_error: 走 Agent 兜底文案 + 标记 execution failed
    """
    p = Path(json_path)
    if not p.exists():
        return ReportSummary(parse_error=f"results.json 不存在: {p}")

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return ReportSummary(parse_error=f"results.json 解析失败: {e}")
    except OSError as e:
        return ReportSummary(parse_error=f"results.json 读取失败: {e}")

    summary = ReportSummary()

    # stats 是 Playwright 自带的统计(可能字段名版本差异,直接收存原始)
    stats = data.get("stats") or {}
    if isinstance(stats, dict):
        summary.raw_stats = stats
        summary.duration_ms = int(stats.get("duration", 0) or 0)

    cases = _walk_suites(data.get("suites", []) or [])
    summary.cases = cases
    summary.total = len(cases)
    for c in cases:
        if c.status == "passed":
            summary.passed += 1
        elif c.status == "failed":
            summary.failed += 1
        elif c.status == "skipped":
            summary.skipped += 1
        elif c.status == "timed_out":
            summary.timed_out += 1
        elif c.status == "interrupted":
            summary.interrupted += 1

    if summary.duration_ms == 0 and cases:
        summary.duration_ms = sum(c.duration_ms for c in cases)

    logger.debug(
        f"解析 Playwright 报告完成 path={p} total={summary.total} "
        f"passed={summary.passed} failed={summary.failed}"
    )
    return summary


# ============================================================================
# 产物归档
# ============================================================================

# 后缀 → 类型(写入 ui_execution_artifacts.artifact_type)
_ARTIFACT_TYPE_BY_SUFFIX = {
    ".png": "screenshot",
    ".jpg": "screenshot",
    ".jpeg": "screenshot",
    ".webm": "video",
    ".mp4": "video",
    ".zip": "trace",         # Playwright trace 一律 .zip
    ".log": "log",
    ".txt": "log",
    ".html": "html_report",
    ".json": "report_json",
}


@dataclass
class ArtifactRecord:
    artifact_type: str       # screenshot / video / trace / log / html_report / report_json
    file_path: str           # 绝对路径
    relative_path: str       # 相对 workspace_root,用于拼 file_url
    file_size: int           # 字节


def collect_artifacts(
    workspace_root: str | Path,
    *,
    include_dirs: Optional[List[str]] = None,
    max_video_size_mb: int = 50,
) -> List[ArtifactRecord]:
    """扫描某次执行的工作区,收集所有产物。

    workspace_root 期望布局(由 execution_service 创建):
        <workspace_root>/
            test-results/   ← Playwright 失败时的 video/trace/screenshot
            html/           ← HTML 报告(整个目录)
            results.json    ← JSON 报告
            run.log         ← stdout+stderr 合并

    include_dirs 不传则扫整个 workspace_root。
    超过 max_video_size_mb 的 .webm/.mp4 会被截断截屏:返回记录里附带 oversized 标记
    (调用方可以选择跳过或转码)。当前实现:超过限额仍记录,字段 file_size 真实,
    上层据此决定是否上传/保留。
    """
    root = Path(workspace_root)
    if not root.exists():
        return []

    candidate_dirs: List[Path] = []
    if include_dirs:
        for sub in include_dirs:
            d = root / sub
            if d.exists():
                candidate_dirs.append(d)
    else:
        candidate_dirs.append(root)

    records: List[ArtifactRecord] = []
    seen: set = set()  # 避免 include_dirs 重叠时重复

    for base in candidate_dirs:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            abs_path = path.resolve()
            if abs_path in seen:
                continue
            seen.add(abs_path)

            suffix = path.suffix.lower()
            artifact_type = _ARTIFACT_TYPE_BY_SUFFIX.get(suffix)
            if not artifact_type:
                # html 报告目录下还有 .ttf / .css / .js 资产,合并归类为 html_report
                if "html" in path.parts:
                    artifact_type = "html_report"
                else:
                    continue

            try:
                size = path.stat().st_size
            except OSError:
                size = 0

            try:
                rel = abs_path.relative_to(root.resolve())
            except ValueError:
                rel = path.name
            rel_str = str(rel).replace("\\", "/")

            records.append(ArtifactRecord(
                artifact_type=artifact_type,
                file_path=str(abs_path),
                relative_path=rel_str,
                file_size=size,
            ))

    return records


def write_combined_log(workspace_root: str | Path, stdout: str, stderr: str) -> str:
    """把子进程的 stdout/stderr 合并写到 <workspace_root>/run.log,返回绝对路径。

    给前端"下载日志"按钮 + Allure 风格回溯用。文件失败仅 logger.warn,不抛异常。
    """
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / "run.log"
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as f:
            if stdout:
                f.write("===== STDOUT =====\n")
                f.write(stdout)
                if not stdout.endswith("\n"):
                    f.write("\n")
            if stderr:
                f.write("\n===== STDERR =====\n")
                f.write(stderr)
                if not stderr.endswith("\n"):
                    f.write("\n")
    except OSError as e:
        logger.warning(f"写 run.log 失败 path={log_path} err={e}")
    return str(log_path.resolve())


def html_report_index(workspace_root: str | Path) -> Optional[str]:
    """返回 HTML 报告主页 index.html 的绝对路径(供 ui_test_reports.report_path 入库)。

    Playwright HTML reporter 会把整目录铺到 outputFolder,里面一定有 index.html。
    """
    candidate = Path(workspace_root) / "html" / "index.html"
    if candidate.exists():
        return str(candidate.resolve())
    return None


__all__ = [
    "CaseResult",
    "ReportSummary",
    "ArtifactRecord",
    "parse_playwright_json",
    "collect_artifacts",
    "write_combined_log",
    "html_report_index",
]
