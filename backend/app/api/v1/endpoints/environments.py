"""
执行环境管理 API
================

前端「系统管理 → 环境管理」的后端接口。

设计要点
--------
- 一套 RESTful 五件套：list / create / update / delete / activate
- 权限走项目全局 DependPermission（在 v1/__init__.py 注册时挂）
- 激活 / 更新 / 删除都会 invalidate 缓存
- 删除激活环境要先 deactivate（前端提示）
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter(tags=["环境管理"])


# ==================== 请求/响应模型 ====================

class EnvironmentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="环境标识（pytest --env 参数值）")
    label: str = Field(..., min_length=1, max_length=100, description="中文名")
    api_base_url: str = Field("", max_length=500)
    ui_base_url: str = Field("", max_length=500)
    ui_login_url: str = Field("", max_length=500)
    username: str = Field("", max_length=200)
    password: str = Field("", max_length=500)
    notes: str = Field("", description="备注")


class EnvironmentUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    api_base_url: Optional[str] = None
    ui_base_url: Optional[str] = None
    ui_login_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    notes: Optional[str] = None


def _normalize_url(url: str) -> str:
    """归一化 URL：去末尾 /，避免拼路径时出现双斜杠导致 404。

    login_url 也去末尾 /，因为业务侧通常直接跳到根路径下的 /login 子路径。
    """
    if not url:
        return ""
    return url.strip().rstrip("/")


def _serialize(row) -> Dict[str, Any]:
    """把 ORM 对象转成前端消费的 dict（密码不返回明文，用星号占位）"""
    return {
        "env_id": row.env_id,
        "name": row.name,
        "label": row.label,
        "api_base_url": row.api_base_url,
        "ui_base_url": row.ui_base_url,
        "ui_login_url": row.ui_login_url,
        "username": row.username,
        # 密码不明文回传，前端编辑时保留占位；如果要改用户会重新填
        "password_placeholder": "******" if row.password else "",
        "is_active": row.is_active,
        "notes": row.notes,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ==================== 端点 ====================

@router.get("", summary="获取环境列表")
async def list_environments(
    keyword: Optional[str] = Query(None, description="按 name/label 模糊搜索"),
):
    from app.models.api_automation import ExecutionEnvironment
    qs = ExecutionEnvironment.all().order_by("-is_active", "-id")
    if keyword:
        from tortoise.expressions import Q
        qs = qs.filter(Q(name__icontains=keyword) | Q(label__icontains=keyword))
    rows = await qs
    return {
        "code": 200, "msg": "OK", "success": True,
        "data": {"items": [_serialize(r) for r in rows], "total": len(rows)},
    }


@router.post("", summary="新建环境")
async def create_environment(req: EnvironmentCreateRequest):
    from app.models.api_automation import ExecutionEnvironment

    # name 全表唯一（作为 pytest --env 参数值，重复会引起歧义）
    exists = await ExecutionEnvironment.filter(name=req.name).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"环境标识已存在: {req.name}")

    env_id = uuid.uuid4().hex
    row = await ExecutionEnvironment.create(
        env_id=env_id,
        name=req.name.strip(),
        label=req.label.strip(),
        api_base_url=_normalize_url(req.api_base_url),
        ui_base_url=_normalize_url(req.ui_base_url),
        ui_login_url=_normalize_url(req.ui_login_url),
        username=req.username or "",
        password=req.password or "",
        notes=req.notes or "",
        is_active=False,  # 新建默认未激活，由用户显式激活
    )
    logger.info(f"新建执行环境: env_id={env_id} name={req.name}")
    return {"code": 200, "msg": "已新建", "success": True, "data": _serialize(row)}


@router.put("/{env_id}", summary="更新环境")
async def update_environment(env_id: str, req: EnvironmentUpdateRequest):
    from app.models.api_automation import ExecutionEnvironment
    from app.services.environment_service import invalidate_cache

    row = await ExecutionEnvironment.filter(env_id=env_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"环境不存在: {env_id}")

    # name 改动要查唯一性
    if req.name is not None and req.name != row.name:
        exists = await ExecutionEnvironment.filter(name=req.name).exclude(env_id=env_id).first()
        if exists:
            raise HTTPException(status_code=400, detail=f"环境标识已存在: {req.name}")
        row.name = req.name.strip()
    if req.label is not None:
        row.label = req.label.strip()
    if req.api_base_url is not None:
        row.api_base_url = _normalize_url(req.api_base_url)
    if req.ui_base_url is not None:
        row.ui_base_url = _normalize_url(req.ui_base_url)
    if req.ui_login_url is not None:
        row.ui_login_url = _normalize_url(req.ui_login_url)
    if req.username is not None:
        row.username = req.username
    # 密码只在显式传入非空时更新（避免前端不填密码保存把已有密码清空）
    if req.password:
        row.password = req.password
    if req.notes is not None:
        row.notes = req.notes
    await row.save()

    # 如果更新的是激活环境，缓存失效（新 URL/账号立刻生效）
    if row.is_active:
        invalidate_cache()

    logger.info(f"更新执行环境: env_id={env_id}")
    return {"code": 200, "msg": "已更新", "success": True, "data": _serialize(row)}


@router.delete("/{env_id}", summary="删除环境")
async def delete_environment(env_id: str):
    from app.models.api_automation import ExecutionEnvironment
    from app.services.environment_service import invalidate_cache

    row = await ExecutionEnvironment.filter(env_id=env_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"环境不存在: {env_id}")
    if row.is_active:
        raise HTTPException(
            status_code=400,
            detail="当前激活环境不能直接删除，请先激活其他环境或先停用",
        )
    await row.delete()
    invalidate_cache()
    logger.info(f"删除执行环境: env_id={env_id} name={row.name}")
    return {"code": 200, "msg": "已删除", "success": True}


@router.post("/{env_id}/activate", summary="激活环境")
async def activate_environment_endpoint(env_id: str):
    from app.services.environment_service import activate_environment

    try:
        row = await activate_environment(env_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "code": 200, "msg": f"已激活: {row.label}",
        "success": True, "data": _serialize(row),
    }


@router.post("/deactivate-all", summary="停用所有环境（回退到 .env）")
async def deactivate_all_endpoint():
    from app.services.environment_service import deactivate_all
    n = await deactivate_all()
    return {
        "code": 200, "msg": f"已停用 {n} 个激活环境，将回退到 .env",
        "success": True, "data": {"deactivated": n},
    }
