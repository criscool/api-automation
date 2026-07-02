from fastapi import APIRouter

from app.core.dependency import DependPermission
from app.settings.config import settings

from .apis import apis_router
from .auditlog import auditlog_router
from .base import base_router
from .depts import depts_router
from .menus import menus_router
from .roles import roles_router
from .users import users_router
from .endpoints.api_automation import router as api_automation_router
from .endpoints.interface_management import router as interface_management_router
from .endpoints.script_management import router as script_management_router
from .endpoints.test_case_management import router as test_case_management_router
from .endpoints.testcase_category_management import router as testcase_category_router
from .endpoints.execution_reports import router as execution_reports_router

from .endpoints.docs import router as docs_router
from .endpoints.scheduled_tasks import router as scheduled_tasks_router
from .endpoints.healer import router as healer_router
from .endpoints.environments import router as environments_router


v1_router = APIRouter()

v1_router.include_router(base_router, prefix="/base")
v1_router.include_router(users_router, prefix="/user", dependencies=[DependPermission])
v1_router.include_router(roles_router, prefix="/role", dependencies=[DependPermission])
v1_router.include_router(menus_router, prefix="/menu", dependencies=[DependPermission])
v1_router.include_router(apis_router, prefix="/api", dependencies=[DependPermission])
v1_router.include_router(depts_router, prefix="/dept", dependencies=[DependPermission])
v1_router.include_router(auditlog_router, prefix="/auditlog", dependencies=[DependPermission])
v1_router.include_router(api_automation_router, prefix="/api-automation", tags=["接口自动化"])
v1_router.include_router(interface_management_router, prefix="/interface", tags=["接口管理"])
v1_router.include_router(script_management_router, prefix="/scripts", tags=["脚本管理"])
v1_router.include_router(test_case_management_router, prefix="/testcases", tags=["用例管理"])
v1_router.include_router(testcase_category_router, prefix="/testcase-categories", tags=["用例分类"])
v1_router.include_router(execution_reports_router, prefix="/execution-reports", tags=["执行报告"])
v1_router.include_router(docs_router, prefix="/docs", tags=["文档管理"])
v1_router.include_router(scheduled_tasks_router, prefix="/api-automation", tags=["定时任务"])
v1_router.include_router(healer_router, prefix="/heal", tags=["AI 诊断"])
v1_router.include_router(environments_router, prefix="/environments", tags=["环境管理"], dependencies=[DependPermission])

# UI 自动化模块（一期）—— 受 UI_AUTOMATION_ENABLED 开关控制，关闭时整段路由不注册
# 零回归：开关关闭时模块完全不挂载，不会产生任何回归影响
if settings.UI_AUTOMATION_ENABLED:
    from .endpoints.ui_automation import (
        batches_router as ui_automation_batches_router,
        health_router as ui_automation_health_router,
        screenshots_router as ui_automation_screenshots_router,
        page_analysis_router as ui_automation_page_analysis_router,
        scripts_router as ui_automation_scripts_router,
        executions_router as ui_automation_executions_router,
        executions_stream_router as ui_automation_executions_stream_router,
        reports_router as ui_automation_reports_router,
        image_library_router as ui_automation_image_library_router,
        recordings_router as ui_automation_recordings_router,
        recordings_stream_router as ui_automation_recordings_stream_router,
        categories_router as ui_automation_categories_router,
    )
    # 远程录制 WebSocket（独立于录制开关，守护进程长连接）
    from app.services.ui_automation.remote_recording import router as remote_recording_router
    v1_router.include_router(
        remote_recording_router,
        prefix="/ui-automation",
        tags=["UI自动化-远程录制"],
    )
    # health 不挂权限，便于运维探测
    v1_router.include_router(
        ui_automation_health_router,
        prefix="/ui-automation",
        tags=["UI自动化"],
    )
    # 业务接口统一加 DependPermission
    v1_router.include_router(
        ui_automation_screenshots_router,
        prefix="/ui-automation/screenshots",
        tags=["UI自动化-截图"],
        dependencies=[DependPermission],
    )
    v1_router.include_router(
        ui_automation_page_analysis_router,
        prefix="/ui-automation/page-analysis",
        tags=["UI自动化-页面分析"],
        dependencies=[DependPermission],
    )
    v1_router.include_router(
        ui_automation_scripts_router,
        prefix="/ui-automation/scripts",
        tags=["UI自动化-脚本管理"],
        dependencies=[DependPermission],
    )
    v1_router.include_router(
        ui_automation_executions_router,
        prefix="/ui-automation/executions",
        tags=["UI自动化-执行"],
        dependencies=[DependPermission],
    )
    # SSE 端点单独挂、不挂权限:浏览器 EventSource 不支持 token header,
    # AuthControl 会拦下来导致后端日志一片空白。改由 execution_id+session_id
    # 双 uuid 隐式鉴权(不知道这俩值就拼不出 URL),与原 ui-automation 对齐。
    v1_router.include_router(
        ui_automation_executions_stream_router,
        prefix="/ui-automation/executions",
        tags=["UI自动化-执行-SSE"],
    )
    v1_router.include_router(
        ui_automation_reports_router,
        prefix="/ui-automation/reports",
        tags=["UI自动化-报告"],
        dependencies=[DependPermission],
    )
    v1_router.include_router(
        ui_automation_image_library_router,
        prefix="/ui-automation/image-library",
        tags=["UI自动化-图片库"],
        dependencies=[DependPermission],
    )
    # 录制管理:POST/GET/DELETE 走鉴权;SSE 走 session_id 隐式鉴权
    if settings.UI_RECORDING_ENABLED:
        v1_router.include_router(
            ui_automation_recordings_router,
            prefix="/ui-automation/recordings",
            tags=["UI自动化-录制"],
            dependencies=[DependPermission],
        )
        v1_router.include_router(
            ui_automation_recordings_stream_router,
            prefix="/ui-automation/recordings",
            tags=["UI自动化-录制-SSE"],
        )
    # 批次执行路由（不受录制开关控制）
    v1_router.include_router(
        ui_automation_batches_router,
        prefix="/ui-automation/batches",
        tags=["UI自动化-批量执行"],
        dependencies=[DependPermission],
    )
    # 用例分类路由
    v1_router.include_router(
        ui_automation_categories_router,
        prefix="/ui-automation/categories",
        tags=["UI自动化-用例分类"],
        dependencies=[DependPermission],
    )
