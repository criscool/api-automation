"""共享业务 fixture（由 ScriptGeneratorAgent 自动生成 + 合并）"""
import pytest

@pytest.fixture
def alarm_type_value(api_client):
    """获取一个有效的 alarm_type 枚举值"""
    url = '/api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types'
    resp = api_client.get(url)
    assert resp.status_code == 200
    data = resp.json()
    assert 'data' in data
    types_list = data['data']
    alarm_type = None
    for item in types_list:
        if item.get('label') == '告警规则类型':
            children = item.get('children', [])
            if children:
                alarm_type = children[0]['value']
                break
    if alarm_type is None:
        for item in types_list:
            if 'children' in item and item['children']:
                alarm_type = item['children'][0]['value']
                break
    assert alarm_type is not None, '无法获取有效的alarm_type'
    return alarm_type

@pytest.fixture
def create_rule_for_test(api_client, alarm_type_value):
    """创建一个用于验证的告警规则，返回 id 和标题，测试结束后清理"""
    create_url = '/api/plugins/com.andisec.plugins.alarm/events/definitions'
    payload = {'title': '测试告警规则', 'description': '用于搜索和删除测试', 'priority': 3, 'config': {'conditions': {}, 'execute_every_ms': 60000, 'group_by': [], 'query': '告警', 'query_parameters': [], 'search_within_ms': 60000, 'series': [], 'streams': [], 'type': 'aggregation-v1'}, 'restrain': None, 'field_spec': {}, 'key_spec': [], 'notification_settings': {'grace_period_ms': 60000, 'backlog_size': None}, 'notifications': [], 'alert': False, 'credibility': 3, 'check_type': 'elasticsearch', 'alarm_type': alarm_type_value, 'disposal_advice': '请检查相关日志', 'check_query': True}
    resp = api_client.post(create_url, json=payload)
    assert resp.status_code == 200, f'创建规则失败: {resp.text}'
    data = resp.json()
    assert 'id' in data, '响应中没有id字段'
    rule_id = data['id']
    yield {'id': rule_id, 'title': '测试告警规则'}
    delete_url = f'/api/plugins/com.andisec.plugins.alarm/events/definitions/{rule_id}'
    del_resp = api_client.delete(delete_url)
    assert del_resp.status_code in (200, 204, 404), f'清理删除规则失败: {del_resp.status_code}'

@pytest.fixture
def created_module(api_client):
    """复制告警事件定义"""
    resp = api_client.post('/api/plugins/com.andisec.plugins.alarm/events/definitions', json={'body': {'id': 'valid-source-definition-id', 'title': '复制规则-测试', 'description': '用于测试的复制规则', 'priority': 3, 'alert': False, 'config': {'type': 'aggregation-v1', 'query': 'plugin_id:100004 OR plugin_sid:14', 'query_parameters': [], 'streams': ['000000000000000000000001'], 'group_by': [], 'series': [], 'conditions': {'expression': None}, 'search_within_ms': 60000, 'execute_every_ms': 60000}, 'field_spec': {}, 'key_spec': [], 'notification_settings': {'grace_period_ms': 0, 'backlog_size': 0}, 'notifications': [], 'storage': [{'type': 'persist-to-streams-v1', 'streams': ['000000000000000000000002']}], 'credibility': 3, 'alarm_type': 7001, 'status': False, 'monitor': {}, 'restrain': [], 'check_type': 'elasticsearch', 'check_query': False}})
    assert resp.status_code == 200
    data = resp.json()
    assert 'data' in data
    resource_id = data['data'].get('id') or data['data'].get('session_id')
    assert resource_id is not None
    yield resource_id
    cleanup_resp = api_client.delete(f'/api/plugins/com.andisec.plugins.alarm/events/definitions/{resource_id}')
    assert cleanup_resp.status_code in (200, 204, 404), f'清理失败 id={resource_id}, status={cleanup_resp.status_code}'

@pytest.fixture(scope='function')
def created_template(api_client):
    """创建告警通知模板，提供模板数据用于后续测试，teardown时自动删除"""
    req_body = {'title': 'test告警通知模板', 'config': {'subject': '告警通知: ${event_definition_title}', 'user_recipients': ['superadmin'], 'body_template': '--- [告警内容] ---------------------------\n标题:       ${event_definition_title}\n描述: ${event_definition_description}\n类型:        ${event_definition_type}\n--- [事件] --------------------------------------\n时间:            ${event.timestamp}\n消息:              ${event.message}\n来源:               ${event.source}\n关键字:                  ${event.key}\n优先级:             ${event.priority}\n字段内容:\n${foreach event.fields field}  ${field.key}: ${field.value}\n${end}\n${if backlog}\n--- [原始日志] ------------------------------------\n此告警关联的原始日志:\n${foreach backlog message}\n${message}\n${end}\n${end}\n', 'type': 'email-notification-v1'}, 'description': ''}
    resp = api_client.post('/api/plugins/com.andisec.plugins.alarm/events/notifications', json=req_body)
    assert resp.status_code == 200, f'创建模板失败，状态码{resp.status_code}'
    data = resp.json()
    assert 'id' in data, '创建模板响应缺少id'
    assert data['title'] == req_body['title']
    template_id = data['id']
    yield data
    resp_del = api_client.delete(f'/api/plugins/com.andisec.plugins.alarm/events/notifications/{template_id}')
    assert resp_del.status_code in (200, 204, 404), f'清理模板{template_id}失败，状态码{resp_del.status_code}'

@pytest.fixture(scope='function')
def selectfield_data(api_client):
    """获取变更记录筛选字段数据，供后续列表查询使用"""
    resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/changeRecord/selectfield')
    assert resp.status_code == 200, f'获取筛选字段失败，状态码{resp.status_code}'
    data = resp.json()
    assert data['type'] == 'success', '筛选字段接口返回type不为success'
    assert 'data' in data, '筛选字段接口返回缺少data'
    assert isinstance(data['data'], list), '筛选字段data应为列表'
    yield data['data']