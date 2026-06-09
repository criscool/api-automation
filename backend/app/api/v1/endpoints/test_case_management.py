"""
测试用例管理API模块

主要功能：
1. 用例查询（列表/详情）
2. 用例软删除
3. 用例执行（单条 / 批量）
   - 单条：拼 nodeid 跑 pytest file::Class::method
   - 批量：按脚本文件分组后并发跑（每组一次 pytest 调用传多个 nodeids）
"""

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger

from app.models.api_automation import (
    TestCase,
    TestExecution,
    TestScript,
    ScriptExecutionResult,
    TestCaseCategory,
)
from app.core.enums import ExecutionStatus
from app.api.v1.endpoints.script_management import _run_pytest_for_one_script

router = APIRouter(tags=["用例管理"])


# ==================== 请求/响应模型 ====================

class TestCaseRunRequest(BaseModel):
    """单用例执行请求"""
    execution_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="执行配置")
    environment: str = Field(default="test", description="执行环境")
    timeout: int = Field(default=300, description="超时时间（秒）")


class TestCaseBatchExecuteRequest(BaseModel):
    """批量用例执行请求"""
    test_ids: List[str] = Field(..., description="要执行的用例 test_id 列表")
    execution_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="执行配置")
    environment: str = Field(default="test", description="执行环境")
    timeout: int = Field(default=300, description="超时时间（秒）")
    max_workers: int = Field(default=4, description="按脚本分组后的并发度")


# ==================== 工具函数 ====================

def _build_nodeid(test_case: TestCase) -> Optional[str]:
    """根据用例的 class_name/method_name 拼 pytest nodeid（不含文件路径前缀）"""
    if not test_case.method_name:
        return None
    if test_case.class_name:
        return f"{test_case.class_name}::{test_case.method_name}"
    return test_case.method_name


