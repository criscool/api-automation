"""
平台文档管理 API — 支持 Markdown 文件的增删查 + 置顶
文件存储在 backend/docs/ 目录
"""

import json
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from loguru import logger

router = APIRouter(tags=["文档管理"])

DOCS_DIR = Path(__file__).resolve().parents[4] / "docs"
PINNED_FILE = DOCS_DIR / ".pinned.json"


def _ensure_docs_dir():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)


def _read_pinned() -> List[str]:
    """读取置顶文档列表，返回有序的文件名数组"""
    if not PINNED_FILE.exists():
        return []
    try:
        data = json.loads(PINNED_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_pinned(pinned: List[str]):
    PINNED_FILE.write_text(json.dumps(pinned, ensure_ascii=False), encoding="utf-8")


class DocItem(BaseModel):
    filename: str
    title: str
    size: int
    pinned: bool = False


@router.get("", summary="获取文档列表")
async def list_docs():
    """列出所有 .md 文档文件，置顶的排在前面"""
    _ensure_docs_dir()
    pinned_list = _read_pinned()
    pinned_set = set(pinned_list)

    docs: List[DocItem] = []
    for f in sorted(DOCS_DIR.glob("*.md")):
        docs.append(DocItem(
            filename=f.name,
            title=f.stem,
            size=f.stat().st_size,
            pinned=f.name in pinned_set,
        ))

    # 置顶的排在前面，按 pinned.json 中的顺序
    docs.sort(key=lambda d: (
        not d.pinned,
        pinned_list.index(d.filename) if d.filename in pinned_list else 999,
        d.filename,
    ))

    return {
        "code": 200,
        "msg": "OK",
        "data": [d.model_dump() for d in docs],
        "success": True,
    }


@router.get("/{filename}", summary="获取文档内容")
async def get_doc(filename: str):
    """获取指定 .md 文档的原始内容"""
    _ensure_docs_dir()
    filepath = DOCS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文档不存在: {filename}")
    if filepath.suffix != ".md":
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")
    content = filepath.read_text(encoding="utf-8")
    return {
        "code": 200,
        "msg": "OK",
        "data": {
            "filename": filename,
            "title": filepath.stem,
            "content": content,
            "size": filepath.stat().st_size,
        },
        "success": True,
    }


@router.post("/upload", summary="上传文档")
async def upload_doc(file: UploadFile = File(...)):
    """上传或覆盖一个 .md 文档"""
    _ensure_docs_dir()
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")
    safe_name = Path(file.filename).name
    filepath = DOCS_DIR / safe_name
    content = await file.read()
    filepath.write_bytes(content)
    logger.info(f"文档已保存: {filepath}")
    return {
        "code": 200,
        "msg": "上传成功",
        "data": {
            "filename": safe_name,
            "title": filepath.stem,
            "size": filepath.stat().st_size,
        },
        "success": True,
    }


@router.delete("/{filename}", summary="删除文档")
async def delete_doc(filename: str):
    """删除一个 .md 文档，同时清理置顶记录"""
    _ensure_docs_dir()
    filepath = DOCS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文档不存在: {filename}")
    if filepath.suffix != ".md":
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")
    os.remove(filepath)
    # 同时从置顶列表中移除
    pinned = _read_pinned()
    if filename in pinned:
        pinned.remove(filename)
        _write_pinned(pinned)
    logger.info(f"文档已删除: {filepath}")
    return {
        "code": 200,
        "msg": "已删除",
        "success": True,
    }


@router.post("/{filename}/pin", summary="置顶文档")
async def pin_doc(filename: str):
    """将文档置顶"""
    _ensure_docs_dir()
    filepath = DOCS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文档不存在: {filename}")
    if filepath.suffix != ".md":
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")
    pinned = _read_pinned()
    if filename not in pinned:
        pinned.insert(0, filename)
        _write_pinned(pinned)
    return {"code": 200, "msg": "已置顶", "success": True}


@router.post("/{filename}/unpin", summary="取消置顶")
async def unpin_doc(filename: str):
    """取消文档置顶"""
    _ensure_docs_dir()
    filepath = DOCS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文档不存在: {filename}")
    pinned = _read_pinned()
    if filename in pinned:
        pinned.remove(filename)
        _write_pinned(pinned)
    return {"code": 200, "msg": "已取消置顶", "success": True}
