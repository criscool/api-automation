"""
LLM模型客户端配置（面向对象版本）
支持任何兼容OpenAI API格式的模型（DeepSeek、通义千问、智谱、Moonshot、Ollama等）
通过 .env 中的 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL 统一配置
"""
from typing import Optional
from autogen_ext.models.openai import OpenAIChatCompletionClient
from loguru import logger

from app.core.config import settings


class LLMClient:
    """大模型客户端管理器（单例模式）"""

    _instance: Optional["LLMClient"] = None
    _client: Optional[OpenAIChatCompletionClient] = None

    def __new__(cls) -> "LLMClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def client(self) -> OpenAIChatCompletionClient:
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self) -> OpenAIChatCompletionClient:
        api_key = settings.LLM_API_KEY
        base_url = settings.LLM_BASE_URL
        model = settings.LLM_MODEL

        if not api_key:
            raise ValueError("未配置 LLM_API_KEY，请在 .env 中设置")

        client = OpenAIChatCompletionClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
            model_info={
                "vision": False,
                "function_calling": True,
                "json_output": True,
                "structured_output": True,
                "family": "unknown",
                "multiple_system_messages": True,
            },
        )
        logger.info(f"模型客户端创建成功: {model} @ {base_url}")
        return client

    def reset(self):
        """重置客户端实例，下次访问时重新创建"""
        self._client = None


def get_model_client(model_type: str = "default") -> OpenAIChatCompletionClient:
    """获取模型客户端（保持向后兼容）"""
    return LLMClient().client
