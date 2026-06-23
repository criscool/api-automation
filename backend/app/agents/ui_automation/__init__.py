"""UI 自动化模块 - agents 子包

阶段二：填充 PageAnalyzerAgent（含内部 GroupChat）/ UiScriptGeneratorAgent（三模板）。
消息体定义见 schemas.py。
"""

from app.agents.ui_automation.schemas import (
    AnalysisType,
    ScriptType,
    UiElementCategory,
    ScriptSource,
    PageAnalysisInput,
    PageAnalysisOutput,
    ScriptGenerationInput,
    ScriptGenerationOutput,
    ManualScriptCreateInput,
    UiElement,
    InteractionStep,
)

# Agent 类（延迟到此处导入，避免 schemas 早期循环依赖）
from app.agents.ui_automation.page_analyzer_agent import PageAnalyzerAgent
from app.agents.ui_automation.script_generator_agent import UiScriptGeneratorAgent
from app.agents.ui_automation.recording_orchestrator_agent import UiRecordingOrchestratorAgent
from app.agents.ui_automation.batch_executor_agent import UiBatchExecutorAgent

__all__ = [
    "AnalysisType",
    "ScriptType",
    "UiElementCategory",
    "ScriptSource",
    "PageAnalysisInput",
    "PageAnalysisOutput",
    "ScriptGenerationInput",
    "ScriptGenerationOutput",
    "ManualScriptCreateInput",
    "UiElement",
    "InteractionStep",
    "PageAnalyzerAgent",
    "UiScriptGeneratorAgent",
    "UiRecordingOrchestratorAgent",
    "UiBatchExecutorAgent",
]

