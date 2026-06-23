"""
Playwright codegen 录制子进程服务

职责(纯框架,不依赖 Agent / DB):
  1. 准备产物路径         generated_ui_tests/recordings/<safe_id>.spec.ts
  2. 子进程编排           shell="npx playwright codegen --target=playwright-test --output=... <url>"
                          via asyncio.to_thread + subprocess.Popen
  3. 头模式启动浏览器       codegen 必须 GUI —— 浏览器弹窗在后端所在机器显示
  4. 超时 + 取消          kill 整个进程组
  5. 路径沙箱             output 必须落在 UI_AUTOMATION_WORKSPACE/UI_RECORDING_RAW_SUBDIR 下
  6. 登录态复用           --load-storage=.auth/user.json 跳过登录页

不做的事:
  - 不落 DB(由 UiRecordingOrchestratorAgent 负责)
  - 不发 SSE(由 Agent 包一层后投递)
  - 不做 AI 后处理(由 RECORDING_POSTPROCESS_PROMPT 负责)

设计参照: execution_service.py 同源风格 —— subprocess.Popen + shell=True + asyncio.to_thread,
避开 SelectorEventLoop 的 subprocess 限制,跨平台进程组管理。

约束:
  录制本质需要 GUI —— 部署在无头服务器上 codegen 会直接报 "Cannot launch browser in headed mode";
  设计上仅支持后端跟前端在同一台机器(开发机/桌面机)的部署模式。
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
from typing import Dict, Literal, Optional

from loguru import logger

from app.settings.config import settings


# ============================================================================
# 数据结构
# ============================================================================

CodegenStatus = Literal["success", "failed", "timeout", "cancelled", "error"]


@dataclass
class CodegenResult:
    session_id: str
    status: CodegenStatus
    exit_code: Optional[int]
    duration_ms: int
    stdout: str
    stderr: str
    error_message: str = ""
    raw_script_path: str = ""  # 录制原始脚本相对 UI_AUTOMATION_WORKSPACE 的路径
    raw_script_content: str = ""  # 直接读出来的脚本内容(供 AI 后处理用)


# ============================================================================
# 模块内状态
# ============================================================================

_running_processes: Dict[str, subprocess.Popen] = {}
_cancel_flags: Dict[str, bool] = {}

_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]")


def _safe_id(session_id: str) -> str:
    """把任意字符串转成可作文件名的安全 id。

    Why: uvicorn --reload 在监听 .py 结尾目录时会触发重启杀子进程(见
    project_uvicorn_reload_pyext_trap 记忆),所以坚决禁止任何点号 / 路径分隔符。
    """
    sid = _SAFE_ID_PATTERN.sub("_", session_id or "anon")
    return sid[:64] or "anon"


# ============================================================================
# 路径准备
# ============================================================================

def _prepare_output_path(session_id: str) -> Dict[str, str]:
    """计算并创建录制产物目录。

    返回:
        recordings_dir: 录制产物目录绝对路径
        output_abs: 录制产物绝对路径
        output_rel: 录制产物相对 workspace 的路径(正斜杠,供入库)
        safe_id: 文件名用的安全 id
    """
    safe = _safe_id(session_id)
    workspace = Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
    rec_dir = workspace / settings.UI_RECORDING_RAW_SUBDIR
    rec_dir.mkdir(parents=True, exist_ok=True)

    output_abs = rec_dir / f"{safe}.spec.ts"
    output_rel = (Path(settings.UI_RECORDING_RAW_SUBDIR) / f"{safe}.spec.ts").as_posix()

    return {
        "recordings_dir": str(rec_dir),
        "output_abs": str(output_abs),
        "output_rel": output_rel,
        "safe_id": safe,
    }


def _validate_storage_state(storage_rel: str) -> Optional[Path]:
    """校验 storage state 文件,返回绝对路径(不存在/越界返回 None)。

    storage_rel: 相对 UI_AUTOMATION_WORKSPACE 的路径,默认 ".auth/user.json"
    """
    if not storage_rel:
        return None
    if ".." in Path(storage_rel).parts:
        logger.warning(f"storage_state 路径含 '..',拒绝: {storage_rel}")
        return None
    if os.path.isabs(storage_rel):
        logger.warning(f"storage_state 必须是相对路径: {storage_rel}")
        return None

    workspace = Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
    candidate = (workspace / storage_rel).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError:
        logger.warning(f"storage_state 逃逸出 workspace: {storage_rel}")
        return None

    if not candidate.exists():
        logger.info(f"storage_state 文件不存在,将从登录页开始录制: {candidate}")
        return None

    return candidate


# ============================================================================
# 命令构造
# ============================================================================

def _build_codegen_command(
    target_url: str,
    output_rel: str,
    storage_state_abs: Optional[Path],
    save_storage_abs: Optional[Path] = None,
) -> str:
    """构造 codegen shell 命令。

    Playwright CLI 把 --output 参数当文件路径处理,Windows 路径分隔符不踩 regex 坑,
    但仍然统一用正斜杠保持跨平台一致。

    storage_state_abs / save_storage_abs:
      - load-storage 读入旧登录态(允许 None,从登录页开始录)
      - save-storage 是必须的 —— 录制结束(关闭浏览器)时 Playwright 会把当前
        cookies + localStorage 一并 dump 到这里。**不传 --save-storage 等于录了白录**:
        用户在浏览器里登录了 sessionId 也不会落盘,user.json 永远是旧的,
        下次跑业务页直接 401(2026-06-18 排查 storage_state 失效定位到这里)。
    """
    out = output_rel.replace("\\", "/")
    parts = [
        "npx --yes playwright codegen",
        f'--target=playwright-test',
        f'--output="{out}"',
        # 自签证书 / 内网 HTTPS 业务站点常见 —— 不加这个参数
        # Chromium 会用 NET::ERR_CERT_AUTHORITY_INVALID 拦死,codegen 直接 exit 1
        '--ignore-https-errors',
    ]
    if storage_state_abs is not None:
        storage_posix = str(storage_state_abs).replace("\\", "/")
        parts.append(f'--load-storage="{storage_posix}"')

    if save_storage_abs is not None:
        save_posix = str(save_storage_abs).replace("\\", "/")
        parts.append(f'--save-storage="{save_posix}"')

    # URL 放最后(positional arg)
    parts.append(f'"{target_url}"')
    return " ".join(parts)


def _build_env(extra_env: Optional[Dict[str, str]]) -> Dict[str, str]:
    """录制子进程的环境变量。

    codegen 不依赖 MidScene / LLM,所以不需要注入 OPENAI_API_KEY 那一套。
    只设字符编码 + 关掉 npm 进度条。
    """
    env = os.environ.copy()
    env["CI"] = "1"
    env["FORCE_COLOR"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env["CHCP"] = "65001"
    # codegen 强制需要 GUI —— 显式标注,后续若有 headless 检查可读这个变量
    env.pop("PLAYWRIGHT_HEADLESS", None)

    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
    return env


# ============================================================================
# 进程组管理(跨平台,逻辑与 execution_service 对齐)
# ============================================================================

def _terminate_process_group_sync(process: subprocess.Popen) -> None:
    """先温和后强硬:SIGTERM/CTRL_BREAK → 等 5s → SIGKILL。"""
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
        logger.error(f"codegen 子进程拒绝退出 pid={process.pid}")


# ============================================================================
# 主入口
# ============================================================================

async def run_codegen(
    *,
    session_id: str,
    target_url: str,
    storage_state_relpath: str = "",
    timeout_seconds: Optional[int] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> CodegenResult:
    """启动 Playwright codegen 录制。

    阻塞到用户关闭浏览器窗口(或 timeout) —— 调用方应在 asyncio 任务里 await,
    并在前端给用户"录制中,请操作完后关闭浏览器"的提示。

    Args:
        session_id: 业务方提供的唯一 id(uuid4().hex),用于文件名 + 取消 key
        target_url: 录制目标 URL,作为 codegen 启动 URL
        storage_state_relpath: 登录态文件相对 UI_AUTOMATION_WORKSPACE 路径,
            如 ".auth/user.json";留空或文件不存在则从登录页开始录
        timeout_seconds: 录制超时,默认 settings.UI_RECORDING_TIMEOUT (30 分钟)
        extra_env: 额外环境变量(预留)

    Returns:
        CodegenResult,status=success 时 raw_script_content 含录制脚本文本
    """
    start_ns = time.perf_counter_ns()
    elapsed_ms = lambda: int((time.perf_counter_ns() - start_ns) / 1_000_000)

    # 1. 准备路径
    try:
        paths = _prepare_output_path(session_id)
    except OSError as e:
        return CodegenResult(
            session_id=session_id, status="error", exit_code=None,
            duration_ms=elapsed_ms(), stdout="", stderr="",
            error_message=f"录制目录创建失败: {e}",
        )

    storage_abs = _validate_storage_state(
        storage_state_relpath or settings.UI_RECORDING_DEFAULT_STORAGE_STATE
    )

    # save-storage 目标:默认就是同一个文件(录完覆盖回去,sessionId 刷新)
    # 注意:_validate_storage_state 要求"文件存在"才返回路径,save 场景下文件可能还不存在,
    # 所以这里独立算一份目标路径,且自动 mkdir 父目录,Playwright codegen 关闭时才写文件。
    save_abs: Optional[Path] = None
    save_relpath = storage_state_relpath or settings.UI_RECORDING_DEFAULT_STORAGE_STATE
    if save_relpath:
        try:
            workspace_root = Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
            candidate = (workspace_root / save_relpath).resolve()
            candidate.relative_to(workspace_root)  # 沙箱
            candidate.parent.mkdir(parents=True, exist_ok=True)
            save_abs = candidate
        except ValueError:
            logger.warning(f"save-storage 逃逸出 workspace,跳过: {save_relpath}")
        except Exception as e:
            logger.warning(f"save-storage 准备目录失败,跳过: {e}")

    # 2. 构造命令
    command_str = _build_codegen_command(
        target_url=target_url,
        output_rel=paths["output_rel"],
        storage_state_abs=storage_abs,
        save_storage_abs=save_abs,
    )
    env = _build_env(extra_env)

    workspace = Path(settings.UI_AUTOMATION_WORKSPACE).resolve()
    timeout = timeout_seconds if timeout_seconds and timeout_seconds > 0 else settings.UI_RECORDING_TIMEOUT

    logger.info(
        f"[codegen {session_id}] starting cmd={command_str} cwd={workspace} "
        f"timeout={timeout}s load_storage={'OK' if storage_abs else 'NONE'} "
        f"save_storage={save_abs or 'NONE'}"
    )

    # 3. 同步 Popen 丢线程池
    _cancel_flags.setdefault(session_id, False)

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
                "exit_code": None, "stdout": "", "stderr": "",
                "timeout": False,
                "start_error": f"未找到 npx,请先安装 Node.js + pnpm install ({fe})",
            }
        except OSError as oe:
            return {
                "exit_code": None, "stdout": "", "stderr": "",
                "timeout": False,
                "start_error": f"启动子进程失败: {oe}",
            }

        _running_processes[session_id] = proc
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
            _running_processes.pop(session_id, None)

    try:
        raw = await asyncio.to_thread(_run_sync)
    except asyncio.CancelledError:
        proc = _running_processes.get(session_id)
        if proc is not None:
            _terminate_process_group_sync(proc)
        _cancel_flags.pop(session_id, None)
        raise

    start_error = str(raw.get("start_error") or "")
    stdout_text = str(raw.get("stdout") or "")
    stderr_text = str(raw.get("stderr") or "")
    exit_code = raw.get("exit_code")
    if not isinstance(exit_code, int) and exit_code is not None:
        exit_code = None  # type: ignore[assignment]
    timeout_hit = bool(raw.get("timeout"))
    cancelled_hit = bool(_cancel_flags.pop(session_id, False))

    # 4. 决定状态
    if start_error:
        return CodegenResult(
            session_id=session_id, status="error", exit_code=None,
            duration_ms=elapsed_ms(), stdout="", stderr="",
            error_message=start_error,
            raw_script_path=paths["output_rel"],
        )

    status: CodegenStatus
    error_message = ""
    if cancelled_hit:
        status = "cancelled"
        error_message = "录制被用户取消"
    elif timeout_hit:
        status = "timeout"
        error_message = f"录制超过 {timeout}s 被强制终止"
    elif exit_code == 0:
        status = "success"
    else:
        status = "failed"
        error_message = f"codegen 退出码 {exit_code}"

    # 5. 读出脚本内容(只有 success/timeout/cancelled 才尝试读 —— 用户可能录到一半关浏览器,
    #    Playwright 仍会把已记录步骤写入 output 文件)
    raw_content = ""
    output_abs = Path(paths["output_abs"])
    if output_abs.exists():
        try:
            raw_content = output_abs.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"读取录制产物失败: {e}")
            raw_content = ""
        else:
            # 文件存在但内容为空 —— 用户立刻关窗口没操作
            if not raw_content.strip() and status == "success":
                status = "failed"
                error_message = "录制产物为空 —— 浏览器关闭前未捕获到任何操作"

    if status == "success" and not output_abs.exists():
        # codegen 居然 exit_code=0 但没文件,只见过 --output 路径异常时出现
        status = "failed"
        error_message = "codegen 返回成功但产物文件未生成"

    logger.info(
        f"[codegen {session_id}] finished status={status} exit={exit_code} "
        f"duration={elapsed_ms()}ms script_size={len(raw_content)}"
    )

    return CodegenResult(
        session_id=session_id,
        status=status,
        exit_code=exit_code if isinstance(exit_code, int) else None,
        duration_ms=elapsed_ms(),
        stdout=stdout_text,
        stderr=stderr_text,
        error_message=error_message,
        raw_script_path=paths["output_rel"],
        raw_script_content=raw_content,
    )


# ============================================================================
# 取消
# ============================================================================

async def cancel_codegen(session_id: str) -> bool:
    """请求取消一次录制(温和地把 codegen 浏览器窗口关掉)。

    返回值:True = 找到目标进程并发出了终止信号;False = 没找到
    """
    process = _running_processes.get(session_id)
    if process is None:
        return False
    _cancel_flags[session_id] = True
    logger.info(f"[codegen {session_id}] cancel requested, terminating process group")
    await asyncio.to_thread(_terminate_process_group_sync, process)
    return True


def list_running_codegen_ids() -> list[str]:
    """诊断用:当前活跃录制 session_id。"""
    return list(_running_processes.keys())


__all__ = [
    "CodegenResult",
    "CodegenStatus",
    "run_codegen",
    "cancel_codegen",
    "list_running_codegen_ids",
]
