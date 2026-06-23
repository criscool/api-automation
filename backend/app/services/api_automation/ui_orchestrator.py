"""[已迁移] UI 自动化编排器服务

本文件原位于 services/api_automation/，按项目模块物理隔离红线已迁移到
services/ui_automation/orchestrator.py。

保留本文件作为短期兼容层，避免任何未知的旧引用立即崩溃。
新代码请直接 import: ``from app.services.ui_automation.orchestrator import ui_orchestrator``
本文件将在阶段二验收稳定后清理。
"""
from app.services.ui_automation.orchestrator import (  # noqa: F401
    UiAutomationDisabledError,
    UiAutomationOrchestrator,
    ui_orchestrator,
)
