import sys
import asyncio

# Windows + uvicorn reload 模式下,worker 进程默认 _WindowsSelectorEventLoop,
# 不支持 asyncio.create_subprocess_exec(执行 Playwright 时直接 NotImplementedError)。
# 必须在 import FastAPI / asyncio.run 之前切到 Proactor,reload watcher 跑在 parent
# 进程不受影响。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from tortoise import Tortoise

from app.core.exceptions import SettingNotFound
from app.core.init_app import (
    init_data,
    make_middlewares,
    register_exceptions,
    register_routers,
)

try:
    from app.settings.config import settings
except ImportError:
    raise SettingNotFound("Can not import settings")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库和基础数据
    await init_data()

    # 免删库增量迁移（新增表/列）
    from app.models.api_automation import _ensure_migration_testcase_categories
    await _ensure_migration_testcase_categories()

    from app.models.api_automation import _ensure_migration_scheduled_tasks
    await _ensure_migration_scheduled_tasks()

    from app.models.api_automation import _ensure_migration_scenario_step
    await _ensure_migration_scenario_step()

    from app.models.api_automation import _ensure_migration_flow_summary
    await _ensure_migration_flow_summary()

    from app.models.api_automation import _ensure_migration_test_script_heal_fields
    await _ensure_migration_test_script_heal_fields()

    # 执行环境管理（API + UI 共用的运行时环境配置）
    from app.models.api_automation import _ensure_migration_execution_environments
    await _ensure_migration_execution_environments()

    # UI 自动化 Allure 报告相关字段（按需生成方案）
    from app.models.ui_automation import _ensure_migration_ui_allure_fields
    await _ensure_migration_ui_allure_fields()

    # UI 自动化脚本"最近执行"字段（脚本管理列表快速展示用）
    from app.models.ui_automation import _ensure_migration_ui_script_last_execution
    await _ensure_migration_ui_script_last_execution()

    # UI 自动化模块（一期）—— 仅在 UI_AUTOMATION_ENABLED=True 时建表 + 注册菜单
    if settings.UI_AUTOMATION_ENABLED:
        from app.models.ui_automation import _ensure_migration_ui_automation_tables
        await _ensure_migration_ui_automation_tables()

        # 用例分类表 + ui_test_scripts.category_id 列（幂等）
        from app.models.ui_automation import _ensure_migration_ui_testcase_categories
        await _ensure_migration_ui_testcase_categories()

        # 幂等迁移：把旧的"一级菜单"占位改造成"UI自动化"，或全新创建
        from app.core.init_app import _ensure_menu_ui_automation
        await _ensure_menu_ui_automation()

        # 阶段三 P3-06:后端重启自愈 —— 把残留 running/pending 标记为 interrupted
        try:
            from app.services.ui_automation.session_service import (
                heal_dangling_executions,
                heal_dangling_recordings,
            )
            await asyncio.wait_for(heal_dangling_executions(), timeout=5)
            await asyncio.wait_for(heal_dangling_recordings(), timeout=5)
        except asyncio.TimeoutError:
            from loguru import logger
            logger.warning("UI 执行自愈超时,跳过")
        except Exception as e:
            from loguru import logger
            logger.error(f"UI 执行自愈失败: {e}")

        # Allure 报告自愈：把僵尸的 generating 状态重置为 failed，避免前端轮询永远不结束
        try:
            from app.api.v1.endpoints.ui_automation.executions import reset_zombie_allure_status
            n = await asyncio.wait_for(reset_zombie_allure_status(), timeout=5)
            if n > 0:
                from loguru import logger
                logger.info(f"Allure 僵尸状态重置: {n} 条")
        except asyncio.TimeoutError:
            from loguru import logger
            logger.warning("Allure 自愈超时,跳过")
        except Exception as e:
            from loguru import logger
            logger.error(f"Allure 自愈失败: {e}")

        # Allure history retention 后台循环：每 24h 清理过期 history 目录
        async def _allure_history_cleanup_loop():
            from loguru import logger
            from app.services.ui_automation.allure_service import cleanup_old_history
            # 启动后先等 5 分钟，避开启动期资源争抢
            await asyncio.sleep(300)
            while True:
                try:
                    n = await cleanup_old_history(retention_days=30)
                    if n > 0:
                        logger.info(f"Allure history retention 清理: {n} 个目录")
                except Exception as e:
                    logger.warning(f"Allure history retention 异常: {e}")
                await asyncio.sleep(24 * 3600)

        asyncio.create_task(_allure_history_cleanup_loop())

    # 初始化API自动化编排器
    try:
        from app.api.v1.endpoints.api_automation import initialize_orchestrator
        await asyncio.wait_for(initialize_orchestrator(), timeout=10)
    except asyncio.TimeoutError:
        from loguru import logger
        logger.warning("初始化API自动化编排器超时，跳过")
    except Exception as e:
        from loguru import logger
        logger.error(f"初始化API自动化编排器失败: {str(e)}")

    # 初始化接口管理编排器
    try:
        from app.api.v1.endpoints.interface_management import initialize_orchestrator as init_interface_orchestrator
        await asyncio.wait_for(init_interface_orchestrator(), timeout=10)
    except asyncio.TimeoutError:
        from loguru import logger
        logger.warning("初始化接口管理编排器超时，跳过")
    except Exception as e:
        from loguru import logger
        logger.error(f"初始化接口管理编排器失败: {str(e)}")

    # 初始化 Marker PDF 服务
    try:
        from app.services.pdf import initialize_marker_service
        success = await asyncio.wait_for(initialize_marker_service(), timeout=10)
        if success:
            from loguru import logger
            logger.info("✅ Marker PDF 服务初始化成功")
        else:
            from loguru import logger
            logger.warning("⚠️ Marker PDF 服务初始化失败，将使用备用 PDF 解析方法")
    except asyncio.TimeoutError:
        from loguru import logger
        logger.warning("Marker PDF 服务初始化超时，跳过")
    except Exception as e:
        from loguru import logger
        logger.error(f"初始化 Marker PDF 服务失败: {str(e)}")

    # 初始化定时任务调度器
    try:
        from app.services.api_automation.scheduled_task_service import get_scheduled_task_service
        _scheduler = get_scheduled_task_service()
        await asyncio.wait_for(_scheduler.start(), timeout=10)
    except asyncio.TimeoutError:
        from loguru import logger
        logger.warning("初始化定时任务调度器超时，跳过")
    except Exception as e:
        from loguru import logger
        logger.error(f"初始化定时任务调度器失败: {str(e)}")

    # UI 自动化产物清理任务(阶段三 P3-09):复用同一 APScheduler 实例
    if settings.UI_AUTOMATION_ENABLED:
        try:
            from app.services.api_automation.scheduled_task_service import get_scheduled_task_service
            from app.services.ui_automation.cleanup_service import register_cleanup_job
            _scheduler = get_scheduled_task_service()
            if _scheduler._scheduler is not None:
                register_cleanup_job(_scheduler._scheduler)
        except Exception as e:
            from loguru import logger
            logger.error(f"注册 UI 产物清理任务失败: {e}")

    yield

    # 关闭定时任务调度器
    try:
        from app.services.api_automation.scheduled_task_service import get_scheduled_task_service
        _scheduler = get_scheduled_task_service()
        await _scheduler.shutdown()
    except Exception as e:
        from loguru import logger
        logger.error(f"关闭定时任务调度器失败: {str(e)}")

    await Tortoise.close_connections()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_TITLE,
        description=settings.APP_DESCRIPTION,
        version=settings.VERSION,
        openapi_url="/openapi.json",
        middleware=make_middlewares(),
        lifespan=lifespan,
    )
    register_exceptions(app)
    register_routers(app, prefix="/api")

    # 挂载 reports 目录为静态资源，前端可直接访问 Allure/HTML/JSON 报告文件
    # 例如：GET /reports/{execution_id}/allure-report/index.html
    reports_dir = Path(__file__).resolve().parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/reports", StaticFiles(directory=str(reports_dir), html=True), name="reports")

    # UI 自动化报告静态资源(阶段三 P3-06):仅在开关开启时挂载,
    # 指向 UI_ARTIFACT_DIR (默认 backend/generated_ui_tests/reports/)
    # 前端通过 /static/ui-reports/exec_<id>/html/index.html 加载报告 iframe
    if settings.UI_AUTOMATION_ENABLED:
        ui_artifact_dir = Path(settings.UI_ARTIFACT_DIR)
        ui_artifact_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/static/ui-reports",
            StaticFiles(directory=str(ui_artifact_dir), html=True),
            name="ui-reports",
        )

        # UI 图片库静态资源(阶段四):指向 {UI_AUTOMATION_WORKSPACE}/image_library
        # 前端用 /static/ui-images/thumbnails/<image_id>.jpg 直接显示缩略图,
        # 避免每张图都走鉴权接口拖累列表渲染。
        ui_image_dir = Path(settings.UI_AUTOMATION_WORKSPACE) / "image_library"
        ui_image_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/static/ui-images",
            StaticFiles(directory=str(ui_image_dir), html=False),
            name="ui-images",
        )

    return app


app = create_app()
