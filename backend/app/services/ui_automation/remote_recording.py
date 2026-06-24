"""
远程录制服务：WebSocket 连接管理 + 守护进程通信

设计约定:
- 单一 WebSocket 连接(一个守护进程对应一个后端实例)
- 通过 session_id 区分不同录制会话
- WebSocket 挂载在现有路由上，和 HTTP 同端口
- 守护进程断连自动清理，下次连接覆盖旧引用
- SSE 事件由现有 SSE 端点通过 DB 状态变化自动推送，本模块只更新 DB
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.settings.config import settings

router = APIRouter(tags=["UI自动化-远程录制"])

# ============================================================================
# 守护进程连接状态（单例，进程内）
# ============================================================================
_connected_ws: Optional[WebSocket] = None


# ============================================================================
# WebSocket 端点
# ============================================================================


@router.websocket("/ws/recording-daemon")
async def recording_daemon_ws(websocket: WebSocket):
    """守护进程 WebSocket 长连接。接收录制指令，回传状态和脚本。"""
    global _connected_ws

    await websocket.accept()
    if _connected_ws is not None:
        try:
            await _connected_ws.close(code=1000, reason="新守护进程连接，旧连接关闭")
        except Exception:
            pass
    _connected_ws = websocket
    logger.info("[remote-recording] 守护进程已连接")

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "status":
                await _update_status(msg["session_id"], msg.get("status", "unknown"))
            elif msg_type == "script":
                await _save_remote_script(msg["session_id"], msg.get("content", ""))
            else:
                logger.warning(f"[remote-recording] 未知消息类型: {msg_type}")
    except WebSocketDisconnect:
        logger.info("[remote-recording] 守护进程断开连接")
    except Exception:
        logger.exception("[remote-recording] WebSocket 异常")
    finally:
        if _connected_ws is websocket:
            _connected_ws = None


# ============================================================================
# 通知守护进程
# ============================================================================


async def notify_daemon(session_id: str, target_url: str, storage_state_relpath: str) -> bool:
    """通知守护进程开始录制。返回 False 表示守护进程未连接。"""
    if _connected_ws is None:
        return False
    try:
        await _connected_ws.send_json({
            "type": "record",
            "session_id": session_id,
            "target_url": target_url,
            "storage_state_relpath": storage_state_relpath,
        })
        logger.info(f"[remote-recording] 已通知守护进程: session_id={session_id}")
        return True
    except Exception:
        logger.exception("[remote-recording] 通知守护进程失败")
        return False


def daemon_connected() -> bool:
    """检查守护进程是否已连接（供前端查询）。"""
    return _connected_ws is not None


# ============================================================================
# 内部：状态更新 & 脚本保存
# ============================================================================


async def _update_status(session_id: str, status: str) -> None:
    """守护进程状态变更 → 更新 DB（SSE 自动感知变化）。"""
    from app.models.ui_automation import UiRecordingSession

    status_map = {
        "launching": "recording",
        "recording": "recording",
        "done": "completed",
        "error": "failed",
    }
    db_status = status_map.get(status, "recording")

    try:
        await UiRecordingSession.filter(session_id=session_id).update(status=db_status)
        logger.info(f"[remote-recording] 状态更新: {session_id} → {db_status}")
    except Exception:
        logger.exception(f"[remote-recording] 更新状态失败: {session_id}")


async def _save_remote_script(session_id: str, content: str) -> None:
    """守护进程回传的脚本 → 落盘 + 入库 + 触发 AI 后处理。"""
    from app.models.ui_automation import UiRecordingSession

    if not content:
        logger.warning(f"[remote-recording] 脚本为空: {session_id}")
        await UiRecordingSession.filter(session_id=session_id).update(
            status="failed", error_message="录制脚本为空"
        )
        return

    # 落盘
    raw_dir = Path(settings.UI_AUTOMATION_WORKSPACE) / settings.UI_RECORDING_RAW_SUBDIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    spec_path = raw_dir / f"{session_id}.spec.ts"
    spec_path.write_text(content, encoding="utf-8")
    logger.info(f"[remote-recording] 脚本已落盘: {spec_path}")

    # 更新 DB（raw_script 字段对齐现有 schema）
    rel_path = f"{settings.UI_RECORDING_RAW_SUBDIR}/{session_id}.spec.ts"
    row = await UiRecordingSession.filter(session_id=session_id).first()
    if not row:
        logger.warning(f"[remote-recording] 会话不存在: {session_id}")
        return

    try:
        row.raw_script_relpath = rel_path
        row.raw_script_content = content
        row.status = "postprocessing"
        await row.save()
    except Exception:
        logger.exception(f"[remote-recording] 更新 DB 失败: {session_id}")
        return

    # 触发 AI 后处理（与 repolish 流程一致）
    try:
        from app.agents.ui_automation.schemas import PostprocessRecordingInput
        postprocess_input = PostprocessRecordingInput(
            session_id=session_id,
            raw_script_path=rel_path,
            target_url=row.target_url or "",
            name=row.name or session_id,
            created_by=row.created_by or "",
            script_style="midscene",
        )
        import asyncio
        asyncio.create_task(_trigger_postprocess(postprocess_input))
    except Exception:
        logger.exception(f"[remote-recording] 触发后处理失败: {session_id}")


async def _trigger_postprocess(inp) -> None:
    """异步触发 AI 后处理。"""
    try:
        from app.services.ui_automation.orchestrator import ui_orchestrator
        await ui_orchestrator.trigger_recording_postprocess(inp)
    except Exception:
        logger.exception(f"[remote-recording] 后处理异常: {inp.session_id}")
