"""
定时任务管理 API 端点
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.models.api_automation import ScheduledTask, TestExecution, TestScript
from app.services.api_automation.scheduled_task_service import get_scheduled_task_service

router = APIRouter(tags=["定时任务"])


def _serialize_task(task: ScheduledTask) -> dict:
    return {
        "taskId": task.task_id,
        "taskName": task.task_name,
        "scriptIds": task.script_ids,
        "categoryIds": task.category_ids,
        "selectionMode": task.selection_mode,
        "environment": task.environment,
        "scheduleType": task.schedule_type,
        "cronExpression": task.cron_expression,
        "scheduleExpression": (
            task.cron_expression
            if task.schedule_type == "cron"
            else f"每{task.interval_value}{task.interval_unit or ''}"
            if task.schedule_type == "interval"
            else task.execution_time.isoformat() if task.execution_time else ""
        ),
        "intervalValue": task.interval_value,
        "intervalUnit": task.interval_unit,
        "executionTime": task.execution_time.isoformat() if task.execution_time else None,
        "parallelExecution": task.parallel_execution,
        "maxWorkers": task.max_workers,
        "timeout": task.timeout,
        "retryOnFailure": task.retry_on_failure,
        "maxRetries": task.max_retries,
        "notifications": task.notifications,
        "status": task.status,
        "lastExecutionTime": task.last_execution_time.isoformat() if task.last_execution_time else None,
        "nextExecutionTime": task.next_execution_time.isoformat() if task.next_execution_time else None,
        "description": task.description,
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
    }


@router.get("/scheduled-tasks", summary="获取定时任务列表")
async def list_scheduled_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    status: Optional[str] = Query(None, description="状态筛选"),
) -> dict:
    try:
        qs = ScheduledTask.all()
        if keyword:
            qs = qs.filter(task_name__icontains=keyword)
        if status:
            qs = qs.filter(status=status)

        total = await qs.count()
        offset = (page - 1) * page_size
        tasks = await qs.order_by("-created_at").offset(offset).limit(page_size)

        return {
            "code": 200,
            "msg": "OK",
            "data": {
                "items": [_serialize_task(t) for t in tasks],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
            "success": True,
        }
    except Exception as e:
        logger.error(f"获取定时任务列表失败: {e}")
        return {"code": 500, "msg": str(e), "data": {}, "success": False}


@router.post("/scheduled-tasks", summary="创建定时任务")
async def create_scheduled_task(data: dict) -> dict:
    try:
        service = get_scheduled_task_service()
        task = ScheduledTask(
            task_id=str(uuid.uuid4()),
            task_name=data.get("taskName", ""),
            script_ids=data.get("scriptIds", []),
            category_ids=data.get("categoryIds", []),
            selection_mode=data.get("selectionMode", "scripts"),
            environment=data.get("environment", "test"),
            schedule_type=data.get("scheduleType", "cron"),
            cron_expression=data.get("cronExpression"),
            interval_value=data.get("intervalValue"),
            interval_unit=data.get("intervalUnit"),
            execution_time=datetime.fromisoformat(data["executionTime"].replace("Z", "+00:00")) if data.get("executionTime") else None,
            parallel_execution=data.get("parallelExecution", False),
            max_workers=data.get("maxWorkers", 1),
            timeout=data.get("timeout", 300),
            retry_on_failure=data.get("retryOnFailure", False),
            max_retries=data.get("maxRetries", 3),
            notifications=data.get("notifications", []),
            description=data.get("description", ""),
            status="enabled",
        )
        await task.save()
        await service.add_task(task)

        return {
            "code": 200,
            "msg": "创建成功",
            "data": _serialize_task(task),
            "success": True,
        }
    except Exception as e:
        logger.error(f"创建定时任务失败: {e}")
        return {"code": 500, "msg": str(e), "data": {}, "success": False}


@router.put("/scheduled-tasks", summary="更新定时任务")
async def update_scheduled_task(data: dict) -> dict:
    try:
        task_id = data.get("taskId")
        if not task_id:
            raise HTTPException(status_code=400, detail="缺少 taskId")

        task = await ScheduledTask.filter(task_id=task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        service = get_scheduled_task_service()

        # 更新字段
        if "taskName" in data:
            task.task_name = data["taskName"]
        if "scriptIds" in data:
            task.script_ids = data["scriptIds"]
        if "categoryIds" in data:
            task.category_ids = data["categoryIds"]
        if "selectionMode" in data:
            task.selection_mode = data["selectionMode"]
        if "environment" in data:
            task.environment = data["environment"]
        if "scheduleType" in data:
            task.schedule_type = data["scheduleType"]
        if "cronExpression" in data:
            task.cron_expression = data["cronExpression"]
        if "intervalValue" in data:
            task.interval_value = data["intervalValue"]
        if "intervalUnit" in data:
            task.interval_unit = data["intervalUnit"]
        if "executionTime" in data and data["executionTime"]:
            task.execution_time = datetime.fromisoformat(data["executionTime"].replace("Z", "+00:00"))
        if "parallelExecution" in data:
            task.parallel_execution = data["parallelExecution"]
        if "maxWorkers" in data:
            task.max_workers = data["maxWorkers"]
        if "timeout" in data:
            task.timeout = data["timeout"]
        if "retryOnFailure" in data:
            task.retry_on_failure = data["retryOnFailure"]
        if "maxRetries" in data:
            task.max_retries = data["maxRetries"]
        if "notifications" in data:
            task.notifications = data["notifications"]
        if "description" in data:
            task.description = data["description"]

        await task.save()
        await service.update_task(task)

        return {
            "code": 200,
            "msg": "更新成功",
            "data": _serialize_task(task),
            "success": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新定时任务失败: {e}")
        return {"code": 500, "msg": str(e), "data": {}, "success": False}


@router.delete("/scheduled-tasks", summary="删除定时任务")
async def delete_scheduled_task(task_id: str = Query(..., alias="taskId")) -> dict:
    try:
        task = await ScheduledTask.filter(task_id=task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        service = get_scheduled_task_service()
        await service.remove_task(task_id)
        await task.delete()

        return {
            "code": 200,
            "msg": "删除成功",
            "data": {},
            "success": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除定时任务失败: {e}")
        return {"code": 500, "msg": str(e), "data": {}, "success": False}


@router.put("/task-status", summary="切换任务启停状态")
async def toggle_task_status(data: dict) -> dict:
    try:
        task_id = data.get("taskId")
        new_status = data.get("status")

        if not task_id or not new_status:
            raise HTTPException(status_code=400, detail="缺少 taskId 或 status")

        task = await ScheduledTask.filter(task_id=task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        task.status = new_status
        await task.save()

        service = get_scheduled_task_service()
        await service.toggle_task(task)

        return {
            "code": 200,
            "msg": "状态更新成功",
            "data": _serialize_task(task),
            "success": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"切换任务状态失败: {e}")
        return {"code": 500, "msg": str(e), "data": {}, "success": False}


@router.get("/task-history", summary="获取任务执行历史")
async def get_task_execution_history(task_id: str = Query(..., alias="taskId")) -> dict:
    try:
        executions = await TestExecution.filter(
            execution_config__contains=task_id,
        ).order_by("-created_at").limit(50)

        items = []
        for e in executions:
            items.append({
                "executionId": e.execution_id,
                "executionTime": e.start_time.isoformat() if e.start_time else None,
                "status": e.status.value if hasattr(e.status, "value") else e.status,
                "duration": e.execution_time,
                "totalTests": e.total_tests,
                "passedTests": e.passed_tests,
                "failedTests": e.failed_tests,
                "successRate": e.success_rate,
                "environment": e.environment,
                "errorMessage": e.error_details[0].get("message", "") if e.error_details else "",
            })

        return {
            "code": 200,
            "msg": "OK",
            "data": items,
            "success": True,
        }
    except Exception as e:
        logger.error(f"获取执行历史失败: {e}")
        return {"code": 500, "msg": str(e), "data": [], "success": False}
