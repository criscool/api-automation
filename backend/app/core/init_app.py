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
                # SSE / 流式接口必须排除 —— middlewares.HttpAuditLogMiddleware
                # 一旦尝试 async for response.body_iterator 就会卡死整个 worker
                r"/stream",
                r"/events",
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
            menu_type=MenuType.CATALOG,
            name="UI自动化",
            path="/ui-automation",
            order=2,
            parent_id=0,
            icon="material-symbols:web",
            is_hidden=False,
            component="Layout",
            keepalive=False,
            redirect="/ui-automation/dashboard",
        )
        ui_auto_parent = await Menu.filter(name="UI自动化", parent_id=0).first()
        ui_auto_children = [
            Menu(
                menu_type=MenuType.MENU,
                name="UI自动化仪表板",
                path="dashboard",
                order=1,
                parent_id=ui_auto_parent.id,
                icon="carbon:dashboard",
                is_hidden=False,
                component="/ui-automation/dashboard",
                keepalive=False,
            ),
        ]
        await Menu.bulk_create(ui_auto_children)

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


async def _ensure_menu_ui_automation():
    """幂等迁移：把占位"一级菜单"改造成"UI自动化"，并补齐阶段二/三的占位子菜单

    零回归保障：
    - 不删除任何现有菜单，仅 update 占位菜单或新增 UI自动化菜单
    - 跑 100 次结果一致
    - 同时确保 UI自动化 一级菜单下子菜单齐全（dashboard 必有，其余占位先建）
    """
    from loguru import logger

    # UI 自动化一级菜单 + 完整子菜单清单（按阶段二/三规划）
    ui_children_spec = [
        {
            "name": "UI自动化仪表板",
            "path": "dashboard",
            "order": 1,
            "icon": "carbon:dashboard",
            "component": "/ui-automation/dashboard",
        },
        {
            "name": "图片库",
            "path": "image-library",
            "order": 2,
            "icon": "mdi:image-multiple-outline",
            "component": "/ui-automation/image-library",
        },
        {
            "name": "页面分析",
            "path": "page-analysis",
            "order": 3,
            "icon": "mdi:image-search-outline",
            "component": "/ui-automation/page-analysis",
        },
        {
            "name": "录制管理",
            "path": "recording-management",
            "order": 4,
            "icon": "mdi:record-rec",
            "component": "/ui-automation/recording-management",
        },
        {
            "name": "脚本管理",
            "path": "script-management",
            "order": 5,
            "icon": "mdi:script-text-outline",
            "component": "/ui-automation/script-management",
        },
        {
            "name": "执行报告",
            "path": "execution-reports",
            "order": 6,
            "icon": "mdi:file-chart",
            "component": "/ui-automation/execution-reports",
        },
    ]

    async def _ensure_children(parent_id: int):
        for spec in ui_children_spec:
            existing = await Menu.filter(parent_id=parent_id, path=spec["path"]).first()
            if existing:
                # 校准 order/icon/component,允许 spec 调整顺序后重启即生效
                dirty = False
                if existing.order != spec["order"]:
                    existing.order = spec["order"]
                    dirty = True
                if existing.icon != spec["icon"]:
                    existing.icon = spec["icon"]
                    dirty = True
                if existing.component != spec["component"]:
                    existing.component = spec["component"]
                    dirty = True
                if existing.name != spec["name"]:
                    existing.name = spec["name"]
                    dirty = True
                if dirty:
                    await existing.save()
            else:
                await Menu.create(
                    menu_type=MenuType.MENU,
                    name=spec["name"],
                    path=spec["path"],
                    order=spec["order"],
                    parent_id=parent_id,
                    icon=spec["icon"],
                    is_hidden=False,
                    component=spec["component"],
                    keepalive=False,
                )

    # 1. 已有"UI自动化"菜单 → 补齐缺失子菜单
    ui_auto = await Menu.filter(name="UI自动化", parent_id=0).first()
    if ui_auto:
        await _ensure_children(ui_auto.id)
        # 把新增的子菜单同步分配给所有角色，避免非超级用户拿不到
        for role in await Role.all():
            for spec in ui_children_spec:
                child = await Menu.filter(parent_id=ui_auto.id, path=spec["path"]).first()
                if child and not await role.menus.filter(id=child.id).exists():
                    await role.menus.add(child)
        return

    # 2. 改造占位"一级菜单"（旧库可能存在）
    legacy = await Menu.filter(name="一级菜单", parent_id=0, path="/top-menu").first()
    if legacy:
        legacy.name = "UI自动化"
        legacy.path = "/ui-automation"
        legacy.icon = "material-symbols:web"
        legacy.menu_type = MenuType.CATALOG
        legacy.component = "Layout"
        legacy.redirect = "/ui-automation/dashboard"
        await legacy.save()
        await _ensure_children(legacy.id)
        logger.info(f"UI自动化菜单：已将占位'一级菜单'改造为'UI自动化'（id={legacy.id}）+ 子菜单")
        return

    # 3. 全新创建
    ui_auto = await Menu.create(
        menu_type=MenuType.CATALOG,
        name="UI自动化",
        path="/ui-automation",
        order=2,
        parent_id=0,
        icon="material-symbols:web",
        is_hidden=False,
        component="Layout",
        keepalive=False,
        redirect="/ui-automation/dashboard",
    )
    await _ensure_children(ui_auto.id)
    logger.info("UI自动化菜单：已全新创建 + 占位子菜单")


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
    await _ensure_menu_ui_automation()
    await ensure_hidden_api_automation_menus()
    await ensure_new_api_automation_menus()
    await init_apis()
    await init_roles()
