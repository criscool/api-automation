"""UI 图片库服务层

职责:
- 上传图片:SHA256 查重 → 不重复落盘 → 生成缩略图 → 入库
- 列表/详情/元数据更新/删除
- 引用计数维护(供 PageAnalyzer 调用)

存储布局(都在 UI_AUTOMATION_WORKSPACE 下,与 screenshots/uploads 物理隔离):
    image_library/
    ├── originals/<sha256[:2]>/<image_id>.<ext>   # 原图,按 sha256 前2位分桶,避免单目录文件过多
    └── thumbnails/<image_id>.jpg                  # 缩略图统一 JPEG,长边 320

零回归:
- 不动 screenshots/uploads(老的 page-analysis 截图上传路径继续工作)
- 不与 UiPageAnalysisResult.source_path 字段强耦合(后续 S5 兼容层处理)
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from PIL import Image
from tortoise.exceptions import DoesNotExist
from tortoise.expressions import Q

from app.models.ui_automation import UiImageLibrary
from app.settings.config import settings


# ============================================================
# 常量
# ============================================================
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_ALLOWED_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
}
_THUMB_LONG_EDGE = 320  # 缩略图长边像素
_THUMB_QUALITY = 80     # JPEG 质量


# ============================================================
# 异常
# ============================================================
class ImageLibraryError(Exception):
    """图片库相关业务错误(由 API 层包装成 HTTPException)"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ============================================================
# 路径工具
# ============================================================
def _library_root() -> Path:
    p = Path(settings.UI_AUTOMATION_WORKSPACE) / "image_library"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _originals_dir(sha256_hex: str) -> Path:
    p = _library_root() / "originals" / sha256_hex[:2]
    p.mkdir(parents=True, exist_ok=True)
    return p


def _thumbnails_dir() -> Path:
    p = _library_root() / "thumbnails"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ext_from_mime(mime: str, fallback_ext: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }
    return mapping.get(mime, fallback_ext or ".png")


# ============================================================
# 缩略图
# ============================================================
def _make_thumbnail(image_bytes: bytes, dest_path: Path) -> bool:
    """生成 JPEG 缩略图。失败不抛,只 log;缩略图缺失不阻塞上传。"""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = im.convert("RGB")
            im.thumbnail((_THUMB_LONG_EDGE, _THUMB_LONG_EDGE))
            im.save(dest_path, "JPEG", quality=_THUMB_QUALITY, optimize=True)
        return True
    except Exception as e:
        logger.warning(f"缩略图生成失败 dest={dest_path.name}: {e}")
        return False


def _read_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    """读取原图宽高,失败返回 (0, 0)"""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            return im.size  # (width, height)
    except Exception as e:
        logger.warning(f"读取图片尺寸失败: {e}")
        return (0, 0)


# ============================================================
# 上传(核心)
# ============================================================
@dataclass
class UploadResult:
    record: UiImageLibrary
    is_duplicate: bool  # 是否命中已有 SHA256(不重复落盘)


async def upload_image(
    file_bytes: bytes,
    original_name: str,
    mime_type: str,
    title: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    page_type: str = "",
    uploaded_by: str = "",
) -> UploadResult:
    """上传图片(SHA256 查重)

    返回:
        UploadResult(record, is_duplicate)
        - is_duplicate=True 时,record 是已存在的记录(同一 SHA256 命中)
        - is_duplicate=False 时,record 是新建的记录

    异常:
        ImageLibraryError:不支持的类型/空文件等
    """
    if not file_bytes:
        raise ImageLibraryError("文件为空", status_code=400)

    if mime_type and mime_type not in _ALLOWED_MIMES:
        raise ImageLibraryError(
            f"不支持的 MIME 类型 {mime_type},仅允许: {', '.join(sorted(_ALLOWED_MIMES))}",
            status_code=400,
        )

    ext = Path(original_name or "").suffix.lower()
    if ext and ext not in _ALLOWED_EXTS:
        raise ImageLibraryError(
            f"不支持的扩展名 {ext},仅允许: {', '.join(sorted(_ALLOWED_EXTS))}",
            status_code=400,
        )

    # 1. SHA256 查重
    sha256_hex = hashlib.sha256(file_bytes).hexdigest()
    existing = await UiImageLibrary.filter(sha256=sha256_hex).first()
    if existing:
        logger.info(f"图片命中 SHA256 已存在: image_id={existing.image_id} sha={sha256_hex[:12]}…")
        return UploadResult(record=existing, is_duplicate=True)

    # 2. 落盘原图
    image_id = f"img_{uuid.uuid4().hex[:16]}"
    final_ext = _ext_from_mime(mime_type, ext)
    original_path = _originals_dir(sha256_hex) / f"{image_id}{final_ext}"
    original_path.write_bytes(file_bytes)

    # 3. 缩略图(失败不阻塞)
    thumb_path = _thumbnails_dir() / f"{image_id}.jpg"
    if not _make_thumbnail(file_bytes, thumb_path):
        thumb_path_str = ""
    else:
        thumb_path_str = str(thumb_path)

    # 4. 读尺寸
    width, height = _read_dimensions(file_bytes)

    # 5. 入库
    record = await UiImageLibrary.create(
        image_id=image_id,
        sha256=sha256_hex,
        original_name=original_name or f"{image_id}{final_ext}",
        file_path=str(original_path),
        thumbnail_path=thumb_path_str,
        file_size=len(file_bytes),
        mime_type=mime_type or "image/png",
        width=width,
        height=height,
        title=title or "",
        description=description or "",
        tags=tags or [],
        page_type=page_type or "",
        reference_count=0,
        uploaded_by=uploaded_by or "",
    )
    logger.info(
        f"图片入库: image_id={image_id} sha={sha256_hex[:12]}… "
        f"size={len(file_bytes)}B dim={width}x{height} tags={tags}"
    )
    return UploadResult(record=record, is_duplicate=False)


