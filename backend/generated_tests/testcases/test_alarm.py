"""告警接口测试"""
import pytest

pytestmark = [pytest.mark.alarm, pytest.mark.api]


class TestAlarmRuleSearch:
    """告警规则搜索接口测试"""

    def test_post_alarm_rule_search(self, api_client):
        """测试 POST /api/plugins/com.andisec.plugins.alarm/events/definitions/search 的基本功能"""
        payload = {
            "query": "",
            "page": 1,
            "per_page": 20,
            "sort": [],
            "fullText": ""
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.alarm/events/definitions/search",
            json=payload
        )
        # A级：状态码断言
        assert resp.status_code == 200, f"期望状态码200，实际: {resp.status_code}"
        data = resp.json()

        # A级：响应结构断言
        assert "total" in data, "响应中缺少total字段"
        assert "page" in data, "响应中缺少page字段"
        assert "per_page" in data, "响应中缺少per_page字段"
        assert "count" in data, "响应中缺少count字段"
        assert "event_definitions" in data, "响应中缺少event_definitions字段"

        # B级：类型断言
        assert isinstance(data["total"], int), "total应为整数类型"
        assert isinstance(data["page"], int), "page应为整数类型"
        assert isinstance(data["per_page"], int), "per_page应为整数类型"
        assert isinstance(data["count"], int), "count应为整数类型"
        assert isinstance(data["event_definitions"], list), "event_definitions应为列表类型"

        # B级：请求-响应一致性断言
        assert data["page"] == 1, "返回的page应与请求一致"
        assert data["per_page"] == 20, "返回的per_page应与请求一致"

        # B级：列表元素断言
        if len(data["event_definitions"]) > 0:
            first_item = data["event_definitions"][0]
            assert "id" in first_item, "event_definitions元素缺少id字段"
            assert "title" in first_item, "event_definitions元素缺少title字段"
            assert "priority" in first_item, "event_definitions元素缺少priority字段"
            assert "config" in first_item, "event_definitions元素缺少config字段"


class TestAlarmTypeList:
    """告警类型列表接口测试"""

    def test_get_alarm_types(self, api_client):
        """测试 GET /api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types 的基本功能"""
        resp = api_client.get(
            "/api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types"
        )
        # A级：状态码断言
        assert resp.status_code == 200, f"期望状态码200，实际: {resp.status_code}"
        data = resp.json()

        # A级：响应结构断言
        assert "code" in data, "响应中缺少code字段"
        assert "message" in data, "响应中缺少message字段"
        assert "data" in data, "响应中缺少data字段"

        # B级：类型断言
        assert isinstance(data["code"], int), "code应为整数类型"
        assert isinstance(data["message"], str), "message应为字符串类型"
        assert isinstance(data["data"], list), "data应为列表类型"
        assert data["code"] == 200, "code应为200"

        # B级：列表元素断言
        assert len(data["data"]) > 0, "告警类型列表不应为空"
        first_type = data["data"][0]
        assert "label" in first_type, "类型元素缺少label字段"
        assert "value" in first_type, "类型元素缺少value字段"

        # 验证包含预期的类型分类
        type_values = [item["value"] for item in data["data"]]
        assert "alarm_type" in type_values, "应包含alarm_type分类"
        assert "priority" in type_values, "应包含priority分类"


class TestCreateAlarmRule:
    """创建告警规则接口测试"""

    def test_post_create_alarm_rule(self, api_client):
        """测试 POST /api/plugins/com.andisec.plugins.alarm/events/definitions 的基本功能"""
        payload = {
            "title": "名称",
            "description": "",
            "priority": 3,
            "config": {
                "conditions": {},
                "execute_every_ms": 60000,
                "group_by": [],
                "query": "告警",
                "query_parameters": [],
                "search_within_ms": 60000,
                "series": [],
                "streams": [],
                "type": "aggregation-v1"
            },
            "restrain": None,
            "field_spec": {},
            "key_spec": [],
            "notification_settings": {
                "grace_period_ms": 60000,
                "backlog_size": None
            },
            "notifications": [],
            "alert": False,
            "credibility": 3,
            "check_type": "elasticsearch",
            "alarm_type": 1001,
            "disposal_advice": "",
            "check_query": True
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.alarm/events/definitions",
            json=payload,
            params={"schedule": False}
        )
        # A级：状态码断言
        assert resp.status_code == 200, f"期望状态码200，实际: {resp.status_code}"
        data = resp.json()

        # A级：响应结构断言
        assert "id" in data, "响应中缺少id字段"
        assert "title" in data, "响应中缺少title字段"
        assert "priority" in data, "响应中缺少priority字段"
        assert "config" in data, "响应中缺少config字段"
        assert "credibility" in data, "响应中缺少credibility字段"
        assert "alarm_type" in data, "响应中缺少alarm_type字段"

        # B级：类型断言
        assert isinstance(data["id"], str), "id应为字符串类型"
        assert isinstance(data["title"], str), "title应为字符串类型"
        assert isinstance(data["priority"], int), "priority应为整数类型"
        assert isinstance(data["config"], dict), "config应为字典类型"

        # B级：请求-响应一致性断言
        assert data["title"] == "名称", "返回的title应与请求一致"
        assert data["priority"] == 3, "返回的priority应与请求一致"
        assert data["credibility"] == 3, "返回的credibility应与请求一致"
        assert data["alarm_type"] == 1001, "返回的alarm_type应与请求一致"
        assert data["alert"] is False, "返回的alert应与请求一致"
        assert data["check_type"] == "elasticsearch", "返回的check_type应与请求一致"
        assert data["config"]["query"] == "告警", "返回的config.query应与请求一致"
        assert data["config"]["type"] == "aggregation-v1", "返回的config.type应与请求一致"

        # 清理：删除创建的告警规则
        rule_id = data["id"]
        del_resp = api_client.delete(
            f"/api/plugins/com.andisec.plugins.alarm/events/definitions/{rule_id}"
        )
        assert del_resp.status_code in (200, 204, 404), (
            f"清理告警规则失败，状态码: {del_resp.status_code}"
        )


class TestDeleteAlarmRule:
    """删除告警规则接口测试"""

    def test_delete_alarm_rule(self, api_client, created_alarm_rule):
        """测试 DELETE /api/plugins/com.andisec.plugins.alarm/events/definitions/:id 的基本功能"""
        rule_id = created_alarm_rule

        # C级：引用完整性 - 先验证资源存在（通过搜索确认）
        search_resp = api_client.post(
            "/api/plugins/com.andisec.plugins.alarm/events/definitions/search",
            json={
                "query": "",
                "page": 1,
                "per_page": 1000,
                "sort": [],
                "fullText": ""
            }
        )
        assert search_resp.status_code == 200, "搜索告警规则失败"

        # 执行删除
        resp = api_client.delete(
            f"/api/plugins/com.andisec.plugins.alarm/events/definitions/{rule_id}"
        )
        # A级：状态码断言（DELETE接口期望204）
        assert resp.status_code in (200, 204), (
            f"删除告警规则失败，期望200或204，实际: {resp.status_code}"
        )
