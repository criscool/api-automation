"""asset-management 接口测试"""
import pytest

pytestmark = [pytest.mark.asset_management, pytest.mark.api]


class TestAssetManagement:
    """资产管理接口测试类"""

    def test_post_add_asset(self, api_client):
        """测试 POST 新增资产的基本功能"""
        add_path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/add"
        request_body = {
            "_id": "",
            "network_card": [
                {
                    "ip": "172.27.18.11",
                    "mac": ""
                }
            ],
            "asset_name": "添加资产测试",
            "mac": "",
            "asset_project": "69e0a5f759e44250c045fa63",
            "asset_stream": "69e0a62159e44250c045fa9a",
            "asset_area": "",
            "asset_type": 3,
            "asset_subtype": 3001,
            "asset_level": 1,
            "host_guard": 0,
            "host_probe": 0,
            "is_manage": 0,
            "asset_manufacturer": "",
            "asset_model": "",
            "asset_director": "",
            "asset_director_phone": "",
            "asset_os": "",
            "asset_longitude": "",
            "asset_latitude": "",
            "asset_describe": "",
            "host_name": "",
            "uplink_device": "",
            "asset_group": "",
            "tag1": "",
            "tag2": "",
            "tag3": ""
        }

        resp = api_client.post(add_path, json=request_body)

        # A级断言：状态码
        assert resp.status_code == 200

        # A级断言：响应结构
        data = resp.json()
        assert "type" in data
        assert "data" in data
        assert "msg" in data

        # B级断言：响应字段类型和值
        assert data["type"] == "success"
        assert data["msg"] == "添加成功"
        assert isinstance(data["data"], str)
        assert len(data["data"]) > 0

        # 获取创建的资产ID用于清理
        created_asset_id = data["data"]

        # 清理：删除刚创建的资产
        delete_path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/delete"
        delete_body = {
            "entities": [created_asset_id]
        }
        cleanup_resp = api_client.post(delete_path, json=delete_body)
        assert cleanup_resp.status_code in (200, 204, 404)

    def test_post_delete_asset(self, api_client):
        """测试 POST 删除资产的基本功能"""
        # 前置：先创建一个资产用于删除
        add_path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/add"
        setup_body = {
            "_id": "",
            "network_card": [
                {
                    "ip": "172.27.18.12",
                    "mac": ""
                }
            ],
            "asset_name": "删除资产测试前置",
            "mac": "",
            "asset_project": "69e0a5f759e44250c045fa63",
            "asset_stream": "69e0a62159e44250c045fa9a",
            "asset_area": "",
            "asset_type": 3,
            "asset_subtype": 3001,
            "asset_level": 1,
            "host_guard": 0,
            "host_probe": 0,
            "is_manage": 0,
            "asset_manufacturer": "",
            "asset_model": "",
            "asset_director": "",
            "asset_director_phone": "",
            "asset_os": "",
            "asset_longitude": "",
            "asset_latitude": "",
            "asset_describe": "",
            "host_name": "",
            "uplink_device": "",
            "asset_group": "",
            "tag1": "",
            "tag2": "",
            "tag3": ""
        }
        setup_resp = api_client.post(add_path, json=setup_body)
        assert setup_resp.status_code == 200
        setup_data = setup_resp.json()
        assert "data" in setup_data
        assert setup_data["type"] == "success"
        created_asset_id = setup_data["data"]
        assert isinstance(created_asset_id, str)
        assert len(created_asset_id) > 0

        # 执行删除
        delete_path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/delete"
        delete_body = {
            "entities": [created_asset_id]
        }
        resp = api_client.post(delete_path, json=delete_body)

        # A级断言：状态码
        assert resp.status_code == 200

        # A级断言：响应结构
        data = resp.json()
        assert "type" in data
        assert "msg" in data

        # B级断言：响应字段值
        assert data["type"] == "success"
        assert data["msg"] == "删除成功"
