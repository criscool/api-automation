"""
远程录制守护进程 — 常驻本地后台，接收后端 WebSocket 指令启动本地 codegen。

用法:
    cd mcp-playwright
    python record-daemon.py --server https://部署服务器IP &

首次运行: 无登录态 → 浏览器从登录页开始 → 手动登录 → 关闭浏览器自动保存
后续运行: --load-storage 加载已保存的登录态 → 直接跳到业务页
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
SERVER = None
for i, arg in enumerate(sys.argv):
    if arg == "--server" and i + 1 < len(sys.argv):
        SERVER = sys.argv[i + 1]
        break

if not SERVER:
    print("用法: python record-daemon.py --server https://服务器IP")
    sys.exit(1)

# WebSocket URL: http → ws, https → wss
_ws_server = SERVER.replace("https://", "wss://").replace("http://", "ws://")
WS_URL = f"{_ws_server}/api/v1/ui-automation/ws/recording-daemon"

# 产物目录（相对 mcp-playwright/）
RECORDINGS_DIR = Path("recordings")
STORAGE_FILE = Path(".auth") / "user.json"

# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------


def _check_npx():
    import shutil
    if shutil.which("npx") is None:
        print("[ERROR] 未找到 npx，请先安装 Node.js + Playwright:")
        print("  npm install")
        print("  npx playwright install chromium")
        sys.exit(1)
    print("[OK] npx 可用")


# ---------------------------------------------------------------------------
# 守护进程主逻辑
# ---------------------------------------------------------------------------


async def main():
    _check_npx()
    RECORDINGS_DIR.mkdir(exist_ok=True)
    STORAGE_FILE.parent.mkdir(exist_ok=True)

    print(f"[daemon] 正在连接 {WS_URL} ...")

    # WebSocket 自动重连
    backoff = 1.0
    while True:
        try:
            await _connect_and_serve()
            backoff = 1.0  # 正常断开后快速重连
        except (ConnectionRefusedError, OSError) as e:
            print(f"[daemon] 连接失败 ({e})，{backoff:.0f}s 后重连...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
        except asyncio.CancelledError:
            break


async def _connect_and_serve():
    """建立 WebSocket 连接并处理录制指令。"""
    # 使用标准库或 websockets 库
    try:
        import websockets
    except ImportError:
        print("[ERROR] 缺少 websockets 库，请执行: pip install websockets")
        sys.exit(1)

    async with websockets.connect(WS_URL, ping_interval=30) as ws:
        print(f"[daemon] 已连接到服务器 {SERVER}")
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "record":
                await _run_codegen(ws, msg)
            else:
                print(f"[daemon] 未知消息: {msg}")


async def _run_codegen(ws, msg: dict):
    """启动 Playwright codegen，完成后回传脚本。"""
    session_id = msg["session_id"]
    target_url = msg["target_url"]
    base_dir = Path.cwd()
    output = (base_dir / "recordings" / f"{session_id}.spec.ts").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    storage_state_abs = None
    if msg.get("storage_state_relpath"):
        storage_state_abs = (base_dir / msg["storage_state_relpath"]).resolve()

    print(f"[daemon] 开始录制: {session_id}")
    print(f"[daemon] 目标: {target_url}")
    print(f"[daemon] 输出: {output}")
    print(f"[daemon] 工作目录: {base_dir}")
    print(f"[daemon] 浏览器即将弹出...")

    await _send(ws, {"type": "status", "session_id": session_id, "status": "launching"})

    load_part = f'--load-storage="{storage_state_abs}"' if storage_state_abs and storage_state_abs.exists() else ""
    cmd = (
        f'npx --yes playwright codegen'
        f' --target=playwright-test'
        f' --output="{output}"'
        f' --ignore-https-errors'
        f' --save-storage="{STORAGE_FILE.resolve()}"'
        f' {load_part}'
        f' "{target_url}"'
    )
    print(f"[daemon] 执行: {cmd}")

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(base_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await _send(ws, {"type": "status", "session_id": session_id, "status": "recording"})
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"[daemon] codegen 退出码: {proc.returncode}")
            if stderr:
                print(f"[daemon] stderr: {stderr.decode('utf-8', errors='replace')[:500]}")
    except Exception as e:
        print(f"[daemon] codegen 异常: {e}")
        await _send(ws, {"type": "status", "session_id": session_id, "status": "error"})
        return

    # 读取生成的脚本
    if output.exists():
        content = output.read_text(encoding="utf-8")
        print(f"[daemon] 录制完成: {output} ({len(content)} 字符)")
        await _send(ws, {
            "type": "script",
            "session_id": session_id,
            "content": content,
        })
    else:
        print(f"[daemon] 未找到输出文件: {output}")
        await _send(ws, {"type": "status", "session_id": session_id, "status": "error"})


async def _send(ws, data: dict):
    try:
        await ws.send(json.dumps(data, ensure_ascii=False))
    except Exception:
        print(f"[daemon] WebSocket 发送失败")


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[daemon] 远程录制守护进程启动")
    print(f"[daemon] 服务器: {SERVER}")
    print(f"[daemon] 登录态文件: {STORAGE_FILE.resolve()}")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[daemon] 已退出")
