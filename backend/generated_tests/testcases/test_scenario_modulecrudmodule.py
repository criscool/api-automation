"""策略CRUD完整生命周期（场景测试，自动生成）

获取下拉选项 → 新增策略 → 搜索验证 → 禁用 → 删除 → 确认清空。add 不返回 _id，需通过 list 刷新后按 strategy_name 匹配提取。
"""
import pytest
from automation.core.utils.scenario_helpers import apply_data_in, extract_data_out, render_path, run_assert
pytestmark = [pytest.mark.strategy_crud, pytest.mark.scenario]

class TestScenarioModulecrudmodule:
    """策略CRUD完整生命周期"""

    def test_chain(self, api_client):
        """获取下拉选项 → 新增策略 → 搜索验证 → 禁用 → 删除 → 确认清空。add 不返回 _id，需通过 list 刷新后按 strategy_name 匹配提取。"""
        ctx: dict = {}
        body, query, path = apply_data_in({}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/selectfield', {}), {}, ctx)
        resp = api_client.get(path, params=query or None)
        assert resp.status_code == 200, f'step 1 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx[1] = {'dataOut': extract_data_out(resp_json, {'strategyTypeId': {'path': "response.data[?(@.value=='strategy_type_id')].list[0].value", 'exampleValue': '6497e000ae5100003e0ef5bb', 'note': '策略类别默认值（默认）'}, 'ruleTypeList': {'path': "response.data[?(@.value=='rule_type')].list[*].value", 'exampleValue': ['1', '2', '3', '4', '5', '8', '10', '11', '20', '21', '22'], 'note': '所有可用规则类型'}})}
        body, query, path = apply_data_in({}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/searchObjectData', {}), {}, ctx)
        resp = api_client.get(path, params=query or None)
        assert resp.status_code == 200, f'step 2 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx[2] = {'dataOut': extract_data_out(resp_json, {'tagGroupId': {'path': 'response.data.assetTagGroupList[0].value', 'exampleValue': '69e0a8f559e44250c045ff2f', 'note': '第一个标签分组的 value，用于 networkList/openPortList/add 的 group_id/tag_group_id'}, 'assetIds': {'path': 'response.data.assetList[*].value', 'exampleValue': ['69e0a8e959e44250c045ff1c'], 'note': '可用资产 ID 列表'}, 'networkIds': {'path': 'response.data.networkList[*].value', 'exampleValue': ['6a0182715e5b1b422224ba4f'], 'note': '可用网段 ID 列表'}})}
        body, query, path = apply_data_in({'per_page': 1000, 'query': '', 'fullText': '', 'page': 1, 'order': ''}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/strategyType/list', {}), {}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 3 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx[3] = {'dataOut': extract_data_out(resp_json, {'strategyTypeIdAlt': {'path': 'response.data.list[0]._id', 'exampleValue': '6497e000ae5100003e0ef5bb', 'note': '策略类型 _id，与 step1 的 strategyTypeId 交叉验证'}})}
        body, query, path = apply_data_in({'asset_id': [], 'network_id': [], 'group_id': ['69e0a8f559e44250c045ff2f']}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/networkList', {}), {'body.group_id[0]': {'from': 'step:2.dataOut.tagGroupId', 'exampleValue': '69e0a8f559e44250c045ff2f'}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 4 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(4, {'dataOut': {}})
        body, query, path = apply_data_in({'asset_id': [], 'network_id': [], 'group_id': ['69e0a8f559e44250c045ff2f']}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/openPortList', {}), {'body.group_id[0]': {'from': 'step:2.dataOut.tagGroupId', 'exampleValue': '69e0a8f559e44250c045ff2f'}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 5 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(5, {'dataOut': {}})
        body, query, path = apply_data_in({'fullText': '', 'order': {}, 'page': 1, 'per_page': 1000, 'query': "rule_type:'1'"}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategyTemplate/list', {}), {'body.query': {'from': 'step:1.dataOut.ruleTypeList', 'value': "rule_type:'1'", 'note': "取 rule_type='1'（端口白名单），按实际需要可替换为其他值"}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 6 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(6, {'dataOut': {}})
        body, query, path = apply_data_in({'_id': '', 'strategy_name': 'test新增策略', 'strategy_source': 1, 'strategy_type_id': '6497e000ae5100003e0ef5bb', 'priority_level': 5, 'is_execute': 1, 'frequency': '', 'time': '', 'hour': '', 'deadline': '', 'strategy_status': 1, 'description': '', 'rule_type': 1, 'rule_info': ['1880'], 'asset_id': [], 'network_id': [], 'tag_group_id': ['69e0a8f559e44250c045ff2f'], 'strategy_template_id': [], 'network_rule_info': [], 'soft_lib_id': []}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/add', {}), {'body.strategy_type_id': {'from': 'step:1.dataOut.strategyTypeId', 'exampleValue': '6497e000ae5100003e0ef5bb'}, 'body.tag_group_id[0]': {'from': 'step:2.dataOut.tagGroupId', 'exampleValue': '69e0a8f559e44250c045ff2f'}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 7 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(7, {'dataOut': {}})
        run_assert(resp_json, {'equals': {'in': 'response.type', 'equalsValue': 'success', 'note': '确认新增成功返回'}}, ctx, step_no=7)
        body, query, path = apply_data_in({'page': 1, 'per_page': 20, 'query': '', 'fullText': '', 'order': {}}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/list', {}), {}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 8 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx[8] = {'dataOut': extract_data_out(resp_json, {'newStrategyId': {'path': "response.data.list[?(@.strategy_name=='test新增策略')]._id", 'exampleValue': '6a1fd3ca5e5b1b422245da91', 'note': '按策略名称匹配提取 _id，用于后续禁用和删除'}, 'newStrategyStatus': {'path': "response.data.list[?(@.strategy_name=='test新增策略')].strategy_status", 'exampleValue': 1, 'note': '确认新增后状态为 1（启用）'}})}
        run_assert(resp_json, {'equals': {'in': "response.data.list[?(@.strategy_name=='test新增策略')].strategy_status", 'equalsValue': 1, 'note': '确认新策略状态为启用'}}, ctx, step_no=8)
        body, query, path = apply_data_in({'page': 1, 'per_page': 20, 'query': '', 'fullText': 'test新增策略', 'order': {}}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/list', {}), {'body.fullText': {'value': 'test新增策略', 'note': '搜索关键词，建议加时间戳避免多环境冲突'}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 9 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(9, {'dataOut': {}})
        run_assert(resp_json, {'gte': {'in': 'response.data.total_num', 'gteValue': 1, 'note': '搜索结果至少包含 1 条'}}, ctx, step_no=9)
        body, query, path = apply_data_in({'ids': ['6a1fd3ca5e5b1b422245da91'], 'status': 2}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/modifyStrategyStatus', {}), {'body.ids[0]': {'from': 'step:8.dataOut.newStrategyId', 'exampleValue': '6a1fd3ca5e5b1b422245da91'}, 'body.status': {'value': 2, 'note': '固定值 2 表示禁用。1=启用, 2=禁用'}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 10 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(10, {'dataOut': {}})
        run_assert(resp_json, {'equals': {'in': 'response.type', 'equalsValue': 'success', 'note': '确认状态修改成功'}}, ctx, step_no=10)
        body, query, path = apply_data_in({'page': 1, 'per_page': 20, 'query': '', 'fullText': 'test新增策略', 'order': {}}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/list', {}), {'body.fullText': {'value': 'test新增策略', 'note': '与 step9 相同的关键词'}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 11 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(11, {'dataOut': {}})
        run_assert(resp_json, {'equals': {'in': 'response.data.list[0].strategy_status', 'equalsValue': 2, 'note': '确认状态已变更为禁用(2)'}}, ctx, step_no=11)
        body, query, path = apply_data_in({'entities': ['6a1fd3ca5e5b1b422245da91']}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/delete', {}), {'body.entities[0]': {'from': 'step:8.dataOut.newStrategyId', 'exampleValue': '6a1fd3ca5e5b1b422245da91'}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 12 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(12, {'dataOut': {}})
        run_assert(resp_json, {'equals': {'in': 'response.type', 'equalsValue': 'success', 'note': '确认删除成功'}}, ctx, step_no=12)
        body, query, path = apply_data_in({'page': 1, 'per_page': 20, 'query': '', 'fullText': 'test新增策略', 'order': {}}, {}, render_path('/api/plugins/com.andisec.plugins.strategy/strategy/list', {}), {'body.fullText': {'value': 'test新增策略'}}, ctx)
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f'step 13 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(13, {'dataOut': {}})
        run_assert(resp_json, {'equals': {'in': 'response.data.total_num', 'equalsValue': '0', 'note': '确认策略已被删除，搜索结果为 0'}}, ctx, step_no=13)