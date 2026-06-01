"""告警模块接口测试"""
import pytest
pytestmark = [pytest.mark.alarm, pytest.mark.api]

class TestAlarm:

    def test_get_alarm_types(self, api_client):
        """获取告警类型列表"""
        url = '/api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types'
        resp = api_client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert 'data' in data
        assert isinstance(data['data'], list)
        if len(data['data']) > 0:
            assert 'label' in data['data'][0]

    def test_create_alarm_rule(self, api_client, alarm_type_value):
        """创建告警规则"""
        create_url = '/api/plugins/com.andisec.plugins.alarm/events/definitions'
        payload = {'title': '测试告警规则', 'description': '正向测试创建的规则', 'priority': 3, 'config': {'conditions': {}, 'execute_every_ms': 60000, 'group_by': [], 'query': '告警', 'query_parameters': [], 'search_within_ms': 60000, 'series': [], 'streams': [], 'type': 'aggregation-v1'}, 'restrain': None, 'field_spec': {}, 'key_spec': [], 'notification_settings': {'grace_period_ms': 60000, 'backlog_size': None}, 'notifications': [], 'alert': False, 'credibility': 3, 'check_type': 'elasticsearch', 'alarm_type': alarm_type_value, 'disposal_advice': '请检查相关日志', 'check_query': True}
        resp = api_client.post(create_url, json=payload)
        assert resp.status_code == 200
        created_data = resp.json()
        assert 'id' in created_data
        rule_id = created_data['id']
        delete_url = f'/api/plugins/com.andisec.plugins.alarm/events/definitions/{rule_id}'
        del_resp = api_client.delete(delete_url)
        assert del_resp.status_code in (200, 204, 404)

    def test_search_alarm_rules_empty(self, api_client):
        """搜索告警规则"""
        search_url = '/api/plugins/com.andisec.plugins.alarm/events/definitions/search'
        payload = {'query': '', 'page': 1, 'per_page': 20, 'sort': [], 'fullText': ''}
        resp = api_client.post(search_url, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'total' in data
        assert data['total'] != 0

    def test_search_after_create(self, api_client, create_rule_for_test):
        """搜索告警规则（验证创建后可见）"""
        rule_info = create_rule_for_test
        created_id = rule_info['id']
        created_title = rule_info['title']
        search_url = '/api/plugins/com.andisec.plugins.alarm/events/definitions/search'
        payload = {'query': created_title, 'page': 1, 'per_page': 20, 'sort': [], 'fullText': ''}
        resp = api_client.post(search_url, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'event_definitions' in data
        definitions = data['event_definitions']
        found_ids = [item.get('id') for item in definitions]
        assert created_id in found_ids, f'未找到创建的规则ID {created_id}'
        for item in definitions:
            if item.get('id') == created_id:
                assert item.get('title') == created_title

    def test_delete_existing_rule(self, api_client, create_rule_for_test):
        """删除告警规则 - 正向删除已存在的规则"""
        rule_id = create_rule_for_test['id']
        delete_url = f'/api/plugins/com.andisec.plugins.alarm/events/definitions/{rule_id}'
        resp = api_client.delete(delete_url)
        assert resp.status_code == 204
        search_url = '/api/plugins/com.andisec.plugins.alarm/events/definitions/search'
        payload = {'query': create_rule_for_test['title'], 'page': 1, 'per_page': 20, 'sort': [], 'fullText': ''}
        search_resp = api_client.post(search_url, json=payload)
        assert search_resp.status_code == 200
        search_data = search_resp.json()
        definitions = search_data.get('event_definitions', [])
        found = any((item.get('id') == rule_id for item in definitions))
        assert not found, f'规则 {rule_id} 仍存在于搜索结果中'

class TestAlarmComprehensiveScreen:
    """告警综合大屏接口测试"""

    def test_post_safety_score(self, api_client):
        """测试安全评分接口的基本功能"""
        payload = {'streamIds': '69e0a62159e44250c045fa9a', 'time_from': '2026-05-18 00:00:00.000', 'time_to': '2026-05-24 23:59:59.999'}
        resp = api_client.post('/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/safetyScore', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'result' in data
        assert isinstance(data['result'], (int, float))
        assert 'message' in data
        assert data['message'] == '请求成功'

    def test_post_safety_situation(self, api_client):
        """测试安全态势接口的基本功能"""
        payload = {'streamIds': '69e0a62159e44250c045fa9a', 'time_from': '2026-05-18 00:00:00.000', 'time_to': '2026-05-24 23:59:59.999'}
        resp = api_client.post('/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/safetySituation', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'result' in data
        assert 'message' in data
        result = data['result']
        assert isinstance(result, dict)
        assert 'assetNum' in result
        assert isinstance(result['assetNum'], int)
        assert 'alarmAssetNum' in result
        assert isinstance(result['alarmAssetNum'], int)
        assert 'disposeAlarmNum' in result
        assert 'notDisposeAlarmNum' in result
        assert 'disposeAlarmRate' in result
        assert 'disposeThreatRate' in result
        assert 'alarmNum' in result
        assert 'threatNum' in result
        assert 'onlineDeviceRate' in result
        assert 'trustDeviceRate' in result
        assert 'areaInfo' in result
        assert isinstance(result['areaInfo'], list)
        if len(result['areaInfo']) > 0:
            area_item = result['areaInfo'][0]
            assert 'streamId' in area_item
            assert 'streamName' in area_item
            assert 'assetNum' in area_item
            assert 'alarmNum' in area_item

    def test_post_vulnerability_of_asset_grade(self, api_client):
        """测试资产等级漏洞分布接口的基本功能"""
        payload = {'streamIds': '69e0a62159e44250c045fa9a', 'time_from': '2026-05-18 00:00:00.000', 'time_to': '2026-05-24 23:59:59.999'}
        resp = api_client.post('/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/getVulnerabilityOfAssetGrade', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        assert data['msg'] == '成功'
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'areaName' in item
            assert isinstance(item['areaName'], str)
            assert 'lowRiskNum' in item
            assert isinstance(item['lowRiskNum'], int)
            assert 'middleRiskNum' in item
            assert isinstance(item['middleRiskNum'], int)
            assert 'highRiskNum' in item
            assert isinstance(item['highRiskNum'], int)

    def test_post_vulnerability_of_asset_area(self, api_client):
        """测试资产区域漏洞分布接口的基本功能"""
        payload = {'streamIds': '69e0a62159e44250c045fa9a', 'time_from': '2026-05-18 00:00:00.000', 'time_to': '2026-05-24 23:59:59.999'}
        resp = api_client.post('/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/getVulnerabilityOfAssetArea', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        assert data['msg'] == '成功'
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'areaName' in item
            assert isinstance(item['areaName'], str)
            assert 'assetNum' in item
            assert isinstance(item['assetNum'], int)

    def test_post_knowasset_list(self, api_client):
        """测试资产列表接口的基本功能"""
        payload = {'query': 'asset_stream:69e0a62159e44250c045fa9a', 'fullText': '', 'order': '', 'page': 1, 'per_page': 20}
        resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        assert data['msg'] == '获取成功'
        result = data['data']
        assert isinstance(result, dict)
        assert 'total_page' in result
        assert 'total_num' in result
        assert 'list' in result
        assert isinstance(result['list'], list)
        if len(result['list']) > 0:
            asset_item = result['list'][0]
            assert '_id' in asset_item
            assert isinstance(asset_item['_id'], str)
            assert 'asset_name' in asset_item
            assert isinstance(asset_item['asset_name'], str)
            assert 'asset_type' in asset_item
            assert 'device' in asset_item
            assert 'asset_status' in asset_item
            assert 'stream_id' in asset_item

    def test_post_real_time_alarm_num(self, api_client):
        """测试实时告警数量接口的基本功能"""
        payload = {'streamIds': '69e0a62159e44250c045fa9a', 'time_from': '2026-05-18 00:00:00.000', 'time_to': '2026-05-24 23:59:59.999', 'type': 2}
        resp = api_client.post('/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/realTimeAlarmNum', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        assert data['msg'] == '获取成功'
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            series_item = result[0]
            assert 'data' in series_item
            assert isinstance(series_item['data'], list)
            assert 'name' in series_item
            assert isinstance(series_item['name'], str)
            assert 'time' in series_item
            assert isinstance(series_item['time'], list)

    def test_post_attack_map(self, api_client):
        """测试攻击地图接口的基本功能"""
        payload = {'time_from': '2026-05-18 00:00:00.000', 'time_to': '2026-05-24 23:59:59.999', 'streamIds': '69e0a62159e44250c045fa9a', 'type': 2}
        resp = api_client.post('/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/attackMap', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'message' in data
        assert data['message'] == '请求成功'
        result = data['data']
        assert isinstance(result, dict)
        assert 'city_info' in result
        assert isinstance(result['city_info'], dict)
        assert 'city_map' in result
        assert isinstance(result['city_map'], dict)
        if result['city_map']:
            assert 'origin2DstMap' in result['city_map']
            assert 'dst2OriginMap' in result['city_map']
        assert 'origin' in result
        assert 'alarm_level_count' in result
        assert isinstance(result['alarm_level_count'], list)

    def test_post_traffic_protocol_info(self, api_client):
        """测试流量协议信息接口的基本功能"""
        payload = {'streamIds': '69e0a62159e44250c045fa9a', 'time_from': '2026-05-18 00:00:00.000', 'time_to': '2026-05-24 23:59:59.999'}
        resp = api_client.post('/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/trafficProtocolInfo', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert isinstance(data['data'], list)
        assert 'message' in data
        assert data['message'] == '请求成功'