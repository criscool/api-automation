"""UI 自动化模块 - services 子包

阶段二填充:
- orchestrator.py: UiAutomationOrchestrator（独立 runtime + Agent 注册 + 落库 + 写文件）

阶段三再追加:
- execution_service.py:      Playwright 单脚本执行
- script_safety_service.py:  脚本静态安全扫描
- report_service.py:         Playwright HTML/JSON 报告解析 + 产物收集
- session_service.py:        启动自愈(running→interrupted)
- cleanup_service.py:        产物定时清理(APScheduler)

阶段四(录制)再追加:
- codegen_runner.py:         Playwright codegen 子进程封装
"""
from app.services.ui_automation import (
    codegen_runner,
    execution_service,
    image_library_service,
    report_service,
    script_safety_service,
)
from app.services.ui_automation.orchestrator import (
    UiAutomationDisabledError,
    UiAutomationOrchestrator,
    ui_orchestrator,
)

__all__ = [
    "UiAutomationDisabledError",
    "UiAutomationOrchestrator",
    "ui_orchestrator",
    "codegen_runner",
    "execution_service",
    "image_library_service",
    "report_service",
    "script_safety_service",
]
