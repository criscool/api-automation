"""UI 自动化 - 执行 / 报告接口(阶段三 P3-05)

执行相关(两步触发,参照原 ui-automation 项目用例执行流程):
  POST   /ui-executions                 预创建 pending 行 + 返回 sse_endpoint(不投递 Topic)
  GET    /ui-executions                  分页查询执行列表
  GET    /ui-executions/{execution_id}   执行详情(含报告 + 产物)
  POST   /ui-executions/{execution_id}/cancel  取消执行(杀子进程组)
  GET    /ui-executions/{execution_id}/events?session_id=...
                                         SSE 实时进度 + 首次订阅时真正投递 Agent

两步触发设计动机:
  原 ui-automation `test_script_execution.py` 的模式 —— POST 只建会话,
  SSE 长连接建立后才 `asyncio.create_task(process_unified_execution_task)`。
  这样保证前端订阅 SSE 一定早于 Agent 第一条进度消息,不会丢早期 ready/preparing 帧。
  我们做了一层并发去重:_started_executions + _kickoff_lock 保证同一 execution_id
  即便被多次 GET /events 也只投递一次 Topic。

报告相关:
  GET    /ui-reports                     分页查询报告
  GET    /ui-reports/{report_id}         报告详情(含 report_url 供前端 iframe 加载)

零回归:整段路由仅在 settings.UI_AUTOMATION_ENABLED 时挂载,
         任何 DB / 模型 / Agent 调用均 lazy import,关闭时不留任何 import 副作用。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from tortoise.expressions import Q

from app.services.ui_automation.orchestrator import (
    UiAutomationDisabledError,
    ui_orchestrator,
)
from app.settings.config import settings


executions_router = APIRouter(tags=["UI自动化-执行"])
# SSE 流单独一个 router:浏览器原生 EventSource 不支持自定义 header,
# AuthControl.is_authed 强制要 token header 会直接 401,导致前端 SSE 不通、
# 后端日志一片空白。鉴权由 (execution_id + session_id) 双 uuid 隐式承担 ——
# 业务方不知道这两个值就构造不出有效 URL,与原 ui-automation 项目对齐。
executions_stream_router = APIRouter(tags=["UI自动化-执行-SSE"])
reports_router = APIRouter(tags=["UI自动化-报告"])


# ============================================================================
# kickoff 去重(进程内单例,够用)
# ============================================================================
# Why: GET /events 可能因为浏览器自动重连被叫多次,或者前端误开两个 tab,
# 我们必须保证同一个 execution_id 只投递一次 Topic,否则会跑出两个子进程。
# DB 状态 pending→running 的原子更新是真正的去重权威,内存 set 只是快速短路。
_started_executions: Set[str] = set()
_kickoff_lock: asyncio.Lock = asyncio.Lock()


async def reset_zombie_allure_status() -> int:
    """启动时把僵尸的 generating 状态重置为 failed。

    场景：后端重启时正好有 Allure 后台任务在跑（asyncio.create_task），
    任务被中断但 DB 里还显示 generating，导致前端轮询永远不会结束。
    启动时一次性扫描，把所有 generating → failed。

    Returns:
        重置的总条数（UiTestReport + UiBatchExecution）。
    """
    try:
        from app.models.ui_automation import UiTestReport, UiBatchExecution
    except Exception:
        return 0
    n1 = await UiTestReport.filter(allure_status="generating").update(
        allure_status="failed",
        allure_error="后端重启时该任务未完成（已被自动重置）",
    )
    n2 = await UiBatchExecution.filter(batch_allure_status="generating").update(
        batch_allure_status="failed",
        batch_allure_error="后端重启时该任务未完成（已被自动重置）",
    )
    return (n1 or 0) + (n2 or 0)


async def _kickoff_execution(execution_id: str, session_id: str) -> None:
    """SSE 订阅生效后真正投递 Topic。

    幂等:同一个 execution_id 重复调用最多投递一次。
    原子性:DB 用 status='pending' 作为筛选条件做 update,只有一次能拿到 1 行影响,
            真正赢家才投递 Topic;输家直接返回。
    """
    try:
        from app.agents.ui_automation.schemas import UiScriptExecutionInput
        from app.models.ui_automation import UiScriptExecution
    except Exception as e:
        logger.warning(f"[kickoff {execution_id}] 模块加载失败,跳过投递: {e}")
        return

    async with _kickoff_lock:
        if execution_id in _started_executions:
            return
        _started_executions.add(execution_id)

    row = await UiScriptExecution.filter(execution_id=execution_id).first()
    if not row:
        logger.warning(f"[kickoff {execution_id}] 执行记录不存在,放弃投递")
        _started_executions.discard(execution_id)
        return

    cfg = row.execution_config or {}
    script_relative_path = cfg.get("script_relative_path") or ""
    timeout_seconds = cfg.get("timeout_seconds")
    extra_env = cfg.get("extra_env") or {}

    if not script_relative_path:
        await UiScriptExecution.filter(execution_id=execution_id).update(
            status="error", error_message="执行配置缺少 script_relative_path"
        )
        return

    # 原子状态迁移:只有把 pending 改成 running 成功的那次才真正投递
    affected = await UiScriptExecution.filter(
        execution_id=execution_id, status="pending"
    ).update(status="running")
    if not affected:
        logger.info(f"[kickoff {execution_id}] 状态已非 pending,跳过投递(可能已被其他订阅者启动)")
        return

    try:
        execution_input = UiScriptExecutionInput(
            execution_id=execution_id,
            session_id=session_id,
            script_id=row.script_id,
            script_relative_path=script_relative_path,
            triggered_by=row.triggered_by or "manual",
            timeout_seconds=timeout_seconds,
            extra_env=extra_env,
        )
    except Exception as e:
        await UiScriptExecution.filter(execution_id=execution_id).update(
            status="error", error_message=f"构造执行输入失败: {e}"[:500]
        )
        return

    try:
        await ui_orchestrator.trigger_execution(execution_input)
        logger.info(f"[kickoff {execution_id}] 已投递 Topic session={session_id}")
    except UiAutomationDisabledError as e:
        await UiScriptExecution.filter(execution_id=execution_id).update(
            status="error", error_message=f"模块未启用: {e}"[:500]
        )
    except Exception as e:
        logger.exception(f"[kickoff {execution_id}] 投递失败: {e}")
        await UiScriptExecution.filter(execution_id=execution_id).update(
            status="error", error_message=f"投递失败: {e}"[:500]
        )


# ============================================================================
# 请求模型
# ============================================================================


class TriggerExecutionRequest(BaseModel):
    script_id: str = Field(..., description="目标脚本 ID")
    triggered_by: str = Field("manual", description="触发人(用户名/ID)")
    timeout_seconds: Optional[int] = Field(
        None, ge=10, le=3600, description="单次执行超时秒数,None=取 settings.UI_PLAYWRIGHT_TIMEOUT"
    )
    extra_env: Dict[str, str] = Field(
        default_factory=dict, description="追加注入子进程的环境变量"
    )
    session_id: Optional[str] = Field(None, description="会话 ID(不传则自动生成)")


# ============================================================================
# 执行路由
# ============================================================================


@executions_router.post("", summary="创建执行会话(不投递 Agent,等 SSE 订阅后再触发)")
async def trigger_execution(req: TriggerExecutionRequest):
    """两步触发第一步:仅落 pending 行 + 返回 sse_endpoint。

    前端拿到 sse_endpoint 后必须立刻 EventSource 连上去,真正的 Topic 投递在
    GET /events 内部完成 —— 这样保证早期 ready/preparing 帧不会丢。
    """
    try:
        from app.models.ui_automation import UiScriptExecution, UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    if not settings.UI_AUTOMATION_ENABLED:
        raise HTTPException(status_code=503, detail="UI 自动化模块未启用")

    script = await UiTestScript.filter(script_id=req.script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail=f"脚本不存在: {req.script_id}")
    if not script.file_path:
        raise HTTPException(
            status_code=400,
            detail=f"脚本无 file_path,无法执行(可能未生成或写盘失败): {req.script_id}",
        )

    execution_id = uuid.uuid4().hex
    session_id = req.session_id or f"ui_exec_{uuid.uuid4().hex[:12]}"

    # 优先级: req.extra_env > .env settings > script.base_url
    extra_env: Dict[str, str] = dict(req.extra_env or {})
    # .env 显式配置优先
    if settings.UI_BASE_URL:
        extra_env.setdefault("UI_BASE_URL", settings.UI_BASE_URL)
    if settings.UI_LOGIN_URL:
        extra_env.setdefault("UI_LOGIN_URL", settings.UI_LOGIN_URL)
    # 脚本自带的 base_url 作为兜底
    if script.base_url and not extra_env.get("UI_BASE_URL"):
        from urllib.parse import urlparse
        try:
            parsed = urlparse(script.base_url.strip())
            origin = (
                f"{parsed.scheme}://{parsed.netloc}"
                if parsed.scheme and parsed.netloc
                else script.base_url.strip()
            )
        except Exception:
            origin = script.base_url.strip()
        extra_env.setdefault("UI_BASE_URL", origin)
        extra_env.setdefault("UI_LOGIN_URL", origin + "/")

    # 预创建 pending 行;script_relative_path / timeout / extra_env 全放进
    # execution_config,供 _kickoff_execution 在 SSE 订阅后还原 UiScriptExecutionInput
    await UiScriptExecution.create(
        execution_id=execution_id,
        script_id=script.script_id,
        status="pending",
        execution_config={
            "script_relative_path": script.file_path,
            "timeout_seconds": req.timeout_seconds,
            "extra_env": extra_env,
            "headless": settings.UI_HEADLESS,
            "session_id": session_id,
        },
        triggered_by=req.triggered_by,
    )

    sse_endpoint = f"/api/v1/ui-automation/executions/{execution_id}/events?session_id={session_id}"

    return {
        "code": 200,
        "msg": "已创建执行会话,请连接 SSE 端点触发执行",
        "data": {
            "execution_id": execution_id,
            "session_id": session_id,
            "script_id": script.script_id,
            "sse_endpoint": sse_endpoint,
        },
        "success": True,
    }


@executions_router.get("", summary="分页查询执行列表")
async def list_executions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    script_id: Optional[str] = Query(None, description="按脚本 ID 过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
):
    try:
        from app.models.ui_automation import UiScriptExecution, UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    qs = UiScriptExecution.all().order_by("-id")
    if script_id:
        qs = qs.filter(script_id=script_id)
    if status:
        qs = qs.filter(status=status)

    total = await qs.count()
    rows = await qs.offset((page - 1) * page_size).limit(page_size)

    # 批量反查 script_id → name（避免 N+1）
    script_ids = list({row.script_id for row in rows if row.script_id})
    name_map: Dict[str, str] = {}
    if script_ids:
        for s in await UiTestScript.filter(script_id__in=script_ids).only("script_id", "name"):
            name_map[s.script_id] = s.name

    items: List[Dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "execution_id": row.execution_id,
                "script_id": row.script_id,
                "script_name": name_map.get(row.script_id, "") or row.script_id,
                "status": row.status,
                "start_time": row.start_time.isoformat() if row.start_time else None,
                "end_time": row.end_time.isoformat() if row.end_time else None,
                "duration_ms": row.duration_ms,
                "exit_code": row.exit_code,
                "error_message": row.error_message,
                "artifact_summary": row.artifact_summary,
                "triggered_by": row.triggered_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    return {
        "code": 200,
        "msg": "OK",
        "data": {"total": total, "page": page, "page_size": page_size, "items": items},
        "success": True,
    }


@executions_router.get("/{execution_id}", summary="执行详情")
async def get_execution(execution_id: str):
    try:
        from app.models.ui_automation import (
            UiExecutionArtifact,
            UiScriptExecution,
            UiTestReport,
            UiTestScript,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    row = await UiScriptExecution.filter(execution_id=execution_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"执行记录不存在: {execution_id}")

    report = await UiTestReport.filter(execution_id=execution_id).first()
    artifacts = await UiExecutionArtifact.filter(execution_id=execution_id).all()

    # 反查用例名（用于前端展示替代 script_id）
    script_name = ""
    if row.script_id:
        s = await UiTestScript.filter(script_id=row.script_id).only("name").first()
        if s:
            script_name = s.name

    return {
        "code": 200,
        "msg": "OK",
        "data": {
            "execution_id": row.execution_id,
            "script_id": row.script_id,
            "script_name": script_name or row.script_id,
            "status": row.status,
            "start_time": row.start_time.isoformat() if row.start_time else None,
            "end_time": row.end_time.isoformat() if row.end_time else None,
            "duration_ms": row.duration_ms,
            "exit_code": row.exit_code,
            "stdout": row.stdout,
            "stderr": row.stderr,
            "error_message": row.error_message,
            "execution_config": row.execution_config,
            "artifact_summary": row.artifact_summary,
            "triggered_by": row.triggered_by,
            "report": (
                {
                    "report_id": report.report_id,
                    "report_url": report.report_url,
                    "report_type": report.report_type,
                    "summary": report.summary,
                    "passed": report.passed,
                    "failed": report.failed,
                    "skipped": report.skipped,
                    # Allure 按需生成状态机
                    "allure_status": report.allure_status,
                    "allure_report_url": report.allure_report_url,
                    "allure_generated_at": (
                        report.allure_generated_at.isoformat()
                        if report.allure_generated_at else None
                    ),
                    "allure_error": report.allure_error,
                }
                if report
                else None
            ),
            "artifacts": [
                {
                    "artifact_id": a.artifact_id,
                    "artifact_type": a.artifact_type,
                    "file_url": a.file_url,
                    "file_size": a.file_size,
                    "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                }
                for a in artifacts
            ],
            "created_at": row.created_at.isoformat() if row.created_at else None,
        },
        "success": True,
    }


@executions_router.post("/{execution_id}/cancel", summary="取消执行")
async def cancel_execution(execution_id: str):
    try:
        from app.services.ui_automation import execution_service
        from app.models.ui_automation import UiScriptExecution
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    row = await UiScriptExecution.filter(execution_id=execution_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"执行记录不存在: {execution_id}")

    cancelled = await execution_service.cancel_execution(execution_id)
    if not cancelled:
        return {
            "code": 200,
            "msg": "未找到运行中的进程(可能已结束)",
            "data": {"execution_id": execution_id, "cancelled": False},
            "success": True,
        }

    return {
        "code": 200,
        "msg": "已发送取消信号",
        "data": {"execution_id": execution_id, "cancelled": True},
        "success": True,
    }


# ==================== Allure 报告（按需触发生成）====================

@executions_router.get("/allure/cli-status", summary="检测服务器是否安装 Allure CLI（前端按钮可用性）")
async def get_allure_cli_status():
    """前端进入执行详情时先调一次，决定「生成 Allure 报告」按钮 disabled 状态。"""
    try:
        from app.services.ui_automation.allure_service import is_allure_cli_available
    except Exception:
        return {"code": 200, "success": True, "data": {"available": False}}
    return {
        "code": 200,
        "success": True,
        "data": {"available": is_allure_cli_available()},
    }


@executions_router.post("/{execution_id}/allure/generate", summary="按需生成单脚本 Allure 报告（异步）")
async def trigger_single_allure(execution_id: str):
    """
    返回时立即写 status=generating；后台 asyncio.create_task 跑实际 generate；
    前端 3s 轮询 GET /executions/{id} 拿 allure_status 字段。
    """
    try:
        from app.models.ui_automation import UiTestReport
        from app.services.ui_automation.allure_service import (
            is_allure_cli_available,
            trigger_single_generate_task,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    row = await UiTestReport.filter(execution_id=execution_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"执行报告记录不存在: {execution_id}")

    if not is_allure_cli_available():
        raise HTTPException(status_code=400, detail="服务器未安装 Allure CLI")

    if row.allure_status == "generating":
        return {
            "code": 200, "success": True,
            "msg": "已有生成任务在进行中",
            "data": {"status": "generating"},
        }

    await trigger_single_generate_task(execution_id=execution_id, script_id=row.script_id)
    return {
        "code": 200, "success": True,
        "msg": "已触发生成（异步）",
        "data": {"status": "generating"},
    }


@executions_router.post("/batches/{batch_id}/allure/generate", summary="按需生成批次 Allure 汇总报告（异步）")
async def trigger_batch_allure(batch_id: str):
    try:
        from app.models.ui_automation import UiBatchExecution, UiScriptExecution
        from app.services.ui_automation.allure_service import (
            is_allure_cli_available,
            trigger_batch_generate_task,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    batch = await UiBatchExecution.filter(batch_id=batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail=f"批次记录不存在: {batch_id}")

    if not is_allure_cli_available():
        raise HTTPException(status_code=400, detail="服务器未安装 Allure CLI")

    if batch.batch_allure_status == "generating":
        return {
            "code": 200, "success": True,
            "msg": "已有生成任务在进行中",
            "data": {"status": "generating"},
        }

    execution_ids = [
        row.execution_id
        for row in await UiScriptExecution.filter(batch_id=batch_id).only("execution_id")
    ]
    if not execution_ids:
        raise HTTPException(status_code=400, detail="批次下无子执行记录")

    await trigger_batch_generate_task(
        batch_id=batch_id,
        batch_name=batch.name or "",
        execution_ids=execution_ids,
    )
    return {
        "code": 200, "success": True,
        "msg": "已触发生成（异步）",
        "data": {"status": "generating"},
    }


@executions_stream_router.get("/{execution_id}/events", summary="SSE 订阅执行进度(首次订阅触发投递)")
async def stream_execution_events(execution_id: str, session_id: str = Query(...)):
    """两步触发第二步:订阅成功后再投递 Topic。"""
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

    # 订阅生效后才真正投递,避免 Agent 早期消息丢失。
    # asyncio.create_task 而非 await:让 event_gen 立刻开始 yield ready 帧,
    # kickoff 出错也走 SSE message 通道告诉前端,不阻塞响应头。
    asyncio.create_task(_kickoff_execution(execution_id, session_id))

    async def event_gen():
        try:
            yield {
                "event": "ready",
                "data": json.dumps(
                    {"execution_id": execution_id, "session_id": session_id},
                    ensure_ascii=False,
                ),
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
            # 终态后从去重 set 摘除,避免长跑后内存膨胀
            _started_executions.discard(execution_id)

    return EventSourceResponse(event_gen())


# ============================================================================
# 报告路由
# ============================================================================


@reports_router.get("", summary="分页查询报告")
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    script_id: Optional[str] = Query(None, description="按脚本 ID 过滤"),
):
    try:
        from app.models.ui_automation import UiTestReport
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    qs = UiTestReport.all().order_by("-id")
    if script_id:
        qs = qs.filter(script_id=script_id)

    total = await qs.count()
    rows = await qs.offset((page - 1) * page_size).limit(page_size)
    items: List[Dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "report_id": row.report_id,
                "execution_id": row.execution_id,
                "script_id": row.script_id,
                "report_type": row.report_type,
                "report_url": row.report_url,
                "summary": row.summary,
                "passed": row.passed,
                "failed": row.failed,
                "skipped": row.skipped,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    return {
        "code": 200,
        "msg": "OK",
        "data": {"total": total, "page": page, "page_size": page_size, "items": items},
        "success": True,
    }


@reports_router.get("/{report_id}", summary="报告详情")
async def get_report(report_id: str):
    try:
        from app.models.ui_automation import UiTestReport
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    row = await UiTestReport.filter(report_id=report_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")

    return {
        "code": 200,
        "msg": "OK",
        "data": {
            "report_id": row.report_id,
            "execution_id": row.execution_id,
            "script_id": row.script_id,
            "report_type": row.report_type,
            "report_url": row.report_url,
            "report_path": row.report_path,
            "summary": row.summary,
            "passed": row.passed,
            "failed": row.failed,
            "skipped": row.skipped,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        },
        "success": True,
    }


# ============================================================================
# 批次执行路由
# ============================================================================

batches_router = APIRouter(tags=["UI自动化-批量执行"])


class BatchTriggerRequest(BaseModel):
    script_ids: List[str] = Field(..., min_length=1, max_length=50)
    name: str = Field("", description="批次名称(可选)")
    triggered_by: str = Field("manual")
    timeout_seconds: Optional[int] = Field(None, ge=10, le=3600)
    extra_env: Dict[str, str] = Field(default_factory=dict)


@batches_router.post("", summary="创建批量执行（直接触发，后台跑）")
async def trigger_batch_execution(req: BatchTriggerRequest):
    try:
        from app.agents.ui_automation.schemas import UiBatchExecutionInput
        from app.models.ui_automation import UiBatchExecution, UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    if not settings.UI_AUTOMATION_ENABLED:
        raise HTTPException(status_code=503, detail="UI 自动化模块未启用")

    # 单批次并发守卫
    running_batch = await UiBatchExecution.filter(status="running").first()
    if running_batch:
        raise HTTPException(
            status_code=409,
            detail=f"已有批次 {running_batch.batch_id} 正在运行中,请等待完成或取消后再提交",
        )

    # 校验脚本
    from pathlib import Path as _Path
    workspace = _Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
    valid_script_ids: List[str] = []
    invalid_script_ids: List[str] = []
    for sid in req.script_ids:
        script = await UiTestScript.filter(script_id=sid).first()
        if not script:
            invalid_script_ids.append(sid)
        elif not script.file_path:
            invalid_script_ids.append(sid)
        elif not (workspace / script.file_path).exists():
            invalid_script_ids.append(sid)
        else:
            valid_script_ids.append(sid)

    if not valid_script_ids:
        raise HTTPException(status_code=400, detail="所有脚本均无效(不存在或无 file_path)")

    batch_id = uuid.uuid4().hex
    session_id = f"ui_batch_{uuid.uuid4().hex[:12]}"

    await UiBatchExecution.create(
        batch_id=batch_id,
        name=req.name or f"批量执行 {datetime.now().strftime('%m-%d %H:%M')}",
        status="pending",
        total_scripts=len(valid_script_ids),
        execution_config={
            "script_ids": valid_script_ids,
            "timeout_seconds": req.timeout_seconds,
            "extra_env": req.extra_env or {},
            "session_id": session_id,
        },
        triggered_by=req.triggered_by,
    )

    # 直接投递执行(不走 SSE 两步触发)
    try:
        await ui_orchestrator.initialize()
    except UiAutomationDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))

    await UiBatchExecution.filter(batch_id=batch_id, status="pending").update(
        status="running", start_time=datetime.now()
    )

    batch_input = UiBatchExecutionInput(
        batch_id=batch_id,
        session_id=session_id,
        script_ids=valid_script_ids,
        name=req.name,
        triggered_by=req.triggered_by,
        timeout_seconds=req.timeout_seconds,
        extra_env=req.extra_env or {},
    )

    try:
        await ui_orchestrator.trigger_batch_execution(batch_input)
        logger.info(f"已投递批量执行 batch={batch_id} scripts={len(valid_script_ids)}")
    except Exception as e:
        logger.exception(f"投递批量执行失败 batch={batch_id}: {e}")
        await UiBatchExecution.filter(batch_id=batch_id).update(
            status="error", error_message=f"投递失败: {e}"[:500]
        )
        raise HTTPException(status_code=500, detail=f"投递失败: {e}")

    return {
        "code": 200,
        "msg": f"已触发批量执行 {len(valid_script_ids)} 个脚本",
        "data": {
            "batch_id": batch_id,
            "script_count": len(valid_script_ids),
            "invalid_script_ids": invalid_script_ids,
        },
        "success": True,
    }


@batches_router.get("", summary="分页查询批次列表")
async def list_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: Optional[str] = Query(None, description="按状态过滤"),
):
    try:
        from app.models.ui_automation import UiBatchExecution
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    qs = UiBatchExecution.all().order_by("-id")
    if status:
        qs = qs.filter(status=status)

    total = await qs.count()
    rows = await qs.offset((page - 1) * page_size).limit(page_size)
    items: List[Dict[str, Any]] = []
    for row in rows:
        items.append({
            "batch_id": row.batch_id,
            "name": row.name,
            "status": row.status,
            "total_scripts": row.total_scripts,
            "success_count": row.success_count,
            "failed_count": row.failed_count,
            "timeout_count": row.timeout_count,
            "cancelled_count": row.cancelled_count,
            "start_time": row.start_time.isoformat() if row.start_time else None,
            "end_time": row.end_time.isoformat() if row.end_time else None,
            "duration_ms": row.duration_ms,
            "triggered_by": row.triggered_by,
            "error_message": row.error_message,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {
        "code": 200,
        "msg": "OK",
        "data": {"total": total, "page": page, "page_size": page_size, "items": items},
        "success": True,
    }


@batches_router.get("/{batch_id}", summary="批次详情（含报告汇总）")
async def get_batch(batch_id: str):
    try:
        from app.models.ui_automation import UiBatchExecution, UiScriptExecution, UiTestReport, UiTestScript
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模型加载失败: {e}")

    row = await UiBatchExecution.filter(batch_id=batch_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"批次不存在: {batch_id}")

    executions = await UiScriptExecution.filter(batch_id=batch_id).all()

    # 批量反查 script_id → name（避免 N+1）
    sub_script_ids = list({e.script_id for e in executions if e.script_id})
    sub_name_map: Dict[str, str] = {}
    if sub_script_ids:
        for s in await UiTestScript.filter(script_id__in=sub_script_ids).only("script_id", "name"):
            sub_name_map[s.script_id] = s.name

    exec_items = []
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    for e in executions:
        report = await UiTestReport.filter(execution_id=e.execution_id).first()
        exec_items.append({
            "execution_id": e.execution_id,
            "script_id": e.script_id,
            "script_name": sub_name_map.get(e.script_id, "") or e.script_id,
            "status": e.status,
            "start_time": e.start_time.isoformat() if e.start_time else None,
            "end_time": e.end_time.isoformat() if e.end_time else None,
            "duration_ms": e.duration_ms,
            "exit_code": e.exit_code,
            "error_message": e.error_message,
            "triggered_by": e.triggered_by,
            "report": {
                "passed": report.passed if report else 0,
                "failed": report.failed if report else 0,
                "skipped": report.skipped if report else 0,
                "report_url": report.report_url if report else "",
            } if report else None,
        })
        if report:
            total_passed += report.passed
            total_failed += report.failed
            total_skipped += report.skipped

    return {
        "code": 200,
        "msg": "OK",
        "data": {
            "batch_id": row.batch_id,
            "name": row.name,
            "status": row.status,
            "total_scripts": row.total_scripts,
            "completed_count": row.completed_count,
            "success_count": row.success_count,
            "failed_count": row.failed_count,
            "timeout_count": row.timeout_count,
            "cancelled_count": row.cancelled_count,
            "safety_blocked_count": row.safety_blocked_count,
            "start_time": row.start_time.isoformat() if row.start_time else None,
            "end_time": row.end_time.isoformat() if row.end_time else None,
            "duration_ms": row.duration_ms,
            "triggered_by": row.triggered_by,
            "error_message": row.error_message,
            # 汇总
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_skipped": total_skipped,
            "executions": exec_items,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            # Allure 批次汇总报告状态机（按需生成）
            "batch_allure_status": row.batch_allure_status,
            "batch_allure_report_url": row.batch_allure_report_url,
            "batch_allure_generated_at": (
                row.batch_allure_generated_at.isoformat()
                if row.batch_allure_generated_at else None
            ),
            "batch_allure_error": row.batch_allure_error,
        },
        "success": True,
    }


@batches_router.post("/{batch_id}/cancel", summary="取消批次")
async def cancel_batch(batch_id: str):
    try:
        from app.models.ui_automation import UiBatchExecution, UiScriptExecution
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"UI 自动化模块未启用: {e}")

    row = await UiBatchExecution.filter(batch_id=batch_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"批次不存在: {batch_id}")

    if row.status not in ("pending", "running"):
        return {
            "code": 200,
            "msg": f"批次状态为 {row.status},无需取消",
            "data": {"batch_id": batch_id, "cancelled": False},
            "success": True,
        }

    # 通知 BatchExecutorAgent 取消
    from app.agents.ui_automation.schemas import UiBatchCancelCommand
    cancel_cmd = UiBatchCancelCommand(batch_id=batch_id, cancelled_by="frontend")
    try:
        await ui_orchestrator.trigger_batch_cancel(batch_id, cancel_cmd)
    except Exception as e:
        logger.warning(f"投递批次取消命令失败 batch={batch_id}: {e}")

    # 杀子进程
    running_execs = await UiScriptExecution.filter(
        batch_id=batch_id, status__in=["pending", "running"]
    ).all()
    for e in running_execs:
        try:
            cancelled = await execution_service.cancel_execution(e.execution_id)
            if cancelled:
                await UiScriptExecution.filter(execution_id=e.execution_id).update(
                    status="cancelled"
                )
        except Exception as ce:
            logger.warning(f"取消子执行失败 execution={e.execution_id}: {ce}")

    # 直接更新批次状态
    await UiBatchExecution.filter(batch_id=batch_id).update(
        status="cancelled", end_time=datetime.now()
    )

    return {
        "code": 200,
        "msg": "已取消",
        "data": {"batch_id": batch_id, "cancelled": True},
        "success": True,
    }





# batch SSE endpoint removed - batches now fire-and-forget via POST

