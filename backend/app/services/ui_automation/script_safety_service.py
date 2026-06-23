"""
UI 自动化脚本静态安全扫描

设计原则：在脚本进入 subprocess 之前先静态扫一遍，命中黑名单直接拒绝执行，避免恶意脚本
利用 Node 直接调系统 API。本扫描是"廉价的兜底"，不替代沙箱——核心隔离仍靠子进程 cwd 限制 +
进程组超时 + 工作区路径校验。

零回归红线：本模块不依赖任何 API 自动化资源，纯函数；扫描失败 (raise) 仅影响 UI 执行链路。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

# ----------------------------------------------------------------------------
# 黑名单：危险 Node 内建模块 + eval 系列
#
# 注意：
#   - require('child_process') / require("child_process") / require(`child_process`) 全覆盖
#   - import 形式: `import { spawn } from "child_process"` / `import cp = require("child_process")`
#   - 动态: `import("child_process")`
#   - eval / new Function / vm 模块（Node 的 in-process 沙箱逃逸路径）
# ----------------------------------------------------------------------------
_BANNED_MODULES = ("fs", "fs/promises", "child_process", "os", "vm", "worker_threads", "cluster")

# 匹配 require / 静态 import / 动态 import 三种引入形态中的某一个模块名
_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    # require('mod') / require("mod") / require(`mod`)
    (
        "require_call",
        re.compile(
            r"""require\s*\(\s*['"`](?P<mod>[^'"`]+)['"`]\s*\)""",
            re.IGNORECASE,
        ),
    ),
    # import ... from 'mod'
    (
        "static_import",
        re.compile(
            r"""\bimport\b[^;]*?from\s*['"](?P<mod>[^'"]+)['"]""",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    # import 'mod' (副作用导入)
    (
        "side_effect_import",
        re.compile(r"""\bimport\s*['"](?P<mod>[^'"]+)['"]""", re.IGNORECASE),
    ),
    # import('mod')  动态
    (
        "dynamic_import",
        re.compile(
            r"""\bimport\s*\(\s*['"`](?P<mod>[^'"`]+)['"`]\s*\)""",
            re.IGNORECASE,
        ),
    ),
)

# 直接禁的关键字 / 调用
_BANNED_LITERALS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("eval_call", re.compile(r"""\beval\s*\(""")),
    ("new_function", re.compile(r"""\bnew\s+Function\s*\(""")),
    # process.binding 是绕过模块系统拿底层 native binding 的老接口
    ("process_binding", re.compile(r"""\bprocess\.binding\s*\(""")),
    # 进程退出/直接 spawn child（防止脚本里手写 child_process）
    ("process_kill", re.compile(r"""\bprocess\.kill\s*\(""")),
)


@dataclass
class SafetyViolation:
    """单条违规命中"""
    rule: str                # require_call / static_import / dynamic_import / side_effect_import / eval_call / ...
    matched_module: str      # 命中的模块名或字面量（eval_call 时为 "eval"）
    line_number: int         # 1-based
    line_text: str           # 原始行内容（最多 200 字）


@dataclass
class SafetyScanResult:
    ok: bool
    violations: List[SafetyViolation]
    file_path: str

    def reason(self) -> str:
        if self.ok:
            return ""
        return "; ".join(
            f"{v.rule}@L{v.line_number}: {v.matched_module}" for v in self.violations[:5]
        )


def scan_source(source: str, file_path: str = "<memory>") -> SafetyScanResult:
    """对源码字符串扫描黑名单。

    YAML 模式脚本(.yaml)目前不调 Node 代码,直接放过;调用方按扩展名分流即可。
    """
    violations: List[SafetyViolation] = []
    banned_set = set(_BANNED_MODULES)

    for line_no, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        line_trim = raw_line[:200]

        # 模块 import / require 类
        for rule_name, pattern in _PATTERNS:
            for m in pattern.finditer(raw_line):
                mod = m.group("mod").strip()
                # 处理子路径: child_process/promises -> child_process
                top = mod.split("/", 1)[0]
                if top in banned_set or mod in banned_set:
                    violations.append(
                        SafetyViolation(
                            rule=rule_name,
                            matched_module=mod,
                            line_number=line_no,
                            line_text=line_trim,
                        )
                    )

        # 直接禁字面量
        for literal_rule, pattern in _BANNED_LITERALS:
            if pattern.search(raw_line):
                violations.append(
                    SafetyViolation(
                        rule=literal_rule,
                        matched_module=literal_rule.replace("_call", "").replace("_", " "),
                        line_number=line_no,
                        line_text=line_trim,
                    )
                )

    return SafetyScanResult(
        ok=not violations,
        violations=violations,
        file_path=file_path,
    )


def scan_file(file_path: str | Path) -> SafetyScanResult:
    """读文件后扫描。文件不存在时 ok=False 并附一条 read_error 违规。"""
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return SafetyScanResult(
            ok=False,
            violations=[
                SafetyViolation(
                    rule="read_error",
                    matched_module=str(p),
                    line_number=0,
                    line_text="file not found",
                )
            ],
            file_path=str(p),
        )

    # YAML 由 MidScene CLI 解释,不跑 Node 任意代码,跳过黑名单
    if p.suffix.lower() in (".yaml", ".yml"):
        return SafetyScanResult(ok=True, violations=[], file_path=str(p))

    try:
        source = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return SafetyScanResult(
            ok=False,
            violations=[
                SafetyViolation(
                    rule="read_error",
                    matched_module=str(p),
                    line_number=0,
                    line_text="file is not valid UTF-8",
                )
            ],
            file_path=str(p),
        )

    return scan_source(source, file_path=str(p))


def scan_files(paths: Iterable[str | Path]) -> List[SafetyScanResult]:
    """批量扫描,返回每个文件的结果列表。"""
    return [scan_file(p) for p in paths]


class ScriptSafetyError(RuntimeError):
    """脚本安全扫描失败 —— 命中黑名单,拒绝执行。"""

    def __init__(self, scan: SafetyScanResult) -> None:
        super().__init__(
            f"脚本 {scan.file_path} 命中安全规则: {scan.reason()}"
        )
        self.scan = scan


def assert_safe(file_path: str | Path) -> SafetyScanResult:
    """便利方法:不安全直接抛 ScriptSafetyError,执行链路直接 502/拒绝。"""
    result = scan_file(file_path)
    if not result.ok:
        raise ScriptSafetyError(result)
    return result


__all__ = [
    "SafetyViolation",
    "SafetyScanResult",
    "ScriptSafetyError",
    "scan_source",
    "scan_file",
    "scan_files",
    "assert_safe",
]
