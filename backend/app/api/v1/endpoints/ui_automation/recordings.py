"""UI 自动化 - 录制接口(阶段四 P4-05)

录制相关(两步触发,与 executions.py 同源风格):
  POST   /ui-automation/recordings                      预创建 idle 会话 + 返回 sse_endpoint
  GET    /ui-automation/recordings                       分页查询录制列表
  GET    /ui-automation/recordings/{session_id}          录制详情(含 final_script)
  POST   /ui-automation/recordings/{session_id}/cancel   取消录制(杀 codegen 子进程)
  POST   /ui-automation/recordings/{session_id}/repolish 对已录制脚本重新跑 LLM 优化(不开浏览器)
  GET    /ui-automation/recordings/{session_id}/events?session_sid=...  SSE 实时进度

两步触发动机与 executions 一致:GET /events 内部 kickoff 才投递 Topic,
保证前端 SSE 订阅一定早于 codegen 子进程启动,不会丢早期"浏览器即将弹出"提示。

零回归:整段路由仅在 settings.UI_AUTOMATION_ENABLED 且 settings.UI_RECORDING_ENABLED 时挂载。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.services.ui_automation.orchestrator import (
    UiAutomationDisabledError,
    ui_orchestrator,
)
from app.settings.config import settings


recordings_router = APIRouter(tags=["UI自动化-录制"])
recordings_stream_router = APIRouter(tags=["UI自动化-录制-SSE"])


# ============================================================================
# kickoff 去重(进程内单例,够用)
# ============================================================================
_started_recordings: Set[str] = set()
_kickoff_lock: asyncio.Lock = asyncio.Lock()


async def _kickoff_recording(session_id: str) -> None:
    """SSE 订阅生效后真正投递 codegen 启动 Topic。

    幂等:同一个 session_id 重复调用最多投递一次。
    原子性:DB 用 status='idle' 作筛选条件做 update,赢家才投递。
    """
    try:
        from app.agents.ui_automation.schemas import StartCodegenInput
        from app.models.ui_automation import UiRecordingSession
    except Exception as e:
        logger.warning(f"[recording-kickoff {session_id}] 模块加载失败: {e}")
        return

    async with _kickoff_lock:
        if session_id in _started_recordings:
            return
        _started_recordings.add(session_id)

    row = await UiRecordingSession.filter(session_id=session_id).first()
    if not row:
        logger.warning(f"[recording-kickoff {session_id}] 会话记录不存在")
        _started_recordings.discard(session_id)
        return

    meta = row.metadata or {}
    timeout_seconds = meta.get("timeout_seconds")
    script_style = (meta.get("script_style") or "playwright").strip().lower()
    if script_style not in ("midscene", "playwright"):
        script_style = "playwright"
    prefetch_flag = bool(meta.get("prefetch_page_semantics", False))

    # 原子状态迁移:只有把 idle 改成 launching 成功的那次才真正投递
    affected = await UiRecordingSession.filter(
        session_id=session_id, status="idle"
    ).update(status="launching")
    if not affected:
        logger.info(f"[recording-kickoff {session_id}] 状态已非 idle,跳过投递")
        return

    try:
        recording_input = StartCodegenInput(
            session_id=session_id,
            name=row.name,
            target_url=row.target_url,
            storage_state_relpath=row.storage_state_path or "",
            timeout_seconds=timeout_seconds,
            created_by=row.created_by or "manual",
            script_style=script_style,
            prefetch_page_semantics=prefetch_flag,
        )
    except Exception as e:
        await UiRecordingSession.filter(session_id=session_id).update(
            status="failed", error_message=f"构造录制输入失败: {e}"[:500]
        )
        return

    # 远程录制模式：通知本地守护进程，不走本地 codegen
    if settings.UI_RECORDING_MODE == "remote":
        from app.services.ui_automation.remote_recording import notify_daemon
        success = await notify_daemon(
            session_id, row.target_url, row.storage_state_path or ""
        )
        if not success:
            await UiRecordingSession.filter(session_id=session_id).update(
                status="failed",
                error_message="录制助手未连接。请在本地执行: python record-daemon.py --server <服务器地址>"
            )
        return

    try:
        await ui_orchestrator.trigger_recording(recording_input)
        logger.info(f"[recording-kickoff {session_id}] 已投递 Topic")
    except UiAutomationDisabledError as e:
        await UiRecordingSession.filter(session_id=session_id).update(
            status="failed", error_message=f"模块未启用: {e}"[:500]
        )
    except Exception as e:
        logger.exception(f"[recording-kickoff {session_id}] 投递失败")
        await UiRecordingSession.filter(session_id=session_id).update(
            status="failed", error_message=f"投递失败: {e}"[:500]
        )


# ============================================================================
# 请求模型
# ============================================================================


class CreateRecordingRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="录制名称(同时作为最终脚本文件名 stem)")
    target_url: str = Field(..., min_length=1, max_length=500, description="录制目标 URL")
    storage_state_relpath: str = Field(
        "", description="登录态文件相对 UI_AUTOMATION_WORKSPACE 路径(留空走 settings 默认值)"
    )
    timeout_seconds: Optional[int] = Field(
        None, ge=60, le=7200, description="录制超时秒(None=取 settings.UI_RECORDING_TIMEOUT)"
    )
    created_by: str = Field("manual", description="发起人")
    script_style: str = Field(
        "playwright",
        description="终态脚本风格: playwright(保留原生 getByRole,推荐;级联/弹窗都能跑) / midscene(AI 改写为 aiTap 调用,仅在原生 selector 完全无效时考虑)",
    )
    prefetch_page_semantics: Optional[bool] = Field(
        None,
        description="是否在录制开始前用 crawl4ai 预抓页面 DOM 字典(辅助 LLM 改写更稳定 selector)。"
                    "留空则取 settings.UI_CRAWL4AI_PREFETCH_DEFAULT。",
    )


class RepolishRecordingRequest(BaseModel):
    """对已录制原始脚本重新跑 AI 优化(不开浏览器)"""
    name: Optional[str] = Field(None, max_length=200, description="新的脚本名(留空沿用会话名)")
    script_style: Optional[str] = Field(
        None,
        description="终态脚本风格,留空沿用会话首次录制时的选择(metadata.script_style)",
    )


# ============================================================================
# 录制路由
# ============================================================================


@recordings_router.post("", summary="创建录制会话(不投递 Agent,等 SSE 订阅后再触发)")
async def create_recording(req: CreateRecordingRequest):
    """两步触发第一步:仅落 idle 行 + 返回 sse_endpoint。"""
    if not settings.UI_AUTOMATION_ENABLED:
        raise HTTPException(status_code=503, detail="UI 自动化模块未启用")
    if not settings.UI_RECORDING_ENABLED:
        raise HTTPException(status_code=503, detail="UI 录制功能未启用")

    try:
        from app.models.ui_automation import UiRecordingSession
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    session_id = uuid.uuid4().hex
    storage_state = req.storage_state_relpath or settings.UI_RECORDING_DEFAULT_STORAGE_STATE
    style = (req.script_style or "playwright").strip().lower()
    if style not in ("midscene", "playwright"):
        style = "playwright"

    # 预抓 page_dict 开关:请求未指定时取 settings 默认值
    if req.prefetch_page_semantics is None:
        prefetch_flag = bool(getattr(settings, "UI_CRAWL4AI_PREFETCH_DEFAULT", False))
    else:
        prefetch_flag = bool(req.prefetch_page_semantics)
    # crawl4ai 总开关关闭时,即使用户勾了也强制 False(防止前端老缓存触发)
    if not getattr(settings, "UI_CRAWL4AI_ENABLED", False):
        prefetch_flag = False

    await UiRecordingSession.create(
        session_id=session_id,
        name=req.name,
        source="codegen",
        target_url=req.target_url,
        storage_state_path=storage_state,
        status="idle",
        metadata={
            "timeout_seconds": req.timeout_seconds,
            "script_style": style,
            "prefetch_page_semantics": prefetch_flag,
        },
        created_by=req.created_by,
    )

    sse_endpoint = f"/api/v1/ui-automation/recordings/{session_id}/events?session_sid={session_id}"

    return {
        "code": 200,
        "msg": "已创建录制会话,请连接 SSE 端点触发录制",
        "data": {
            "session_id": session_id,
            "name": req.name,
            "target_url": req.target_url,
            "sse_endpoint": sse_endpoint,
        },
        "success": True,
    }


@recordings_router.get("", summary="分页查询录制列表")
async def list_recordings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: Optional[str] = Query(None, description="按状态过滤"),
):
    try:
        from app.models.ui_automation import UiRecordingSession
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    qs = UiRecordingSession.all().order_by("-id")
    if status:
        qs = qs.filter(status=status)

    total = await qs.count()
    rows = await qs.offset((page - 1) * page_size).limit(page_size)
    items: List[Dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "session_id": row.session_id,
                "name": row.name,
                "source": row.source,
                "target_url": row.target_url,
                "status": row.status,
                "raw_script_path": row.raw_script_path,
                "final_script_id": row.final_script_id,
                "duration_ms": row.duration_ms,
                "error_message": row.error_message,
                "script_style": (row.metadata or {}).get("script_style") or "playwright",
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    return {
        "code": 200,
        "msg": "OK",
        "data": {"total": total, "page": page, "page_size": page_size, "items": items},
        "success": True,
    }


@recordings_router.get("/{session_id}", summary="录制详情")
async def get_recording(session_id: str):
    try:
        from app.models.ui_automation import UiRecordingSession, UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    row = await UiRecordingSession.filter(session_id=session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"录制会话不存在: {session_id}")

    final_script = None
    if row.final_script_id:
        script_row = await UiTestScript.filter(script_id=row.final_script_id).first()
        if script_row:
            final_script = {
                "script_id": script_row.script_id,
                "name": script_row.name,
                "file_path": script_row.file_path,
                "content": script_row.content,
                "source_type": script_row.source_type,
                "status": script_row.status,
            }

    return {
        "code": 200,
        "msg": "OK",
        "data": {
            "session_id": row.session_id,
            "name": row.name,
            "source": row.source,
            "target_url": row.target_url,
            "storage_state_path": row.storage_state_path,
            "status": row.status,
            "raw_script_path": row.raw_script_path,
            "final_script_id": row.final_script_id,
            "final_script": final_script,
            "duration_ms": row.duration_ms,
            "error_message": row.error_message,
            "metadata": row.metadata,
            "script_style": (row.metadata or {}).get("script_style") or "playwright",
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        },
        "success": True,
    }


@recordings_router.delete("/{session_id}", summary="删除录制会话(可选清理原始脚本文件)")
async def delete_recording(session_id: str, purge_raw: bool = Query(True, description="是否一并删除录制原始脚本文件")):
    """删除一条录制会话记录。

    安全策略:
      - 运行中状态(launching/recording/postprocessing) 拒绝删除,请先取消
      - 终态脚本(UiTestScript) 不删 —— 它由脚本管理模块独立持有,删了会破坏脚本管理页
      - 原始脚本文件(recordings/<safe_id>.spec.ts) 默认随会话一起删,
        因为这是 codegen 为本次会话单独生成的产物,会话没了文件就是孤儿
    """
    try:
        from app.models.ui_automation import UiRecordingSession
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    row = await UiRecordingSession.filter(session_id=session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"录制会话不存在: {session_id}")

    if row.status in ("launching", "recording", "postprocessing"):
        raise HTTPException(
            status_code=400,
            detail=f"会话状态为 {row.status},请先取消再删除",
        )

    raw_deleted = False
    raw_path = row.raw_script_path or ""
    if purge_raw and raw_path:
        from pathlib import Path
        workspace = Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
        candidate = (workspace / raw_path).resolve()
        try:
            candidate.relative_to(workspace)  # 防越界
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
                raw_deleted = True
        except (ValueError, OSError) as e:
            logger.warning(f"[recording {session_id}] 清理原始脚本失败,忽略: {e}")

    await row.delete()
    _started_recordings.discard(session_id)

    return {
        "code": 200,
        "msg": "已删除",
        "data": {
            "session_id": session_id,
            "raw_script_purged": raw_deleted,
        },
        "success": True,
    }


@recordings_router.post("/{session_id}/cancel", summary="取消录制")
async def cancel_recording(session_id: str):
    try:
        from app.models.ui_automation import UiRecordingSession
        from app.services.ui_automation import codegen_runner
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    row = await UiRecordingSession.filter(session_id=session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"录制会话不存在: {session_id}")

    # 尝试杀本地 codegen 子进程（可能已死/远程录制/后端重启后进程不在）
    proc_cancelled = await codegen_runner.cancel_codegen(session_id)

    # 无论子进程是否找到，只要当前状态是"运行中"（launching/recording/postprocessing），
    # 都强制把 DB 状态改为 cancelled，避免僵尸卡住列表
    running_states = ("launching", "recording", "postprocessing")
    db_updated = False
    if row.status in running_states:
        from datetime import datetime as _dt
        await UiRecordingSession.filter(session_id=session_id).update(
            status="cancelled",
            end_time=_dt.now(),
            error_message="用户手动取消" if proc_cancelled else "用户取消（子进程已不存在，直接标终态）",
        )
        db_updated = True

    if proc_cancelled:
        msg = "已发送取消信号"
    elif db_updated:
        msg = "子进程不存在，已直接标记为已取消"
    else:
        msg = f"当前状态为 {row.status}，无需取消"

    return {
        "code": 200,
        "msg": msg,
        "data": {
            "session_id": session_id,
            "process_cancelled": proc_cancelled,
            "db_updated": db_updated,
        },
        "success": True,
    }


@recordings_router.post("/{session_id}/repolish", summary="对已录制脚本重新跑 AI 优化")
async def repolish_recording(session_id: str, req: RepolishRecordingRequest):
    """对一段已经成功录制(raw_script_path 已落地)的会话重跑 LLM 后处理。

    场景:用户对当前 AI 优化结果不满意,换 prompt 或换模型再跑一遍,不重新打开浏览器。
    """
    if not settings.UI_AUTOMATION_ENABLED:
        raise HTTPException(status_code=503, detail="UI 自动化模块未启用")
    if not settings.UI_RECORDING_ENABLED:
        raise HTTPException(status_code=503, detail="UI 录制功能未启用")

    try:
        from app.models.ui_automation import UiRecordingSession
        from app.agents.ui_automation.schemas import PostprocessRecordingInput
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    row = await UiRecordingSession.filter(session_id=session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"录制会话不存在: {session_id}")
    if not row.raw_script_path:
        raise HTTPException(
            status_code=400,
            detail="该会话没有原始脚本,无法重新优化(录制可能未完成)",
        )

    try:
        # 风格优先级:本次 repolish 请求 > 会话原本 metadata > 默认 playwright(原生优先)
        meta = row.metadata or {}
        if req.script_style:
            style = (req.script_style or "playwright").strip().lower()
        else:
            style = (meta.get("script_style") or "playwright").strip().lower()
        if style not in ("midscene", "playwright"):
            style = "playwright"

        # 把本次选定的风格写回 metadata,后续 repolish 默认沿用
        if req.script_style and style != meta.get("script_style"):
            new_meta = dict(meta)
            new_meta["script_style"] = style
            await UiRecordingSession.filter(session_id=session_id).update(metadata=new_meta)

        postprocess_input = PostprocessRecordingInput(
            session_id=session_id,
            raw_script_path=row.raw_script_path,
            target_url=row.target_url,
            name=req.name or row.name,
            created_by=row.created_by,
            script_style=style,
        )
        await ui_orchestrator.trigger_recording_postprocess(postprocess_input)
    except UiAutomationDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception(f"[recording {session_id}] 重新优化触发失败")
        raise HTTPException(status_code=500, detail=f"触发失败: {e}")

    return {
        "code": 200,
        "msg": "已触发重新优化,请订阅 SSE 查看进度",
        "data": {
            "session_id": session_id,
            "sse_endpoint": f"/api/v1/ui-automation/recordings/{session_id}/events?session_sid={session_id}",
        },
        "success": True,
    }


@recordings_stream_router.get(
    "/{session_id}/events", summary="SSE 订阅录制进度(首次订阅触发投递)"
)
async def stream_recording_events(session_id: str, session_sid: str = Query(...)):
    """两步触发第二步:订阅成功后再投递 Topic。

    Note: 参数命名为 session_sid 是为了和 FastAPI path 参数 session_id 区分,
    实际两者应该相等(由 POST /recordings 返回的 sse_endpoint 自动拼好)。
    """
    if session_sid != session_id:
        raise HTTPException(status_code=400, detail="session_sid 必须等于 session_id")

    if not ui_orchestrator.is_running:
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

    # 订阅生效后才真正投递,避免 Agent 早期消息丢失
    asyncio.create_task(_kickoff_recording(session_id))

    async def event_gen():
        try:
            yield {
                "event": "ready",
                "data": json.dumps({"session_id": session_id}, ensure_ascii=False),
            }
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield {
                        "event": "ping",
                        "data": json.dumps({"ts": asyncio.get_event_loop().time()}),
                    }
                    continue
                yield {
                    "event": "message",
                    "data": json.dumps(payload, ensure_ascii=False, default=str),
                }
                if done_flag["done"] and queue.empty():
                    break
        finally:
            ui_orchestrator.unsubscribe(session_id, _cb)
            _started_recordings.discard(session_id)

    return EventSourceResponse(event_gen())
