"""
Playwright 子进程执行服务

职责(纯框架,不依赖 Agent / DB):
  1. 准备隔离工作区     reports/exec_<id>/{test-results, html, results.json, run.log}
  2. 并发闸门          asyncio.Semaphore(UI_MAX_CONCURRENT_EXECUTIONS)
  3. 子进程编排         shell="npx playwright test <rel_path>"  via asyncio.to_thread
  4. 超时 + 取消        kill 整个进程组,不让 Chromium / node 残留
  5. 输出回传           子进程跑完后按行批量回调 progress_callback
  6. 路径沙箱           script_relative_path 必须位于 UI_AUTOMATION_WORKSPACE 内的 scripts/ 下

不做的事:
  - 不查 DB / 不写 DB (由 UiDataPersistenceAgent 负责)
  - 不发 SSE 消息 (由 UiScriptExecutorAgent 包一层 StreamMessage 后投递)
  - 不解析报告 (交 report_service.parse_playwright_json)

设计参照: 原 ui-automation 项目 playwright_script_executor_agent.py 的 subprocess.run + shell=True 路径。
不上 asyncio.create_subprocess_exec 的原因: uvicorn --reload 在 Windows 下会强制走
SelectorEventLoop,而 Selector loop 不支持 subprocess —— 改成 shell 一行命令后丢
asyncio.to_thread() 跑同步 Popen,既绕开事件循环兼容性问题,又保留 await 语义。

零回归:本模块独立运转,UI_AUTOMATION_ENABLED=False 时 API 层直接拦截,根本不会调到这里。
"""
from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Literal, Optional

from loguru import logger

from app.settings.config import settings


# ============================================================================
# 数据结构
# ============================================================================

ExecutionStatus = Literal["success", "failed", "timeout", "cancelled", "safety_blocked", "error"]


@dataclass
class ExecutionProgress:
    """实时进度事件 - 推给 progress_callback"""
    phase: Literal["queued", "preparing", "running", "finishing"]
    line: str = ""                  # 子进程一行输出(running 阶段)
    stream: Literal["stdout", "stderr", ""] = ""
    elapsed_ms: int = 0


@dataclass
class ExecutionResult:
    execution_id: str
    status: ExecutionStatus
    exit_code: Optional[int]
    duration_ms: int
    stdout: str
    stderr: str
    error_message: str = ""
    # 隔离工作区路径(供持久化层和报告解析用)
    workspace_dir: str = ""
    html_report_dir: str = ""
    json_report_file: str = ""
    log_file: str = ""
    workspace_relative: str = ""    # 相对 UI_ARTIFACT_DIR 的路径,用于拼 file_url


# ============================================================================
# 模块内状态
# ============================================================================

_semaphore: Optional[asyncio.Semaphore] = None
_running_processes: Dict[str, subprocess.Popen] = {}
_cancel_flags: Dict[str, bool] = {}

_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]")


def _get_semaphore() -> asyncio.Semaphore:
    """惰性创建闸门 —— 必须在 event loop 内调用。"""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, int(settings.UI_MAX_CONCURRENT_EXECUTIONS)))
    return _semaphore


def _safe_id(execution_id: str) -> str:
    """把任意字符串转成可作目录名的安全 id。

    Why: uvicorn --reload 在监听 .py 结尾目录时会触发重启杀子进程(见
    project_uvicorn_reload_pyext_trap 记忆),所以坚决禁止任何点号 / 路径分隔符。
    """
    sid = _SAFE_ID_PATTERN.sub("_", execution_id or "anon")
    return sid[:64] or "anon"


# ============================================================================
# 工作区与命令准备
# ============================================================================

