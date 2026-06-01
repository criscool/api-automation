"""资产生命周期 - 完整 CRUD（场景测试，自动生成）

新增资产 → 列表查询 → 删除资产 的完整流程，可作为冒烟测试基线。每个 step 的 endpoint 字段为该步骤完整的 API 规格快照（method/path/pathParams/request/response/bodyShape）。
"""
import pytest

from automation.core.utils.scenario_helpers import (
    apply_data_in,
    extract_data_out,
    render_path,
    run_assert,
)

pytestmark = [pytest.mark.asset_management, pytest.mark.scenario]


class TestScenarioModuleModuleCrud:
    """资产生命周期 - 完整 CRUD"""

    def test_chain(self, api_client):
        """新增资产 → 列表查询 → 删除资产 的完整流程，可作为冒烟测试基线。每个 step 的 endpoint 字段为该步骤完整的 API 规格快照（method/path/pathParams/request/response/bodyShape）。"""
        ctx: dict = {}

        # ============ step 1: 获取资产类型/子类型可选值（用于 add 的 asset_type、asset_subtype） ============
        body, query, path = apply_data_in(
            {},
            {},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/assettype', {}),
            {},
            ctx,
        )
        resp = api_client.get(path, params=query or None)
        assert resp.status_code == 200, f"step 1 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx[1] = {'dataOut': extract_data_out(resp_json, {   'asset_type': {'path': 'response.data[].value', 'exampleValue': 3},
    'asset_subtype': {'path': 'response.data[].children[].value', 'exampleValue': 3001}})}

        # ============ step 2: 获取项目/数据集级联可选值（用于 add 的 asset_project、asset_stream） ============
        body, query, path = apply_data_in(
            {},
            {},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/projectstreamselect', {}),
            {},
            ctx,
        )
        resp = api_client.get(path, params=query or None)
        assert resp.status_code == 200, f"step 2 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx[2] = {'dataOut': extract_data_out(resp_json, {   'asset_project': {   'path': 'response.data[].project_id',
                         'exampleValue': '69e0a5f759e44250c045fa63'},
    'asset_stream': {   'path': 'response.data[].streams[].stream_Id',
                        'exampleValue': '69e0a62159e44250c045fa9a'}})}

        # ============ step 3: 获取标签可选值（用于 add 的 tag1/tag2/tag3，可选字段） ============
        body, query, path = apply_data_in(
            {},
            {},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/taglist', {}),
            {},
            ctx,
        )
        resp = api_client.get(path, params=query or None)
        assert resp.status_code == 200, f"step 3 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx[3] = {'dataOut': extract_data_out(resp_json, {   'tag1': {   'path': 'response.data[fixed_name=tag1].list[]._id',
                'exampleValue': '69e0a8ce59e44250c045fefa'},
    'tag2': {   'path': 'response.data[fixed_name=tag2].list[]._id',
                'exampleValue': '69e0a8db59e44250c045ff0a'},
    'tag3': {   'path': 'response.data[fixed_name=tag3].list[]._id',
                'exampleValue': '69e0a8e359e44250c045ff12'}})}

        # ============ step 4: 用前 3 步获取的值新增资产，返回新资产 _id ============
        body, query, path = apply_data_in(
            {   '_id': '',
                'network_card': [{'ip': '172.27.18.11', 'mac': ''}],
                'asset_name': '添加资产测试',
                'mac': '',
                'asset_project': '69e0a5f759e44250c045fa63',
                'asset_stream': '69e0a62159e44250c045fa9a',
                'asset_area': '',
                'asset_type': 3,
                'asset_subtype': 3001,
                'asset_level': 1,
                'host_guard': 0,
                'host_probe': 0,
                'is_manage': 0,
                'asset_manufacturer': '',
                'asset_model': '',
                'asset_director': '',
                'asset_director_phone': '',
                'asset_os': '',
                'asset_longitude': '',
                'asset_latitude': '',
                'asset_describe': '',
                'host_name': '',
                'uplink_device': '',
                'asset_group': '',
                'tag1': '',
                'tag2': '',
                'tag3': ''},
            {},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/add', {}),
            {   'asset_type': {'from': 'step:1.dataOut.asset_type'},
                'asset_subtype': {'from': 'step:1.dataOut.asset_subtype'},
                'asset_project': {'from': 'step:2.dataOut.asset_project'},
                'asset_stream': {'from': 'step:2.dataOut.asset_stream'},
                'tag1': {'from': 'step:3.dataOut.tag1', 'optional': True},
                'tag2': {'from': 'step:3.dataOut.tag2', 'optional': True},
                'tag3': {'from': 'step:3.dataOut.tag3', 'optional': True}},
            ctx,
        )
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f"step 4 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx[4] = {'dataOut': extract_data_out(resp_json, {'newAssetId': {'path': 'response.data', 'exampleValue': '6a16b1b45e5b1b42223bdc61'}})}

        # ============ step 5: 刷新列表，断言新资产出现在结果中（按 _id 或 asset_name 校验） ============
        body, query, path = apply_data_in(
            {'page': 1, 'per_page': 20, 'query': '', 'fullText': '', 'order': ''},
            {},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list', {}),
            {},
            ctx,
        )
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f"step 5 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(5, {'dataOut': {}})
        run_assert(resp_json, {'find': {'in': 'response.data.list[]._id', 'equalsRef': 'step:4.dataOut.newAssetId'}}, ctx, step_no=5)

        # ============ step 6: 用步骤 4 返回的 _id 删除资产（清理测试数据） ============
        body, query, path = apply_data_in(
            {'entities': ['6a16b1b45e5b1b42223bdc61']},
            {},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/delete', {}),
            {'entities[0]': {'from': 'step:4.dataOut.newAssetId'}},
            ctx,
        )
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f"step 6 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(6, {'dataOut': {}})

        # ============ step 7: 再次查询，断言资产已不存在（验证删除生效） ============
        body, query, path = apply_data_in(
            {'page': 1, 'per_page': 20, 'query': '', 'fullText': '', 'order': ''},
            {},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list', {}),
            {},
            ctx,
        )
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f"step 7 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(7, {'dataOut': {}})
        run_assert(resp_json, {'notFind': {'in': 'response.data.list[]._id', 'equalsRef': 'step:4.dataOut.newAssetId'}}, ctx, step_no=7)

