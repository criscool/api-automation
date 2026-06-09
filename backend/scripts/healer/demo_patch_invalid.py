"""PATCH_INVALID 演示脚本

不依赖 LLM 输出（LLM 是否产出语法错不可控），直接构造一个 fake HealerSession，
让 patch.fixed_method_code 故意带语法错（缺右括号），然后调 apply_patch：

期望返回：
  status = "PATCH_INVALID"
  applied = False
  verified = False
  heal_failed_count += 1
  DB.last_heal_status = "PATCH_INVALID"
  脚本文件 + DB.content 都不会被改动（fail-fast）
"""
import asyncio
import sys
import time
import uuid
from pathlib import Path

# 确保能 import app.*
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))


async def main():
    from tortoise import Tortoise
    from app.settings import TORTOISE_ORM
    from app.services.api_automation.healer_service import healer_service, HealerSession
    from app.models.api_automation import TestScript

    await Tortoise.init(config=TORTOISE_ORM)

    # 找一条真实脚本
    script = await TestScript.filter(file_path="testcases/test_scenario_modulecrudmodule.py").first()
    if not script:
        print("ERROR: 找不到 testcases/test_scenario_modulecrudmodule.py 的 TestScript 记录")
        return

    before = {
        "heal_attempts": script.heal_attempts,
        "heal_failed_count": script.heal_failed_count,
        "last_heal_status": script.last_heal_status,
        "content_len": len(script.content or ""),
    }
    print("BEFORE:", before)

    # 构造 fake session
    session_id = str(uuid.uuid4())
    session = HealerSession(session_id, script.script_id, None)
    session.status = "DONE"
    session.finished_at = time.time()
    session.result = {
        "verdict": "SCRIPT_FIX",
        "analysis": {"confidence": 0.99, "summary": "fake"},
        "patch": {
            "fixed_method": "test_chain",
            # 故意构造的语法错代码：左括号未闭合
            "fixed_method_code": (
                "    def test_chain(self, api_client):\n"
                "        ctx = {\n"
                "        # 缺右括号 -> SyntaxError\n"
                "        resp = api_client.get('/oops'\n"
                "        return resp\n"
            ),
            "risk_tags": ["demo_patch_invalid"],
        },
        "evidence_summary": {
            "test_case": {"class_name": "TestScenarioModulecrudmodule", "method_name": "test_chain"},
            "script_path": script.file_path,
            "has_useful_signal": True,
        },
    }

    # 注入到单例
    healer_service._sessions[session_id] = session
    print(f"FAKE SESSION ID: {session_id}")

    result = await healer_service.apply_patch(session_id, rerun=False, environment="test")
    print("\n=== apply_patch RESULT ===")
    for k, v in result.items():
        if k == "message":
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {v!r}")

    await script.refresh_from_db()
    after = {
        "heal_attempts": script.heal_attempts,
        "heal_failed_count": script.heal_failed_count,
        "last_heal_status": script.last_heal_status,
        "content_len": len(script.content or ""),
    }
    print("\nAFTER:", after)

    print("\n=== 断言 ===")
    expectations = [
        ("status", result.get("status") == "PATCH_INVALID", "应为 PATCH_INVALID"),
        ("applied", result.get("applied") is False, "未应用"),
        ("verified", result.get("verified") is False, "未验证"),
        ("heal_failed_count++", after["heal_failed_count"] == before["heal_failed_count"] + 1, f"+1 ({before['heal_failed_count']}→{after['heal_failed_count']})"),
        ("content 未变", after["content_len"] == before["content_len"], f"长度 {before['content_len']}={after['content_len']}"),
        ("last_heal_status", after["last_heal_status"] == "PATCH_INVALID", f"={after['last_heal_status']}"),
    ]
    all_ok = True
    for name, ok, msg in expectations:
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {name}: {msg}")
        if not ok:
            all_ok = False

    print("\n" + ("RESULT: ALL OK" if all_ok else "RESULT: SOME CHECKS FAILED"))

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
