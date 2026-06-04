from fastapi import APIRouter

from app.core.dependency import DependPermission

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

from .endpoints.scheduled_tasks import router as scheduled_tasks_router


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
v1_router.include_router(scheduled_tasks_router, prefix="/api-automation", tags=["定时任务"])
