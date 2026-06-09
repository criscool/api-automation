"""清理 bug 2 演示残留的 "test新增策略"

bug 2 让 step 12 用 PUT 调 delete 接口（405），导致新增的策略没被删掉，
后续重跑会在 step 7 add 时撞名报 ApiError。这个脚本一次性清干净。

复用 generated_tests/ 的鉴权 + client，与原脚本走的同一接口，零侵入。
"""
import sys
from pathlib import Path

# 让 import automation.* 可用
GENERATED_TESTS_DIR = Path(__file__).resolve().parents[2] / "generated_tests"
sys.path.insert(0, str(GENERATED_TESTS_DIR))

from automation.core.config.loader import config as app_cfg
from automation.api.modules.login_api import login
from automation.api.client.base_client import BaseClient

STRATEGY_NAME = "test新增策略"


def main():
    app_cfg.load(env="test")
    print(f"base_url = {app_cfg.api.base_url}")

    login_resp = login()
    if login_resp.get("code"):
        print(f"登录失败: {login_resp}")
        return 1
    print("登录成功")

    client = BaseClient()

    # 1. 查询同名策略
    list_url = "/api/plugins/com.andisec.plugins.strategy/strategy/list"
    resp = client.post(list_url, json={
        "page": 1, "per_page": 1000, "query": "", "fullText": STRATEGY_NAME, "order": {},
    })
    print(f"list status={resp.status_code}")
    data = resp.json().get("data") or {}
    items = data.get("list") or []
    matched = [it for it in items if it.get("strategy_name") == STRATEGY_NAME]
    print(f"匹配到 {len(matched)} 条 strategy_name='{STRATEGY_NAME}'")

    if not matched:
        print("无残留，无需清理")
        return 0

    ids = [it.get("_id") for it in matched if it.get("_id")]
    print(f"待删 _id: {ids}")

    # 2. POST delete（脚本主导方法，不是 PUT）
    del_url = "/api/plugins/com.andisec.plugins.strategy/strategy/delete"
    resp = client.post(del_url, json={"entities": ids})
    body = resp.json() if resp.content else {}
    print(f"delete status={resp.status_code} body.type={body.get('type')}")

    # 3. 复查
    resp = client.post(list_url, json={
        "page": 1, "per_page": 1000, "query": "", "fullText": STRATEGY_NAME, "order": {},
    })
    items_after = (resp.json().get("data") or {}).get("list") or []
    remain = [it for it in items_after if it.get("strategy_name") == STRATEGY_NAME]
    print(f"清理后剩 {len(remain)} 条")
    return 0 if not remain else 1


if __name__ == "__main__":
    sys.exit(main())
