"""
端到端验证 conftest.py 复用机制 + AST 合并行为。

模拟两份 JSON 文档先后生成测试脚本，验证：
1. 第一份文档：fixture 输出到 conftest.py，test 文件只含测试类
2. 第二份文档：另一组 fixture 合并入同一份 conftest.py
3. test_xxx.py 两份各自合并（已通过之前 verify_merger.py 验证）
"""
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent
MERGER_PATH = ROOT / "app" / "agents" / "api_automation" / "script_merger.py"
spec = importlib.util.spec_from_file_location("script_merger", MERGER_PATH)
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)


# ============================================================
# 场景：两份 JSON 文档分别生成的 conftest 内容
# ============================================================

# 第一份文档（告警.json）生成的 conftest（含 alarm-rule fixture）
conftest_v1 = '''"""共享业务 fixture（由 ScriptGeneratorAgent 自动生成 + 合并）"""
import pytest


@pytest.fixture
def created_post_alarm_rule(api_client):
    """创建告警规则"""
    resp = api_client.post("/api/alarm-rule", json={"title": "x"})
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    resource_id = data["data"].get("id") or data["data"].get("session_id")
    assert resource_id is not None

    yield resource_id

    # teardown: 容忍 404（资源已被测试方法删除是预期场景）
    cleanup_resp = api_client.delete(f"/api/alarm-rule/{resource_id}")
    assert cleanup_resp.status_code in (200, 204, 404), \\
        f"清理失败 id={resource_id}, status={cleanup_resp.status_code}"
'''

# 第二份文档（事件.json）生成的 conftest（含 event fixture）
conftest_v2 = '''"""共享业务 fixture（由 ScriptGeneratorAgent 自动生成 + 合并）"""
import pytest


@pytest.fixture
def created_post_event(api_client):
    """创建事件"""
    resp = api_client.post("/api/event", json={"name": "e"})
    assert resp.status_code == 200
    data = resp.json()
    resource_id = data["data"]["id"]
    assert resource_id is not None

    yield resource_id

    cleanup_resp = api_client.delete(f"/api/event/{resource_id}")
    assert cleanup_resp.status_code in (200, 204, 404)
'''

# 合并
merged = sm.merge_pytest_scripts(conftest_v1, conftest_v2)
print("=" * 60)
print("合并后的 testcases/conftest.py:")
print("=" * 60)
print(merged)
print("=" * 60)

# 验证
tree = ast.parse(merged)
fixtures = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
print("conftest 内 fixture 列表:", fixtures)
assert "created_post_alarm_rule" in fixtures, "第一份的 fixture 应保留"
assert "created_post_event" in fixtures, "第二份的 fixture 应合并进来"
assert merged.count("import pytest") == 1, "import 应去重"
assert "yield" in merged, "应使用 yield 而非 return"
assert "in (200, 204, 404)" in merged, "应有 404 容忍"
print("\n[PASS] 两份 JSON 的业务 fixture 都进入了同一份 conftest.py")


# ============================================================
# 场景：重复上传同一份 JSON（幂等性）
# ============================================================
twice = sm.merge_pytest_scripts(merged, conftest_v1)
tree2 = ast.parse(twice)
fixtures2 = [n.name for n in tree2.body if isinstance(n, ast.FunctionDef)]
assert fixtures2.count("created_post_alarm_rule") == 1, "重复合并应幂等"
assert fixtures2.count("created_post_event") == 1
print("[PASS] 重复合并幂等：fixture 不重复堆叠")
print("\n全部通过")
