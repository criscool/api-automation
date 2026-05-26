"""告警规则搜索 接口测试"""
import pytest

pytestmark = [pytest.mark.module, pytest.mark.api]

class TestModule:

    def test_post_api_plugins_com_andisec_plugins_alarm_events_definitions_search(self, api_client):
        """测试 POST /api/plugins/com.andisec.plugins.alarm/events/definitions/search 的基本功能"""
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.alarm/events/definitions/search",
            json={
            "body": {}
}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, dict)
        assert result.get("body") == "{}"

    def test_get_api_plugins_com_andisec_plugins_alarm_events_definitions_alarm_types(self, api_client):
        """测试 GET /api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types 的基本功能"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert result is not None