def _prepare_workspace(execution_id: str) -> Dict[str, str]:
    """为本次执行创建隔离目录。

    布局:
        UI_ARTIFACT_DIR/
            exec_<safe_id>/
                test-results/   ← Playwright trace/video/screenshot 落地
                html/           ← HTML 报告(供 StaticFiles 暴露 iframe)
    """
    safe = _safe_id(execution_id)
    artifact_root = Path(settings.UI_ARTIFACT_DIR).resolve()
    workspace = artifact_root / f"exec_{safe}"

    test_results = workspace / "test-results"
    html_dir = workspace / "html"
    json_file = workspace / "results.json"
    log_file = workspace / "run.log"
    # allure-results: Playwright 跑测试时通过 allure-playwright reporter 写入；
    # allure HTML 由 allure_service 按需 generate（按钮触发），不在此预建
    allure_results_dir = workspace / "allure-results"

    test_results.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)
    allure_results_dir.mkdir(parents=True, exist_ok=True)

    try:
        workspace_relative = workspace.relative_to(artifact_root)
        workspace_relative_str = str(workspace_relative).replace("\\", "/")
    except ValueError:
        workspace_relative_str = workspace.name

    return {
        "workspace_dir": str(workspace),
        "test_results_dir": str(test_results),
        "html_report_dir": str(html_dir),
        "json_report_file": str(json_file),
        "log_file": str(log_file),
        "allure_results_dir": str(allure_results_dir),
        "workspace_relative": workspace_relative_str,
        "safe_id": safe,
    }


