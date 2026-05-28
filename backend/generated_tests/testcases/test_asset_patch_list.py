"""资产清点-补丁列表接口测试"""
import pytest

pytestmark = [pytest.mark.asset_patch, pytest.mark.api]


class TestAssetPatchList:
    """资产清点-补丁列表模块接口测试"""

    def test_patch_list_query(self, api_client):
        """测试补丁列表查询接口基本功能"""
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemPatchResource/getlist",
            json={
                "page": 1,
                "per_page": 20,
                "query": ""
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            item = result["list"][0]
            assert "install_num" in item
            assert "name" in item
            assert "key" in item
            assert "install_rate" in item
            assert isinstance(item["install_num"], (int, float))
            assert isinstance(item["name"], str)
            assert isinstance(item["key"], str)
            assert isinstance(item["install_rate"], (int, float))

    def test_patch_select_fields_for_data(self, api_client):
        """测试补丁筛选字段接口基本功能"""
        resp = api_client.get(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemPatchResource/selectFieldsForData"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        result = data["data"]
        assert isinstance(result, list)
        if len(result) > 0:
            field_item = result[0]
            assert "label" in field_item
            assert "value" in field_item
            assert "list" in field_item
            assert isinstance(field_item["label"], str)
            assert isinstance(field_item["value"], str)
            assert isinstance(field_item["list"], list)
            if len(field_item["list"]) > 0:
                option = field_item["list"][0]
                assert "label" in option
                assert "count" in option
                assert "value" in option

    def test_asset_select_fields_for_asset(self, api_client):
        """测试终端筛选字段接口基本功能"""
        resp = api_client.get(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemPatchResource/selectFieldsForAsset"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        result = data["data"]
        assert isinstance(result, list)
        if len(result) > 0:
            field_item = result[0]
            assert "label" in field_item
            assert "value" in field_item
            assert "list" in field_item
            assert isinstance(field_item["label"], str)
            assert isinstance(field_item["value"], str)
            assert isinstance(field_item["list"], list)
            if len(field_item["list"]) > 0:
                option = field_item["list"][0]
                assert "label" in option
                assert "count" in option
                assert "value" in option

    def test_asset_list_query(self, api_client):
        """测试终端列表查询接口基本功能"""
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemPatchResource/getassetlist",
            json={
                "page": 1,
                "per_page": 20,
                "query": ""
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            item = result["list"][0]
            assert "asset_name" in item
            assert "asset_ip" in item
            assert "software_count" in item
            assert "guid" in item
            assert isinstance(item["asset_name"], str)
            assert isinstance(item["asset_ip"], str)
            assert isinstance(item["guid"], str)
            assert isinstance(item["software_count"], (int, float))

    def test_patch_detail_info(self, api_client):
        """测试补丁终端详情接口 - 先查询补丁列表获取key再查详情"""
        # 先获取补丁列表以获取有效的key
        list_resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemPatchResource/getlist",
            json={
                "page": 1,
                "per_page": 20,
                "query": ""
            }
        )
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["type"] == "success"

        # 确定查询用的key
        patch_key = "60c40b9034d048536ba3eff3f1243395"
        if len(list_data["data"]["list"]) > 0:
            patch_key = list_data["data"]["list"][0]["key"]

        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemPatchResource/getInfo",
            json={
                "page": 1,
                "per_page": 20,
                "query": patch_key
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            item = result["list"][0]
            assert "host_name" in item
            assert "asset_ip" in item
            assert "guid" in item
            assert isinstance(item["host_name"], str)
            assert isinstance(item["asset_ip"], str)
            assert isinstance(item["guid"], str)

    def test_asset_patch_detail_info(self, api_client):
        """测试终端补丁详情接口 - 先查询终端列表获取guid再查详情"""
        # 先获取终端列表以获取有效的guid
        list_resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemPatchResource/getassetlist",
            json={
                "page": 1,
                "per_page": 20,
                "query": ""
            }
        )
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["type"] == "success"

        # 确定查询用的guid
        asset_guid = "46D51377EC23F7DD6F53C690D3684888"
        if len(list_data["data"]["list"]) > 0:
            asset_guid = list_data["data"]["list"][0]["guid"]

        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemPatchResource/getassetinfo",
            json={
                "page": 1,
                "per_page": 20,
                "query": asset_guid
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            item = result["list"][0]
            assert "patch_name" in item
            assert "install_time" in item
            assert isinstance(item["patch_name"], str)
            assert isinstance(item["install_time"], str)
