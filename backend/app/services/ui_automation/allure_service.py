"""
按需生成 UI 自动化的 Allure 报告 — 单脚本 / 批次

设计要点
--------
1. **按需触发**：playwright 跑测试时 allure-playwright reporter 写 `allure-results/`，
   本模块通过 API 接口被前端按钮调用，才执行 `allure generate` 出 HTML。
2. **历史趋势**：按 script_id / batch_name 维度维护长期 history 目录，让 Allure 报告里
   "Trend" 模块能显示跨次曲线。
3. **静默降级**：allure CLI 不在 PATH 时返回 None，调用方据此判断；
   subprocess timeout / 非 0 返回码也降级为 None。
4. **30 天 retention**：cleanup_old_history 由 app 启动时的循环任务调用。

约定
----
- 单脚本 results 在 `<UI_ARTIFACT_DIR>/exec_<exec_id>/allure-results/`
- 单脚本 report 输出到 `<UI_ARTIFACT_DIR>/exec_<exec_id>/allure-report/`
- 批次 report 输出到 `<UI_ARTIFACT_DIR>/batch_<batch_id>/allure-report/`
- history 长期目录 `<UI_ARTIFACT_DIR>/_allure_history/<key>/`
- 报告 URL 通过 FastAPI StaticFiles 挂载 `/static/ui-reports/` 暴露
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from loguru import logger

from app.settings.config import settings


# allure generate 单次调用最长 180s（防止卡死拖资源）
ALLURE_TIMEOUT_SECONDS = 180


def is_allure_cli_available() -> bool:
    """探测 allure CLI 是否在 PATH 里。前端按钮 disabled 状态依赖此判断。"""
    return shutil.which("allure") is not None


async def generate_single_allure(
    *,
    execution_id: str,
    script_id: Optional[str] = None,
) -> Optional[str]:
    """生成单脚本的 Allure 报告。

    Args:
        execution_id: 执行 ID（决定 results / report 目录）
        script_id: 用于 history 隔离 key；为空则不享用历史趋势

    Returns:
        成功时返回相对 URL（如 ``/static/ui-reports/exec_xxx/allure-report/index.html``）；
        results 为空 / allure CLI 缺失 / generate 失败均返回 None。
    """
    exec_dir = Path(settings.UI_ARTIFACT_DIR) / f"exec_{execution_id}"
    results_dir = exec_dir / "allure-results"
    report_dir = exec_dir / "allure-report"

    if not results_dir.exists() or not any(results_dir.iterdir()):
        logger.warning(f"[allure {execution_id}] allure-results 为空或不存在，跳过 generate")
        return None

    history_key = f"script_{script_id}" if script_id else None
    ok = await _generate_with_history(
        results_dirs=[str(results_dir)],
        report_dir=str(report_dir),
        history_key=history_key,
    )
    if not ok:
        return None
    return f"/static/ui-reports/exec_{execution_id}/allure-report/index.html"


async def generate_batch_allure(
    *,
    batch_id: str,
    batch_name: str,
    execution_ids: List[str],
) -> Optional[str]:
    """合并多个子执行的 allure-results 生成批次级汇总报告。

    Allure CLI 原生支持 ``allure generate <dir1> <dir2> ... -o <out>``，多个 results
    目录会被按 historyId / suite 树合并展示。
    """
    sub_dirs: List[str] = []
    for eid in execution_ids:
        d = Path(settings.UI_ARTIFACT_DIR) / f"exec_{eid}" / "allure-results"
        if d.exists() and any(d.iterdir()):
            sub_dirs.append(str(d))
    if not sub_dirs:
        logger.warning(f"[allure batch {batch_id}] 无可用 allure-results 子目录")
        return None

    batch_dir = Path(settings.UI_ARTIFACT_DIR) / f"batch_{batch_id}"
    report_dir = batch_dir / "allure-report"

    # 历史 key 按批次名 slug 隔离：同名批次的多次执行可看趋势
    slug = re.sub(r"\W+", "_", (batch_name or "").lower()).strip("_")[:64] or "unnamed"
    history_key = f"batch_{slug}"

    ok = await _generate_with_history(
        results_dirs=sub_dirs,
        report_dir=str(report_dir),
        history_key=history_key,
    )
    if not ok:
        return None
    return f"/static/ui-reports/batch_{batch_id}/allure-report/index.html"


async def _generate_with_history(
    *,
    results_dirs: List[str],
    report_dir: str,
    history_key: Optional[str],
) -> bool:
    """调 allure generate，含历史目录复用 + 回灌。

    流程：
        1. 把长期 history 拷到第一个 results_dir/history/（allure 据此识别历史轨迹）
        2. 跑 allure generate
        3. 把新生成的 report_dir/history/ 拷回长期目录，供下次复用
    """
    allure_cli = shutil.which("allure")
    if not allure_cli:
        logger.warning("allure CLI 未安装，generate 跳过")
        return False

    history_dir: Optional[Path] = None
    if history_key:
        history_dir = Path(settings.UI_ARTIFACT_DIR) / "_allure_history" / history_key
        history_dir.mkdir(parents=True, exist_ok=True)
        if any(history_dir.iterdir()):
            try:
                shutil.copytree(
                    history_dir,
                    Path(results_dirs[0]) / "history",
                    dirs_exist_ok=True,
                )
            except Exception as e:
                logger.warning(f"复制 history 进 results 失败（不致命）: {e}")

    # 跑 allure generate
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [allure_cli, "generate", *results_dirs, "-o", report_dir, "--clean"],
            capture_output=True,
            text=True,
            timeout=ALLURE_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            logger.warning(
                f"allure generate 非零返回 rc={proc.returncode} "
                f"stderr={(proc.stderr or '')[:500]}"
            )
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"allure generate 超时（{ALLURE_TIMEOUT_SECONDS}s）")
        return False
    except Exception as e:
        logger.warning(f"allure generate 异常: {e}")
        return False

    # 回灌新 history 到长期目录
    if history_dir:
        new_history = Path(report_dir) / "history"
        if new_history.exists():
            try:
                shutil.copytree(new_history, history_dir, dirs_exist_ok=True)
            except Exception as e:
                logger.warning(f"回灌新 history 失败（不致命）: {e}")
    return True


async def cleanup_old_history(retention_days: int = 30) -> int:
    """清理 ``_allure_history/`` 下 mtime 超过 retention_days 的子目录。

    Returns:
        清理的目录数量。
    """
    root = Path(settings.UI_ARTIFACT_DIR) / "_allure_history"
    if not root.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(child.stat().st_mtime)
            if mtime < cutoff:
                shutil.rmtree(child)
                removed += 1
        except Exception as e:
            logger.warning(f"清理历史目录失败 {child}: {e}")
    return removed


# ============================================================================
# 高层触发器：DB 状态机管理 + 后台任务（供 API 层 + 自动生成钩子共用）
# ============================================================================

async def trigger_single_generate_task(
    *,
    execution_id: str,
    script_id: Optional[str] = None,
) -> bool:
    """触发单脚本 Allure 生成的后台任务。

    - 检测 Allure CLI 可用性 + DB 记录存在
    - 若已在 generating 直接返回 False（避免重复触发）
    - 立即把 DB 状态标为 generating + 清空 error
    - 启动 asyncio.create_task 跑生成任务，任务成功/失败会更新 DB

    Returns:
        True 表示已成功启动后台任务；False 表示因 CLI 缺失 / 记录不存在 / 已在生成中 而未启动
    """
    from app.models.ui_automation import UiTestReport

    if not is_allure_cli_available():
        logger.debug(f"[allure {execution_id}] CLI 不可用，跳过自动生成")
        return False

    row = await UiTestReport.filter(execution_id=execution_id).first()
    if not row:
        logger.debug(f"[allure {execution_id}] UiTestReport 不存在，跳过")
        return False
    if row.allure_status == "generating":
        logger.debug(f"[allure {execution_id}] 已有生成任务在进行中，跳过")
        return False

    await UiTestReport.filter(execution_id=execution_id).update(
        allure_status="generating", allure_error=""
    )

    async def _run():
        try:
            url = await generate_single_allure(
                execution_id=execution_id, script_id=script_id or row.script_id
            )
            if url:
                await UiTestReport.filter(execution_id=execution_id).update(
                    allure_report_url=url,
                    allure_status="ready",
                    allure_generated_at=datetime.now(),
                )
            else:
                await UiTestReport.filter(execution_id=execution_id).update(
                    allure_status="failed",
                    allure_error="生成失败（详见服务器日志）",
                )
        except Exception as e:
            logger.exception(f"[allure {execution_id}] 自动生成异常")
            await UiTestReport.filter(execution_id=execution_id).update(
                allure_status="failed", allure_error=str(e)[:500]
            )

    asyncio.create_task(_run())
    return True


async def trigger_batch_generate_task(
    *,
    batch_id: str,
    batch_name: str = "",
    execution_ids: Optional[List[str]] = None,
) -> bool:
    """触发批次级 Allure 汇总生成的后台任务。

    execution_ids 未提供时会从 UiScriptExecution 反查。
    """
    from app.models.ui_automation import UiBatchExecution, UiScriptExecution

    if not is_allure_cli_available():
        logger.debug(f"[allure batch {batch_id}] CLI 不可用，跳过自动生成")
        return False

    batch = await UiBatchExecution.filter(batch_id=batch_id).first()
    if not batch:
        return False
    if batch.batch_allure_status == "generating":
        return False

    if execution_ids is None:
        execution_ids = [
            row.execution_id
            for row in await UiScriptExecution.filter(batch_id=batch_id).only("execution_id")
        ]
    if not execution_ids:
        return False

    resolved_name = batch_name or batch.name or ""

    await UiBatchExecution.filter(batch_id=batch_id).update(
        batch_allure_status="generating", batch_allure_error=""
    )

    async def _run():
        try:
            url = await generate_batch_allure(
                batch_id=batch_id,
                batch_name=resolved_name,
                execution_ids=execution_ids,
            )
            if url:
                await UiBatchExecution.filter(batch_id=batch_id).update(
                    batch_allure_report_url=url,
                    batch_allure_status="ready",
                    batch_allure_generated_at=datetime.now(),
                )
            else:
                await UiBatchExecution.filter(batch_id=batch_id).update(
                    batch_allure_status="failed",
                    batch_allure_error="生成失败（详见服务器日志）",
                )
        except Exception as e:
            logger.exception(f"[allure batch {batch_id}] 自动生成异常")
            await UiBatchExecution.filter(batch_id=batch_id).update(
                batch_allure_status="failed", batch_allure_error=str(e)[:500]
            )

    asyncio.create_task(_run())
    return True