def _validate_script_path(script_relative_path: str) -> Path:
    """把相对路径校验到 workspace 内,失败抛 ValueError。"""
    if not script_relative_path:
        raise ValueError("script_relative_path 不能为空")
    if ".." in Path(script_relative_path).parts:
        raise ValueError("script_relative_path 禁止包含 '..'")
    if os.path.isabs(script_relative_path):
        raise ValueError("script_relative_path 必须是相对路径(相对 UI_AUTOMATION_WORKSPACE)")

    workspace = Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
    candidate = (workspace / script_relative_path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError:
        raise ValueError(f"script_relative_path 逃逸出 workspace: {script_relative_path}")

    if not candidate.exists():
        raise FileNotFoundError(f"脚本不存在: {candidate}")

    return candidate


def _build_command_str(script_relative_path: str) -> str:
    """构造 shell 命令字符串(供 shell=True 使用)。

    - .yaml/.yml → MidScene CLI
    - .ts/.js/.spec.ts → Playwright test runner

    路径必须用正斜杠:Playwright CLI 把 `playwright test <arg>` 的 arg 当正则表达式处理,
    Windows 风格的反斜杠会被当成转义符吃掉(如 `\\t` `\\n`),导致 "No tests found"。
    """
    suffix = Path(script_relative_path).suffix.lower()
    rel_posix = script_relative_path.replace("\\", "/")
    if suffix in (".yaml", ".yml"):
        return f'npx --yes @midscene/cli run "{rel_posix}"'
    return f'npx --yes playwright test "{rel_posix}"'


# ============================================================================
# 配置兜底:从 API 业务的 YAML 配置回退取 base_url / 登录凭据
# ============================================================================
# 设计意图:
#   API 自动化业务在 generated_tests/automation/core/config/{settings.yaml, env/*.yaml}
#   里已经维护了 api.base_url + auth.username/password,UI 自动化跟它跑的是同一台被测系统、
#   同一个登录账号 —— 没必要让用户去 .env 重新填一份。
#
#   优先级:.env(settings.UI_BASE_URL/UI_LOGIN_*) > YAML(api.base_url/auth.*) > 空
#   .env 显式给了就用 .env(留个紧急覆盖口),否则自动回退到 YAML,两边都没就维持空字符串
#   (playwright.config.ts 那一侧自己看 baseURL=undefined 会怎样处理)。
#
#   失败不抛 —— YAML 缺失/语法错误 → 走 .env 那条线,不阻塞 UI 执行流程。

_API_YAML_CONFIG_CACHE: Optional[dict] = None


def _load_api_yaml_config() -> dict:
    """加载 generated_tests/automation/core/config 的合并配置。

    缓存到模块级变量,执行多个 UI 用例不重复 IO。返回 {} 表示加载失败/无可用配置。
    """
    global _API_YAML_CONFIG_CACHE
    if _API_YAML_CONFIG_CACHE is not None:
        return _API_YAML_CONFIG_CACHE

    try:
        # generated_tests 与 backend 同级 (或在 backend 下,看 UI_AUTOMATION_WORKSPACE 怎么走)
        # 不依赖 UI_AUTOMATION_WORKSPACE —— 它指 UI 的 generated_ui_tests,跟 API 配置无关
        backend_root = Path(__file__).resolve().parents[3]  # services/ui_automation/execution_service.py → backend/
        cfg_dir = backend_root / "generated_tests" / "automation" / "core" / "config"
        if not cfg_dir.exists():
            _API_YAML_CONFIG_CACHE = {}
            return _API_YAML_CONFIG_CACHE

        # 复用 generated_tests 自己的 loader —— 它已经处理了多层 merge + AUTOMATION_* 环境变量覆盖
        import importlib.util
        loader_path = cfg_dir / "loader.py"
        spec = importlib.util.spec_from_file_location("_api_automation_config_loader", loader_path)
        if not spec or not spec.loader:
            _API_YAML_CONFIG_CACHE = {}
            return _API_YAML_CONFIG_CACHE
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg = mod.Config().load()  # 内部读 AUTOMATION_ENV,默认 test
        _API_YAML_CONFIG_CACHE = cfg.to_dict()
        logger.debug(f"已从 API YAML 加载兜底配置: env={cfg.env}")
        return _API_YAML_CONFIG_CACHE
    except Exception as e:
        logger.warning(f"加载 API YAML 配置失败,UI 子进程将只用 .env: {e}")
        _API_YAML_CONFIG_CACHE = {}
        return _API_YAML_CONFIG_CACHE


async def _resolve_ui_base_url() -> str:
    """UI baseURL 解析优先级:
        DB 激活环境.ui_base_url > settings.UI_BASE_URL > YAML api.base_url > 空串

    async 化：需要读 DB 激活环境。调用方 _build_env 已在 async 上下文里。
    """
    # 第一优先级：DB 激活环境
    try:
        from app.services.environment_service import get_active_environment
        active_env = await get_active_environment()
        if active_env and active_env.ui_base_url:
            # 兜底 rstrip 末尾 /，避免拼路径出现 //（老数据兼容）
            return active_env.ui_base_url.rstrip("/")
    except Exception:
        pass  # DB 读失败则继续 fallback

    if settings.UI_BASE_URL:
        return settings.UI_BASE_URL
    cfg = _load_api_yaml_config()
    return (cfg.get("api", {}) or {}).get("base_url", "") or ""


async def _resolve_ui_login_credentials() -> Dict[str, str]:
    """UI 登录凭据解析优先级:
        DB 激活环境 > settings.UI_LOGIN_* > YAML auth.* > 空串

    auth.setup.ts 实际上会用 UI_LOGIN_URL 作为登录页地址,通常跟 baseURL 同源即可。
    """
    # 第一优先级：DB 激活环境
    active_env = None
    try:
        from app.services.environment_service import get_active_environment
        active_env = await get_active_environment()
    except Exception:
        pass

    yaml_cfg = _load_api_yaml_config()
    auth = yaml_cfg.get("auth", {}) or {}
    api_section = yaml_cfg.get("api", {}) or {}

    def _pick(db_val: str, env_val: str, yaml_val: str) -> str:
        # 三层优先级：DB > .env > YAML
        return db_val or env_val or yaml_val or ""

    return {
        "UI_LOGIN_URL": _pick(
            active_env.ui_login_url if active_env else "",
            settings.UI_LOGIN_URL,
            api_section.get("base_url", ""),
        ),
        "UI_LOGIN_USER": _pick(
            active_env.username if active_env else "",
            settings.UI_LOGIN_USERNAME,
            auth.get("username", ""),
        ),
        "UI_LOGIN_PASS": _pick(
            active_env.password if active_env else "",
            settings.UI_LOGIN_PASSWORD,
            auth.get("password", ""),
        ),
    }


async def _build_env(workspace_paths: Dict[str, str], extra_env: Optional[Dict[str, str]]) -> Dict[str, str]:
    env = os.environ.copy()
    env["PW_OUTPUT_DIR"] = workspace_paths["test_results_dir"]
    env["PW_HTML_REPORT_DIR"] = workspace_paths["html_report_dir"]
    env["PW_JSON_REPORT_FILE"] = workspace_paths["json_report_file"]
    # allure-playwright reporter 写入目录（每次执行都写，后端按需 generate 用）
    env["PW_ALLURE_RESULTS_DIR"] = workspace_paths["allure_results_dir"]
    env["UI_HEADLESS"] = "true" if settings.UI_HEADLESS else "false"

    # baseURL 兜底:.env 没填就回退到 API 业务 YAML 的 api.base_url
    base_url = await _resolve_ui_base_url()
    if base_url:
        env["UI_BASE_URL"] = base_url

    # 登录凭据兜底:.env 没填就回退到 API 业务 YAML 的 auth.username/password
    # auth.setup.ts 直接读这三个,不在则用 setup 内的硬编码默认值
    for k, v in (await _resolve_ui_login_credentials()).items():
        if v:
            env[k] = v

    # 单 test 超时(秒 → 毫秒): 透传给 playwright.config.ts 的 timeout 字段,
    # 控制 setup 用例 / 业务用例各自能跑多久。子进程总超时由
    # settings.UI_PLAYWRIGHT_SUBPROCESS_TIMEOUT 单独控制,见 run_playwright_script。
    env["UI_PLAYWRIGHT_TIMEOUT_MS"] = str(int((settings.UI_PLAYWRIGHT_TIMEOUT or 120) * 1000))
    # 避免 npm/pnpm 在没有 TTY 时的进度条把输出弄乱
    env["CI"] = "1"
    env["FORCE_COLOR"] = "0"
    # Windows 子进程默认 GBK,Node/Playwright/MidScene 写中文日志会落成 cp936,
    # Python 端用 utf-8 解码就乱码。强制 utf-8 + chcp 65001 与原 ui-automation 项目对齐。
    env["PYTHONIOENCODING"] = "utf-8"
    env["CHCP"] = "65001"

    # ---- MidScene LLM 配置 -----------------------------------------------
    # MidScene.js (>=0.16) 在 fixture.ts/aiAssert/aiWaitFor 内部直接读 process.env,
    # 没找到 OPENAI_API_KEY/OPENAI_BASE_URL/MIDSCENE_MODEL_NAME 就会抛
    # "Cannot find config for AI model"。
    #
    # 必须用 VLM(视觉大模型) —— aiTap/aiInput 在运行时会把当前页面截图发给模型
    # 让它返回元素坐标,文本模型(deepseek-v4-pro 等推理模型)接不了图,会报
    # "401 The API key format is incorrect" 之类的误导性错误。对齐原 ui-automation
    # 项目的做法:配豆包 UI-TARS 或通义 QwenVL。
    #
    # 配置优先级:UI_MIDSCENE_*(专用) > DOUBAO_*(视觉)。不再回退到通用 LLM_* ——
    # 那样会悄悄用非 VLM 模型,问题难排查,不如直接报错让用户去 .env 里补。
    midscene_key = settings.UI_MIDSCENE_API_KEY or settings.DOUBAO_API_KEY
    midscene_base = settings.UI_MIDSCENE_BASE_URL or settings.DOUBAO_BASE_URL
    midscene_model = settings.UI_MIDSCENE_MODEL_NAME or settings.DOUBAO_VISION_MODEL

    if not (midscene_key and midscene_base and midscene_model):
        raise RuntimeError(
            "MidScene VLM 配置缺失 —— 请在 .env 中填写 UI_MIDSCENE_API_KEY/BASE_URL/MODEL_NAME "
            "或 DOUBAO_API_KEY/BASE_URL/VISION_MODEL(必须是视觉大模型,如 qwen3-vl-flash / "
            "doubao-1-5-ui-tars-250428,不能用 deepseek 等纯文本模型)。"
            f"当前: key={'OK' if midscene_key else 'EMPTY'}, "
            f"base={midscene_base or 'EMPTY'}, model={midscene_model or 'EMPTY'}"
        )

    env["OPENAI_API_KEY"] = midscene_key
    env["OPENAI_BASE_URL"] = midscene_base
    env["MIDSCENE_MODEL_NAME"] = midscene_model
    # MidScene 对 qwen-vl / ui-tars 视觉模型有专门的坐标解码模式,
    # 通用 OpenAI 协议跑这些模型会丢精度。按模型名前缀自动启用。
    model_lower = midscene_model.lower()
    if "qwen" in model_lower and "vl" in model_lower:
        env.setdefault("MIDSCENE_USE_QWEN_VL", "1")
    elif "ui-tars" in model_lower or "uitars" in model_lower:
        env.setdefault("MIDSCENE_USE_VLM_UI_TARS", "1")
    # 诊断日志:把最终 LLM 注入情况打出来(脱敏),省得下次再卡 Cannot find config
    logger.info(
        f"[exec env] OPENAI_API_KEY=set({len(midscene_key)} chars) "
        f"OPENAI_BASE_URL={midscene_base} "
        f"MIDSCENE_MODEL_NAME={midscene_model} "
        f"USE_QWEN_VL={env.get('MIDSCENE_USE_QWEN_VL', '0')} "
        f"USE_VLM_UI_TARS={env.get('MIDSCENE_USE_VLM_UI_TARS', '0')}"
    )

    # ---- helpers/auth.ts 登录凭证 ----------------------------------------
    if settings.UI_LOGIN_URL:
        env["UI_LOGIN_URL"] = settings.UI_LOGIN_URL
    if settings.UI_LOGIN_USERNAME:
        env["UI_LOGIN_USERNAME"] = settings.UI_LOGIN_USERNAME
    if settings.UI_LOGIN_PASSWORD:
        env["UI_LOGIN_PASSWORD"] = settings.UI_LOGIN_PASSWORD

    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
    return env


# ============================================================================
# 进程组管理(跨平台)
# ============================================================================

def _terminate_process_group_sync(process: subprocess.Popen) -> None:
    """先温和后强硬:SIGTERM/CTRL_BREAK → 等 5s → SIGKILL。

    POSIX: 杀整个 process group,清理 node + Chromium 派生进程
    Windows: send_signal(CTRL_BREAK_EVENT) → 进程组都收到
    """
    if process.poll() is not None:
        return

    try:
        if sys.platform == "win32":
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            except (ValueError, OSError):
                process.terminate()
        else:
            try:
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    except Exception as e:
        logger.warning(f"发送 terminate 信号失败 pid={process.pid} err={e}")

    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        if sys.platform == "win32":
            process.kill()
        else:
            try:
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except Exception as e:
        logger.warning(f"强杀进程组失败 pid={process.pid} err={e}")

    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        logger.error(f"子进程拒绝退出 pid={process.pid}")


# ============================================================================
# 主入口
# ============================================================================

ProgressCallback = Callable[[ExecutionProgress], Awaitable[None]]


async def run_playwright_script(
    *,
    execution_id: str,
    script_relative_path: str,
    timeout_seconds: Optional[int] = None,
    extra_env: Optional[Dict[str, str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> ExecutionResult:
    """执行单个 Playwright/MidScene 脚本。

    Args:
        execution_id: 业务方提供的唯一 id(uuid4().hex 即可),用作目录名 + 取消 key
        script_relative_path: 相对 UI_AUTOMATION_WORKSPACE 的脚本路径,如 "scripts/test_login.spec.ts"
        timeout_seconds: 超过则杀进程组,返回 status=timeout;None 时取 settings.UI_PLAYWRIGHT_TIMEOUT
        extra_env: 追加注入子进程的环境变量
        progress_callback: 异步回调,跑完后逐行回灌一次(对齐原 ui-automation 项目)
    """
    start_ns = time.perf_counter_ns()

    async def _emit(progress: ExecutionProgress) -> None:
        if progress_callback is None:
            return
        try:
            await progress_callback(progress)
        except Exception as cb_err:
            logger.warning(f"progress_callback 抛异常,忽略 err={cb_err}")

    await _emit(ExecutionProgress(phase="queued", elapsed_ms=0))

    sem = _get_semaphore()
    async with sem:
        elapsed_ms = lambda: int((time.perf_counter_ns() - start_ns) / 1_000_000)
        await _emit(ExecutionProgress(phase="preparing", elapsed_ms=elapsed_ms()))

        # --- 1. 校验脚本路径 ---
        try:
            _validate_script_path(script_relative_path)
        except (ValueError, FileNotFoundError) as e:
            return ExecutionResult(
                execution_id=execution_id,
                status="error",
                exit_code=None,
                duration_ms=elapsed_ms(),
                stdout="",
                stderr="",
                error_message=f"脚本路径校验失败: {e}",
            )

        # --- 2. 准备隔离工作区 ---
        try:
            paths = _prepare_workspace(execution_id)
        except OSError as e:
            return ExecutionResult(
                execution_id=execution_id,
                status="error",
                exit_code=None,
                duration_ms=elapsed_ms(),
                stdout="",
                stderr="",
                error_message=f"工作区创建失败: {e}",
            )

        command_str = _build_command_str(script_relative_path)
        try:
            env = await _build_env(paths, extra_env)
        except RuntimeError as e:
            return ExecutionResult(
                execution_id=execution_id,
                status="error",
                exit_code=None,
                duration_ms=elapsed_ms(),
                stdout="",
                stderr="",
                error_message=str(e),
                workspace_dir=paths["workspace_dir"],
                html_report_dir=paths["html_report_dir"],
                json_report_file=paths["json_report_file"],
                log_file=paths["log_file"],
                workspace_relative=paths["workspace_relative"],
            )
        workspace = Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
        # 子进程总超时(controls Popen.communicate 杀进程组的时机)
        # 不能复用 UI_PLAYWRIGHT_TIMEOUT —— 那是单 test 超时,给 playwright.config.ts 用。
        # 之前耦合一个值时,setup 慢就把业务用例时间挤掉甚至直接被杀。
        timeout = (
            timeout_seconds if timeout_seconds and timeout_seconds > 0
            else settings.UI_PLAYWRIGHT_SUBPROCESS_TIMEOUT
        )

        logger.info(
            f"[exec {execution_id}] starting cmd={command_str} cwd={workspace} timeout={timeout}s"
        )

        await _emit(ExecutionProgress(phase="running", elapsed_ms=elapsed_ms()))

        # --- 3. 同步 Popen + communicate(timeout) 丢线程池跑 ---
        # shell=True 让 Windows 自动解析 npx → npx.cmd;同时避开
        # asyncio.create_subprocess_exec 在 SelectorEventLoop(uvicorn --reload worker)
        # 下不被支持的问题。
        _cancel_flags.setdefault(execution_id, False)

        def _run_sync() -> Dict[str, object]:
            popen_kwargs: Dict[str, object] = {
                "shell": True,
                "cwd": str(workspace),
                "env": env,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True

            try:
                proc = subprocess.Popen(command_str, **popen_kwargs)  # type: ignore[arg-type]
            except FileNotFoundError as fe:
                return {
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "timeout": False,
                    "start_error": f"未找到 npx,请先 bash setup_ui_runtime.sh 安装 Node.js + 依赖 ({fe})",
                }
            except OSError as oe:
                return {
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "timeout": False,
                    "start_error": f"启动子进程失败: {oe}",
                }

            _running_processes[execution_id] = proc
            try:
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                    return {
                        "exit_code": proc.returncode,
                        "stdout": stdout or "",
                        "stderr": stderr or "",
                        "timeout": False,
                        "start_error": "",
                    }
                except subprocess.TimeoutExpired:
                    _terminate_process_group_sync(proc)
                    try:
                        stdout, stderr = proc.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        stdout, stderr = "", ""
                    return {
                        "exit_code": proc.returncode if proc.returncode is not None else -1,
                        "stdout": stdout or "",
                        "stderr": stderr or "",
                        "timeout": True,
                        "start_error": "",
                    }
            finally:
                _running_processes.pop(execution_id, None)

        try:
            raw = await asyncio.to_thread(_run_sync)
        except asyncio.CancelledError:
            # 协程被外部取消 —— 顺手把子进程也终结掉
            proc = _running_processes.get(execution_id)
            if proc is not None:
                _terminate_process_group_sync(proc)
            _cancel_flags.pop(execution_id, None)
            raise

        start_error = str(raw.get("start_error") or "")
        stdout_text = str(raw.get("stdout") or "")
        stderr_text = str(raw.get("stderr") or "")
        exit_code = raw.get("exit_code")  # type: ignore[assignment]
        if not isinstance(exit_code, int) and exit_code is not None:
            exit_code = None  # type: ignore[assignment]
        timeout_hit = bool(raw.get("timeout"))

        cancelled_hit = bool(_cancel_flags.pop(execution_id, False))

        # --- 4. 跑完后逐行回灌(对齐原 ui-automation 项目的批量推送) ---
        for line in stdout_text.splitlines():
            await _emit(ExecutionProgress(
                phase="running", line=line, stream="stdout", elapsed_ms=elapsed_ms(),
            ))
        for line in stderr_text.splitlines():
            await _emit(ExecutionProgress(
                phase="running", line=line, stream="stderr", elapsed_ms=elapsed_ms(),
            ))

        # --- 5. 收尾 + 落 log ---
        await _emit(ExecutionProgress(phase="finishing", elapsed_ms=elapsed_ms()))

        if start_error:
            return ExecutionResult(
                execution_id=execution_id,
                status="error",
                exit_code=None,
                duration_ms=elapsed_ms(),
                stdout="",
                stderr="",
                error_message=start_error,
                workspace_dir=paths["workspace_dir"],
                html_report_dir=paths["html_report_dir"],
                json_report_file=paths["json_report_file"],
                log_file=paths["log_file"],
                workspace_relative=paths["workspace_relative"],
            )

        status: ExecutionStatus
        error_message = ""
        if cancelled_hit:
            status = "cancelled"
            error_message = "执行被外部取消"
        elif timeout_hit:
            status = "timeout"
            error_message = f"执行超过 {timeout}s 被强制终止"
        elif exit_code == 0:
            status = "success"
        else:
            status = "failed"
            error_message = f"子进程退出码 {exit_code}"

        from app.services.ui_automation.report_service import write_combined_log
        log_path = write_combined_log(
            paths["workspace_dir"],
            stdout_text,
            stderr_text,
        )

        result = ExecutionResult(
            execution_id=execution_id,
            status=status,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            duration_ms=elapsed_ms(),
            stdout=stdout_text,
            stderr=stderr_text,
            error_message=error_message,
            workspace_dir=paths["workspace_dir"],
            html_report_dir=paths["html_report_dir"],
            json_report_file=paths["json_report_file"],
            log_file=log_path,
            workspace_relative=paths["workspace_relative"],
        )

        logger.info(
            f"[exec {execution_id}] finished status={status} exit={exit_code} "
            f"duration={result.duration_ms}ms"
        )
        return result


# ============================================================================
# 取消
# ============================================================================

async def cancel_execution(execution_id: str) -> bool:
    """请求取消一次执行。

    返回值:True = 找到目标进程并发出了终止信号;False = 没找到(可能已结束)
    """
    process = _running_processes.get(execution_id)
    if process is None:
        return False
    _cancel_flags[execution_id] = True
    logger.info(f"[exec {execution_id}] cancel requested, terminating process group")
    await asyncio.to_thread(_terminate_process_group_sync, process)
    return True


def list_running_execution_ids() -> List[str]:
    """诊断 / 启动自愈用:当前活跃执行 id。"""
    return list(_running_processes.keys())


__all__ = [
    "ExecutionProgress",
    "ExecutionResult",
    "ExecutionStatus",
    "ProgressCallback",
    "run_playwright_script",
    "cancel_execution",
    "list_running_execution_ids",
]
