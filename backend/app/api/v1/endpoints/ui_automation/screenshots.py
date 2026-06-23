"""UI 自动化 - 截图上传

POST /screenshots/upload
- 校验 MIME / 后缀（jpg/jpeg/png/webp/bmp）
- 校验大小（默认 10MB，由 UI_SCREENSHOT_MAX_MB 控制；未配置时取 10）
- 保存到 ``{UI_AUTOMATION_WORKSPACE}/screenshots/uploads/<uuid>.<ext>``
- 返回服务器侧绝对路径 + 相对路径（前端发起分析时回填到 PageAnalysisInput.screenshot_path）
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from loguru import logger

from app.settings.config import settings


router = APIRouter(tags=["UI自动化-截图"])

_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_ALLOWED_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
}


def _max_mb() -> int:
    return getattr(settings, "UI_SCREENSHOT_MAX_MB", 10) or 10


def _uploads_dir() -> Path:
    p = Path(settings.UI_AUTOMATION_WORKSPACE) / "screenshots" / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.post("/upload", summary="上传页面截图")
async def upload_screenshot(file: UploadFile = File(...)):
    if not settings.UI_AUTOMATION_ENABLED:
        raise HTTPException(status_code=503, detail="UI 自动化模块未启用")

    logger.info(
        f"截图上传请求: filename={file.filename!r} content_type={file.content_type!r}"
    )

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {ext}，仅允许: {', '.join(sorted(_ALLOWED_EXTS))}",
        )

    if file.content_type and file.content_type not in _ALLOWED_MIMES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 MIME 类型 {file.content_type}",
        )

    content = await file.read()
    max_bytes = _max_mb() * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过大小限制 {_max_mb()}MB（实际 {len(content) // 1024}KB）",
        )
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    uploads = _uploads_dir()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    abs_path = uploads / safe_name
    abs_path.write_bytes(content)

    rel_path = os.path.relpath(abs_path, settings.UI_AUTOMATION_WORKSPACE)
    logger.info(f"截图上传成功: file={safe_name} size={len(content)}B")

    return {
        "code": 200,
        "msg": "上传成功",
        "data": {
            "filename": safe_name,
            "original_name": file.filename,
            "size": len(content),
            "screenshot_path": str(abs_path).replace("\\", "/"),
            "relative_path": rel_path.replace("\\", "/"),
        },
        "success": True,
    }
