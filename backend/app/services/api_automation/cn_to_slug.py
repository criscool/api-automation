"""
中文用例名 → 英文 snake_case slug 的 LLM 翻译工具
================================================

仅供"依赖 JSON 快速导入"通道使用，把用户输入的中文用例名翻译为可作为
脚本文件名 stem 的英文标识符。LLM 调用失败 / 输出不合格时返回 None，
由调用方走 ScriptGeneratorAgent._sanitize_name 静态字典 fallback。
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from loguru import logger

from app.core.agents.llms import get_model_client


_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

_PROMPT_TEMPLATE = """把以下中文翻译为简洁的英文 snake_case 标识符，仅输出标识符本身，不要任何引号、解释、Markdown 代码块标记：

要求：
- 长度 2-4 个单词
- 全小写，单词间用下划线分隔
- 只能含字母、数字、下划线
- 必须以字母开头
- 不超过 64 字符

中文: {name}
"""


async def translate_to_slug(
    chinese_name: str,
    timeout: float = 10.0,
    model_type: str = "deepseek",
) -> Optional[str]:
    """把中文用例名翻译为 snake_case 英文 slug。

    成功 → 返回符合 ^[a-z][a-z0-9_]{{1,63}}$ 的字符串。
    失败 / 超时 / 输出不合格 → 返回 None，由调用方 fallback。

    全程包 try/except，绝不抛出，避免阻塞导入主流程。
    """
    chinese_name = (chinese_name or "").strip()
    if not chinese_name:
        return None

    try:
        # 延迟 import 避免循环依赖
        from autogen_core.models import UserMessage

        client = get_model_client(model_type)
        prompt = _PROMPT_TEMPLATE.format(name=chinese_name)

        result = await asyncio.wait_for(
            client.create(messages=[UserMessage(content=prompt, source="user")]),
            timeout=timeout,
        )
        raw = (result.content or "").strip()
        # 容忍模型偶尔加引号 / 反引号 / 末尾标点
        slug = raw.strip("`'\"").strip().strip(".,;:").lower()
        # 取首行（防止模型多输出几行）
        slug = slug.splitlines()[0].strip() if slug else ""

        if _SLUG_RE.match(slug):
            logger.info(f"LLM 翻译成功: '{chinese_name}' → '{slug}'")
            return slug

        logger.warning(
            f"LLM 翻译输出不符合 slug 格式: '{chinese_name}' → '{raw[:80]}'，"
            f"将由调用方 fallback"
        )
        return None
    except asyncio.TimeoutError:
        logger.warning(f"LLM 翻译超时 ({timeout}s): '{chinese_name}'")
        return None
    except Exception as e:
        logger.warning(f"LLM 翻译异常: '{chinese_name}', 错误: {e}")
        return None
