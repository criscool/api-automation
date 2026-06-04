import pytest

pytestmark = [pytest.mark.变更记录, pytest.mark.api]

class TestChangeRecord:
    """变更记录模块接口测试"""

    def test_get_selectfield(self, api_client):
        """变更记录筛选字段-正向：成功获取筛选字段的可选值"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.assetbase/assetbase/changeRecord/selectfield")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["type"] == "success"
        assert "data" in data
        fields = data["data"]
        assert isinstance(fields, list)
        field_values = [item["value"] for item in fields if "value" in item]
        assert "asset_stream_id" in field_values, "筛选字段应包含数据集(asset_stream_id)"
        assert "asset_type" in field_values, "筛选字段应包含资产类型(asset_type)"
        assert "change_type" in field_values, "筛选字段应包含变更类型(change_type)"

    def test_get_change_record_list(self, api_client, selectfield_data):
        """变更记录列表-正向分页查询：使用空筛选条件分页查询，验证接口正常返回分页数据"""
        assert isinstance(selectfield_data, list)
        assert len(selectfield_data) > 0

        req_body = {
            "page": 1,
            "per_page": 20,
            "query": "",
            "fullText": "",
            "order": ""
        }
        resp = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/changeRecord/list", json=req_body)
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["type"] == "success"
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        # 请求-响应一致性：page
        # 列表接口没有回显page/per_page，此处不强制一致性断言
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            record = result["list"][0]
            assert "_id" in record
            assert "asset_ip" in record
