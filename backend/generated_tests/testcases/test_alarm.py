"""告警模块接口测试"""
import pytest

pytestmark = [pytest.mark.alarm, pytest.mark.api]


class TestAlarmComprehensiveScreen:
    """告警综合大屏接口测试"""

    def test_post_safety_score(self, api_client):
        """测试安全评分接口的基本功能"""
        payload = {
            "streamIds": "69e0a62159e44250c045fa9a",
            "time_from": "2026-05-18 00:00:00.000",
            "time_to": "2026-05-24 23:59:59.999"
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/safetyScore",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "result" in data
        assert isinstance(data["result"], (int, float))
        assert "message" in data
        assert data["message"] == "请求成功"

    def test_post_safety_situation(self, api_client):
        """测试安全态势接口的基本功能"""
        payload = {
            "streamIds": "69e0a62159e44250c045fa9a",
            "time_from": "2026-05-18 00:00:00.000",
            "time_to": "2026-05-24 23:59:59.999"
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/safetySituation",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "result" in data
        assert "message" in data
        result = data["result"]
        assert isinstance(result, dict)
        assert "assetNum" in result
        assert isinstance(result["assetNum"], int)
        assert "alarmAssetNum" in result
        assert isinstance(result["alarmAssetNum"], int)
        assert "disposeAlarmNum" in result
        assert "notDisposeAlarmNum" in result
        assert "disposeAlarmRate" in result
        assert "disposeThreatRate" in result
        assert "alarmNum" in result
        assert "threatNum" in result
        assert "onlineDeviceRate" in result
        assert "trustDeviceRate" in result
        assert "areaInfo" in result
        assert isinstance(result["areaInfo"], list)
        if len(result["areaInfo"]) > 0:
            area_item = result["areaInfo"][0]
            assert "streamId" in area_item
            assert "streamName" in area_item
            assert "assetNum" in area_item
            assert "alarmNum" in area_item

    def test_post_vulnerability_of_asset_grade(self, api_client):
        """测试资产等级漏洞分布接口的基本功能"""
        payload = {
            "streamIds": "69e0a62159e44250c045fa9a",
            "time_from": "2026-05-18 00:00:00.000",
            "time_to": "2026-05-24 23:59:59.999"
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/getVulnerabilityOfAssetGrade",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        assert data["msg"] == "成功"
        result = data["data"]
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert "areaName" in item
            assert isinstance(item["areaName"], str)
            assert "lowRiskNum" in item
            assert isinstance(item["lowRiskNum"], int)
            assert "middleRiskNum" in item
            assert isinstance(item["middleRiskNum"], int)
            assert "highRiskNum" in item
            assert isinstance(item["highRiskNum"], int)

    def test_post_vulnerability_of_asset_area(self, api_client):
        """测试资产区域漏洞分布接口的基本功能"""
        payload = {
            "streamIds": "69e0a62159e44250c045fa9a",
            "time_from": "2026-05-18 00:00:00.000",
            "time_to": "2026-05-24 23:59:59.999"
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/getVulnerabilityOfAssetArea",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        assert data["msg"] == "成功"
        result = data["data"]
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert "areaName" in item
            assert isinstance(item["areaName"], str)
            assert "assetNum" in item
            assert isinstance(item["assetNum"], int)

    def test_post_knowasset_list(self, api_client):
        """测试资产列表接口的基本功能"""
        payload = {
            "query": "asset_stream:69e0a62159e44250c045fa9a",
            "fullText": "",
            "order": "",
            "page": 1,
            "per_page": 20
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        assert data["msg"] == "获取成功"
        result = data["data"]
        assert isinstance(result, dict)
        assert "total_page" in result
        assert "total_num" in result
        assert "list" in result
        assert isinstance(result["list"], list)
        if len(result["list"]) > 0:
            asset_item = result["list"][0]
            assert "_id" in asset_item
            assert isinstance(asset_item["_id"], str)
            assert "asset_name" in asset_item
            assert isinstance(asset_item["asset_name"], str)
            assert "asset_type" in asset_item
            assert "device" in asset_item
            assert "asset_status" in asset_item
            assert "stream_id" in asset_item

    def test_post_real_time_alarm_num(self, api_client):
        """测试实时告警数量接口的基本功能"""
        payload = {
            "streamIds": "69e0a62159e44250c045fa9a",
            "time_from": "2026-05-18 00:00:00.000",
            "time_to": "2026-05-24 23:59:59.999",
            "type": 2
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/realTimeAlarmNum",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "msg" in data
        assert data["msg"] == "获取成功"
        result = data["data"]
        assert isinstance(result, list)
        if len(result) > 0:
            series_item = result[0]
            assert "data" in series_item
            assert isinstance(series_item["data"], list)
            assert "name" in series_item
            assert isinstance(series_item["name"], str)
            assert "time" in series_item
            assert isinstance(series_item["time"], list)

    def test_post_attack_map(self, api_client):
        """测试攻击地图接口的基本功能"""
        payload = {
            "time_from": "2026-05-18 00:00:00.000",
            "time_to": "2026-05-24 23:59:59.999",
            "streamIds": "69e0a62159e44250c045fa9a",
            "type": 2
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/attackMap",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert "message" in data
        assert data["message"] == "请求成功"
        result = data["data"]
        assert isinstance(result, dict)
        assert "city_info" in result
        assert isinstance(result["city_info"], dict)
        assert "city_map" in result
        assert isinstance(result["city_map"], dict)
        if result["city_map"]:
            assert "origin2DstMap" in result["city_map"]
            assert "dst2OriginMap" in result["city_map"]
        assert "origin" in result
        assert "alarm_level_count" in result
        assert isinstance(result["alarm_level_count"], list)

    def test_post_traffic_protocol_info(self, api_client):
        """测试流量协议信息接口的基本功能"""
        payload = {
            "streamIds": "69e0a62159e44250c045fa9a",
            "time_from": "2026-05-18 00:00:00.000",
            "time_to": "2026-05-24 23:59:59.999"
        }
        resp = api_client.post(
            "/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/trafficProtocolInfo",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type" in data
        assert data["type"] == "success"
        assert "data" in data
        assert isinstance(data["data"], list)
        assert "message" in data
        assert data["message"] == "请求成功"
