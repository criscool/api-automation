"""UI 自动化 - 脚本管理接口

POST   /scripts/generate           基于已有 analysis_id 触发 AI 脚本生成
POST   /scripts/manual             手动新建脚本（不走 AI 流水线）
GET    /scripts                    分页列表
GET    /scripts/{script_id}        详情
PUT    /scripts/{script_id}        编辑（更新 content / name / status / base_url 等）
DELETE /scripts/{script_id}        删除（同步删除工作目录文件）

阶段二验收：脚本可保存到数据库 + 可在脚本管理页面查询。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from tortoise.expressions import Q

from app.services.ui_automation.orchestrator import (
    UiAutomationDisabledError,
    ui_orchestrator,
)
from app.settings.config import settings


router = APIRouter(tags=["UI自动化-脚本管理"])


# ============================================================================
# 请求模型
# ============================================================================


class GenerateScriptRequest(BaseModel):
    page_analysis_id: str = Field(..., description="关联的 PageAnalysisOutput.analysis_id")
    script_type: str = Field(..., description="playwright_classic / playwright_midscene / yaml_midscene")
    script_name: str = Field(..., description="脚本名称")
    user_intent: str = Field("", description="用户补充测试意图（可选）")
    target_url: Optional[str] = Field(None, description="覆盖 page_analysis.page_url 的目标 URL")
    project_id: Optional[int] = Field(None, description="项目 ID（可选）")
    session_id: Optional[str] = Field(None, description="会话 ID（不传则自动生成）")


class ManualScriptRequest(BaseModel):
    name: str = Field(..., description="脚本名称")
    script_type: str = Field(..., description="playwright_classic / playwright_midscene / yaml_midscene")
    content: str = Field(..., description="脚本完整内容")
    auxiliary_files: Dict[str, str] = Field(default_factory=dict, description="附属文件（fixture.ts 等）")
    page_analysis_id: Optional[str] = Field(None, description="关联分析 ID（可选）")
    description: str = Field("", description="脚本描述（可选）")
    base_url: str = Field("", description="脚本默认 base_url（可选）")


class UpdateScriptRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    base_url: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None


# ============================================================================
# 辅助
# ============================================================================


_VALID_SCRIPT_TYPES = {"playwright_classic", "playwright_midscene", "yaml_midscene"}


def _scripts_dir() -> Path:
    p = Path(settings.UI_AUTOMATION_WORKSPACE) / "scripts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_script_file(file_name: str, content: str) -> str:
    safe_name = os.path.basename(file_name) or f"{uuid.uuid4().hex}.txt"
    abs_path = _scripts_dir() / safe_name
    abs_path.write_text(content, encoding="utf-8")
    return os.path.join("scripts", safe_name).replace("\\", "/")


# ============================================================================
# 路由
# ============================================================================


@router.get("/check/{analysis_id}", summary="检查分析记录是否已有关联脚本或正在生成")
async def check_script_status(analysis_id: str):
    try:
        from app.models.ui_automation import UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    # 1. 检查是否已有生成成功的脚本
    existing_script = await UiTestScript.filter(analysis_id=analysis_id, status="active").first()
    if existing_script:
        return {
            "code": 200,
            "msg": "已存在脚本",
            "data": {
                "exists": True,
                "script_id": existing_script.script_id,
                "status": "completed"
            },
            "success": True
        }

    # 2. 检查是否有正在生成的会话 (Orchestrator 维护)
    active_session_id = ui_orchestrator.get_active_session_by_analysis(analysis_id)
    if active_session_id:
        return {
            "code": 200,
            "msg": "脚本正在生成中",
            "data": {
                "exists": False,
                "session_id": active_session_id,
                "status": "processing"
            },
            "success": True
        }

    return {
        "code": 200,
        "msg": "尚未生成脚本",
        "data": {"exists": False, "status": "none"},
        "success": True
    }


@router.post("/generate", summary="基于分析结果触发 AI 脚本生成")
async def generate_script(req: GenerateScriptRequest):
    if req.script_type not in _VALID_SCRIPT_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的 script_type: {req.script_type}")

    try:
        from app.agents.ui_automation.schemas import ScriptGenerationInput, ScriptType
        from app.models.ui_automation import UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    # 防重：如果已经有成功的脚本，不再生成
    existing = await UiTestScript.filter(analysis_id=req.page_analysis_id, status="active").first()
    if existing:
        return {
            "code": 200,
            "msg": "脚本已存在，无需重复生成",
            "data": {"script_id": existing.script_id, "is_reused": True},
            "success": True
        }

    # 自愈:DB 没有 active 脚本但 orchestrator 内存还锁着 → 视为脏锁清掉,
    # 防止"脚本被删了但内存锁未释放,后续 /scripts/check 永远报正在生成中"
    stale_session = ui_orchestrator.get_active_session_by_analysis(req.page_analysis_id)
    if stale_session:
        logger.warning(
            f"检测到脏的脚本生成锁(DB 无活跃脚本但内存有锁): "
            f"analysis_id={req.page_analysis_id} stale_session={stale_session},清掉重新生成"
        )
        ui_orchestrator.clear_script_gen_lock(req.page_analysis_id)

    session_id = req.session_id or f"ui_gen_{uuid.uuid4().hex[:12]}"
    try:
        script_input = ScriptGenerationInput(
            session_id=session_id,
            page_analysis_id=req.page_analysis_id,
            script_type=ScriptType(req.script_type),
            script_name=req.script_name,
            user_intent=req.user_intent,
            target_url=req.target_url,
            project_id=req.project_id,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        await ui_orchestrator.generate_script(script_input)
    except UiAutomationDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception(f"脚本生成投递失败: {e}")
        raise HTTPException(status_code=500, detail=f"脚本生成投递失败: {e}")

    return {
        "code": 200,
        "msg": "已投递脚本生成",
        "data": {"session_id": session_id, "script_type": req.script_type},
        "success": True,
    }


@router.post("/manual", summary="手动新建脚本（不走 AI 流水线）")
async def create_manual_script(req: ManualScriptRequest):
    if req.script_type not in _VALID_SCRIPT_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的 script_type: {req.script_type}")

    try:
        from app.models.ui_automation import UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    script_id = f"ui_manual_{uuid.uuid4().hex[:12]}"
    ext = ".spec.ts" if req.script_type.startswith("playwright") else ".yaml"
    file_name = f"{script_id}{ext}"

    file_path = ""
    try:
        file_path = await asyncio.to_thread(_write_script_file, file_name, req.content)
        for aux_name, aux_content in (req.auxiliary_files or {}).items():
            await asyncio.to_thread(_write_script_file, aux_name, aux_content)
    except Exception as fs_err:
        logger.warning(f"手动脚本写文件失败,仅入库: {fs_err}")

    obj = await UiTestScript.create(
        script_id=script_id,
        analysis_id=req.page_analysis_id or "",
        name=req.name,
        description=req.description,
        script_type=req.script_type,
        source_type="manual",
        content=req.content,
        file_path=file_path,
        tags=[],
        status="active",
        base_url=req.base_url,
        created_by="manual",
    )

    return {
        "code": 200,
        "msg": "创建成功",
        "data": {"script_id": obj.script_id, "file_path": file_path},
        "success": True,
    }


@router.get("", summary="分页查询脚本列表")
async def list_scripts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = Query(None, description="按名称/描述模糊匹配"),
    script_type: Optional[str] = Query(None, description="过滤脚本类型"),
    source_type: Optional[str] = Query(None, description="ai / manual"),
    include_archived: bool = Query(False, description="是否含归档(软删)脚本"),
):
    try:
        from app.models.ui_automation import UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    qs = UiTestScript.all().order_by("-id")
    if not include_archived:
        # 默认不含 archived,前端列表干净;后台审计需要看历史时传 include_archived=true
        qs = qs.exclude(status="archived")
    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
    if script_type:
        qs = qs.filter(script_type=script_type)
    if source_type:
        qs = qs.filter(source_type=source_type)

    total = await qs.count()
    rows = await qs.offset((page - 1) * page_size).limit(page_size)
    items: List[Dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "script_id": row.script_id,
                "name": row.name,
                "description": row.description,
                "script_type": row.script_type,
                "source_type": row.source_type,
                "analysis_id": row.analysis_id,
                "file_path": row.file_path,
                "status": row.status,
                "base_url": row.base_url,
                "tags": row.tags,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )

    return {
        "code": 200,
        "msg": "OK",
        "data": {"total": total, "page": page, "page_size": page_size, "items": items},
        "success": True,
    }


@router.get("/{script_id}", summary="脚本详情")
async def get_script(script_id: str):
    try:
        from app.models.ui_automation import UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    row = await UiTestScript.filter(script_id=script_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"脚本不存在: {script_id}")

    return {
        "code": 200,
        "msg": "OK",
        "data": {
            "script_id": row.script_id,
            "name": row.name,
            "description": row.description,
            "script_type": row.script_type,
            "source_type": row.source_type,
            "analysis_id": row.analysis_id,
            "content": row.content,
            "file_path": row.file_path,
            "status": row.status,
            "base_url": row.base_url,
            "tags": row.tags,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
        "success": True,
    }


@router.put("/{script_id}", summary="更新脚本")
async def update_script(script_id: str, req: UpdateScriptRequest):
    try:
        from app.models.ui_automation import UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    row = await UiTestScript.filter(script_id=script_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"脚本不存在: {script_id}")

    changed = False
    if req.name is not None:
        row.name = req.name
        changed = True
    if req.description is not None:
        row.description = req.description
        changed = True
    if req.base_url is not None:
        row.base_url = req.base_url
        changed = True
    if req.status is not None:
        row.status = req.status
        changed = True
    if req.tags is not None:
        row.tags = req.tags
        changed = True
    if req.content is not None:
        row.content = req.content
        changed = True
        # 同步重写文件
        if row.file_path:
            try:
                abs_path = Path(settings.UI_AUTOMATION_WORKSPACE) / row.file_path
                await asyncio.to_thread(_write_script_file, abs_path.name, req.content)
            except Exception as e:
                logger.warning(f"更新脚本文件失败 script_id={script_id}: {e}")

    if changed:
        await row.save()

    return {"code": 200, "msg": "已更新", "data": {"script_id": script_id}, "success": True}


@router.delete("/{script_id}", summary="删除脚本")
async def delete_script(script_id: str):
    try:
        from app.models.ui_automation import UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    row = await UiTestScript.filter(script_id=script_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"脚本不存在: {script_id}")

    # 工作目录文件清理（生成产物，非用户数据）
    if row.file_path:
        try:
            file_abs = Path(settings.UI_AUTOMATION_WORKSPACE) / row.file_path
            if file_abs.exists() and file_abs.is_file():
                await asyncio.to_thread(file_abs.unlink)
        except Exception as e:
            logger.warning(f"删除脚本文件失败 script_id={script_id} err={e}")

    associated_analysis_id = row.analysis_id
    await row.delete()

    # 同步清掉 orchestrator 的脚本生成内存锁,否则用户删完想重新生成时
    # /scripts/check 仍报"正在生成中",前端进不去生成入口
    if associated_analysis_id:
        ui_orchestrator.clear_script_gen_lock(associated_analysis_id)

    return {"code": 200, "msg": "已删除", "data": {"script_id": script_id}, "success": True}
