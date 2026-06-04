"""资产清点-进程列表接口测试"""
import pytest

pytestmark = [pytest.mark.资产清点_进程列表, pytest.mark.api]


class TestAssetProcess:
    """资产清点-进程列表测试类"""

    def test_process_list_pagination(self, api_client):
        """进程列表查询-正常分页无搜索"""
        body = {
            "page": "1",
            "per_page": 20,
            "query": ""
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/getlist",
            json=body
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            item = result["list"][0]
            assert "name" in item
            assert "key" in item

    def test_process_filter_fields(self, api_client):
        """进程筛选字段查询-正常获取下拉选项"""
        resp = api_client.get(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/selectFieldsForData"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, list)
        if len(result) > 0:
            field = result[0]
            assert "label" in field
            assert "value" in field
            assert "list" in field

    def test_asset_filter_fields(self, api_client):
        """终端筛选字段查询-正常获取终端/区域选项"""
        resp = api_client.get(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/selectFieldsForAsset"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, list)
        if len(result) > 0:
            field = result[0]
            assert "label" in field
            assert "value" in field

    def test_asset_list_pagination(self, api_client):
        """终端列表查询-正常分页无搜索"""
        body = {
            "page": 1,
            "per_page": 20,
            "query": ""
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/getassetlist",
            json=body
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "software_count" in str(data) or any("software_count" in str(item) for item in result.get("list", []))
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            item = result["list"][0]
            assert "asset_name" in item
            assert "asset_ip" in item

    def test_process_detail(self, api_client):
        """进程详情查询-正常分页查询指定进程"""
        body = {
            "page": 1,
            "per_page": 20,
            "query": "b3477e52d95d4c357fd8da7b0fd20e16"
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/getInfo",
            json=body
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            item = result["list"][0]
            assert "asset_ip" in item
            assert "network_card" in item

    def test_asset_detail(self, api_client):
        """终端详情查询-正常查询指定终端"""
        body = {
            "page": 1,
            "per_page": 20,
            "query": "46D51377EC23F7DD6F53C690D3684888"
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/getassetinfo",
            json=body
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            item = result["list"][0]
            assert "md5" in item
            assert "sha1" in item
            assert "absolute_ptah" in item
