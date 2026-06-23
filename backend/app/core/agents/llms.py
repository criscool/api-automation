"""
LLM 模型客户端管理（配置驱动多模型注册表）

通过 app/config/api_automation_config.yaml 的 llm_models 节点配置模型，
api_key / base_url / model 都通过环境变量名映射（*_env），避免敏感信息落盘。

新增模型只需改 yaml，不改代码。
"""
import os
from pathlib import Path
from typing import Dict, Optional, Any

import yaml
from autogen_ext.models.openai import OpenAIChatCompletionClient
from loguru import logger

from app.core.config import settings


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "api_automation_config.yaml"


class LLMClient:
    """大模型客户端管理器：按 model_type 维护多客户端缓存"""

    _instance: Optional["LLMClient"] = None
    _registry: Optional[Dict[str, Dict[str, Any]]] = None
    _clients: Dict[str, OpenAIChatCompletionClient] = {}

    def __new__(cls) -> "LLMClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _load_registry(cls) -> Dict[str, Dict[str, Any]]:
        if cls._registry is not None:
            return cls._registry
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            cls._registry = cfg.get("llm_models", {}) or {}
            logger.info(f"LLM 注册表加载完成，模型数: {len(cls._registry)}")
        except FileNotFoundError:
            logger.warning(f"未找到 LLM 注册表配置 {CONFIG_PATH}，将回退到 settings.LLM_*")
            cls._registry = {}
        return cls._registry

    @classmethod
    def _resolve_spec(cls, model_type: str) -> Dict[str, Any]:
        registry = cls._load_registry()
        spec = registry.get(model_type)
        if spec is None:
            if model_type == "default":
                return {}
            raise KeyError(f"未注册的模型类型: {model_type}，请在 api_automation_config.yaml 的 llm_models 中配置")
        # 解析软链
        seen = {model_type}
        while "alias_of" in spec:
            target = spec["alias_of"]
            if target in seen:
                raise ValueError(f"LLM 注册表存在循环 alias: {seen}")
            seen.add(target)
            spec = registry.get(target)
            if spec is None:
                raise KeyError(f"alias_of 指向未注册的模型: {target}")
        return spec

    def get(self, model_type: str = "default") -> OpenAIChatCompletionClient:
        if model_type in self._clients:
            return self._clients[model_type]

        spec = self._resolve_spec(model_type)
        if spec:
            client = self._build_from_spec(model_type, spec)
        else:
            client = self._build_from_settings(model_type)

        self._clients[model_type] = client
        return client

    @staticmethod
    def _read_env(name: Optional[str]) -> Optional[str]:
        """读取环境变量：os.environ 优先；缺失时回退到 pydantic settings 同名属性（兼容 .env 自动加载）"""
        if not name:
            return None
        val = os.getenv(name)
        if val:
            return val
        return getattr(settings, name, None) or None

    def _build_from_spec(self, model_type: str, spec: Dict[str, Any]) -> OpenAIChatCompletionClient:
        api_key = self._read_env(spec.get("api_key_env"))
        if not api_key:
            raise ValueError(
                f"模型 {model_type} 的 api_key 未配置，请在 .env 中设置 {spec.get('api_key_env')}"
            )

        base_url = self._read_env(spec.get("base_url_env")) or spec.get("base_url_default")
        model = self._read_env(spec.get("model_env")) or spec.get("model_default")
        model_info = spec.get("model_info") or {}

        client = OpenAIChatCompletionClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
            model_info=model_info,
        )
        logger.info(f"模型客户端创建成功 [{model_type}]: {model} @ {base_url}")
        return client

    def _build_from_settings(self, model_type: str) -> OpenAIChatCompletionClient:
        """注册表缺失时的兜底：沿用旧 settings.LLM_* 行为"""
        api_key = settings.LLM_API_KEY
        if not api_key:
            raise ValueError("未配置 LLM_API_KEY，请在 .env 中设置")
        client = OpenAIChatCompletionClient(
            model=settings.LLM_MODEL,
            api_key=api_key,
            base_url=settings.LLM_BASE_URL,
            model_info={
                "vision": False,
                "function_calling": True,
                "json_output": True,
                "structured_output": True,
                "family": "unknown",
                "multiple_system_messages": True,
            },
        )
        logger.info(f"模型客户端创建成功（兜底） [{model_type}]: {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")
        return client

    def reset(self, model_type: Optional[str] = None):
        """重置客户端实例（model_type 为 None 时全部重置）"""
        if model_type is None:
            self._clients.clear()
            self._registry = None
        else:
            self._clients.pop(model_type, None)

    @property
    def client(self) -> OpenAIChatCompletionClient:
        """向后兼容旧属性访问"""
        return self.get("default")


def get_model_client(model_type: str = "default") -> OpenAIChatCompletionClient:
    """按 model_type 获取模型客户端

    Args:
        model_type: 注册表中的 key，例如 "default" / "deepseek" / "doubao_vision"
    """
    return LLMClient().get(model_type)
