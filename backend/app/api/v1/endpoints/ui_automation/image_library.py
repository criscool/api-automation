"""UI 图片库 - 5 个 API 接口

POST   /upload                — 上传图片(支持 SHA256 自动查重复用)
GET    /                      — 分页列表(支持 keyword/page_type/tag 过滤)
GET    /{image_id}            — 详情
PATCH  /{image_id}            — 更新元数据(title/description/tags/page_type)
DELETE /{image_id}            — 删除(reference_count>0 时返回 409,?force=true 强删)

零回归:
- 仅在 UI_AUTOMATION_ENABLED 时挂载
- 与既有 /ui-automation/screenshots 物理隔离(不同 service、不同存储目录)
- 不修改 page-analysis 既有入口(兼容层在 S5 单独做)

图片二进制访问:走 app/__init__.py mount 的 /static/ui-images/...,不在本路由暴露
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.services.ui_automation import image_library_service as svc
from app.services.ui_automation.image_library_service import ImageLibraryError
from app.settings.config import settings


router = APIRouter(tags=["UI自动化-图片库"])


# ============================================================
# 请求/响应 schema
# ============================================================
class UpdateImageMetaIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    page_type: Optional[str] = None


# ============================================================
# 公共工具
# ============================================================
def _check_enabled():
    if not settings.UI_AUTOMATION_ENABLED:
        raise HTTPException(status_code=503, detail="UI 自动化模块未启用")


def _to_http(e: ImageLibraryError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.message)


# ============================================================
# 1. 上传
# ============================================================
@router.post("/upload", summary="上传图片到图片库(SHA256 自动查重)")
async def upload_to_library(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    tags: str = Form("", description="逗号分隔的标签,例: login,critical"),
    page_type: str = Form(""),
    uploaded_by: str = Form(""),
):
    _check_enabled()
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    content = await file.read()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    try:
        result = await svc.upload_image(
            file_bytes=content,
            original_name=file.filename,
            mime_type=file.content_type or "",
            title=title,
            description=description,
            tags=tag_list,
            page_type=page_type,
            uploaded_by=uploaded_by,
        )
    except ImageLibraryError as e:
        raise _to_http(e)

    data = svc.serialize(result.record)
    data["is_duplicate"] = result.is_duplicate

    return {
        "code": 200,
        "msg": "已存在(命中 SHA256)" if result.is_duplicate else "上传成功",
        "data": data,
        "success": True,
    }


# ============================================================
# 2. 列表
# ============================================================
@router.get("", summary="分页列出图片库")
async def list_library(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query("", description="匹配 title/description/original_name"),
    page_type: str = Query("", description="按页面类型筛选"),
    tag: str = Query("", description="按单个 tag 筛选"),
):
    _check_enabled()
    data = await svc.list_images(
        page=page,
        page_size=page_size,
        keyword=keyword,
        page_type=page_type,
        tag=tag,
    )
    return {"code": 200, "msg": "OK", "data": data, "success": True}


# ============================================================
# 3. 详情
# ============================================================
@router.get("/{image_id}", summary="图片详情")
async def get_library_image(image_id: str):
    _check_enabled()
    try:
        rec = await svc.get_image(image_id)
    except ImageLibraryError as e:
        raise _to_http(e)
    return {
        "code": 200,
        "msg": "OK",
        "data": svc.serialize(rec),
        "success": True,
    }


# ============================================================
# 4. 更新元数据
# ============================================================
@router.patch("/{image_id}", summary="更新图片元数据(不动文件)")
async def update_library_image(image_id: str, payload: UpdateImageMetaIn):
    _check_enabled()
    try:
        rec = await svc.update_meta(
            image_id,
            title=payload.title,
            description=payload.description,
            tags=payload.tags,
            page_type=payload.page_type,
        )
    except ImageLibraryError as e:
        raise _to_http(e)
    return {
        "code": 200,
        "msg": "已更新",
        "data": svc.serialize(rec),
        "success": True,
    }


# ============================================================
# 5. 删除
# ============================================================
@router.delete("/{image_id}", summary="删除图片(reference_count>0 默认 409)")
async def delete_library_image(
    image_id: str,
    force: bool = Query(False, description="true 时即便有引用也强制删除"),
):
    _check_enabled()
    try:
        result = await svc.delete_image(image_id, force=force)
    except ImageLibraryError as e:
        raise _to_http(e)
    return {
        "code": 200,
        "msg": "已删除",
        "data": result,
        "success": True,
    }
