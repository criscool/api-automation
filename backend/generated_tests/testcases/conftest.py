"""共享业务 fixture（由 ScriptGeneratorAgent 自动生成 + 合并）"""
import pytest

@pytest.fixture
def created_create(api_client):
    """创建告警规则"""
    resp = api_client.post('/api/plugins/com.andisec.plugins.alarm/events/definitions', json={'body': {'title': '名称', 'description': '', 'priority': 3, 'config': {'conditions': {}, 'execute_every_ms': 60000, 'group_by': [], 'query': '告警', 'query_parameters': [], 'search_within_ms': 60000, 'series': [], 'streams': [], 'type': 'aggregation-v1'}, 'restrain': null, 'field_spec': {}, 'key_spec': [], 'notification_settings': {'grace_period_ms': 60000, 'backlog_size': null}, 'notifications': [], 'alert': false, 'credibility': 3, 'check_type': 'elasticsearch', 'alarm_type': 1001, 'disposal_advice': '', 'check_query': true}})
    assert resp.status_code == 200
    data = resp.json()
    assert 'data' in data
    resource_id = data['data'].get('id') or data['data'].get('session_id')
    assert resource_id is not None
    yield resource_id
    cleanup_resp = api_client.delete(f'/api/plugins/com.andisec.plugins.alarm/events/definitions/{resource_id}')
    assert cleanup_resp.status_code in (200, 204, 404), f'清理失败 id={resource_id}, status={cleanup_resp.status_code}'

@pytest.fixture
def created_alarm_rule(api_client):
    """创建告警规则，供依赖链使用，测试结束后自动清理"""
    payload = {'title': '自动化测试告警规则', 'description': '', 'priority': 3, 'config': {'conditions': {}, 'execute_every_ms': 60000, 'group_by': [], 'query': '告警', 'query_parameters': [], 'search_within_ms': 60000, 'series': [], 'streams': [], 'type': 'aggregation-v1'}, 'restrain': None, 'field_spec': {}, 'key_spec': [], 'notification_settings': {'grace_period_ms': 60000, 'backlog_size': None}, 'notifications': [], 'alert': False, 'credibility': 3, 'check_type': 'elasticsearch', 'alarm_type': 1001, 'disposal_advice': '', 'check_query': True}
    resp = api_client.post('/api/plugins/com.andisec.plugins.alarm/events/definitions', json=payload, params={'schedule': False})
    assert resp.status_code == 200, f'创建告警规则失败，状态码: {resp.status_code}'
    data = resp.json()
    assert 'id' in data, '创建告警规则响应中缺少id字段'
    rule_id = data['id']
    assert isinstance(rule_id, str) and len(rule_id) > 0, '告警规则id无效'
    yield rule_id
    del_resp = api_client.delete(f'/api/plugins/com.andisec.plugins.alarm/events/definitions/{rule_id}')
    assert del_resp.status_code in (200, 204, 404), f'清理告警规则失败，状态码: {del_resp.status_code}'