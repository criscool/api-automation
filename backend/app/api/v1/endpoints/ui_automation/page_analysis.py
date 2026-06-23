"""UI 自动化 - 页面分析接口

POST /page-analysis/analyze              触发页面分析（image/text/hybrid 三种 analysis_type 统一入口）
GET  /page-analysis/stream/{session_id}  SSE 订阅分析进度
GET  /page-analysis                       分页查询历史分析记录
GET  /page-analysis/{analysis_id}        查询单条分析记录详情（含元素清单）
DELETE /page-analysis/{analysis_id}      删除一条分析记录及其元素
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from tortoise.expressions import Q

from app.services.ui_automation.orchestrator import (
    UiAutomationDisabledError,
    ui_orchestrator,
)
from app.services.ui_automation import image_library_service as image_lib
from app.services.ui_automation.image_library_service import ImageLibraryError


router = APIRouter(tags=["UI自动化-页面分析"])


class AnalyzeRequest(BaseModel):
    analysis_type: str = Field(..., description="image / text / hybrid / live_url")
    page_name: str = Field(..., description="页面名称")
    page_url: Optional[str] = Field(None, description="页面 URL（可选）")
    screenshot_path: Optional[str] = Field(None, description="截图服务器路径（image/hybrid 必填,或改用 image_id）")
    image_id: Optional[str] = Field(None, description="图片库 image_id(优先级高于 screenshot_path)")
    text_description: Optional[str] = Field(None, description="文字测试需求（text/hybrid 必填）")
    project_id: Optional[int] = Field(None, description="项目 ID（可选）")
    session_id: Optional[str] = Field(None, description="会话 ID（不传则自动生成）")
    # live_url 模式专用(crawl4ai 实时抓取)
    live_url: Optional[str] = Field(None, description="实时抓取的目标 URL(live_url 模式必填)")
    storage_state_relpath: Optional[str] = Field(
        None,
        description="登录态 storage state 相对 UI_AUTOMATION_WORKSPACE 的路径(live_url 模式可选,不填则未登录抓)",
    )


@router.post("/analyze", summary="触发页面分析")
async def analyze(req: AnalyzeRequest):
    try:
        from app.agents.ui_automation.schemas import AnalysisType, PageAnalysisInput
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化未启用或模块加载失败: {e}")

    try:
        analysis_type = AnalysisType(req.analysis_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"不支持的 analysis_type: {req.analysis_type}")

    # ============================================================
    # 图片库兼容层(阶段四 S5)
    # - image_id 优先于 screenshot_path:翻译为绝对路径
    # - 引用计数 +1,last_used_at 刷新(防误删 + 排序)
    # - 老的 screenshot_path 直接落盘路径继续可用,不破坏既有链路
    # ============================================================
    resolved_screenshot_path = req.screenshot_path
    resolved_image_id = req.image_id

    if resolved_image_id:
        try:
            resolved_screenshot_path = await image_lib.get_file_path(resolved_image_id)
            await image_lib.increment_reference(resolved_image_id)
            logger.info(
                f"page-analysis 走图片库: image_id={resolved_image_id} → {resolved_screenshot_path}"
            )
        except ImageLibraryError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message)

    # 1. 生成请求指纹，用于防重(把 image_id 也算进去,避免不同图被合并)
    import hashlib
    fingerprint_content = (
        f"{req.page_name}_{req.page_url or ''}_{resolved_image_id or ''}"
        f"_{resolved_screenshot_path or ''}_{req.text_description or ''}"
    )
    fingerprint = hashlib.md5(fingerprint_content.encode()).hexdigest()

    # 2. 检查编排器中是否有正在进行的相同任务
    existing_session_id = ui_orchestrator.get_active_session_by_fingerprint(fingerprint)
    if existing_session_id:
        logger.info(f"检测到重复分析请求，复用现有会话: {existing_session_id}")
        return {
            "code": 200,
            "msg": "该页面分析任务已在运行中，已自动关联",
            "data": {"session_id": existing_session_id, "is_reused": True, "fingerprint": fingerprint},
            "success": True,
        }

    session_id = req.session_id or f"ui_{uuid.uuid4().hex[:12]}"

    try:
        analysis_input = PageAnalysisInput(
            session_id=session_id,
            analysis_type=analysis_type,
            page_name=req.page_name,
            page_url=req.page_url,
            screenshot_path=resolved_screenshot_path,
            text_description=req.text_description,
            project_id=req.project_id,
            fingerprint=fingerprint,
            live_url=req.live_url,
            storage_state_relpath=req.storage_state_relpath,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        await ui_orchestrator.analyze_page(analysis_input)
    except UiAutomationDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception(f"分析投递失败: {e}")
        raise HTTPException(status_code=500, detail=f"分析投递失败: {e}")

    return {
        "code": 200,
        "msg": "已投递分析任务",
        "data": {
            "session_id": session_id,
            "analysis_type": req.analysis_type,
            "image_id": resolved_image_id,
        },
        "success": True,
    }


@router.get("/stream/{session_id}", summary="SSE 订阅页面分析进度")
async def stream(session_id: str):
    if not ui_orchestrator.is_running:
        # 编排器尚未启动也允许订阅（队列可正常等首条消息），但若 module disable 直接返回
        try:
            await ui_orchestrator.initialize()
        except UiAutomationDisabledError as e:
            raise HTTPException(status_code=503, detail=str(e))

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    done_flag = {"done": False}

    async def _cb(payload: Dict[str, Any]) -> None:
        await queue.put(payload)
        if payload.get("is_final"):
            done_flag["done"] = True

    ui_orchestrator.subscribe(session_id, _cb)

    async def event_gen():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # 心跳，避免代理中断
                    yield {"event": "ping", "data": json.dumps({"ts": asyncio.get_event_loop().time()})}
                    continue
                yield {
                    "event": "message",
                    "data": json.dumps(payload, ensure_ascii=False, default=str),
                }
                if done_flag["done"] and queue.empty():
                    break
        finally:
            ui_orchestrator.unsubscribe(session_id, _cb)

    return EventSourceResponse(event_gen())


@router.get("", summary="分页查询页面分析记录")
async def list_analyses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = Query(None, description="按 page_name / page_type 模糊匹配"),
):
    try:
        from app.models.ui_automation import UiPageAnalysisResult
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    qs = UiPageAnalysisResult.all().order_by("-id")
    if keyword:
        qs = qs.filter(
            Q(page_type__icontains=keyword)
            | Q(user_description__icontains=keyword)
            | Q(page_summary__icontains=keyword)
        )

    total = await qs.count()
    rows = await qs.offset((page - 1) * page_size).limit(page_size)
    items: List[Dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "analysis_id": row.analysis_id,
                "session_id": row.session_id,
                "source_type": row.source_type,
                "page_type": row.page_type,
                "page_summary": row.page_summary,
                "from_fallback": row.from_fallback,
                "status": row.status,
                "elements_count": len(row.elements or []),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    return {
        "code": 200,
        "msg": "OK",
        "data": {"total": total, "page": page, "page_size": page_size, "items": items},
        "success": True,
    }


@router.get("/{analysis_id}", summary="获取分析详情")
async def get_analysis(analysis_id: str):
    try:
        from app.models.ui_automation import UiPageAnalysisResult, UiPageElement
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    # 优先从内存缓存返回（命中时不带 DB 元素行，但 raw_response 完整）
    cached = ui_orchestrator.get_analysis_result(analysis_id)
    row = await UiPageAnalysisResult.filter(analysis_id=analysis_id).first()
    if not row and not cached:
        raise HTTPException(status_code=404, detail=f"分析记录不存在: {analysis_id}")

    detail: Dict[str, Any]
    if row:
        elements = await UiPageElement.filter(analysis_id=analysis_id).order_by("order_index").all()
        detail = {
            "analysis_id": row.analysis_id,
            "session_id": row.session_id,
            "source_type": row.source_type,
            "source_path": row.source_path,
            "user_description": row.user_description,
            "page_type": row.page_type,
            "page_summary": row.page_summary,
            "elements": row.elements or [],
            "suggested_steps": row.suggested_steps or [],
            "from_fallback": row.from_fallback,
            "status": row.status,
            "raw_response": row.raw_response,
            "elements_rows": [
                {
                    "element_id": el.element_id,
                    "element_type": el.element_type,
                    "name": el.name,
                    "selector": el.selector,
                    "selector_type": el.selector_type,
                    "fallback_selectors": el.fallback_selectors,
                    "text_content": el.text_content,
                    "bbox": el.bbox,
                    "confidence": el.confidence,
                    "order_index": el.order_index,
                }
                for el in elements
            ],
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    else:
        detail = {"analysis_id": analysis_id, "raw_response": cached, "from_cache": True}

    return {"code": 200, "msg": "OK", "data": detail, "success": True}


@router.delete("/{analysis_id}", summary="删除分析记录")
async def delete_analysis(analysis_id: str):
    try:
        from app.models.ui_automation import UiPageAnalysisResult, UiPageElement
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    deleted_main = await UiPageAnalysisResult.filter(analysis_id=analysis_id).delete()
    deleted_el = await UiPageElement.filter(analysis_id=analysis_id).delete()
    if deleted_main == 0 and deleted_el == 0:
        raise HTTPException(status_code=404, detail=f"分析记录不存在: {analysis_id}")
    return {
        "code": 200,
        "msg": "已删除",
        "data": {"analysis_id": analysis_id, "elements_deleted": deleted_el},
        "success": True,
    }
