"""资产详情查看（场景测试，自动生成）

列表行点击进入资产详情侧滑面板的典型下钻流程：先 list 拿到 _id，再 showinfo 拉完整资产信息。
"""
import pytest

from automation.core.utils.scenario_helpers import (
    apply_data_in,
    extract_data_out,
    render_path,
    run_assert,
)

pytestmark = [pytest.mark.asset_management, pytest.mark.scenario]


class TestScenarioDetail:
    """资产详情查看"""

    def test_chain(self, api_client):
        """列表行点击进入资产详情侧滑面板的典型下钻流程：先 list 拿到 _id，再 showinfo 拉完整资产信息。"""
        ctx: dict = {}

        # ============ step 1: 查询资产列表，获取候选 _id ============
        body, query, path = apply_data_in(
            {'page': 1, 'per_page': 20, 'query': '', 'fullText': '', 'order': ''},
            {},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list', {}),
            {},
            ctx,
        )
        resp = api_client.post(path, json=body, params=query or None)
        assert resp.status_code == 200, f"step 1 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx[1] = {'dataOut': extract_data_out(resp_json, {'assetId': {'path': 'response.data.list[0]._id', 'exampleValue': '69e0a8e959e44250c045ff1c'}})}

        # ============ step 2: 用列表返回的 _id 查询资产完整详情（含 software/cpu/memory/disk/backup_time/t ============
        body, query, path = apply_data_in(
            {},
            {'_id': '69e0a8e959e44250c045ff1c'},
            render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/showinfo', {}),
            {'query._id': {'from': 'step:1.dataOut.assetId'}},
            ctx,
        )
        resp = api_client.get(path, params=query or None)
        assert resp.status_code == 200, f"step 2 status={resp.status_code}, body={resp.text[:200]}"
        resp_json = resp.json() if resp.content else {}
        ctx.setdefault(2, {'dataOut': {}})
        run_assert(resp_json, {'equals': {'in': 'response.data._id', 'equalsRef': 'step:1.dataOut.assetId'}}, ctx, step_no=2)

