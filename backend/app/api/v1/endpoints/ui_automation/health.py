"""UI 自动化健康检查

返回结构包含运行时依赖自检（node/playwright/chromium/工作区/LLM 可达性），
便于阶段一就发现服务器环境问题。
"""
import os
import shutil
import subprocess
from typing import Any, Dict

from fastapi import APIRouter
from loguru import logger

from app.settings.config import settings

router = APIRouter(tags=["UI自动化"])


def _check_command(cmd: list[str], timeout: int = 5) -> Dict[str, Any]:
    """运行命令获取版本，失败返回 unavailable。"""
    binary = cmd[0]
    if shutil.which(binary) is None:
        return {"available": False, "reason": f"{binary} 未安装"}
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            return {"available": False, "reason": result.stderr.strip()[:200] or "non-zero exit"}
        return {"available": True, "version": result.stdout.strip().splitlines()[0] if result.stdout else ""}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "command timeout"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """UI 自动化模块健康检查（含运行时前置依赖自检）

    返回结构：
    {
        "code": 200, "msg": "OK", "success": true,
        "data": {
            "enabled": true,
            "status": "ok|degraded|disabled",
            "checks": {...}
        }
    }
    """
    if not settings.UI_AUTOMATION_ENABLED:
        return {
            "code": 200,
            "msg": "UI 自动化模块已停用（UI_AUTOMATION_ENABLED=false）",
            "success": True,
            "data": {"enabled": False, "status": "disabled", "checks": {}},
        }

    checks: Dict[str, Any] = {}

    # 1. Node.js
    checks["node"] = _check_command(["node", "--version"])

    # 2. Playwright（在工作区里检测）
    workspace = settings.UI_AUTOMATION_WORKSPACE
    workspace_exists = os.path.isdir(workspace)
    checks["workspace"] = {
        "available": workspace_exists,
        "path": workspace,
        "writable": os.access(workspace, os.W_OK) if workspace_exists else False,
    }

    # 3. Playwright CLI（在 workspace 下能跑就行）
    if workspace_exists and shutil.which("npx"):
        try:
            result = subprocess.run(
                ["npx", "--no-install", "playwright", "--version"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            checks["playwright"] = {
                "available": result.returncode == 0,
                "version": result.stdout.strip() if result.returncode == 0 else "",
                "reason": result.stderr.strip()[:200] if result.returncode != 0 else "",
            }
        except Exception as e:
            checks["playwright"] = {"available": False, "reason": str(e)[:200]}
    else:
        checks["playwright"] = {"available": False, "reason": "npx 不可用或 workspace 不存在"}

    # 4. LLM Key 配置（不实际调用，只看是否配置）
    # 注意：项目通过 pydantic BaseSettings 加载 .env，配置在 settings 对象上而不在 os.environ
    try:
        from app.core.config import settings as core_settings
        llm_text_configured = bool(core_settings.LLM_API_KEY)
    except Exception:
        llm_text_configured = False
    checks["llm_text"] = {
        "configured": llm_text_configured or bool(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")),
    }
    checks["llm_vision"] = {
        "configured": bool(settings.DOUBAO_API_KEY or os.getenv("DOUBAO_API_KEY")),
        "model": settings.DOUBAO_VISION_MODEL,
    }

    # 5. 总体状态
    blocking = []
    if not checks["node"]["available"]:
        blocking.append("node 未安装")
    if not checks["workspace"]["available"]:
        blocking.append("workspace 不存在")
    if not checks["playwright"]["available"]:
        blocking.append("playwright 不可用")

    if blocking:
        status = "degraded"
        msg = f"UI 自动化模块降级运行：{'; '.join(blocking)}"
        logger.warning(msg)
    else:
        status = "ok"
        msg = "UI 自动化模块就绪"

    return {
        "code": 200,
        "msg": msg,
        "success": True,
        "data": {
            "enabled": True,
            "status": status,
            "checks": checks,
        },
    }
