"""上联设备表单选择（场景测试，自动生成）

新增资产时『上联设备』字段的级联查询：先选数据集，再用数据集 stream_Id 查可作为上联的设备
"""
import pytest
from automation.core.utils.scenario_helpers import apply_data_in, extract_data_out, render_path, run_assert
pytestmark = [pytest.mark.asset_management, pytest.mark.scenario]

class TestScenarioModule:
    """上联设备表单选择"""

    def test_chain(self, api_client):
        """新增资产时『上联设备』字段的级联查询：先选数据集，再用数据集 stream_Id 查可作为上联的设备"""
        ctx: dict = {}
        body, query, path = apply_data_in({}, {}, render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/projectstreamselect', {}), {}, ctx)
        resp = api_client.get(path, params=query or None)
        assert resp.status_code == 200, f'step 1 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx[1] = {'dataOut': extract_data_out(resp_json, {'streamId': {'path': 'response.data[0].streams[0].stream_Id', 'exampleValue': '69e0a62159e44250c045fa9a'}})}
        body, query, path = apply_data_in({}, {}, render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/getUplinkDeviceList/:id', {}), {'pathParams.:id': {'from': 'step:1.dataOut.streamId'}}, ctx)
        resp = api_client.get(path, params=query or None)
        assert resp.status_code == 200, f'step 2 status={resp.status_code}, body={resp.text[:200]}'
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(2, {'dataOut': {}})