"""asset-management-搜索详情 接口测试"""
import pytest

pytestmark = [pytest.mark.asset_management, pytest.mark.api]


class TestAssetManagementSearchDetail:
    """资产详情接口测试类"""

    def test_get_asset_showinfo(self, api_client):
        """测试 GET 资产详情接口的基本功能"""
        resp = api_client.get(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/showinfo",
            params={"_id": "69e0a8e959e44250c045ff1c"}
        )
        assert resp.status_code == 200

        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data

        result = data["data"]
        assert isinstance(result, dict)

        # 验证核心字段存在性
        assert "_id" in result
        assert "asset_name" in result
        assert "asset_type" in result
        assert "asset_subtype" in result
        assert "device" in result
        assert "asset_status" in result
        assert "asset_area" in result
        assert "asset_project" in result
        assert "create_time" in result
        assert "mac" in result
        assert "asset_level" in result
        assert "online_status" in result

        # 验证字段类型
        assert isinstance(result["_id"], str)
        assert isinstance(result["asset_name"], str)
        assert isinstance(result["asset_type"], str)
        assert isinstance(result["device"], str)
        assert isinstance(result["asset_status"], str)

        # 验证请求-响应一致性：请求的 _id 应与响应中的 _id 一致
        assert result["_id"] == "69e0a8e959e44250c045ff1c"

        # 验证嵌套结构
        if "network_card" in result:
            assert isinstance(result["network_card"], list)
            if len(result["network_card"]) > 0:
                assert "ip" in result["network_card"][0]
                assert "mac" in result["network_card"][0]

        if "software" in result:
            assert isinstance(result["software"], list)

        # 验证标签结构
        if "tag1" in result and result["tag1"]:
            assert isinstance(result["tag1"], dict)
            assert "tag_name" in result["tag1"]
            if "info" in result["tag1"]:
                assert isinstance(result["tag1"]["info"], dict)