async def _ensure_script_file_on_disk(script_file_path: str, generated_tests_dir: Path) -> Path:
    """确保脚本文件在磁盘上存在；不存在则从数据库 TestScript.content 落盘"""
    target = generated_tests_dir / script_file_path
    if target.exists():
        return target

    script = await TestScript.filter(file_path=script_file_path, is_active=True).first()
    if not script:
        raise HTTPException(status_code=404, detail=f"脚本文件不存在且无法回写: {script_file_path}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script.content, encoding="utf-8")
    return target


def _build_case_level_flow_summary(tc: TestCase, script_fs: Dict[str, Any] = None) -> Dict[str, Any]:
    """从单条 TestCase 派生用例级 flow_summary。

    - scenario 型脚本下的用例（1 用例 = 整条链路）→ 直接复用脚本 flow_summary
    - cases 型 / 未分类 → 用例自身派生（1 步骤 + 自身断言）
    """
    # scenario 型：用例代表整条 chain，直接用脚本级 flow_summary
    if script_fs and script_fs.get("kind") == "scenario":
        return script_fs

    # cases / 未知：用例自己 = 1 步骤 + 自身断言
    ep = tc.endpoint
    if ep is None:
        return {}
    method = ep.method.value if hasattr(ep.method, "value") else str(ep.method)
    purpose = (tc.description or "").strip()
    if not purpose:
        name = tc.name or ""
        purpose = name.split(" - ", 1)[1] if " - " in name else name
    step = {
        "no": 1,
        "method": method.upper(),
        "path": ep.path or "",
        "purpose": purpose,
    }
    asserts: List[Dict[str, Any]] = []
    for a in (tc.assertions or []):
        if isinstance(a, dict):
            asserts.append({
                "kind": str(a.get("comparison_operator") or "equals"),
                "in": str(a.get("assertion_type") or ""),
                "expected": {"value": a.get("expected_value")},
                "desc": str(a.get("description") or ""),
                "step_no": 1,
            })
    return {
        "kind": "case",
        "step_count": 1,
        "assertion_count": len(asserts),
        "primary_action": f"[1] {step['method']} {step['path']}",
        "steps": [step],
        "assertions": asserts,
    }


def _serialize_case_for_list(tc: TestCase, cat_map: dict = None, script_lookup: dict = None) -> Dict[str, Any]:
    """列表行序列化：刚好够前端"用例管理"页用的字段

    script_lookup: {script_file_path / script_file_name: {"flow_summary": dict, "script_id": str}}
        用于 scenario 型用例复用脚本级 flow_summary，以及 AI 诊断按钮使用 script_id
    """
    endpoint = tc.endpoint  # 已 prefetch
    interface_info: Dict[str, Any] = {}
    if endpoint:
        interface_info = {
            "interface_id": endpoint.interface_id,
            "name": endpoint.name,
            "method": endpoint.method.value if hasattr(endpoint.method, "value") else str(endpoint.method),
            "path": endpoint.path,
        }

    script_file_name = ""
    if tc.script_file_path:
        script_file_name = Path(tc.script_file_path).name

    category_info: Dict[str, Any] = {}
    if cat_map:
        cat = cat_map.get(tc.category_id)
        if cat:
            category_info = {
                "category_id": cat.category_id,
                "name": cat.name,
            }

    # 取该用例所属脚本的 flow_summary + script_id
    script_entry = {}
    if script_lookup and tc.script_file_path:
        script_entry = script_lookup.get(tc.script_file_path) or script_lookup.get(script_file_name) or {}
    script_fs = script_entry.get("flow_summary") or {}
    script_id = script_entry.get("script_id") or ""

    flow_summary = _build_case_level_flow_summary(tc, script_fs)

    return {
        "test_id": tc.test_id,
        "name": tc.name,
        "description": tc.description,
        "test_type": tc.test_type.value if hasattr(tc.test_type, "value") else str(tc.test_type),
        "test_level": tc.test_level.value if hasattr(tc.test_level, "value") else str(tc.test_level),
        "priority": tc.priority.value if hasattr(tc.priority, "value") else str(tc.priority),
        "tags": tc.tags or [],
        "interface_info": interface_info,
        "category_info": category_info,
        "script_id": script_id,
        "script_file_name": script_file_name,
        "script_file_path": tc.script_file_path or "",
        "class_name": tc.class_name or "",
        "method_name": tc.method_name or "",
        "generated_by": tc.generated_by,
        "last_execution_status": tc.last_execution_status,
        "last_execution_time": tc.last_execution_time.isoformat() if tc.last_execution_time else None,
        "flow_summary": flow_summary,
        "created_at": tc.created_at.isoformat() if tc.created_at else None,
        "updated_at": tc.updated_at.isoformat() if tc.updated_at else None,
    }


def _serialize_case_for_detail(tc: TestCase, cat_map: dict = None, script_lookup: dict = None) -> Dict[str, Any]:
    """详情序列化：列表字段 + test_data/assertions/setup/teardown"""
    data = _serialize_case_for_list(tc, cat_map, script_lookup)
    data.update({
        "test_data": tc.test_data or [],
        "assertions": tc.assertions or [],
        "setup_steps": tc.setup_steps or [],
        "teardown_steps": tc.teardown_steps or [],
        "dependencies": tc.dependencies or [],
        "timeout": tc.timeout,
        "retry_count": tc.retry_count,
        "document_id": tc.document_id if hasattr(tc, "document_id") else None,
    })
    return data


# ==================== 列表 / 详情 API ====================

@router.get("", summary="获取用例列表")
@router.get("/", summary="获取用例列表", include_in_schema=False)
async def get_all_test_cases(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    search: Optional[str] = Query(None, description="按用例名/描述模糊搜索"),
    test_type: Optional[str] = Query(None, description="测试类型筛选"),
    document_id: Optional[str] = Query(None, description="文档ID筛选"),
    interface_id: Optional[str] = Query(None, description="接口ID筛选"),
    include_inactive: bool = Query(False, description="是否包含已删除"),
    category_id: Optional[str] = Query(None, description="用例分类ID筛选（含子分类）"),
    uncategorized: bool = Query(False, description="只返回未分类用例"),
):
    """分页查询用例"""
    try:
        qs = TestCase.all().prefetch_related("endpoint", "document", "category")

        if not include_inactive:
            qs = qs.filter(is_active=True)
        if search:
            qs = qs.filter(name__icontains=search)
        if test_type:
            qs = qs.filter(test_type=test_type)
        if document_id:
            qs = qs.filter(document__doc_id=document_id)
        if interface_id:
            qs = qs.filter(endpoint__interface_id=interface_id)
        if uncategorized:
            qs = qs.filter(category_id__isnull=True)
        elif category_id:
            cat_ids = await _get_category_subtree_ids(category_id)
            if cat_ids:
                qs = qs.filter(category_id__in=cat_ids)

        total = await qs.count()
        rows = await qs.order_by("-created_at").offset((page - 1) * page_size).limit(page_size)

        # 构建分类 lookup dict（绕过 Tortoise FK 同步访问问题）
        cat_ids_in_result = {tc.category_id for tc in rows if tc.category_id}
        cat_map = {}
        if cat_ids_in_result:
            cats = await TestCaseCategory.filter(id__in=list(cat_ids_in_result)).all()
            cat_map = {c.id: c for c in cats}

        # 构建脚本 lookup —— 用于 scenario 型用例复用脚本级链路展示 + AI 诊断按钮取 script_id
        # 同一 file_path 可能有多条 TestScript（历史重复导入），优先取 flow_summary 非空 + 最近更新
        script_paths = {tc.script_file_path for tc in rows if tc.script_file_path}
        script_lookup: Dict[str, Any] = {}
        if script_paths:
            scripts = await TestScript.filter(
                file_path__in=list(script_paths), is_active=True
            ).only("script_id", "file_path", "file_name", "flow_summary").order_by("-updated_at")
            for s in scripts:
                fs = s.flow_summary or {}
                entry = {"flow_summary": fs, "script_id": s.script_id or ""}
                if s.file_path:
                    existing = script_lookup.get(s.file_path)
                    if not existing or not existing.get("flow_summary"):
                        script_lookup[s.file_path] = entry
                if s.file_name:
                    existing = script_lookup.get(s.file_name)
                    if not existing or not existing.get("flow_summary"):
                        script_lookup[s.file_name] = entry

        items = [_serialize_case_for_list(tc, cat_map, script_lookup) for tc in rows]

        return {
            "code": 200,
            "msg": "OK",
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            },
            "success": True,
        }
    except Exception as e:
        logger.error(f"获取用例列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取用例列表失败: {str(e)}")


