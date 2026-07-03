"""
脚本管理API模块
专门处理测试脚本的管理和执行功能

主要功能：
1. 脚本查询和详情获取
2. 脚本状态管理
3. 脚本执行和监控
4. 执行历史和日志管理
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger

from app.services.api_automation.interface_script_service import InterfaceScriptService
from app.services.api_automation.test_case_repair_service import repair_test_case_mapping
from app.core.enums import ExecutionStatus

router = APIRouter(tags=["脚本管理"])

# ==================== 请求和响应模型 ====================

class ScriptExecutionRequest(BaseModel):
    """脚本执行请求"""
    script_ids: List[str] = Field(..., description="要执行的脚本ID列表")
    execution_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="执行配置")
    environment: str = Field(default="test", description="执行环境")
    timeout: int = Field(default=300, description="超时时间（秒）")
    parallel: bool = Field(default=False, description="是否并行执行")
    max_workers: int = Field(default=1, description="最大并行数")


class SingleScriptExecutionRequest(BaseModel):
    """单个脚本执行请求"""
    execution_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="执行配置")
    environment: str = Field(default="test", description="执行环境")
    timeout: int = Field(default=300, description="超时时间（秒）")


class ScriptStatusUpdateRequest(BaseModel):
    """脚本状态更新请求"""
    status: str = Field(..., description="新状态")
    is_executable: Optional[bool] = Field(None, description="是否可执行")


class BatchScriptStatusUpdateRequest(BaseModel):
    """批量脚本状态更新请求"""
    script_ids: List[str] = Field(..., description="脚本ID列表")
    status: str = Field(..., description="新状态")
    is_executable: Optional[bool] = Field(None, description="是否可执行")


class ManualScriptRegisterRequest(BaseModel):
    """手动注册脚本请求"""
    name: str = Field(..., description="脚本名称")
    description: str = Field(default="", description="脚本描述")
    file_name: str = Field(..., description="脚本文件名（如 test_login.py）")
    file_path: str = Field(..., description="相对于 generated_tests/ 的路径（如 testcases/test_login.py）")
    content: Optional[str] = Field(None, description="脚本内容（为空则从文件读取）")
    framework: str = Field(default="pytest", description="测试框架")
    tags: List[str] = Field(default_factory=list, description="标签")
    api_path: str = Field(default="", description="被测接口路径（如 /api/system/sessions）")
    api_method: str = Field(default="POST", description="被测接口方法（GET/POST/PUT/DELETE）")


class ScriptContentUpdateRequest(BaseModel):
    """脚本代码内容更新请求"""
    content: str = Field(..., min_length=1, description="新的脚本源代码（不能为空）")


# ==================== JUnit XML 统计解析 ====================


def _parse_junit_stats(junit_path) -> tuple:
    """从 pytest 生成的 junit.xml 中精确提取测试统计。

    返回 (total, passed, failed, errors, skipped)。
    解析失败时返回全 0，调用方会回退字符串匹配。
    """
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(str(junit_path))
        root = tree.getroot()

        # pytest 输出格式：<testsuites> 包一个或多个 <testsuite>
        if root.tag == "testsuites":
            suites = root.findall("testsuite")
            if not suites:
                # 尝试把自己当 testsuite（极端兼容）
                return _parse_one_suite(root)
            total = passed = failed = errors = skipped = 0
            for ts in suites:
                t, p, f, e, s = _parse_one_suite(ts)
                total += t; passed += p; failed += f; errors += e; skipped += s
            return total, passed, failed, errors, skipped
        elif root.tag == "testsuite":
            return _parse_one_suite(root)
        return 0, 0, 0, 0, 0
    except Exception:
        return 0, 0, 0, 0, 0


def _parse_one_suite(suite) -> tuple:
    """解析单个 <testsuite>，返回 (total, passed, failed, errors, skipped)。"""
    t = int(suite.attrib.get("tests", 0))
    f = int(suite.attrib.get("failures", 0))
    e = int(suite.attrib.get("errors", 0))
    s = int(suite.attrib.get("skipped", 0))
    return t, t - f - e - s, f, e, s


# ==================== 手动脚本注册API ====================


@router.post("/register", summary="注册手动封装的脚本")
async def register_manual_script(request: ManualScriptRegisterRequest):
    """
    将手动封装的测试脚本注册到系统中，使其在前端脚本管理页面可见。
    
    脚本来源标记为 MANUAL。对于没有关联接口的手动脚本，
    会自动创建一个"手动脚本"占位文档和接口记录。
    """
    try:
        import uuid
        from pathlib import Path
        from app.models.api_automation import TestScript, ApiDocument, ApiInterface
        from app.core.enums import SessionStatus, HttpMethod

        # 如果没有传内容，从文件读取
        content = request.content
        if not content:
            script_file = Path("generated_tests") / request.file_path
            if not script_file.exists():
                raise HTTPException(status_code=404, detail=f"脚本文件不存在: {request.file_path}")
            content = script_file.read_text(encoding="utf-8")

        # 检查是否已注册
        existing = await TestScript.filter(file_path=request.file_path, is_active=True).first()
        if existing:
            existing.content = content
            existing.name = request.name
            existing.description = request.description
            await existing.save()

            # 同时更新关联的占位接口信息
            interface_id = f"manual-{request.file_name.replace('.py', '').replace('test_', '')}"
            from app.models.api_automation import ApiInterface
            manual_interface = await ApiInterface.filter(interface_id=interface_id).first()
            if manual_interface:
                method_map = {"GET": HttpMethod.GET, "POST": HttpMethod.POST, "PUT": HttpMethod.PUT, "DELETE": HttpMethod.DELETE, "PATCH": HttpMethod.PATCH}
                manual_interface.name = request.name
                manual_interface.path = request.api_path or manual_interface.path
                manual_interface.method = method_map.get(request.api_method.upper(), HttpMethod.POST) if request.api_method else manual_interface.method
                await manual_interface.save()

            return {
                "code": 200,
                "msg": "脚本已更新",
                "data": {"script_id": existing.script_id, "action": "updated"},
                "success": True
            }

        # 获取或创建"手动脚本"占位文档
        manual_doc = await ApiDocument.filter(doc_id="manual-scripts-doc").first()
        if not manual_doc:
            manual_doc = await ApiDocument.create(
                doc_id="manual-scripts-doc",
                session_id="manual",
                file_name="手动封装脚本",
                file_path="manual",
                doc_format="custom",
                api_info={"title": "手动封装脚本", "version": "1.0", "description": "手动编写的测试脚本集合"},
                parse_status=SessionStatus.COMPLETED,
                endpoints_count=0,
                confidence_score=1.0,
                is_active=True,
            )

        # 获取或创建该脚本对应的占位接口
        interface_id = f"manual-{request.file_name.replace('.py', '').replace('test_', '')}"
        manual_interface = await ApiInterface.filter(interface_id=interface_id).first()

        # 解析 method 枚举
        method_map = {"GET": HttpMethod.GET, "POST": HttpMethod.POST, "PUT": HttpMethod.PUT, "DELETE": HttpMethod.DELETE, "PATCH": HttpMethod.PATCH}
        api_method = method_map.get(request.api_method.upper(), HttpMethod.POST)

        if not manual_interface:
            manual_interface = await ApiInterface.create(
                interface_id=interface_id,
                document=manual_doc,
                name=request.name,
                path=request.api_path or f"/manual/{request.file_name}",
                method=api_method,
                description=request.description,
                is_active=True,
            )
        else:
            # 更新已有占位接口的信息
            manual_interface.name = request.name
            manual_interface.description = request.description
            manual_interface.path = request.api_path or manual_interface.path
            manual_interface.method = api_method
            await manual_interface.save()

        # 创建脚本记录
        script = await TestScript.create(
            script_id=str(uuid.uuid4()),
            name=request.name,
            description=request.description,
            file_name=request.file_name,
            file_path=request.file_path,
            content=content,
            interface=manual_interface,
            document=manual_doc,
            framework=request.framework,
            language="python",
            version="1.0",
            dependencies=["pytest", "requests", "pycryptodome"],
            status="ACTIVE",
            is_executable=True,
            generated_by="MANUAL",
            code_quality_score="A",
            is_active=True,
        )

        return {
            "code": 200,
            "msg": "脚本注册成功",
            "data": {"script_id": script.script_id, "action": "created"},
            "success": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册手动脚本失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"注册脚本失败: {str(e)}")


# ==================== 接口脚本查询API ====================

@router.get("/interfaces/{interface_id}/scripts", summary="获取接口的所有脚本")
async def get_interface_scripts(
    interface_id: str,
    include_inactive: bool = Query(False, description="是否包含非活跃脚本")
):
    """获取指定接口的所有测试脚本"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_interface_scripts(interface_id, include_inactive)

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取接口脚本失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取接口脚本失败: {str(e)}")


