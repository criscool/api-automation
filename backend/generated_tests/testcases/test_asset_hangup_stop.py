"""
资产管理学习与启停接口测试
"""
import pytest
import time

pytestmark = [pytest.mark.asset_hangup_stop, pytest.mark.api]


@pytest.fixture(scope="module")
def target_asset(api_client):
    """获取一个真实的资产 ID 用于测试"""
    resp = api_client.post(
        "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list",
        json={"page": 1, "per_page": 1, "query": "", "order": "", "fullText": ""}
    )
    assert resp.status_code == 200
    data = resp.json().get("data", {})
    lst = data.get("list", [])
    if not lst:
        pytest.skip("系统中没有可用资产，跳过启停测试")
    return lst[0]["_id"]


class TestAssetHangupStop:
    """启用资产接口测试"""

    def test_enable_hanged_asset_success(self, api_client, target_asset):
        """
        TC: f2234ad5-a8f0-4964-906b-f5f52f59aaad
        启用已挂停资产 - 正常请求
        """
        # 后端要求 stime 和 etime 不能为空
        payload = {
            "_id": target_asset,
            "stime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "etime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 3600))
        }
        resp = api_client.put(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/hangupandstop",
            json=payload
        )
        assert resp.status_code == 200, f"期望200, 得到{resp.status_code}, 响应: {resp.text}"
        data = resp.json()
        assert data.get("type") == "success"
        assert "修改成功" in data.get("msg", "")

    def test_enable_hanged_asset_verify_status(self, api_client, target_asset):
        """
        TC: eae46148-969f-4818-89aa-3013ac87b58d
        启用已挂停资产 - 验证状态变更
        """
        payload = {
            "_id": target_asset,
            "stime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "etime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 3600))
        }
        resp = api_client.put(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/hangupandstop",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("type") == "success"
        # 返回 data 包含 MongoDB 的 WriteResult 字符串
        assert "n=1" in str(data.get("data", ""))

    def test_enable_asset_response_time(self, api_client, target_asset):
        """
        TC: a9a835bc-0f28-4042-9279-0d5050015333
        启用资产响应时间验证
        """
        payload = {
            "_id": target_asset,
            "stime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "etime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 3600))
        }
        resp = api_client.put(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/hangupandstop",
            json=payload
        )
        assert resp.status_code == 200
        elapsed = resp.elapsed.total_seconds()
        assert elapsed < 5.0, f"响应时间 {elapsed:.3f}s 超过5秒"
        data = resp.json()
        assert data.get("type") == "success"
