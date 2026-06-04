"""资产网段 接口测试"""
import pytest

pytestmark = [pytest.mark.asset, pytest.mark.api]

BASE = "/api/plugins/com.andisec.plugins.assetbase/AssetNetworkSegment/asset/networksegment"

# ============================================================
# 测试用例
# ============================================================

class TestAsset:

    def test_get_filter_test(self, api_client, created_filter):
        """验证获取网段筛选字段可选值，返回200和有效数据结构"""
        resp = api_client.get(f"{BASE}/select")
        assert resp.status_code == 200
        data = resp.json()
        is_success = data.get("type") == "success" or data.get("code") == 200
        assert is_success
        assert isinstance(data.get("data"), list)
        assert len(data["data"]) > 0

    def test_get_data_test(self, api_client, created_data):
        """验证获取网段关联数据（数据集和网络位置下拉）"""
        resp = api_client.get(f"{BASE}/relation")
        assert resp.status_code == 200
        data = resp.json()
        # 兼容处理：有的接口直接返回数据字典，有的包裹在 data 字段中
        target = data.get("data") if "data" in data and isinstance(data["data"], dict) else data
        assert "region_relation" in target
        assert "network_location" in target
        assert len(target["region_relation"]["list"]) > 0

    def test_post_query_param(self, created_list):
        """使用有效默认参数分页查询网段列表"""
        assert created_list is not None
        assert "entries" in created_list
        # 有可能 total 在上一层或者这一层
        assert "total" in created_list or "count" in created_list

    def test_post_query_query(self, api_client):
        """使用有效的查询条件进行分页查询"""
        resp = api_client.post(f"{BASE}/entries", json={
            "page": 1, "per_page": 10, "query": "create_method:1", "fullText": "", "order": ""
        })
        assert resp.status_code == 200
        data = resp.json()
        target = data.get("data") if "data" in data and isinstance(data["data"], dict) else data
        assert "entries" in target

    def test_post_query_query_2(self, api_client):
        """使用 fullText 参数进行全字段模糊搜索"""
        resp = api_client.post(f"{BASE}/entries", json={
            "page": 1, "per_page": 10, "query": "", "fullText": "内网", "order": ""
        })
        assert resp.status_code == 200
        data = resp.json()
        target = data.get("data") if "data" in data and isinstance(data["data"], dict) else data
        assert "entries" in target

    def test_post_add_test(self, created_add_edit):
        """新增网段，验证返回200和成功响应"""
        assert created_add_edit is not None
        is_success = created_add_edit.get("type") == "success" or created_add_edit.get("code") == 200
        assert is_success

    def test_post_edit_test(self, api_client, created_list):
        """编辑已有网段，验证更新成功"""
        entries = created_list.get("entries", [])
        if not entries:
            pytest.skip("没有可用网段，跳过编辑测试")
        segment = entries[0]
        # 修改网段 IP 以避免“网段已存在”错误
        import time
        new_segment = f"10.254.{int(time.time()) % 255}.0/24"
        resp = api_client.post(f"{BASE}/entry/save", json={
            "id": segment["id"],
            "network_segment": new_segment,
            "stream": segment.get("stream_id") or segment.get("stream", ""),
            "network_location": 1,
            "network_name": segment.get("network_name", "") + "_edited"
        })
        assert resp.status_code == 200
        data = resp.json()
        is_success = data.get("type") == "success" or data.get("code") == 200
        assert is_success, f"编辑网段失败: {data}"

    def test_post_query_test(self, created_detail):
        """查询网段关联资产列表，验证分页结构"""
        assert created_detail is not None
        # 这里断言由 fixture 保证，或者在这里检查 detail 内容
        target = created_detail.get("data") if "data" in created_detail and isinstance(created_detail["data"], dict) else created_detail
        assert "entries" in target or "list" in target

    def test_post_delete_test(self, created_delete):
        """删除网段，验证成功"""
        assert created_delete is not None
        is_success = created_delete.get("type") == "success" or created_delete.get("code") == 200
        assert is_success