@router.get("/interfaces/{interface_id}/scripts/statistics", summary="获取接口脚本统计")
async def get_interface_script_statistics(interface_id: str):
    """获取接口的脚本统计信息"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_interface_script_statistics(interface_id)

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取接口脚本统计失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取接口脚本统计失败: {str(e)}")


@router.get("/interfaces/{interface_id}/scripts/generation-history", summary="获取脚本生成历史")
async def get_script_generation_history(
    interface_id: str,
    limit: int = Query(10, description="返回记录数量限制")
):
    """获取接口的脚本生成历史"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_script_generation_history(interface_id, limit)

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取脚本生成历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取脚本生成历史失败: {str(e)}")


@router.get("/documents/{document_id}/scripts/overview", summary="获取文档脚本概览")
async def get_document_script_overview(document_id: str):
    """获取文档的脚本概览信息"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_document_script_overview(document_id)

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取文档脚本概览失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取文档脚本概览失败: {str(e)}")


@router.get("/", summary="获取所有脚本列表")
async def get_all_scripts(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    status: Optional[str] = Query(None, description="状态筛选"),
    framework: Optional[str] = Query(None, description="框架筛选"),
    interface_id: Optional[str] = Query(None, description="接口ID筛选"),
    document_id: Optional[str] = Query(None, description="文档ID筛选"),
    include_inactive: bool = Query(False, description="是否包含非活跃脚本")
):
    """获取所有测试脚本列表，支持分页和筛选"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_all_scripts(
            page=page,
            page_size=page_size,
            search=search,
            status=status,
            framework=framework,
            interface_id=interface_id,
            document_id=document_id,
            include_inactive=include_inactive
        )

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except Exception as e:
        logger.error(f"获取脚本列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取脚本列表失败: {str(e)}")


