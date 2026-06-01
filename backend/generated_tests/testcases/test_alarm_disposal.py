import pytest

pytestmark = [pytest.mark.alarm_disposal, pytest.mark.api]


class TestAlarmDisposal:
    """告警处置模块接口测试"""

    def test_get_entity_types(self, api_client):
        """获取事件实体类型-正向：成功获取告警事件的处理器类型、字段提供器类型、存储处理器类型及聚合函数配置"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.alarm/events/entity_types")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert "processor_types" in data
        assert "field_provider_types" in data
        assert "storage_handler_types" in data
        assert "aggregation_functions" in data
        assert isinstance(data["processor_types"], list)
        assert isinstance(data["aggregation_functions"], list)
        assert "aggregation-v1" in data["processor_types"]

    def test_alarm_search(self, api_client):
        """告警列表搜索-正向分页查询：使用状态筛选未确认告警进行分页搜索，验证接口正常返回分页数据"""
        req_body = {
            "query": " status:0",
            "sort": [],
            "page": 1,
            "per_page": 20
        }
        resp = api_client.post("/api/plugins/com.andisec.plugins.alarm/events/searchv2", json=req_body)
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert "events" in data
        assert "parameters" in data
        assert "total_events" in data
        assert isinstance(data["events"], list)
        # 请求-响应一致性：分页参数回显
        params = data["parameters"]
        assert params["page"] == req_body["page"]
        assert params["per_page"] == req_body["per_page"]
        if len(data["events"]) > 0:
            event = data["events"][0]
            assert "id" in event
            assert event["status"] == 0  # 确认搜索出的告警状态为未确认

    def test_get_alarm_labels(self, api_client):
        """获取告警筛选标签-正向：成功获取告警列表筛选字段的可选值（告警类型/项目/数据集）"""
        resp = api_client.get("/api/plugins/com.andisec.plugins.alarm/events/alarm/labels")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["code"] == 200
        assert "data" in data
        labels = data["data"]
        assert isinstance(labels, list)
        label_values = [item["value"] for item in labels if "value" in item]
        assert "alarm_type" in label_values
        assert "projects" in label_values
        assert "streams" in label_values

    def test_dispose_alarm(self, api_client):
        """处置告警-正向忽略：对指定告警进行忽略处置操作，验证处置成功"""
        # 前置：获取一个告警ID
        search_body = {
            "query": " status:0",
            "sort": [],
            "page": 1,
            "per_page": 1
        }
        resp_search = api_client.post("/api/plugins/com.andisec.plugins.alarm/events/searchv2", json=search_body)
        assert resp_search.status_code == 200
        search_data = resp_search.json()
        assert len(search_data["events"]) > 0, "无可用告警进行处置"
        alarm_id = search_data["events"][0]["id"]

        # 处置请求
        dispose_body = {
            "dispose_detail": "测试忽略",
            "dispose_result": "成功",
            "alarm_id": alarm_id,
            "dispose_person_id": "1",
            "dispose_person_name": "superadmin",
            "dispose_type": 1
        }
        resp = api_client.post("/api/plugins/com.andisec.plugins.alarm/events/dispose", json=dispose_body)
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["code"] == 200
        assert "data" in data
        assert data["data"] == True
        # 处置操作无需清理，告警状态下次可能被其他测试使用

    def test_alarm_detail(self, api_client):
        """告警详情-正向：通过告警ID获取告警详情及处置记录"""
        # 前置：获取告警ID
        search_body = {
            "query": " status:0",
            "sort": [],
            "page": 1,
            "per_page": 1
        }
        resp_search = api_client.post("/api/plugins/com.andisec.plugins.alarm/events/searchv2", json=search_body)
        assert resp_search.status_code == 200
        search_data = resp_search.json()
        assert len(search_data["events"]) > 0
        alarm_id = search_data["events"][0]["id"]

        # 请求详情
        resp = api_client.get(f"/api/plugins/com.andisec.plugins.alarm/events/detailV2/{alarm_id}")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["code"] == 200
        assert "data" in data
        detail = data["data"]
        assert "title" in detail
        assert "alarmDetail" in detail
        alarm_detail = detail["alarmDetail"]
        assert "alarmLevel" in alarm_detail
        assert "triggeredAtTime" in alarm_detail
        # 验证告警ID一致性（通过返回字段？没有直接返回ID，可跳过）

    def test_investigate_type(self, api_client):
        """告警调查类型-正向：通过告警ID获取告警的调查类型"""
        search_body = {
            "query": " status:0",
            "sort": [],
            "page": 1,
            "per_page": 1
        }
        resp_search = api_client.post("/api/plugins/com.andisec.plugins.alarm/events/searchv2", json=search_body)
        assert resp_search.status_code == 200
        search_data = resp_search.json()
        assert len(search_data["events"]) > 0
        alarm_id = search_data["events"][0]["id"]

        resp = api_client.get(f"/api/plugins/com.andisec.plugins.alarm/events/investigate/type/{alarm_id}")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["code"] == 200
        assert "data" in data
        assert "type" in data["data"]
        assert data["data"]["type"] == "aggregation-v1"

    def test_aggregation_data(self, api_client):
        """获取告警调查聚合数据-正向：使用有效的告警ID获取告警的调查聚合数据（查询条件、时间范围等）"""
        search_body = {
            "query": " status:0",
            "sort": [],
            "page": 1,
            "per_page": 1
        }
        resp_search = api_client.post("/api/plugins/com.andisec.plugins.alarm/events/searchv2", json=search_body)
        assert resp_search.status_code == 200
        search_data = resp_search.json()
        assert len(search_data["events"]) > 0
        alarm_id = search_data["events"][0]["id"]

        resp = api_client.get(f"/api/plugins/com.andisec.plugins.alarm/events/investigate/{alarm_id}/aggregation-v1")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = resp.json()
        assert data["code"] == 200
        assert "data" in data
        agg_data = data["data"]
        assert "ctime" in agg_data
        assert "utime" in agg_data
        assert "queryStr" in agg_data
        assert "streams" in agg_data
        assert isinstance(agg_data["streams"], list)
