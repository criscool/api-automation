"""UI 自动化模块 - API endpoints 路由聚合

阶段二注册的路由：
- health           健康检查（无权限，便于探测）
- screenshots     截图上传
- page-analysis   页面分析触发 / SSE / 列表 / 详情 / 删除
- scripts         脚本生成 / 手动新建 / 列表 / 详情 / 更新 / 删除

阶段三新增:
- executions      触发执行 / 列表 / 详情 / 取消 / SSE 事件流
- reports         报告列表 / 详情

阶段四(图片库)新增:
- image-library   上传/列表/详情/更新元数据/删除(SHA256 查重 + 引用计数)

阶段四(录制)新增:
- recordings      创建录制 / 列表 / 详情 / 取消 / 重新优化 / SSE 事件流

阶段五(批量执行)新增:
- batches         创建批次 / 列表 / 详情 / 取消 / SSE 事件流
"""
from .health import router as health_router
from .screenshots import router as screenshots_router
from .page_analysis import router as page_analysis_router
from .scripts import router as scripts_router
from .executions import (
    batches_router,
    executions_router,
    executions_stream_router,
    reports_router,
)
from .image_library import router as image_library_router
from .recordings import recordings_router, recordings_stream_router

__all__ = [
    "health_router",
    "screenshots_router",
    "page_analysis_router",
    "scripts_router",
    "executions_router",
    "executions_stream_router",
    "reports_router",
    "image_library_router",
    "recordings_router",
    "recordings_stream_router",
    "batches_router",
]
