"""
定时任务调度服务
基于 APScheduler + AsyncIOExecutor，管理定时任务的调度和执行
"""
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from app.models.api_automation import ScheduledTask, TestScript, TestExecution
from app.core.enums import ExecutionStatus


class ScheduledTaskService:
    """定时任务调度服务（单例）"""

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._job_map: Dict[str, str] = {}  # task_id → apscheduler job_id

    # ---- 生命周期 ----

    async def start(self):
        """启动调度器：加载所有 enabled 任务并注册到 APScheduler"""
        self._scheduler = AsyncIOScheduler()
        self._scheduler.start()
        logger.info("APScheduler 调度器已启动")

        tasks = await ScheduledTask.filter(status="enabled")
        for task in tasks:
            try:
                self._schedule_task(task)
            except Exception as e:
                logger.error(f"注册定时任务失败 task_id={task.task_id}: {e}")

        logger.info(f"已注册 {len(self._job_map)} 个定时任务")

    async def shutdown(self):
        """关闭调度器"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("APScheduler 调度器已关闭")

    # ---- 调度器操作 ----

    def _build_trigger(self, task: ScheduledTask):
        """根据任务配置构造 APScheduler trigger"""
        if task.schedule_type == "cron":
            parts = [p.replace("?", "*") for p in task.cron_expression.strip().split()]
            return CronTrigger(
                second=parts[0] if len(parts) > 0 else "0",
                minute=parts[1] if len(parts) > 1 else "0",
                hour=parts[2] if len(parts) > 2 else "*",
                day=parts[3] if len(parts) > 3 else "*",
                month=parts[4] if len(parts) > 4 else "*",
                day_of_week=parts[5] if len(parts) > 5 else "*",
            )
        elif task.schedule_type == "interval":
            kwargs = {
                "minutes": task.interval_value,
            }
            if task.interval_unit == "hours":
                kwargs = {"hours": task.interval_value}
            elif task.interval_unit == "days":
                kwargs = {"days": task.interval_value}
            elif task.interval_unit == "weeks":
                kwargs = {"weeks": task.interval_value}
            return IntervalTrigger(**kwargs)
        elif task.schedule_type == "once":
            return DateTrigger(run_date=task.execution_time)
        else:
            raise ValueError(f"不支持的调度类型: {task.schedule_type}")

    def _schedule_task(self, task: ScheduledTask):
        """注册单个任务到调度器"""
        trigger = self._build_trigger(task)

        job = self._scheduler.add_job(
            self._execute_wrapper,
            trigger=trigger,
            args=[task.task_id],
            id=f"task_{task.task_id}",
            replace_existing=True,
            max_instances=1,
        )

        self._job_map[task.task_id] = job.id

        # 更新 next_execution_time
        next_run = job.next_run_time
        if next_run:
            task.next_execution_time = next_run.replace(tzinfo=None)
        return job

    def _unschedule_task(self, task_id: str):
        """从调度器移除任务"""
        job_id = self._job_map.pop(task_id, None)
        if job_id and self._scheduler:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

    # ---- 供 CRUD 接口调用的方法 ----

    async def add_task(self, task: ScheduledTask):
        """新增任务并注册到调度器"""
        if task.status == "enabled":
            self._schedule_task(task)
            await task.save(update_fields=["next_execution_time"])

    async def update_task(self, task: ScheduledTask):
        """更新任务后重新调度"""
        self._unschedule_task(task.task_id)
        if task.status == "enabled":
            self._schedule_task(task)
            await task.save(update_fields=["next_execution_time"])

    async def remove_task(self, task_id: str):
        """删除任务"""
        self._unschedule_task(task_id)

    async def toggle_task(self, task: ScheduledTask):
        """启停切换"""
        if task.status == "enabled":
            self._schedule_task(task)
            await task.save(update_fields=["next_execution_time"])
        else:
            self._unschedule_task(task.task_id)
            task.next_execution_time = None
            await task.save(update_fields=["next_execution_time"])

    # ---- 执行回调 ----

    async def _execute_wrapper(self, task_id: str):
        """APScheduler job 回调：执行关联的脚本"""
        import asyncio as _asyncio

        task = await ScheduledTask.filter(task_id=task_id).first()
        if not task:
            logger.warning(f"定时任务不存在: {task_id}")
            return

        logger.info(f"定时任务触发: {task.task_name} (task_id={task_id})")

        retries = task.max_retries if task.retry_on_failure else 1
        for attempt in range(retries):
            try:
                await self._run_scripts(task)
                break
            except Exception as e:
                logger.error(f"定时任务执行失败 task_id={task_id}, attempt={attempt+1}: {e}")
                if attempt == retries - 1:
                    raise

    async def _resolve_categories_to_scripts(self, category_ids: list):
        """递归收集分类下所有 TestCase，按 script_file_path 去重，返回 TestScript 列表"""
        from app.models.api_automation import TestCase, TestCaseCategory, TestScript

        if not category_ids:
            return []

        # 递归收集所有子孙节点
        all_category_pks = set()
        async def _collect_children(parent_id: str):
            cats = await TestCaseCategory.filter(parent_id=parent_id)
            for c in cats:
                all_category_pks.add(c.id)
                await _collect_children(c.category_id)

        # 根据 category_id (UUID string) 找到 db PK
        top_cats = await TestCaseCategory.filter(category_id__in=category_ids)
        for cat in top_cats:
            all_category_pks.add(cat.id)
            await _collect_children(cat.category_id)

        if not all_category_pks:
            return []

        # 查该分类下所有TestCase的script_file_path
        cases = await TestCase.filter(
            category_id__in=list(all_category_pks),
            is_active=True,
        ).only("script_file_path")

        paths = list(set(c.script_file_path for c in cases if c.script_file_path))
        if not paths:
            return []

        scripts = await TestScript.filter(
            file_path__in=paths,
            is_active=True,
        ).select_related("document")

        logger.info(
            f"分类维度解析: {len(category_ids)} 个分类 → "
            f"{len(all_category_pks)} 个分类节点 → "
            f"{len(paths)} 个脚本 (共 {len(cases)} 条用例)"
        )
        return scripts

    async def _run_scripts(self, task: ScheduledTask):
        """执行任务关联的所有脚本"""
        from app.models.api_automation import TestScript

        if task.selection_mode == "categories":
            scripts = await self._resolve_categories_to_scripts(task.category_ids or [])
        else:
            scripts = await TestScript.filter(
                script_id__in=task.script_ids,
                is_active=True,
            ).select_related("document")

        if not scripts:
            logger.warning(f"定时任务 {task.task_id}: 没有可执行的脚本")
            return

        backend_dir = Path(__file__).resolve().parents[3]
        generated_tests_dir = backend_dir / "generated_tests"
        reports_root = backend_dir / "reports"

        async def _run_one(script):
            execution_id = str(uuid.uuid4())
            execution_dir = reports_root / execution_id
            execution_dir.mkdir(parents=True, exist_ok=True)

            script_file = generated_tests_dir / script.file_path
            if not script_file.exists():
                script_file.parent.mkdir(parents=True, exist_ok=True)
                script_file.write_text(script.content, encoding="utf-8")

            start_time = datetime.now()
            await TestExecution.create(
                execution_id=execution_id,
                session_id=execution_id,
                document=script.document,
                execution_config={
                    "script_id": script.script_id,
                    "source": "scheduled_task",
                    "task_id": task.task_id,
                },
                environment=task.environment,
                parallel=task.parallel_execution,
                max_workers=task.max_workers,
                status=ExecutionStatus.RUNNING,
                start_time=start_time,
                description=f"定时任务执行: {task.task_name} → {script.name}",
            )

            from app.api.v1.endpoints.script_management import _execute_script_in_background
            _asyncio.create_task(_execute_script_in_background(
                execution_id=execution_id,
                script_id=script.script_id,
                script_file_path=script.file_path,
                script_name=script.name,
                generated_tests_dir=generated_tests_dir,
                execution_dir=execution_dir,
                env_name=task.environment,
                timeout=task.timeout,
                start_time=start_time,
            ))

        if task.parallel_execution:
            await asyncio.gather(*[_run_one(s) for s in scripts])
        else:
            for script in scripts:
                await _run_one(script)

        # 更新任务执行时间
        now = datetime.now()
        task.last_execution_time = now
        if task.schedule_type == "once":
            task.status = "completed"
            self._unschedule_task(task.task_id)
            task.next_execution_time = None
        else:
            job_id = self._job_map.get(task.task_id)
            if job_id and self._scheduler:
                job = self._scheduler.get_job(job_id)
                if job and job.next_run_time:
                    task.next_execution_time = job.next_run_time.replace(tzinfo=None)

        await task.save(update_fields=["last_execution_time", "next_execution_time", "status"])


# 全局单例
_scheduled_task_service: Optional[ScheduledTaskService] = None


def get_scheduled_task_service() -> ScheduledTaskService:
    global _scheduled_task_service
    if _scheduled_task_service is None:
        _scheduled_task_service = ScheduledTaskService()
    return _scheduled_task_service
