"""
执行环境管理服务
================

供 API + UI 自动化共用的执行环境（URL / 登录账号）配置读写。

设计要点
--------
1. **单点激活**：`is_active=True` 全表最多 1 条；`activate_environment` 在事务里保证
2. **运行时读**：不写 `.env`，`get_active_environment` 每次读 DB（带内存缓存，激活时手动 invalidate）
3. **无激活时回退**：调用方拿到 None 时用 `.env` + YAML 兜底（现状不变）

被谁用
------
- `script_management._run_pytest_for_one_script`：API 自动化 pytest 子进程 env 注入
- `ui_automation.execution_service._resolve_ui_base_url / _resolve_ui_login_credentials`：
  UI 自动化配置解析优先层
- `api.v1.endpoints.environments`：CRUD/激活接口
"""
from __future__ import annotations

from typing import Optional
from loguru import logger

# 内存缓存 —— 单进程共享；后端多实例时每个进程各自缓存，激活会自动同步（DB 是权威）
# _cache_valid=False 时下次访问强制回源 DB
_active_cache: Optional["ExecutionEnvironment"] = None  # type: ignore[name-defined]
_cache_valid: bool = False


def invalidate_cache() -> None:
    """标记缓存失效，下次 get_active_environment 会强制回源。"""
    global _cache_valid
    _cache_valid = False


async def get_active_environment():
    """获取当前激活的执行环境。

    Returns:
        ExecutionEnvironment | None：无激活环境时返回 None，调用方需 fallback
    """
    global _active_cache, _cache_valid
    if _cache_valid:
        return _active_cache

    try:
        from app.models.api_automation import ExecutionEnvironment
        _active_cache = await ExecutionEnvironment.filter(is_active=True).first()
        _cache_valid = True
        return _active_cache
    except Exception as e:
        # 模型未加载或表未建成时，返回 None 让调用方 fallback
        logger.warning(f"读取激活环境失败（将 fallback 到 .env/YAML）: {e}")
        return None


async def activate_environment(env_id: str):
    """激活指定环境。事务里保证 is_active=True 唯一。

    Raises:
        ValueError: env_id 对应的环境不存在
    """
    from tortoise.transactions import in_transaction
    from app.models.api_automation import ExecutionEnvironment

    async with in_transaction():
        row = await ExecutionEnvironment.filter(env_id=env_id).first()
        if not row:
            raise ValueError(f"环境不存在: {env_id}")
        # 先把其他激活环境置为 False（应该最多 1 条，兜底防脏数据）
        await ExecutionEnvironment.filter(is_active=True).exclude(env_id=env_id).update(is_active=False)
        row.is_active = True
        await row.save()

    invalidate_cache()
    logger.info(f"环境已激活: env_id={env_id} name={row.name}")
    return row


async def deactivate_all() -> int:
    """把所有激活环境置为未激活（用于'停用/回退到 .env'场景）。返回受影响行数。"""
    from app.models.api_automation import ExecutionEnvironment
    affected = await ExecutionEnvironment.filter(is_active=True).update(is_active=False)
    invalidate_cache()
    logger.info(f"已停用所有激活环境，影响 {affected} 条")
    return affected


__all__ = [
    "get_active_environment",
    "activate_environment",
    "deactivate_all",
    "invalidate_cache",
]