@router.get("/{test_id}", summary="获取用例详情")
async def get_test_case_detail(test_id: str):
    """获取单条用例详情"""
    try:
        tc = await TestCase.filter(test_id=test_id).prefetch_related("endpoint", "document").first()
        if not tc:
            raise HTTPException(status_code=404, detail=f"用例不存在: {test_id}")

        # 构建分类 lookup
        cat_map = {}
        if tc.category_id:
            cat = await TestCaseCategory.filter(id=tc.category_id).first()
            if cat:
                cat_map = {cat.id: cat}

        # 反查该用例所属脚本（scenario 型用例需要完整链路 + AI 诊断需 script_id）
        script_lookup: Dict[str, Any] = {}
        if tc.script_file_path:
            s = await TestScript.filter(
                file_path=tc.script_file_path, is_active=True
            ).only("script_id", "file_path", "file_name", "flow_summary").order_by("-updated_at").first()
            if s:
                entry = {"flow_summary": s.flow_summary or {}, "script_id": s.script_id or ""}
                if s.file_path:
                    script_lookup[s.file_path] = entry
                if s.file_name:
                    script_lookup[s.file_name] = entry

        return {
            "code": 200,
            "msg": "OK",
            "data": _serialize_case_for_detail(tc, cat_map, script_lookup),
            "success": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用例详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取用例详情失败: {str(e)}")


@router.delete("/{test_id}", summary="删除用例（软删除）")
async def delete_test_case(test_id: str):
    """软删除用例"""
    try:
        tc = await TestCase.filter(test_id=test_id, is_active=True).first()
        if not tc:
            raise HTTPException(status_code=404, detail=f"用例不存在: {test_id}")
        tc.is_active = False
        await tc.save()
        return {"code": 200, "msg": "用例已删除", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除用例失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除用例失败: {str(e)}")


# ==================== 单用例执行 API ====================

@router.post("/{test_id}/run", summary="执行单条用例（异步）")
async def run_single_test_case(test_id: str, request: TestCaseRunRequest):
    """启动单用例执行：file::Class::method 形式跑 pytest，立即返回 execution_id"""
    tc = await TestCase.filter(test_id=test_id, is_active=True).prefetch_related("document").first()
    if not tc:
        raise HTTPException(status_code=404, detail=f"用例不存在: {test_id}")
    if not tc.script_file_path:
        raise HTTPException(status_code=400, detail="用例未关联脚本文件，无法执行")

    nodeid = _build_nodeid(tc)
    if not nodeid:
        raise HTTPException(status_code=400, detail="用例缺少 method_name，无法定位 pytest 节点")

    backend_dir = Path(__file__).resolve().parents[4]
    generated_tests_dir = backend_dir / "generated_tests"
    reports_root = backend_dir / "reports"

    await _ensure_script_file_on_disk(tc.script_file_path, generated_tests_dir)

    execution_id = str(uuid.uuid4())
    execution_dir = reports_root / execution_id
    execution_dir.mkdir(parents=True, exist_ok=True)

    env_name = request.environment or "test"
    timeout = request.timeout or 300

    start_time = datetime.now()
    await TestExecution.create(
        execution_id=execution_id,
        session_id=execution_id,
        document=tc.document,
        execution_config={
            "test_ids": [test_id],
            "script_file_path": tc.script_file_path,
            "nodeids": [nodeid],
            **(request.execution_config or {}),
        },
        environment=env_name,
        parallel=False,
        max_workers=1,
        status=ExecutionStatus.RUNNING,
        start_time=start_time,
        description=f"单用例执行: {tc.name}",
    )

    asyncio.create_task(_execute_test_cases_in_background(
        execution_id=execution_id,
        groups=[{
            "script_file_path": tc.script_file_path,
            "test_cases": [{
                "test_id": tc.test_id,
                "name": tc.name,
                "nodeid": nodeid,
            }],
        }],
        generated_tests_dir=generated_tests_dir,
        execution_dir=execution_dir,
        env_name=env_name,
        timeout=timeout,
        max_workers=1,
        batch_start_time=start_time,
    ))

    return {
        "code": 200,
        "msg": "用例执行已启动",
        "data": {
            "execution_id": execution_id,
            "test_id": test_id,
            "status": "RUNNING",
            "message": "任务已启动，请在「执行报告」页面查看进度和结果",
            "start_time": start_time.isoformat(),
        },
        "success": True,
    }


# ==================== 批量用例执行 API ====================

@router.post("/execute", summary="批量执行用例（异步，按脚本分组并发）")
async def execute_test_cases(request: TestCaseBatchExecuteRequest):
    """批量执行多条用例：按 script_file_path 分组，每组一次 pytest 调用传多个 nodeids"""
    if not request.test_ids:
        raise HTTPException(status_code=400, detail="用例ID列表不能为空")

    cases = await TestCase.filter(
        test_id__in=request.test_ids, is_active=True
    ).prefetch_related("document")

    if not cases:
        raise HTTPException(status_code=404, detail="未找到任何可执行的用例")

    # 按脚本文件分组
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    first_document = None
    for tc in cases:
        if not tc.script_file_path:
            continue
        nodeid = _build_nodeid(tc)
        if not nodeid:
            continue
        grouped[tc.script_file_path].append({
            "test_id": tc.test_id,
            "name": tc.name,
            "nodeid": nodeid,
        })
        if first_document is None:
            first_document = tc.document

    if not grouped:
        raise HTTPException(status_code=400, detail="所选用例都缺少 script_file_path 或 method_name，无法执行")

    backend_dir = Path(__file__).resolve().parents[4]
    generated_tests_dir = backend_dir / "generated_tests"
    reports_root = backend_dir / "reports"

    # 确保脚本文件都在磁盘上
    for script_file_path in grouped.keys():
        await _ensure_script_file_on_disk(script_file_path, generated_tests_dir)

    execution_id = str(uuid.uuid4())
    execution_dir = reports_root / execution_id
    execution_dir.mkdir(parents=True, exist_ok=True)

    env_name = request.environment or "test"
    timeout = request.timeout or 300
    max_workers = max(1, min(request.max_workers or 4, 8))

    groups = [
        {"script_file_path": sf, "test_cases": items}
        for sf, items in grouped.items()
    ]

    start_time = datetime.now()
    await TestExecution.create(
        execution_id=execution_id,
        session_id=execution_id,
        document=first_document,
        execution_config={
            "test_ids": request.test_ids,
            "max_workers": max_workers,
            "groups": [
                {
                    "script_file_path": g["script_file_path"],
                    "nodeids": [c["nodeid"] for c in g["test_cases"]],
                }
                for g in groups
            ],
            **(request.execution_config or {}),
        },
        environment=env_name,
        parallel=len(groups) > 1,
        max_workers=max_workers,
        status=ExecutionStatus.RUNNING,
        start_time=start_time,
        description=f"批量执行 {sum(len(g['test_cases']) for g in groups)} 条用例（{len(groups)} 个脚本并发度 {max_workers}）",
    )

    asyncio.create_task(_execute_test_cases_in_background(
        execution_id=execution_id,
        groups=groups,
        generated_tests_dir=generated_tests_dir,
        execution_dir=execution_dir,
        env_name=env_name,
        timeout=timeout,
        max_workers=max_workers,
        batch_start_time=start_time,
    ))

    return {
        "code": 200,
        "msg": "批量执行任务已启动",
        "data": {
            "execution_id": execution_id,
            "test_case_count": sum(len(g["test_cases"]) for g in groups),
            "script_count": len(groups),
            "max_workers": max_workers,
            "status": "RUNNING",
            "start_time": start_time.isoformat(),
        },
        "success": True,
    }


# ==================== 后台执行 ====================

async def _execute_test_cases_in_background(
    execution_id: str,
    groups: List[Dict[str, Any]],
    generated_tests_dir: Path,
    execution_dir: Path,
    env_name: str,
    timeout: int,
    max_workers: int,
    batch_start_time: datetime,
):
    """按脚本分组并发执行用例。每组 = 一次 pytest 调用（传多个 nodeids）。"""
    semaphore = asyncio.Semaphore(max_workers)
    results: List[Optional[Dict[str, Any]]] = [None] * len(groups)

    async def run_group(idx: int, group: Dict[str, Any]):
        async with semaphore:
            # 注意：safe_name 不能以 .py 结尾，否则 uvicorn --reload 的 watchgod 会把
            # 该目录当 Python 文件改动，在 pytest 跑到一半时触发 reload，子进程被 Ctrl+C 杀掉
            safe_name = (
                group["script_file_path"]
                .replace("/", "_")
                .replace("\\", "_")
                .replace(".", "_")
            )
            script_dir = execution_dir / "scripts" / safe_name
            nodeids = [c["nodeid"] for c in group["test_cases"]]
            try:
                res = await _run_pytest_for_one_script(
                    script_file_path=group["script_file_path"],
                    script_dir=script_dir,
                    generated_tests_dir=generated_tests_dir,
                    env_name=env_name,
                    timeout=timeout,
                    nodeids=nodeids,
                )
                results[idx] = res
            except Exception as e:
                logger.error(f"用例组执行异常 script={group['script_file_path']}: {e}", exc_info=True)
                results[idx] = {
                    "return_code": -1,
                    "stdout": "",
                    "stderr": f"执行异常: {e}",
                    "start_time": datetime.now(),
                    "end_time": datetime.now(),
                    "duration": 0.0,
                    "passed": 0, "failed": 0, "errors": 1, "skipped": 0, "total": 0,
                    "success_rate": 0.0,
                    "report_files": [],
                    "allure_results_dir": None,
                }

    await asyncio.gather(*[run_group(i, g) for i, g in enumerate(groups)], return_exceptions=False)

    batch_end_time = datetime.now()
    agg_total = sum(r["total"] for r in results)
    agg_passed = sum(r["passed"] for r in results)
    agg_failed = sum(r["failed"] for r in results)
    agg_errors = sum(r["errors"] for r in results)
    agg_skipped = sum(r["skipped"] for r in results)
    agg_success_rate = (agg_passed / agg_total * 100) if agg_total > 0 else 0.0
    all_ok = all(r["return_code"] == 0 for r in results)

    # 合并所有脚本组的 allure-results 到一份汇总报告。Allure CLI 原生支持多 results 目录入参，
    # 自动按 historyId/suite 树合并；失败仅记 warning，不污染 test_execution.status
    merged_report_entry: Optional[Dict[str, Any]] = None
    allure_dirs = [r.get("allure_results_dir") for r in results if r.get("allure_results_dir")]
    if allure_dirs:
        try:
            import shutil as _shutil
            import subprocess as _subprocess
            allure_cli = _shutil.which("allure")
            if allure_cli:
                merged_dir = execution_dir / "merged-allure-report"
                cmd = [allure_cli, "generate", *allure_dirs, "-o", str(merged_dir), "--clean"]
                proc = await asyncio.to_thread(
                    _subprocess.run,
                    cmd, capture_output=True, text=True, timeout=120, check=False,
                )
                if proc.returncode == 0 and (merged_dir / "index.html").exists():
                    merged_report_entry = {
                        "script_file_path": "",  # 汇总报告不归属单脚本
                        "format": "allure",
                        "name": "index.html",
                        "path": str(merged_dir / "index.html"),
                        "url": f"/reports/{execution_id}/merged-allure-report/index.html",
                        "is_merged": True,
                    }
                else:
                    logger.warning(
                        f"合并 Allure 报告失败 execution_id={execution_id} "
                        f"return_code={proc.returncode} stderr={(proc.stderr or '')[:500]}"
                    )
            else:
                logger.warning(f"未找到 allure CLI，跳过合并报告生成 execution_id={execution_id}")
        except Exception as e:
            logger.warning(f"合并 Allure 报告异常 execution_id={execution_id}: {e}")

    # 聚合报告文件
    batch_report_files: List[Dict[str, Any]] = []
    if merged_report_entry:
        batch_report_files.append(merged_report_entry)
    for group, res in zip(groups, results):
        for rf in res["report_files"]:
            batch_report_files.append({
                "script_file_path": group["script_file_path"],
                "format": rf["format"],
                "name": rf["name"],
                "path": rf["abs_path"],
                "url": f"/reports/{execution_id}/scripts/{rf['rel_path']}",
            })

    try:
        test_execution = await TestExecution.filter(execution_id=execution_id).first()
        if test_execution:
            test_execution.status = ExecutionStatus.SUCCESS if all_ok else ExecutionStatus.FAILED
            test_execution.end_time = batch_end_time
            test_execution.execution_time = round((batch_end_time - batch_start_time).total_seconds(), 2)
            test_execution.total_tests = agg_total
            test_execution.passed_tests = agg_passed
            test_execution.failed_tests = agg_failed
            test_execution.skipped_tests = agg_skipped
            test_execution.error_tests = agg_errors
            test_execution.success_rate = round(agg_success_rate, 2)
            test_execution.summary = {
                "all_ok": all_ok,
                "group_count": len(groups),
                "test_case_count": sum(len(g["test_cases"]) for g in groups),
                "groups": [
                    {
                        "script_file_path": g["script_file_path"],
                        "test_ids": [c["test_id"] for c in g["test_cases"]],
                        "return_code": r["return_code"],
                        "passed": r["passed"],
                        "failed": r["failed"],
                        "errors": r["errors"],
                        "skipped": r["skipped"],
                        "stdout_tail": (r["stdout"] or "")[-1000:],
                        "stderr_tail": (r["stderr"] or "")[-1000:],
                    }
                    for g, r in zip(groups, results)
                ],
            }
            test_execution.report_files = batch_report_files
            await test_execution.save()

            # 给每个脚本组也写一条 ScriptExecutionResult（保留按脚本聚合的可观测性）
            for group, res in zip(groups, results):
                script = await TestScript.filter(file_path=group["script_file_path"], is_active=True).first()
                if not script:
                    continue
                await ScriptExecutionResult.create(
                    result_id=str(uuid.uuid4()),
                    execution=test_execution,
                    script=script,
                    script_name=script.name,
                    script_path=group["script_file_path"] or "",
                    start_time=res["start_time"],
                    end_time=res["end_time"],
                    duration=res["duration"],
                    status="PASSED" if res["return_code"] == 0 else "FAILED",
                    exit_code=res["return_code"],
                    total_tests=res["total"],
                    passed_tests=res["passed"],
                    failed_tests=res["failed"],
                    skipped_tests=res["skipped"],
                    error_tests=res["errors"],
                    stdout=(res["stdout"] or "")[-5000:],
                    stderr=(res["stderr"] or "")[-5000:],
                    error_message=(res["stderr"] or "")[-500:] if res["return_code"] != 0 else "",
                )

            # 更新每条用例的最近一次执行状态
            for group, res in zip(groups, results):
                # 简单策略：整组通过 → 用例都 PASSED；否则按 stdout 行尝试匹配 nodeid
                stdout = res.get("stdout") or ""
                for case in group["test_cases"]:
                    nid = case["nodeid"]
                    if f"{nid} PASSED" in stdout:
                        case_status = "PASSED"
                    elif f"{nid} FAILED" in stdout:
                        case_status = "FAILED"
                    elif f"{nid} ERROR" in stdout:
                        case_status = "ERROR"
                    elif f"{nid} SKIPPED" in stdout:
                        case_status = "SKIPPED"
                    else:
                        case_status = "PASSED" if res["return_code"] == 0 else "FAILED"

                    tc = await TestCase.filter(test_id=case["test_id"]).first()
                    if tc:
                        tc.last_execution_status = case_status
                        tc.last_execution_time = res["end_time"]
                        await tc.save()
    except Exception as e:
        logger.error(f"用例执行落库失败 execution_id={execution_id}: {e}", exc_info=True)
        # 兜底：即使落库失败也把执行记录标记为失败，避免永久卡在 RUNNING
        from datetime import datetime as dt
        try:
            test_execution = await TestExecution.filter(execution_id=execution_id).first()
            if test_execution and test_execution.status == ExecutionStatus.RUNNING:
                test_execution.status = ExecutionStatus.FAILED
                test_execution.end_time = dt.now()
                test_execution.error_message = str(e)[:1000]
                await test_execution.save()
        except Exception:
            pass


# ==================== 分类筛选辅助 + 用例移动 ====================

async def _get_category_subtree_ids(category_id: str) -> list:
    """递归获取指定分类及其所有子分类的数据库 id"""
    cat = await TestCaseCategory.filter(category_id=category_id, is_active=True).first()
    if not cat:
        return []
    ids = [cat.id]
    children = await TestCaseCategory.filter(parent=cat, is_active=True).all()
    for child in children:
        child_ids = await _get_category_subtree_ids(child.category_id)
        ids.extend(child_ids)
    return ids


class MoveTestCaseRequest(BaseModel):
    test_id: str = Field(..., description="用例 test_id")
    category_id: Optional[str] = Field(None, description="目标分类 category_id，空则移出")


class BatchMoveTestCaseRequest(BaseModel):
    test_ids: List[str] = Field(..., description="用例 test_id 列表")
    category_id: Optional[str] = Field(None, description="目标分类 category_id，空则移出")


@router.put("/{test_id}/move", summary="移动单条用例到分类")
async def move_test_case(test_id: str, req: MoveTestCaseRequest):
    try:
        tc = await TestCase.filter(test_id=test_id, is_active=True).first()
        if not tc:
            raise HTTPException(status_code=404, detail="用例不存在")

        if req.category_id:
            cat = await TestCaseCategory.filter(category_id=req.category_id, is_active=True).first()
            if not cat:
                raise HTTPException(status_code=404, detail="目标分类不存在")
            tc.category = cat
        else:
            tc.category = None

        await tc.save(update_fields=["category_id"])
        return {"code": 200, "msg": "移动成功", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移动用例失败: {e}")
        raise HTTPException(status_code=500, detail=f"移动失败: {e}")


@router.put("/batch-move", summary="批量移动用例")
async def batch_move_test_cases(req: BatchMoveTestCaseRequest):
    try:
        cat = None
        if req.category_id:
            cat = await TestCaseCategory.filter(category_id=req.category_id, is_active=True).first()
            if not cat:
                raise HTTPException(status_code=404, detail="目标分类不存在")

        updated = await TestCase.filter(
            test_id__in=req.test_ids, is_active=True
        ).update(category=cat)

        return {
            "code": 200,
            "msg": f"已移动 {updated} 条用例",
            "data": {"moved": updated},
            "success": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量移动用例失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量移动失败: {e}")
