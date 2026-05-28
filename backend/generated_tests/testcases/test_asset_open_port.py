"""资产清点-端口列表接口测试"""
import pytest

pytestmark = [pytest.mark.asset_open_port, pytest.mark.api]


class TestAssetOpenPort:
    """资产清点-端口列表接口测试类"""

    def test_port_list_query(self, api_client):
        """测试端口列表查询接口基本功能"""
        path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/getlist"
        payload = {
            "page": 1,
            "per_page": 20,
            "query": ""
        }
        resp = api_client.post(path, json=payload)

        # A级：状态码断言
        assert resp.status_code == 200

        # A级：响应结构断言
        data = resp.json()
        assert "type" in data
        assert "data" in data
        assert "msg" in data
        assert data["type"] == "success"

        # B级：响应类型断言
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)

        # B级：列表元素断言
        if len(result["list"]) > 0:
            first_item = result["list"][0]
            assert "install_num" in first_item
            assert "open_port" in first_item
            assert "key" in first_item
            assert isinstance(first_item["install_num"], int)
            assert isinstance(first_item["open_port"], int)
            assert isinstance(first_item["key"], str)

    def test_port_list_query_pagination(self, api_client):
        """测试端口列表查询接口分页功能"""
        path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/getlist"
        payload = {
            "page": 2,
            "per_page": 5,
            "query": ""
        }
        resp = api_client.post(path, json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "success"
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)

    def test_select_fields_for_data(self, api_client):
        """测试端口筛选字段接口基本功能"""
        path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/selectFieldsForData"
        resp = api_client.get(path)

        # A级：状态码断言
        assert resp.status_code == 200

        # A级：响应结构断言
        data = resp.json()
        assert "type" in data
        assert "data" in data
        assert "msg" in data
        assert data["type"] == "success"

        # B级：响应类型断言
        result = data["data"]
        assert isinstance(result, list)

        # B级：列表元素断言
        if len(result) > 0:
            first_item = result[0]
            assert "label" in first_item
            assert "value" in first_item
            assert "list" in first_item
            assert isinstance(first_item["label"], str)
            assert isinstance(first_item["value"], str)
            assert isinstance(first_item["list"], list)

            # 验证子列表结构
            if len(first_item["list"]) > 0:
                sub_item = first_item["list"][0]
                assert "label" in sub_item
                assert "count" in sub_item
                assert "value" in sub_item
                assert isinstance(sub_item["count"], int)

    def test_select_fields_for_asset(self, api_client):
        """测试终端筛选字段接口基本功能"""
        path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/selectFieldsForAsset"
        resp = api_client.get(path)

        # A级：状态码断言
        assert resp.status_code == 200

        # A级：响应结构断言
        data = resp.json()
        assert "type" in data
        assert "data" in data
        assert "msg" in data
        assert data["type"] == "success"

        # B级：响应类型断言
        result = data["data"]
        assert isinstance(result, list)

        # B级：列表元素断言
        if len(result) > 0:
            first_item = result[0]
            assert "label" in first_item
            assert "value" in first_item
            assert "list" in first_item
            assert isinstance(first_item["label"], str)
            assert isinstance(first_item["value"], str)
            assert isinstance(first_item["list"], list)

            if len(first_item["list"]) > 0:
                sub_item = first_item["list"][0]
                assert "label" in sub_item
                assert "count" in sub_item
                assert "value" in sub_item
                assert isinstance(sub_item["count"], int)

    def test_asset_list_query(self, api_client):
        """测试终端列表查询接口基本功能"""
        path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/getassetlist"
        payload = {
            "page": 1,
            "per_page": 20,
            "query": ""
        }
        resp = api_client.post(path, json=payload)

        # A级：状态码断言
        assert resp.status_code == 200

        # A级：响应结构断言
        data = resp.json()
        assert "type" in data
        assert "data" in data
        assert "msg" in data
        assert data["type"] == "success"

        # B级：响应类型断言
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)

        # B级：列表元素断言
        if len(result["list"]) > 0:
            first_item = result["list"][0]
            assert "asset_name" in first_item
            assert "asset_area" in first_item
            assert "asset_ip" in first_item
            assert "software_count" in first_item
            assert "guid" in first_item
            assert "network_card" in first_item
            assert isinstance(first_item["asset_name"], str)
            assert isinstance(first_item["asset_ip"], str)
            assert isinstance(first_item["guid"], str)
            assert isinstance(first_item["network_card"], list)
            assert isinstance(first_item["software_count"], int)

            # 验证网卡信息结构
            if len(first_item["network_card"]) > 0:
                nic = first_item["network_card"][0]
                assert "ip" in nic
                assert "mac" in nic

    def test_port_asset_detail(self, api_client):
        """测试端口终端详情接口基本功能 - 先从端口列表获取key再查询详情"""
        # 先获取端口列表以获取有效的 key
        list_path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/getlist"
        list_payload = {
            "page": 1,
            "per_page": 20,
            "query": ""
        }
        list_resp = api_client.post(list_path, json=list_payload)
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["type"] == "success"

        # 获取第一个端口的 key 用于查询详情
        port_list = list_data["data"]["list"]
        query_key = "09a51a114049b6fdb03940abf454ec5e"
        if len(port_list) > 0:
            query_key = port_list[0]["key"]

        # 查询端口终端详情
        detail_path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/getassetinfo"
        detail_payload = {
            "page": 1,
            "per_page": 20,
            "query": query_key
        }
        resp = api_client.post(detail_path, json=detail_payload)

        # A级：状态码断言
        assert resp.status_code == 200

        # A级：响应结构断言
        data = resp.json()
        assert "type" in data
        assert "data" in data
        assert "msg" in data
        assert data["type"] == "success"

        # B级：响应类型断言
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)

        # B级：列表元素断言
        if len(result["list"]) > 0:
            first_item = result["list"][0]
            assert "host_name" in first_item
            assert "asset_area" in first_item
            assert "asset_ip" in first_item
            assert "guid" in first_item
            assert "network_card" in first_item
            assert isinstance(first_item["host_name"], str)
            assert isinstance(first_item["asset_ip"], str)
            assert isinstance(first_item["guid"], str)
            assert isinstance(first_item["network_card"], list)

    def test_asset_port_detail(self, api_client):
        """测试终端端口详情接口基本功能 - 先从终端列表获取guid再查询详情"""
        # 先获取终端列表以获取有效的 guid
        list_path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/getassetlist"
        list_payload = {
            "page": 1,
            "per_page": 20,
            "query": ""
        }
        list_resp = api_client.post(list_path, json=list_payload)
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["type"] == "success"

        # 获取第一个终端的 guid 用于查询详情
        asset_list = list_data["data"]["list"]
        query_guid = "46D51377EC23F7DD6F53C690D3684888"
        if len(asset_list) > 0:
            query_guid = asset_list[0]["guid"]

        # 查询终端端口详情
        detail_path = "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetOpenPortResource/getInfo"
        detail_payload = {
            "page": 1,
            "per_page": 20,
            "query": query_guid
        }
        resp = api_client.post(detail_path, json=detail_payload)

        # A级：状态码断言
        assert resp.status_code == 200

        # A级：响应结构断言
        data = resp.json()
        assert "type" in data
        assert "data" in data
        assert "msg" in data
        assert data["type"] == "success"

        # B级：响应类型断言
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)

        # B级：列表元素断言
        if len(result["list"]) > 0:
            first_item = result["list"][0]
            assert "port_name" in first_item
            assert "agreement" in first_item
            assert "service_name" in first_item
            assert isinstance(first_item["port_name"], int)
            assert isinstance(first_item["agreement"], str)
            assert isinstance(first_item["service_name"], str)
