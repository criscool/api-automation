from contextlib import asynccontextmanager
import asyncio
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

    yield
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

    return app


app = create_app()
