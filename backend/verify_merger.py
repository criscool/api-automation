"""
验证 script_merger 的合并行为。

用法（项目根 backend/ 下）:
    python verify_merger.py

不依赖 tortoise / FastAPI / autogen，仅加载 merger 单文件。
"""
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent
MERGER_PATH = ROOT / "app" / "agents" / "api_automation" / "script_merger.py"

spec = importlib.util.spec_from_file_location("script_merger", MERGER_PATH)
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)


def banner(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 场景 1：跨文档合并 —— 告警.json（创建） + 告警1.json（查询+删除）
# ---------------------------------------------------------------------------
first_upload = '''"""alarm 创建接口测试 - 来自 告警.json"""
import pytest

@pytest.fixture
def created_alarm_id(api_client):
    resp = api_client.post("/api/alarm", json={"title": "first"})
    return resp.json()["data"]["id"]

class TestAlarm:
    def test_create_alarm(self, api_client):
        resp = api_client.post("/api/alarm", json={"title": "first"})
        assert resp.status_code == 200
'''

second_upload = '''"""alarm 查询/删除接口测试 - 来自 告警1.json"""
import pytest
import json  # 第二次新增的 import

class TestAlarm:
    def test_list_alarms(self, api_client):
        resp = api_client.get("/api/alarm")
        assert resp.status_code == 200

    def test_delete_alarm(self, api_client, created_alarm_id):
        api_client.delete(f"/api/alarm/{created_alarm_id}")
'''

banner("场景 1：跨文档合并")
print("\n--- 第一次上传后的文件 ---")
print(first_upload)
print("--- 第二次上传时生成的内容（如果不合并就会直接覆盖上面）---")
print(second_upload)
merged = sm.merge_pytest_scripts(first_upload, second_upload)
print("--- AST 合并后的最终文件 ---")
print(merged)

tree = ast.parse(merged)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
methods = [m.name for m in cls.body if isinstance(m, ast.FunctionDef)]
print("最终 class 内方法:", methods)
assert "test_create_alarm" in methods, "第一次的 create 应保留"
assert "test_list_alarms" in methods
assert "test_delete_alarm" in methods
assert merged.count("import pytest") == 1, "import 应去重"
assert "import json" in merged, "新增的 import 应保留"
print("[PASS] 跨文档合并：3 个方法全部保留，imports 已去重")


# ---------------------------------------------------------------------------
# 场景 2：重复上传同一份 JSON —— 验证幂等
# ---------------------------------------------------------------------------
banner("场景 2：重复上传同一份 JSON（幂等性）")
once = sm.merge_pytest_scripts(first_upload, first_upload)
twice = sm.merge_pytest_scripts(once, first_upload)
assert ast.dump(ast.parse(once)) == ast.dump(ast.parse(twice)), "二次合并应稳定"
cls = next(n for n in ast.parse(once).body if isinstance(n, ast.ClassDef))
method_names = [m.name for m in cls.body if isinstance(m, ast.FunctionDef)]
assert method_names.count("test_create_alarm") == 1, "方法不应重复"
print("[PASS] 重复上传：方法数量不会增长，AST 等价")


# ---------------------------------------------------------------------------
# 场景 3：同名方法 —— 新覆盖旧
# ---------------------------------------------------------------------------
banner("场景 3：同名 fixture/方法新覆盖旧")
old = '''import pytest

@pytest.fixture
def created_id(api_client):
    return "OLD_VALUE"

class TestX:
    def test_one(self, api_client):
        assert "OLD_IMPL" == "OLD_IMPL"
'''
new = '''import pytest

@pytest.fixture
def created_id(api_client):
    return "NEW_VALUE"

class TestX:
    def test_one(self, api_client):
        assert "NEW_IMPL" == "NEW_IMPL"
'''
merged3 = sm.merge_pytest_scripts(old, new)
assert "NEW_VALUE" in merged3 and "OLD_VALUE" not in merged3
assert "NEW_IMPL" in merged3 and "OLD_IMPL" not in merged3
print("[PASS] 同名节点：新版替换旧版")


# ---------------------------------------------------------------------------
# 场景 4：语法错误回退
# ---------------------------------------------------------------------------
banner("场景 4：旧文件语法错误时回退")
broken = "def x(:\n  pass"
fallback = sm.merge_pytest_scripts(broken, first_upload)
assert fallback == first_upload
print("[PASS] 语法错误：回退到新覆盖（与原行为一致）")


# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("  全部验证通过")
print("=" * 60)
