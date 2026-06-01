"""
资产管理学习与启停接口测试
"""
import pytest

pytestmark = [pytest.mark.asset_hangup_stop, pytest.mark.api]


class TestAssetHangupStop:
    """启用资产接口测试"""

    def test_enable_hanged_asset_success(self, api_client):
        """
        TC: f2234ad5-a8f0-4964-906b-f5f52f59aaad
        启用已挂停资产 - 正常请求
        """
        asset_id = "69e0a5f759e44250c045fa63"  # 需替换为实际挂停资产ID
        resp = api_client.put(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/hangupandstop",
            json={"_id": asset_id}
        )
        assert resp.status_code == 200, f"期望200, 得到{resp.status_code}"
        data = resp.json()
        assert "type" in data
        assert "data" in data
        assert "msg" in data
        assert data["type"] == "success"
        assert data["msg"] == "修改成功"
        result = data["data"]
        assert isinstance(result, str)
        assert "updateOfExisting=true" in result

    def test_enable_hanged_asset_verify_status(self, api_client):
        """
        TC: eae46148-969f-4818-89aa-3013ac87b58d
        启用已挂停资产 - 验证状态变更
        """
        asset_id = "69e0a5f759e44250c045fa63"
        resp = api_client.put(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/hangupandstop",
            json={"_id": asset_id}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "success"
        assert "修改成功" in data["msg"]
        assert "n=1" in data.get("data", "")

    def test_enable_asset_response_time(self, api_client):
        """
        TC: a9a835bc-0f28-4042-9279-0d5050015333
        启用资产响应时间验证
        """
        asset_id = "60d5f9f8e4b0f2a1b2c3d4e5"
        resp = api_client.put(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/hangupandstop",
            json={"_id": asset_id}
        )
        assert resp.status_code == 200
        elapsed = resp.elapsed.total_seconds()
        assert elapsed < 2.0, f"响应时间 {elapsed:.3f}s 超过2秒"
        data = resp.json()
        assert data["type"] == "success"
        assert "修改成功" in data["msg"]
