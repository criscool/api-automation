"""
AI 诊断与自愈 - HTTP 路由

接口：
- POST /heal/diagnose                       触发诊断
- GET  /heal/sessions/{session_id}/stream   SSE 进度
- GET  /heal/sessions/{session_id}/result   拿最终结果（轮询兜底）
- GET  /heal/sessions/{session_id}/patch    下载补丁 .patch 文件
- POST /heal/sessions/{session_id}/apply    应用补丁 + 可选重跑验证
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.services.api_automation.healer_service import healer_service


router = APIRouter()


class DiagnoseRequest(BaseModel):
    script_id: str = Field(..., description="脚本 ID（必填）")
    test_case_id: Optional[str] = Field(None, description="可选，指定具体失败用例")


@router.post("/diagnose", summary="启动一次 AI 诊断（异步）")
async def diagnose(req: DiagnoseRequest):
    """
    立即返回 session_id，实际诊断在后台跑。
    前端拿到 session_id 后用 SSE 订阅进度，或轮询 result 接口。
    """
    try:
        session = await healer_service.diagnose_async(
            script_id=req.script_id,
            test_case_id=req.test_case_id,
        )
        return {
            "code": 200,
            "msg": "OK",
            "data": {
                "session_id": session.session_id,
                "status": session.status,
            },
            "success": True,
        }
    except Exception as e:
        logger.error(f"启动诊断失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动诊断失败: {e}")


@router.get("/sessions/{session_id}/stream", summary="SSE 订阅诊断进度")
async def stream(session_id: str):
    session = await healer_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    async def event_gen():
        async for evt in healer_service.stream_events(session_id):
            import json
            yield {
                "event": evt.get("event", "message"),
                "data": json.dumps(evt.get("data", {}), ensure_ascii=False),
            }

    return EventSourceResponse(event_gen())


@router.get("/sessions/{session_id}/result", summary="获取诊断最终结果")
async def get_result(session_id: str):
    session = await healer_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    return {
        "code": 200,
        "msg": "OK",
        "data": {
            **session.to_summary(),
            "result": session.result if session.status == "DONE" else None,
        },
        "success": True,
    }


@router.get("/sessions/{session_id}/patch", summary="下载补丁 .patch")
async def download_patch(session_id: str):
    session = await healer_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    if session.status != "DONE":
        raise HTTPException(status_code=409, detail=f"session status={session.status}")

    patch_text = (session.result.get("patch") or {}).get("patch") or ""
    if not patch_text:
        raise HTTPException(status_code=404, detail="本次诊断未生成补丁")

    return PlainTextResponse(
        content=patch_text,
        media_type="text/x-diff",
        headers={
            "Content-Disposition": f'attachment; filename="heal_{session_id[:8]}.patch"',
        },
    )


class ApplyPatchRequest(BaseModel):
    rerun: bool = Field(True, description="是否在应用后立即重跑该用例验证")
    environment: str = Field("test", description="重跑使用的环境（test/staging/prod）")


@router.post("/sessions/{session_id}/apply", summary="应用补丁并可选重跑验证")
async def apply_patch(session_id: str, req: ApplyPatchRequest):
    """
    将诊断会话中的方法补丁写回脚本（DB + 文件），并可选触发 pytest 重跑：
    - rerun=True 且重跑通过 → 标记 VERIFIED_PASS，熔断计数归零
    - rerun=True 且重跑失败 → 自动回滚 content，熔断计数 +1，连续 3 次后熔断
    - rerun=False → 仅落盘，由用户手工验证
    """
    try:
        result = await healer_service.apply_patch(
            session_id=session_id,
            rerun=req.rerun,
            environment=req.environment,
        )
        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"应用补丁失败 session={session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"应用补丁失败: {e}")