# ============================================================
# 查询
# ============================================================
async def list_images(
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    page_type: str = "",
    tag: str = "",
) -> Dict[str, Any]:
    """分页列出图片,默认按 last_used_at desc, id desc"""
    page = max(1, page)
    page_size = max(1, min(100, page_size))

    qs = UiImageLibrary.all()
    if page_type:
        qs = qs.filter(page_type=page_type)
    if keyword:
        kw = keyword.strip()
        qs = qs.filter(
            Q(title__icontains=kw)
            | Q(description__icontains=kw)
            | Q(original_name__icontains=kw)
        )

    total = await qs.count()
    rows = (
        await qs.order_by("-last_used_at", "-id")
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # tag 在 JSONField 里,SQLite 上没法走索引;先取出再 python 过滤
    items: List[Dict[str, Any]] = []
    for r in rows:
        if tag and tag not in (r.tags or []):
            continue
        items.append(_serialize(r))

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_image(image_id: str) -> UiImageLibrary:
    try:
        return await UiImageLibrary.get(image_id=image_id)
    except DoesNotExist:
        raise ImageLibraryError(f"图片不存在: {image_id}", status_code=404)


async def get_file_path(image_id: str) -> str:
    """给 PageAnalyzer 等内部模块用:把 image_id 翻译成磁盘路径"""
    rec = await get_image(image_id)
    if not rec.file_path or not os.path.exists(rec.file_path):
        raise ImageLibraryError(f"图片文件丢失或路径无效: {image_id}", status_code=410)
    return rec.file_path


# ============================================================
# 更新元数据(不动文件)
# ============================================================
async def update_meta(
    image_id: str,
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    page_type: Optional[str] = None,
) -> UiImageLibrary:
    rec = await get_image(image_id)
    if title is not None:
        rec.title = title
    if description is not None:
        rec.description = description
    if tags is not None:
        rec.tags = tags
    if page_type is not None:
        rec.page_type = page_type
    await rec.save()
    return rec


# ============================================================
# 删除
# ============================================================
async def delete_image(image_id: str, force: bool = False) -> Dict[str, Any]:
    """删除图片

    - reference_count > 0 且 force=False → 抛 409
    - force=True 强删 + 解除引用(后续 S5 兼容层负责把 source_path 改回空)

    返回被清理的文件列表(便于审计)
    """
    rec = await get_image(image_id)
    if rec.reference_count > 0 and not force:
        raise ImageLibraryError(
            f"图片被 {rec.reference_count} 个分析引用,需先解除引用或使用 force=true",
            status_code=409,
        )

    deleted_files: List[str] = []
    for p in (rec.file_path, rec.thumbnail_path):
        if p and os.path.exists(p):
            try:
                os.remove(p)
                deleted_files.append(p)
            except OSError as e:
                logger.warning(f"删除文件失败 {p}: {e}")

    await rec.delete()
    logger.info(f"图片删除: image_id={image_id} files={len(deleted_files)} force={force}")
    return {"image_id": image_id, "deleted_files": deleted_files}


# ============================================================
# 引用计数(供 PageAnalyzer/前端勾选时调用)
# ============================================================
async def increment_reference(image_id: str) -> UiImageLibrary:
    from datetime import datetime
    rec = await get_image(image_id)
    rec.reference_count = (rec.reference_count or 0) + 1
    rec.last_used_at = datetime.now()
    await rec.save()
    return rec


async def decrement_reference(image_id: str) -> UiImageLibrary:
    rec = await get_image(image_id)
    rec.reference_count = max(0, (rec.reference_count or 0) - 1)
    await rec.save()
    return rec


# ============================================================
# 序列化
# ============================================================
def _serialize(rec: UiImageLibrary) -> Dict[str, Any]:
    return {
        "id": rec.id,
        "image_id": rec.image_id,
        "sha256": rec.sha256,
        "original_name": rec.original_name,
        "file_path": rec.file_path,
        "thumbnail_path": rec.thumbnail_path,
        "file_size": rec.file_size,
        "mime_type": rec.mime_type,
        "width": rec.width,
        "height": rec.height,
        "title": rec.title,
        "description": rec.description,
        "tags": rec.tags or [],
        "page_type": rec.page_type,
        "reference_count": rec.reference_count,
        "last_used_at": rec.last_used_at.isoformat() if rec.last_used_at else None,
        "uploaded_by": rec.uploaded_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def serialize(rec: UiImageLibrary) -> Dict[str, Any]:
    """对外公开的序列化(给 API 层和测试用)"""
    return _serialize(rec)
