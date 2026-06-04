import shutil

from aerich import Command
from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from tortoise.expressions import Q

from app.api import api_router
from app.controllers.api import api_controller
from app.controllers.user import UserCreate, user_controller
from app.core.exceptions import (
    DoesNotExist,
    DoesNotExistHandle,
    HTTPException,
    HttpExcHandle,
    IntegrityError,
    IntegrityHandle,
    RequestValidationError,
    RequestValidationHandle,
    ResponseValidationError,
    ResponseValidationHandle,
)
from app.log import logger
from app.models.admin import Api, Menu, Role
from app.schemas.menus import MenuType
from app.settings.config import settings

from .middlewares import BackGroundTaskMiddleware, HttpAuditLogMiddleware


def make_middlewares():
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
            allow_methods=settings.CORS_ALLOW_METHODS,
            allow_headers=settings.CORS_ALLOW_HEADERS,
        ),
        Middleware(BackGroundTaskMiddleware),
        Middleware(
            HttpAuditLogMiddleware,
            methods=["GET", "POST", "PUT", "DELETE"],
            exclude_paths=[
                "/api/v1/base/access_token",
                "/docs",
                "/openapi.json",
            ],
        ),
    ]
    return middleware


def register_exceptions(app: FastAPI):
    app.add_exception_handler(DoesNotExist, DoesNotExistHandle)
    app.add_exception_handler(HTTPException, HttpExcHandle)
    app.add_exception_handler(IntegrityError, IntegrityHandle)
    app.add_exception_handler(RequestValidationError, RequestValidationHandle)
    app.add_exception_handler(ResponseValidationError, ResponseValidationHandle)


def register_routers(app: FastAPI, prefix: str = "/api"):
    app.include_router(api_router, prefix=prefix)


async def init_superuser():
    user = await user_controller.model.exists()
    if not user:
        await user_controller.create_user(
            UserCreate(
                username="admin",
                email="admin@admin.com",
                password="123456",
                is_active=True,
                is_superuser=True,
            )
        )


async def init_menus():
    menus = await Menu.exists()
    if not menus:
        parent_menu = await Menu.create(
            menu_type=MenuType.CATALOG,
            name="系统管理",
            path="/system",
            order=1,
            parent_id=0,
            icon="carbon:gui-management",
            is_hidden=False,
            component="Layout",
            keepalive=False,
            redirect="/system/user",
        )
        children_menu = [
            Menu(
                menu_type=MenuType.MENU,
                name="用户管理",
                path="user",
                order=1,
                parent_id=parent_menu.id,
                icon="material-symbols:person-outline-rounded",
                is_hidden=False,
                component="/system/user",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="角色管理",
                path="role",
                order=2,
                parent_id=parent_menu.id,
                icon="carbon:user-role",
                is_hidden=False,
                component="/system/role",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="菜单管理",
                path="menu",
                order=3,
                parent_id=parent_menu.id,
                icon="material-symbols:list-alt-outline",
                is_hidden=False,
                component="/system/menu",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="API管理",
                path="api",
                order=4,
                parent_id=parent_menu.id,
                icon="ant-design:api-outlined",
                is_hidden=False,
                component="/system/api",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="部门管理",
                path="dept",
                order=5,
                parent_id=parent_menu.id,
                icon="mingcute:department-line",
                is_hidden=False,
                component="/system/dept",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="审计日志",
                path="auditlog",
                order=6,
                parent_id=parent_menu.id,
                icon="ph:clipboard-text-bold",
                is_hidden=False,
                component="/system/auditlog",
                keepalive=False,
            ),
        ]
        await Menu.bulk_create(children_menu)
        await Menu.create(
            menu_type=MenuType.MENU,
            name="一级菜单",
            path="/top-menu",
            order=2,
            parent_id=0,
            icon="material-symbols:featured-play-list-outline",
            is_hidden=False,
            component="/top-menu",
            keepalive=False,
            redirect="",
        )

        # API自动化菜单
        api_auto_menu = await Menu.create(
            menu_type=MenuType.CATALOG,
            name="API自动化",
            path="/api-automation",
            order=3,
            parent_id=0,
            icon="mdi:api",
            is_hidden=False,
            component="Layout",
            keepalive=False,
            redirect="/api-automation/dashboard",
        )
        api_auto_children = [
            Menu(
                menu_type=MenuType.MENU,
                name="API自动化仪表板",
                path="dashboard",
                order=1,
                parent_id=api_auto_menu.id,
                icon="mdi:view-dashboard",
                is_hidden=False,
                component="/api-automation/dashboard",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="接口管理",
                path="interface-management",
                order=2,
                parent_id=api_auto_menu.id,
                icon="mdi:api-off",
                is_hidden=False,
                component="/api-automation/interface-management",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="文档工作流",
                path="document-workflow",
                order=3,
                parent_id=api_auto_menu.id,
                icon="mdi:file-document-outline",
                is_hidden=False,
                component="/api-automation/document-workflow",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="脚本管理",
                path="script-management",
                order=4,
                parent_id=api_auto_menu.id,
                icon="mdi:test-tube",
                is_hidden=False,
                component="/api-automation/script-management",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="测试执行",
                path="test-execution",
                order=5,
                parent_id=api_auto_menu.id,
                icon="mdi:play-circle-outline",
                is_hidden=True,
                component="/api-automation/test-execution",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="定时任务",
                path="scheduled-tasks",
                order=6,
                parent_id=api_auto_menu.id,
                icon="mdi:clock-outline",
                is_hidden=False,
                component="/api-automation/scheduled-tasks",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="执行报告",
                path="execution-reports",
                order=7,
                parent_id=api_auto_menu.id,
                icon="mdi:file-chart",
                is_hidden=False,
                component="/api-automation/execution-reports",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="分析详情",
                path="analysis-detail",
                order=8,
                parent_id=api_auto_menu.id,
                icon="mdi:chart-line",
                is_hidden=True,
                component="/api-automation/analysis-detail",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="脚本预览",
                path="script-preview",
                order=9,
                parent_id=api_auto_menu.id,
                icon="mdi:script-text-outline",
                is_hidden=True,
                component="/api-automation/script-preview",
                keepalive=False,
            ),
        ]
        await Menu.bulk_create(api_auto_children)


