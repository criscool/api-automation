"""告警规则搜索 接口测试"""
import pytest

pytestmark = [pytest.mark.module, pytest.mark.api]

class TestModule:

    def test_post_api_plugins_com_andisec_plugins_alarm_events_definitions_search(self, api_client):
        """测试 POST /api/plugins/com.andisec.plugins.alarm/events/definitions/search 的基本功能"""
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.alarm/events/definitions/search",
            json={
            "body": {
                        "query": "",
                        "page": 1,
                        "per_page": 20,
                        "sort": [],
                        "fullText": ""
            }
}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert result.get("body") == "{'query': '', 'page': 1, 'per_page': 20, 'sort': [], 'fullText': ''}"

    def test_get_api_plugins_com_andisec_plugins_alarm_events_definitions_alarm_types(self, api_client):
        """测试 GET /api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types 的基本功能"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert result is not None

    def test_post_api_plugins_com_andisec_plugins_alarm_events_definitions(self, created_create):
        """测试 POST /api/plugins/com.andisec.plugins.alarm/events/definitions 的基本功能"""
        assert created_create is not None

    def test_delete_api_plugins_com_andisec_plugins_alarm_events_definitions_id(self, api_client, created_create):
        """测试 DELETE /api/plugins/com.andisec.plugins.alarm/events/definitions/:id 的基本功能"""
        resp = api_client.delete(f"/api/plugins/com.andisec.plugins.alarm/events/definitions/{created_create}")
        assert resp.status_code == 200