# ==================== 脚本基础管理API ====================

@router.get("/{script_id}", summary="获取脚本详细信息")
async def get_script_detail(script_id: str):
    """获取测试脚本的详细信息"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_script_detail(script_id)

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取脚本详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取脚本详情失败: {str(e)}")


@router.put("/{script_id}/status", summary="更新脚本状态")
async def update_script_status(script_id: str, request: ScriptStatusUpdateRequest):
    """更新测试脚本的状态"""
    try:
        script_service = InterfaceScriptService()
        success = await script_service.update_script_status(
            script_id=script_id,
            status=request.status,
            is_executable=request.is_executable
        )

        return {
            "code": 200,
            "msg": "脚本状态更新成功",
            "success": success
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"更新脚本状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新脚本状态失败: {str(e)}")


@router.put("/{script_id}/content", summary="更新脚本代码内容")
async def update_script_content(script_id: str, request: ScriptContentUpdateRequest):
    """修改测试脚本的源代码，同时更新数据库和磁盘文件"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.update_script_content(
            script_id=script_id,
            content=request.content,
        )

        return {
            "code": 200,
            "msg": "脚本内容已更新",
            "data": result,
            "success": True,
        }

    except SyntaxError as e:
        raise HTTPException(
            status_code=400,
            detail=f"脚本语法错误: {e.msg} (第 {e.lineno} 行)",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        logger.error(f"更新脚本内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"更新脚本内容失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新脚本内容失败: {str(e)}")


@router.delete("/{script_id}", summary="删除脚本")
async def delete_script(
    script_id: str,
    soft_delete: bool = Query(True, description="是否软删除")
):
    """删除测试脚本"""
    try:
        script_service = InterfaceScriptService()
        success = await script_service.delete_script(script_id, soft_delete)

        return {
            "code": 200,
            "msg": "脚本删除成功",
            "success": success
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"删除脚本失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除脚本失败: {str(e)}")


@router.put("/batch-status", summary="批量更新脚本状态")
async def batch_update_script_status(request: BatchScriptStatusUpdateRequest):
    """批量更新脚本状态"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.batch_update_script_status(
            script_ids=request.script_ids,
            status=request.status,
            is_executable=request.is_executable
        )

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"批量更新脚本状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"批量更新脚本状态失败: {str(e)}")


# ==================== 脚本执行API ====================


@router.post("/{script_id}/run", summary="启动脚本执行（异步）")
async def run_single_script(script_id: str, request: SingleScriptExecutionRequest):
    """
    启动后台异步执行任务，立即返回 execution_id（status=RUNNING）。
    实际执行（pytest + Allure 生成 + 落库）在后台进行，
    可在「执行报告」页面查看实时状态和最终结果。
    """
    import asyncio
    import uuid
    from pathlib import Path
    from datetime import datetime
    from app.models.api_automation import TestScript, TestExecution

    # 加载脚本（需要 select_related 拿 document 外键）
    script = await TestScript.filter(script_id=script_id, is_active=True).select_related("document").first()
    if not script:
        raise HTTPException(status_code=404, detail=f"脚本不存在: {script_id}")

    # 准备执行环境
    backend_dir = Path(__file__).resolve().parents[4]
    generated_tests_dir = backend_dir / "generated_tests"
    reports_root = backend_dir / "reports"

    script_file = generated_tests_dir / script.file_path
    if not script_file.exists():
        script_file.parent.mkdir(parents=True, exist_ok=True)
        script_file.write_text(script.content, encoding="utf-8")

    # 生成 execution_id 并创建报告目录
    execution_id = str(uuid.uuid4())
    execution_dir = reports_root / execution_id
    execution_dir.mkdir(parents=True, exist_ok=True)

    env_name = request.environment or "test"
    timeout = request.timeout or 300

    # INSERT TestExecution (status=RUNNING)
    start_time = datetime.now()
    await TestExecution.create(
        execution_id=execution_id,
        session_id=execution_id,
        document=script.document,
        execution_config={"script_id": script_id, **(request.execution_config or {})},
        environment=env_name,
        parallel=False,
        max_workers=1,
        status=ExecutionStatus.RUNNING,
        start_time=start_time,
        description=f"单脚本执行: {script.name}",
    )

    # 调度后台任务（不 await，立即返回）
    asyncio.create_task(_execute_script_in_background(
        execution_id=execution_id,
        script_id=script_id,
        script_file_path=script.file_path,
        script_name=script.name,
        generated_tests_dir=generated_tests_dir,
        execution_dir=execution_dir,
        env_name=env_name,
        timeout=timeout,
        start_time=start_time,
    ))

    return {
        "code": 200,
        "msg": "执行任务已启动",
        "data": {
            "execution_id": execution_id,
            "script_id": script_id,
            "status": "RUNNING",
            "message": "任务已启动，请在「执行报告」页面查看进度和结果",
            "start_time": start_time.isoformat(),
        },
        "success": True,
    }


async def _execute_script_in_background(
    execution_id: str,
    script_id: str,
    script_file_path: str,
    script_name: str,
    generated_tests_dir,
    execution_dir,
    env_name: str,
    timeout: int,
    start_time,
):
    """
    后台执行脚本。本函数不与 HTTP 请求生命周期绑定，
    执行过程的所有错误都会被捕获并落库为 FAILED 状态，避免 task 静默死亡。
    """
    import asyncio
    import os
    import subprocess
    import shutil
    import sys
    import uuid
    from datetime import datetime
    from app.models.api_automation import TestScript, TestExecution, ScriptExecutionResult

    return_code = -1
    stdout = ""
    stderr = ""
    end_time = start_time
    report_files = []
    passed = failed = errors = skipped = total = 0
    success_rate = 0.0

    # 读激活环境（无则回退 env_name + YAML）
    subprocess_env = os.environ.copy()
    try:
        from app.services.environment_service import get_active_environment
        active_env = await get_active_environment()
    except Exception:
        active_env = None

    if active_env:
        env_name = active_env.name or env_name
        if active_env.api_base_url:
            subprocess_env["AUTOMATION_API__BASE_URL"] = active_env.api_base_url.rstrip("/")
        if active_env.username:
            subprocess_env["AUTOMATION_AUTH__USERNAME"] = active_env.username
        if active_env.password:
            subprocess_env["AUTOMATION_AUTH__PASSWORD"] = active_env.password
        subprocess_env["AUTOMATION_ENV"] = env_name

    try:
        # 构建 pytest 命令
        junit_path = execution_dir / "junit.xml"
        cmd_parts = [
            sys.executable, "-m", "pytest", script_file_path,
            "--env", env_name,
            "-v", "--tb=short", "--no-header",
            "--junitxml", str(junit_path),
        ]

        html_path = execution_dir / "report.html"
        try:
            import pytest_html  # noqa: F401
            cmd_parts.extend(["--html", str(html_path), "--self-contained-html"])
        except ImportError:
            html_path = None

        allure_results_dir = execution_dir / "allure-results"
        try:
            import allure_pytest  # noqa: F401
            cmd_parts.extend(["--alluredir", str(allure_results_dir)])
            has_allure_plugin = True
        except ImportError:
            has_allure_plugin = False

        # 跑 pytest
        def _run_pytest():
            try:
                return subprocess.run(
                    cmd_parts,
                    cwd=str(generated_tests_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding="utf-8",
                    errors="replace",
                    env=subprocess_env,
                )
            except subprocess.TimeoutExpired as e:
                return e

        proc_result = await asyncio.to_thread(_run_pytest)
        if isinstance(proc_result, subprocess.TimeoutExpired):
            return_code = -1
            stderr = f"执行超时（{timeout}秒）"
        else:
            return_code = proc_result.returncode
            stdout = proc_result.stdout
            stderr = proc_result.stderr

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # 解析统计 —— 从 junit.xml 读取，不再靠字符串匹配 stdout
        # 字符串匹配（stdout.count(" PASSED") 等）在编码 / 输出格式变化时全 0，
        # junit.xml 是 pytest 的机器可读报告，统计永远精确。
        if junit_path.exists():
            total, passed, failed, errors, skipped = _parse_junit_stats(junit_path)
        else:
            # 极端兜底：junit.xml 都没生成，回退字符串匹配
            passed = stdout.count(" PASSED")
            failed = stdout.count(" FAILED")
            errors = stdout.count(" ERROR")
            skipped = stdout.count(" SKIPPED")
            total = passed + failed + errors + skipped
        success_rate = (passed / total * 100) if total > 0 else 0.0

        # 生成 Allure 静态站点
        allure_report_dir = execution_dir / "allure-report"
        allure_generated = False
        if has_allure_plugin and allure_results_dir.exists():
            allure_cli = shutil.which("allure")
            if allure_cli:
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        [allure_cli, "generate", str(allure_results_dir),
                         "-o", str(allure_report_dir), "--clean"],
                        capture_output=True, text=True, timeout=60, check=False,
                    )
                    allure_generated = (allure_report_dir / "index.html").exists()
                except Exception as e:
                    logger.warning(f"生成 Allure 静态站点失败: {e}")

        # 组装 report_files
        if allure_generated:
            allure_index = allure_report_dir / "index.html"
            report_files.append({
                "format": "allure", "name": "index.html",
                "path": str(allure_index),
                "url": f"/reports/{execution_id}/allure-report/index.html",
            })
        if html_path and html_path.exists():
            report_files.append({
                "format": "html", "name": "report.html",
                "path": str(html_path),
                "url": f"/reports/{execution_id}/report.html",
            })
        if junit_path.exists():
            report_files.append({
                "format": "junit", "name": "junit.xml",
                "path": str(junit_path),
                "url": f"/reports/{execution_id}/junit.xml",
            })

    except Exception as e:
        logger.error(f"后台执行任务异常 execution_id={execution_id}: {e}", exc_info=True)
        stderr = f"后台执行异常: {e}\n{stderr}"
        return_code = -1
        end_time = datetime.now()

    # 落库（无论成功或失败都要更新）
    try:
        test_execution = await TestExecution.filter(execution_id=execution_id).first()
        if test_execution:
            test_execution.status = ExecutionStatus.SUCCESS if return_code == 0 else ExecutionStatus.FAILED
            test_execution.end_time = end_time
            test_execution.execution_time = round((end_time - start_time).total_seconds(), 2)
            test_execution.total_tests = total
            test_execution.passed_tests = passed
            test_execution.failed_tests = failed
            test_execution.skipped_tests = skipped
            test_execution.error_tests = errors
            test_execution.success_rate = round(success_rate, 2)
            test_execution.summary = {
                "script_id": script_id,
                "script_name": script_name,
                "return_code": return_code,
                "stdout_tail": stdout[-2000:] if stdout else "",
                "stderr_tail": stderr[-2000:] if stderr else "",
            }
            test_execution.report_files = report_files
            await test_execution.save()

            # 创建 ScriptExecutionResult
            script = await TestScript.filter(script_id=script_id).first()
            if script:
                await ScriptExecutionResult.create(
                    result_id=str(uuid.uuid4()),
                    execution=test_execution,
                    script=script,
                    script_name=script_name,
                    script_path=script_file_path or "",
                    start_time=start_time,
                    end_time=end_time,
                    duration=round((end_time - start_time).total_seconds(), 2),
                    status="PASSED" if return_code == 0 else "FAILED",
                    exit_code=return_code,
                    total_tests=total,
                    passed_tests=passed,
                    failed_tests=failed,
                    skipped_tests=skipped,
                    error_tests=errors,
                    stdout=stdout[-5000:] if stdout else "",
                    stderr=stderr[-5000:] if stderr else "",
                    error_message=stderr[-500:] if return_code != 0 and stderr else "",
                )

                # 更新脚本执行统计
                script.execution_count += 1
                if return_code == 0:
                    script.success_count += 1
                script.last_execution_time = end_time
                await script.save()
    except Exception as e:
        logger.error(f"后台任务落库失败 execution_id={execution_id}: {e}", exc_info=True)


# ============================================================
# 批量并发执行：单脚本路径不动，新增并发后台任务
# ============================================================

async def _run_pytest_for_one_script(
    script_file_path: str,
    script_dir,
    generated_tests_dir,
    env_name: str,
    timeout: int,
    nodeids: Optional[List[str]] = None,
):
    """跑单个脚本（或脚本里指定的若干 nodeids），仅返回执行原始结果（不落库）。

    nodeids: 如 ["TestAlarm::test_create_alarm_success", ...]，非空时只跑这些方法；
             空时跑整个文件。

    返回 dict：return_code/stdout/stderr/start_time/end_time/duration/
              passed/failed/errors/skipped/total/success_rate/report_files
    """
    import asyncio
    import os
    import subprocess
    import shutil
    import sys
    from datetime import datetime

    script_dir.mkdir(parents=True, exist_ok=True)
    start_time = datetime.now()

    # 读激活的执行环境；有则用它的 name 覆盖参数 env_name，并注入 AUTOMATION_* 环境变量
    # 无激活环境时保持现状（用参数传入的 env_name + YAML 兜底）
    subprocess_env = os.environ.copy()
    try:
        from app.services.environment_service import get_active_environment
        active_env = await get_active_environment()
    except Exception:
        active_env = None

    if active_env:
        # 用激活环境的 name 决定 pytest --env（YAML 骨架），值由 AUTOMATION_* 覆盖
        # 注意：如果激活环境 name 对应的 YAML 不存在会失败，用户新建时需自建 YAML
        # 或者复用现有 name（test/staging/prod）作为骨架
        env_name = active_env.name or env_name
        if active_env.api_base_url:
            # 兜底 rstrip，兼容老数据末尾带 / 的情况（避免拼路径出现 //）
            subprocess_env["AUTOMATION_API__BASE_URL"] = active_env.api_base_url.rstrip("/")
        if active_env.username:
            subprocess_env["AUTOMATION_AUTH__USERNAME"] = active_env.username
        if active_env.password:
            subprocess_env["AUTOMATION_AUTH__PASSWORD"] = active_env.password
        # AUTOMATION_ENV 兼容旧代码
        subprocess_env["AUTOMATION_ENV"] = env_name
        logger.info(
            f"[pytest env] 应用激活环境: name={active_env.name} "
            f"api_base_url={active_env.api_base_url} username={active_env.username}"
        )
    else:
        logger.info(f"[pytest env] 未激活环境，使用参数 env_name={env_name}（YAML 兜底）")

    # 构造 pytest target：有 nodeids 时跑 file::Class::method，否则跑整个文件
    if nodeids:
        targets = [f"{script_file_path}::{nid}" for nid in nodeids]
    else:
        targets = [script_file_path]

    junit_path = script_dir / "junit.xml"
    cmd_parts = [
        sys.executable, "-m", "pytest", *targets,
        "--env", env_name,
        "-v", "--tb=short", "--no-header",
        "--junitxml", str(junit_path),
    ]

    html_path = script_dir / "report.html"
    try:
        import pytest_html  # noqa: F401
        cmd_parts.extend(["--html", str(html_path), "--self-contained-html"])
    except ImportError:
        html_path = None

    allure_results_dir = script_dir / "allure-results"
    try:
        import allure_pytest  # noqa: F401
        cmd_parts.extend(["--alluredir", str(allure_results_dir)])
        has_allure_plugin = True
    except ImportError:
        has_allure_plugin = False

    return_code = -1
    stdout = ""
    stderr = ""

    def _run_pytest():
        try:
            return subprocess.run(
                cmd_parts,
                cwd=str(generated_tests_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                env=subprocess_env,
            )
        except subprocess.TimeoutExpired as e:
            return e

    proc_result = await asyncio.to_thread(_run_pytest)
    if isinstance(proc_result, subprocess.TimeoutExpired):
        return_code = -1
        stderr = f"执行超时（{timeout}秒）"
    else:
        return_code = proc_result.returncode
        stdout = proc_result.stdout or ""
        stderr = proc_result.stderr or ""

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    if junit_path.exists():
        total, passed, failed, errors, skipped = _parse_junit_stats(junit_path)
    else:
        passed = stdout.count(" PASSED")
        failed = stdout.count(" FAILED")
        errors = stdout.count(" ERROR")
        skipped = stdout.count(" SKIPPED")
        total = passed + failed + errors + skipped
    success_rate = (passed / total * 100) if total > 0 else 0.0

    # 每脚本独立 Allure 站点（可选，便于单点查看）
    allure_report_dir = script_dir / "allure-report"
    allure_generated = False
    if has_allure_plugin and allure_results_dir.exists():
        allure_cli = shutil.which("allure")
        if allure_cli:
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [allure_cli, "generate", str(allure_results_dir),
                     "-o", str(allure_report_dir), "--clean"],
                    capture_output=True, text=True, timeout=60, check=False,
                )
                allure_generated = (allure_report_dir / "index.html").exists()
            except Exception as e:
                logger.warning(f"生成 Allure 静态站点失败: {e}")

    # 报告文件相对路径（用于拼前端 URL，由调用方加上 execution_id 前缀）
    report_files = []
    if allure_generated:
        report_files.append({
            "format": "allure", "name": "index.html",
            "rel_path": f"{script_dir.name}/allure-report/index.html",
            "abs_path": str(allure_report_dir / "index.html"),
        })
    if html_path and html_path.exists():
        report_files.append({
            "format": "html", "name": "report.html",
            "rel_path": f"{script_dir.name}/report.html",
            "abs_path": str(html_path),
        })
    if junit_path.exists():
        report_files.append({
            "format": "junit", "name": "junit.xml",
            "rel_path": f"{script_dir.name}/junit.xml",
            "abs_path": str(junit_path),
        })

    return {
        "return_code": return_code,
        "stdout": stdout,
        "stderr": stderr,
        "start_time": start_time,
        "end_time": end_time,
        "duration": round(duration, 2),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "total": total,
        "success_rate": round(success_rate, 2),
        "report_files": report_files,
        # 暴露原始 allure-results 目录，供批量执行做跨脚本合并
        "allure_results_dir": str(allure_results_dir) if (has_allure_plugin and allure_results_dir.exists()) else None,
    }


async def _execute_batch_in_background(
    execution_id: str,
    scripts_meta: list,
    generated_tests_dir,
    execution_dir,
    env_name: str,
    timeout: int,
    max_workers: int,
    batch_start_time,
):
    """批量并发跑脚本 + 聚合落库。

    scripts_meta: List[Dict]，每项 {script_id, script_pk, script_name, file_path}
    """
    import asyncio
    import uuid
    from datetime import datetime
    from app.models.api_automation import TestScript, TestExecution, ScriptExecutionResult

    semaphore = asyncio.Semaphore(max_workers)
    results: list = [None] * len(scripts_meta)

    async def run_one(idx: int, meta: dict):
        async with semaphore:
            script_dir = execution_dir / "scripts" / meta["script_id"]
            try:
                res = await _run_pytest_for_one_script(
                    script_file_path=meta["file_path"],
                    script_dir=script_dir,
                    generated_tests_dir=generated_tests_dir,
                    env_name=env_name,
                    timeout=timeout,
                )
                results[idx] = res
            except Exception as e:
                logger.error(f"脚本执行异常 script_id={meta['script_id']}: {e}", exc_info=True)
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
                }

    await asyncio.gather(*[run_one(i, m) for i, m in enumerate(scripts_meta)], return_exceptions=False)

    # 聚合统计 + 落库
    batch_end_time = datetime.now()
    agg_total = sum(r["total"] for r in results)
    agg_passed = sum(r["passed"] for r in results)
    agg_failed = sum(r["failed"] for r in results)
    agg_errors = sum(r["errors"] for r in results)
    agg_skipped = sum(r["skipped"] for r in results)
    agg_success_rate = (agg_passed / agg_total * 100) if agg_total > 0 else 0.0

    # 批次状态：所有脚本 return_code==0 → SUCCESS，否则 FAILED
    all_ok = all(r["return_code"] == 0 for r in results)

    # 聚合报告文件（URL 加 execution_id 前缀）
    batch_report_files = []
    for meta, res in zip(scripts_meta, results):
        for rf in res["report_files"]:
            batch_report_files.append({
                "script_id": meta["script_id"],
                "script_name": meta["script_name"],
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
                "script_count": len(scripts_meta),
                "script_ids": [m["script_id"] for m in scripts_meta],
                "all_ok": all_ok,
            }
            test_execution.report_files = batch_report_files
            await test_execution.save()

            # 每脚本一行 ScriptExecutionResult
            for meta, res in zip(scripts_meta, results):
                script = await TestScript.filter(script_id=meta["script_id"]).first()
                if not script:
                    continue
                await ScriptExecutionResult.create(
                    result_id=str(uuid.uuid4()),
                    execution=test_execution,
                    script=script,
                    script_name=meta["script_name"],
                    script_path=meta["file_path"] or "",
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
                    stdout=res["stdout"][-5000:] if res["stdout"] else "",
                    stderr=res["stderr"][-5000:] if res["stderr"] else "",
                    error_message=res["stderr"][-500:] if res["return_code"] != 0 and res["stderr"] else "",
                )

                script.execution_count += 1
                if res["return_code"] == 0:
                    script.success_count += 1
                script.last_execution_time = res["end_time"]
                await script.save()
    except Exception as e:
        logger.error(f"批量执行落库失败 execution_id={execution_id}: {e}", exc_info=True)


@router.post("/execute", summary="批量执行脚本")
async def execute_scripts(request: ScriptExecutionRequest):
    """批量启动脚本执行（异步）。多个脚本之间并发，单脚本内部仍串行。

    立即返回 execution_id，实际跑 pytest + 落库在后台进行，
    可在「执行报告」页面查看进度和最终结果。
    """
    import asyncio
    import uuid
    from pathlib import Path
    from datetime import datetime
    from app.models.api_automation import TestScript, TestExecution

    if not request.script_ids:
        raise HTTPException(status_code=400, detail="脚本ID列表不能为空")

    # 加载脚本（需要 select_related 拿 document 外键）
    scripts = []
    for sid in request.script_ids:
        s = await TestScript.filter(
            script_id=sid, is_active=True, is_executable=True
        ).select_related("document").first()
        if not s:
            raise HTTPException(status_code=404, detail=f"脚本不存在或不可执行: {sid}")
        scripts.append(s)

    backend_dir = Path(__file__).resolve().parents[4]
    generated_tests_dir = backend_dir / "generated_tests"
    reports_root = backend_dir / "reports"

    # 确保脚本文件落盘
    for s in scripts:
        sf = generated_tests_dir / s.file_path
        if not sf.exists():
            sf.parent.mkdir(parents=True, exist_ok=True)
            sf.write_text(s.content, encoding="utf-8")

    execution_id = str(uuid.uuid4())
    execution_dir = reports_root / execution_id
    execution_dir.mkdir(parents=True, exist_ok=True)

    env_name = request.environment or "test"
    timeout = request.timeout or 300
    max_workers = max(1, min(request.max_workers or 4, 8))  # 上限 8

    start_time = datetime.now()
    await TestExecution.create(
        execution_id=execution_id,
        session_id=execution_id,
        document=scripts[0].document,  # 取首个脚本的文档作为关联
        execution_config={
            "script_ids": request.script_ids,
            "max_workers": max_workers,
            **(request.execution_config or {}),
        },
        environment=env_name,
        parallel=True,
        max_workers=max_workers,
        status=ExecutionStatus.RUNNING,
        start_time=start_time,
        description=f"批量执行 {len(scripts)} 个脚本（并发度 {max_workers}）",
    )

    scripts_meta = [
        {
            "script_id": s.script_id,
            "script_pk": s.id,
            "script_name": s.name,
            "file_path": s.file_path,
        }
        for s in scripts
    ]

    asyncio.create_task(_execute_batch_in_background(
        execution_id=execution_id,
        scripts_meta=scripts_meta,
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
            "script_count": len(scripts),
            "max_workers": max_workers,
            "status": "RUNNING",
            "message": "任务已启动，请在「执行报告」页面查看进度和结果",
            "start_time": start_time.isoformat(),
        },
        "success": True,
    }


@router.post("/{script_id}/execute", summary="执行单个脚本")
async def execute_single_script(script_id: str, request: SingleScriptExecutionRequest):
    """执行单个测试脚本 - 通过智能体执行"""
    try:
        # 导入智能体相关模块
        from app.agents.api_automation.schemas import TestExecutionInput, GeneratedScript
        from app.core.agents.runtime_manager import runtime_manager
        from app.core.types import TopicTypes
        from autogen_core import TopicId
        import uuid
        from datetime import datetime

        # 获取脚本详情
        script_service = InterfaceScriptService()
        script_detail = await script_service.get_script_detail(script_id)

        if not script_detail:
            raise ValueError(f"脚本不存在: {script_id}")

        # 准备脚本数据
        import tempfile
        import os

        # 创建跨平台的临时脚本路径
        temp_dir = tempfile.gettempdir()
        scripts_dir = os.path.join(temp_dir, "scripts")
        os.makedirs(scripts_dir, exist_ok=True)  # 确保目录存在
        script_filename = f"{script_id}.py"
        script_file_path = os.path.join(scripts_dir, script_filename)

        script_data = GeneratedScript(
            script_id=script_id,
            script_name=script_detail.get("name", f"script_{script_id}"),
            file_path=script_file_path,
            script_content=script_detail.get("content", ""),
            framework=script_detail.get("framework", "pytest"),
            dependencies=script_detail.get("dependencies", [])
        )

        # 创建执行输入 - 修复字段名和参数
        # 将超时时间添加到执行配置中
        execution_config = request.execution_config or {}
        if request.timeout:
            execution_config["timeout"] = request.timeout

        execution_input = TestExecutionInput(
            session_id=str(uuid.uuid4()),
            document_id=script_detail.get("document_id", ""),
            scripts=[script_data],
            execution_config=execution_config,
            environment=request.environment,
            parallel=False,
            max_workers=1
        )

        # 获取运行时并发送消息给智能体
        runtime = await runtime_manager.get_runtime()

        # 发送执行请求到脚本执行智能体
        await runtime.publish_message(
            execution_input,
            topic_id=TopicId(type=TopicTypes.TEST_EXECUTOR.value, source="api")
        )

        # 返回执行已启动的响应
        return {
            "code": 200,
            "msg": "OK",
            "data": {
                "execution_id": execution_input.session_id,
                "script_id": script_id,
                "status": "STARTED",
                "message": "脚本执行已通过智能体启动",
                "start_time": datetime.now().isoformat()
            },
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"执行脚本失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"执行脚本失败: {str(e)}")


@router.get("/{script_id}/execution/{execution_id}", summary="获取脚本执行结果")
async def get_script_execution_result(script_id: str, execution_id: str):
    """获取脚本执行结果"""
    try:
        # 从响应收集器获取执行结果
        from app.core.agents.runtime_manager import runtime_manager

        collector = runtime_manager.get_response_collector()
        if not collector:
            raise HTTPException(status_code=500, detail="响应收集器未初始化")

        # 查找执行结果
        results = collector.get_results()
        execution_result = None

        for result_key, result_data in results.items():
            if (isinstance(result_data, dict) and
                result_data.get("session_id") == execution_id):
                execution_result = result_data
                break

        if execution_result:
            return {
                "code": 200,
                "msg": "OK",
                "data": execution_result,
                "success": True
            }
        else:
            # 如果没有找到结果，返回执行中状态
            return {
                "code": 200,
                "msg": "OK",
                "data": {
                    "execution_id": execution_id,
                    "script_id": script_id,
                    "status": "RUNNING",
                    "message": "脚本正在执行中..."
                },
                "success": True
            }

    except Exception as e:
        logger.error(f"获取执行结果失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取执行结果失败: {str(e)}")


# ==================== 执行历史和监控API ====================

@router.get("/{script_id}/executions", summary="获取脚本执行历史")
async def get_script_execution_history(
    script_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量")
):
    """获取脚本的执行历史记录"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_script_execution_history(
            script_id=script_id,
            page=page,
            page_size=page_size
        )

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取脚本执行历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取脚本执行历史失败: {str(e)}")


# ==================== 执行详情和日志API ====================

@router.get("/executions/{execution_id}", summary="获取执行详情")
async def get_execution_detail(execution_id: str):
    """获取脚本执行的详细信息"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_execution_detail(execution_id)

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取执行详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取执行详情失败: {str(e)}")


@router.get("/executions/{execution_id}/logs", summary="获取执行日志")
async def get_execution_logs(
    execution_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=1000, description="每页数量")
):
    """获取脚本执行的日志信息"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.get_execution_logs(
            execution_id=execution_id,
            page=page,
            page_size=page_size
        )

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取执行日志失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取执行日志失败: {str(e)}")