async def init_apis():
    apis = await api_controller.model.exists()
    if not apis:
        await api_controller.refresh_api()


async def ensure_hidden_api_automation_menus():
    """补全 API 自动化模块的隐藏菜单（幂等，启动时调用一次）。"""
    api_auto_menu = await Menu.filter(path="/api-automation", parent_id=0).first()
    if not api_auto_menu:
        return

    hidden_menus = [
        {
            "name": "分析详情",
            "path": "analysis-detail",
            "order": 8,
            "icon": "mdi:chart-line",
            "component": "/api-automation/analysis-detail",
        },
        {
            "name": "脚本预览",
            "path": "script-preview",
            "order": 9,
            "icon": "mdi:script-text-outline",
            "component": "/api-automation/script-preview",
        },
    ]

    for m in hidden_menus:
        menu_obj = await Menu.filter(
            parent_id=api_auto_menu.id, path=m["path"]
        ).first()
        if not menu_obj:
            menu_obj = await Menu.create(
                menu_type=MenuType.MENU,
                name=m["name"],
                path=m["path"],
                order=m["order"],
                parent_id=api_auto_menu.id,
                icon=m["icon"],
                is_hidden=True,
                component=m["component"],
                keepalive=False,
            )

        # 把菜单同步分配给所有现有角色，避免非超级用户因 role_menu 缺失而 404
        for role in await Role.all():
            if not await role.menus.filter(id=menu_obj.id).exists():
                await role.menus.add(menu_obj)


async def ensure_new_api_automation_menus():
    """幂等补全新菜单（用例管理等），并同步分配角色。"""
    api_auto_menu = await Menu.filter(path="/api-automation", parent_id=0).first()
    if not api_auto_menu:
        return

    new_menus = [
        {
            "name": "用例管理",
            "path": "testcase-management",
            "order": 5,
            "icon": "mdi:file-tree",
            "is_hidden": False,
            "component": "/api-automation/testcase-management",
        },
    ]

    for m in new_menus:
        menu_obj = await Menu.filter(
            parent_id=api_auto_menu.id, path=m["path"]
        ).first()
        if not menu_obj:
            menu_obj = await Menu.create(
                menu_type=MenuType.MENU,
                name=m["name"],
                path=m["path"],
                order=m["order"],
                parent_id=api_auto_menu.id,
                icon=m["icon"],
                is_hidden=m["is_hidden"],
                component=m["component"],
                keepalive=False,
            )

        for role in await Role.all():
            if not await role.menus.filter(id=menu_obj.id).exists():
                await role.menus.add(menu_obj)


async def init_db():
    command = Command(tortoise_config=settings.TORTOISE_ORM)
    try:
        await command.init_db(safe=True)
    except FileExistsError:
        pass

    await command.init()
    try:
        # 跳过自动迁移，避免Aerich的bug
        logger.info("跳过Aerich自动迁移，使用手动初始化的数据库")
        # await command.migrate()
    except AttributeError:
        logger.warning("unable to retrieve model history from database, model history will be created from scratch")
        shutil.rmtree("migrations")
        await command.init_db(safe=True)

    try:
        await command.upgrade(run_in_transaction=True)
    except Exception as e:
        logger.warning(f"Aerich upgrade failed, but database is already initialized: {str(e)}")
        # 数据库已经通过bypass_aerich.py初始化，所以可以忽略这个错误


async def init_roles():
    roles = await Role.exists()
    if not roles:
        admin_role = await Role.create(
            name="管理员",
            desc="管理员角色",
        )
        user_role = await Role.create(
            name="普通用户",
            desc="普通用户角色",
        )

        # 分配所有API给管理员角色
        all_apis = await Api.all()
        await admin_role.apis.add(*all_apis)
        # 分配所有菜单给管理员和普通用户
        all_menus = await Menu.all()
        await admin_role.menus.add(*all_menus)
        await user_role.menus.add(*all_menus)

        # 为普通用户分配基本API
        basic_apis = await Api.filter(Q(method__in=["GET"]) | Q(tags="基础模块"))
        await user_role.apis.add(*basic_apis)


async def init_data():
    await init_db()
    await init_superuser()
    await init_menus()
    await ensure_hidden_api_automation_menus()
    await ensure_new_api_automation_menus()
    await init_apis()
    await init_roles()
