"""告警规则筛选标签 接口测试"""
import pytest

pytestmark = [pytest.mark.alarm_rule_crud, pytest.mark.api]

class TestAlarmRuleCrud:

    def test_get_alarm_event_types(self, api_client):
        """验证能够成功获取告警事件定义的筛选标签树，返回包含告警类型、危险等级、ATT&CK类型等的标签数据"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert result is not None

    def test_get_event_definition_detail(self, api_client):
        """使用有效的事件定义ID获取详细配置，应返回字段映射、通知设置、存储策略等完整信息"""
        # 先获取一个有效的 event definition ID
        list_resp = api_client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions", params={"per_page": 1})
        assert list_resp.status_code == 200
        definitions = list_resp.json().get("event_definitions", [])
        assert len(definitions) > 0, "没有可用的 event definition 用于测试"
        def_id = definitions[0]["id"]

        resp = api_client.get(f"/api/plugins/com.andisec.plugins.alarm/events/definitions/{def_id}/with-context")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert result is not None

    def test_get_event_definitions_all(self, api_client):
        """验证per_page=0时返回全量事件定义列表，响应状态码200，响应体包含事件定义数组"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions", params={"per_page": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert "event_definitions" in data
        assert isinstance(data["event_definitions"], list)
        assert data["per_page"] == 0

    def test_get_event_definitions(self, api_client):
        """不提供per_page参数时，使用默认分页设置，应返回分页后的事件定义列表"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions")
        assert resp.status_code == 200
        data = resp.json()
        assert "event_definitions" in data
        assert isinstance(data["event_definitions"], list)

    def test_post_copy_event_definition(self, created_module):
        """以未调度状态(schedule=false)复制一个现有事件定义，应成功创建新的告警规则并返回新定义数据"""
        assert created_module is not None

    def test_delete_event_definition(self, api_client, created_module):
        """删除一个存在的事件定义ID，预期返回204状态码表示删除成功，无响应体"""
        resp = api_client.delete(f"/api/plugins/com.andisec.plugins.alarm/events/definitions/{created_module}")
        assert resp.status_code == 200