@router.post("/executions/{execution_id}/stop", summary="停止执行")
async def stop_execution(execution_id: str):
    """停止正在执行的脚本"""
    try:
        script_service = InterfaceScriptService()
        result = await script_service.stop_execution(execution_id)

        return {
            "code": 200,
            "msg": "OK",
            "data": result,
            "success": True
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"停止执行失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"停止执行失败: {str(e)}")


# ==================== TestCase 映射修复 API ====================

class RepairMappingRequest(BaseModel):
    """修复映射请求"""
    test_case_ids: Optional[List[str]] = Field(None, description="要修复的 test_case_id 列表，不传则修复全部缺失映射的用例")


@router.post("/repair-mapping", summary="修复 TestCase 脚本映射")
async def repair_mapping(request: RepairMappingRequest = None):
    """
    修复 class_name/method_name/script_file_path 为空的 TestCase 记录。

    通过 AST 解析已有的 TestScript 脚本文件，反向匹配 TestCase 与 pytest 方法，
    补齐缺失的映射字段，使用例可以正常执行。

    - 传 test_case_ids：只修复指定用例
    - 不传：修复所有缺失映射的用例
    """
    try:
        ids = request.test_case_ids if request else None
        result = await repair_test_case_mapping(ids)

        if result["errors"]:
            logger.warning(
                f"映射修复部分失败: repaired={result['repaired']}, "
                f"skipped={result['skipped']}, errors={len(result['errors'])}"
            )
        else:
            logger.info(f"映射修复完成: repaired={result['repaired']}, skipped={result['skipped']}")

        return {
            "code": 200,
            "msg": f"修复完成: 成功 {result['repaired']}, 跳过 {result['skipped']}, 错误 {len(result['errors'])}",
            "data": result,
            "success": True
        }

    except Exception as e:
        logger.error(f"修复映射失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"修复映射失败: {str(e)}")
