"""共享业务 fixture（由 ScriptGeneratorAgent 自动生成 + 合并）"""
import pytest
import time

@pytest.fixture
def created_post_assetTag_getDefaultAssetTagList(api_client):
    """获取默认标签分组"""
    resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/getDefaultAssetTagList', json={'body': {}})
    assert resp.status_code == 200
    data = resp.json()
    assert 'data' in data
    resource_id = data['data'].get('id') or data['data'].get('session_id')
    assert resource_id is not None
    return resource_id

@pytest.fixture
def created_list(api_client, created_post_assetTag_getDefaultAssetTagList):
    """获取标签列表"""
    resp = api_client.post(f'/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/getAssetTagList', json={'body': {'query': 'pId:6497e027ae510000360ef5b1', 'fullText': '', 'per_page': 20, 'page': 1, 'order': ''}})
    assert resp.status_code == 200
    data = resp.json()
    assert 'data' in data
    resource_id = data['data'].get('id') or data['data'].get('session_id')
    assert resource_id is not None
    return resource_id

@pytest.fixture
def created_post_assetTag_addAssetTag(api_client, created_list):
    """新增标签"""
    resp = api_client.post(f'/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/addAssetTag', json={'body': {'pId': '6497e027ae510000360ef5b1', 'name': '测试标签', 'desc': '这是一个正向测试标签'}})
    assert resp.status_code == 200
    data = resp.json()
    assert 'data' in data
    resource_id = data['data'].get('id') or data['data'].get('session_id')
    assert resource_id is not None
    return resource_id

@pytest.fixture
def created_delete(api_client, created_post_assetTag_addAssetTag):
    """删除标签"""
    resp = api_client.post(f'/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/deleteAssetTag', json={'body': {'_ids': ['6a182abb5e5b1b42223d7930']}})
    assert resp.status_code == 200
    data = resp.json()
    assert 'data' in data
    resource_id = data['data'].get('id') or data['data'].get('session_id')
    assert resource_id is not None
    return resource_id
ASSET_BASE = '/api/plugins/com.andisec.plugins.assetbase/AssetNetworkSegment/asset/networksegment'

@pytest.fixture(scope='module')
def created_filter(api_client):
    """获取筛选字段可选值，返回第一个字段的 value 供路径参数使用"""
    resp = api_client.get(f'{ASSET_BASE}/select')
    assert resp.status_code == 200, f'获取筛选字段失败: {resp.text[:200]}'
    data = resp.json()
    fields = data.get('data', [])
    assert len(fields) > 0, '筛选字段列表为空'
    return fields[0]['value']

@pytest.fixture(scope='module')
def created_data(api_client):
    """获取关联数据（数据集/网络位置下拉），返回第一个数据集的 value"""
    resp = api_client.get(f'{ASSET_BASE}/relation')
    assert resp.status_code == 200, f'获取关联数据失败: {resp.text[:200]}'
    data = resp.json()
    region = data.get('region_relation', {})
    lst = region.get('list', [])
    assert len(lst) > 0, '关联数据集列表为空'
    return lst[0]['value']

@pytest.fixture(scope='module')
def created_add_edit(api_client):
    """新增一条网段，返回响应；测试结束后尝试删除（清理）"""
    ts = int(time.time())
    name = f'pytest-add-{ts}'
    payload = {'id': '', 'network_segment': f'10.99.{ts % 255}.0/24', 'stream': '69e0a62159e44250c045fa9a', 'network_location': 1, 'network_name': name}
    resp = api_client.post(f'{ASSET_BASE}/entry/save', json=payload)
    assert resp.status_code == 200, f'新增网段失败: {resp.text[:200]}'
    data = resp.json()
    is_success = data.get('type') == 'success' or data.get('code') == 200
    if not is_success and '已存在' in data.get('msg', ''):
        is_success = True
    assert is_success, f'新增网段业务失败: {data}'
    list_resp = api_client.post(f'{ASSET_BASE}/entries', json={'page': 1, 'per_page': 20, 'query': f'network_name:{name}', 'fullText': '', 'order': ''})
    segment_id = None
    if list_resp.status_code == 200:
        res_data = list_resp.json()
        entries = res_data.get('entries') or res_data.get('data', {}).get('entries', [])
        for e in entries:
            if e.get('network_name') == name:
                segment_id = e.get('id')
                break
    yield data
    if segment_id:
        api_client.post(f'{ASSET_BASE}/entry/delete', json=[segment_id])

@pytest.fixture(scope='module')
def created_detail(api_client):
    """查询第一个网段的关联资产列表"""
    list_resp = api_client.post(f'{ASSET_BASE}/entries', json={'page': 1, 'per_page': 1, 'query': '', 'fullText': '', 'order': ''})
    assert list_resp.status_code == 200
    res_data = list_resp.json()
    entries = res_data.get('entries') or res_data.get('data', {}).get('entries', [])
    if not entries:
        pytest.skip('没有可用的网段，跳过关联资产查询测试')
    segment_id = entries[0]['id']
    resp = api_client.post(f'{ASSET_BASE}/entry', json={'page': 1, 'per_page': 20, 'query': '', 'asset_network_segment': segment_id})
    assert resp.status_code == 200, f'查询关联资产失败: {resp.text[:200]}'
    return resp.json()

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
    """复制告警事件定义 (实际上是创建一个带唯一查询的规则)"""
    import time
    ts = int(time.time())
    unique_query = f'plugin_id:100004 OR plugin_sid:14 OR timestamp:{ts}'
    payload = {'title': f'复制规则-测试-{ts}', 'description': '用于测试的复制规则', 'priority': 3, 'alert': False, 'config': {'type': 'aggregation-v1', 'query': unique_query, 'query_parameters': [], 'streams': ['000000000000000000000001'], 'group_by': [], 'series': [], 'conditions': {'expression': None}, 'search_within_ms': 60000, 'execute_every_ms': 60000}, 'field_spec': {}, 'key_spec': [], 'notification_settings': {'grace_period_ms': 0, 'backlog_size': 0}, 'notifications': [], 'storage': [{'type': 'persist-to-streams-v1', 'streams': ['000000000000000000000002']}], 'credibility': 3, 'alarm_type': 7001, 'status': False, 'monitor': {}, 'restrain': [], 'check_type': 'elasticsearch', 'check_query': False}
    resp = api_client.post('/api/plugins/com.andisec.plugins.alarm/events/definitions', json=payload)
    assert resp.status_code == 200, f'创建测试规则失败: {resp.text}'
    data = resp.json()
    target_data = data.get('data') or data
    resource_id = target_data.get('id') or target_data.get('session_id')
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
    is_success = data.get('type') == 'success' or data.get('code') == 200
    assert is_success, '筛选字段接口返回失败'
    target_data = data.get('data')
    assert isinstance(target_data, list), '筛选字段data应为列表'
    yield target_data