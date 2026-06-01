import pytest

pytestmark = [pytest.mark.未知资产搜索, pytest.mark.api]

class TestUnknownAssetSearch:
    """未知资产搜索模块接口测试"""

    def test_get_selectfield(self, api_client):
        """获取未知资产筛选字段-正向：成功获取筛选字段的可选值"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.assetbase/UnKnowAsset/selectfield")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["code"] == 200
        assert "data" in data
        fields = data["data"]
        assert isinstance(fields, list)
        field_values = [item["value"] for item in fields if "value" in item]
        assert "asset_type" in field_values, "筛选字段应包含设备类型(asset_type)"
        assert "asset_project" in field_values, "筛选字段应包含项目(asset_project)"

    def test_get_entries(self, api_client, selectfield_data):
        """未知资产列表-正向分页查询：不使用搜索条件，验证接口正常返回分页数据"""
        assert isinstance(selectfield_data, list)
        assert len(selectfield_data) > 0

        req_body = {
            "page": 1,
            "per_page": 20,
            "query": "",
            "fullText": "",
            "order": {}
        }
        resp = api_client.post("/api/plugins/com.andisec.plugins.assetbase/UnKnowAsset/unknowasset/entries", json=req_body)
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["code"] == 200
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total" in result
        assert "page" in result
        assert "perPage" in result
        assert "entries" in result
        assert result["page"] == req_body["page"]
        assert result["perPage"] == req_body["per_page"]
        assert isinstance(result["entries"], list)
        if len(result["entries"]) > 0:
            entry = result["entries"][0]
            assert "id" in entry
            assert "ip" in entry
