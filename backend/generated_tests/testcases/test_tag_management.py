import pytest

pytestmark = [pytest.mark.标签管理, pytest.mark.api]


class TestAssetTagManagement:
    """标签管理模块接口测试"""

    def test_get_default_asset_tag_list(self, api_client):
        """获取默认标签分组-正向：验证成功获取内置默认标签分组列表（业务/环境/地点）"""
        # 请求体为空JSON对象
        resp = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/getDefaultAssetTagList", json={})
        
        # A级断言：状态码
        assert resp.status_code == 200, f"预期状态码200，实际{resp.status_code}"
        
        # A级断言：响应Content-Type包含application/json
        assert "application/json" in resp.headers.get("Content-Type", ""), "响应Content-Type应包含application/json"
        
        # 解析响应体
        data = resp.json()
        assert "type" in data, "响应JSON必须包含type字段"
        assert "data" in data, "响应JSON必须包含data字段"
        assert "msg" in data, "响应JSON必须包含msg字段"
        assert data["type"] == "success", "响应type应为success"
        
        # B级断言：响应类型断言
        result = data["data"]
        assert isinstance(result, list), "data字段应该是列表"
        
        # B级断言：列表元素断言（默认至少包含业务/环境/地点三个分组）
        assert len(result) >= 3, f"预期至少3个默认分组，实际{len(result)}"
        for item in result:
            assert "_id" in item, "分组缺少_id字段"
            assert "name" in item, "分组缺少name字段"
            assert "fixed_name" in item, "分组缺少fixed_name字段"
            assert "desc" in item, "分组缺少desc字段"

    def test_get_asset_tag_list(self, api_client):
        """获取标签列表-正向：使用有效的分组ID分页查询标签列表，验证能正常获取标签数据"""
        # 前置步骤：获取默认标签分组，提取第一个分组的ID
        resp_default = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/getDefaultAssetTagList", json={})
        assert resp_default.status_code == 200
        default_data = resp_default.json()
        assert "data" in default_data and isinstance(default_data["data"], list) and len(default_data["data"]) > 0
        p_id = default_data["data"][0]["_id"]
        
        # 请求体：使用动态获取的分组ID进行查询
        req_body = {
            "query": f"pId:{p_id}",
            "fullText": "标签",
            "per_page": 20,
            "page": 1,
            "order": ""
        }
        resp = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/getAssetTagList", json=req_body)
        
        # A级断言：状态码
        assert resp.status_code == 200, f"预期状态码200，实际{resp.status_code}"
        
        # A级断言：响应Content-Type包含application/json
        assert "application/json" in resp.headers.get("Content-Type", ""), "响应Content-Type应包含application/json"
        
        # 解析响应体
        data = resp.json()
        assert "type" in data, "响应JSON必须包含type字段"
        assert "data" in data, "响应JSON必须包含data字段"
        assert "msg" in data, "响应JSON必须包含msg字段"
        assert data["type"] == "success", "响应type应为success"
        
        # B级断言：响应类型断言
        result = data["data"]
        assert isinstance(result, dict), "data字段应该是字典"
        assert "total_page" in result, "缺少total_page字段"
        assert "total_num" in result, "缺少total_num字段"
        assert "list" in result, "缺少list字段"
        
        # B级断言：列表元素断言
        tag_list = result["list"]
        assert isinstance(tag_list, list), "list字段应该是列表"
        if len(tag_list) > 0:
            for tag in tag_list:
                assert "_id" in tag, "标签缺少_id字段"
                assert "name" in tag, "标签缺少name字段"
                # 验证查询条件：返回的标签pId应与查询一致
                assert tag["pId"] == p_id, f"标签pId应为{p_id}，实际{tag['pId']}"

    def test_add_asset_tag(self, api_client):
        """新增标签-正向：在有效的默认分组下新增标签，验证标签创建成功并返回相关数据"""
        # 前置步骤：获取默认标签分组，提取第一个分组的ID
        resp_default = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/getDefaultAssetTagList", json={})
        assert resp_default.status_code == 200
        default_data = resp_default.json()
        assert "data" in default_data and isinstance(default_data["data"], list) and len(default_data["data"]) > 0
        p_id = default_data["data"][0]["_id"]
        
        # 请求体：创建标签
        tag_name = "测试标签_001"
        req_body = {
            "pId": p_id,
            "name": tag_name,
            "desc": "正向测试新增标签"
        }
        resp = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/addAssetTag", json=req_body)
        
        # A级断言：状态码
        assert resp.status_code == 200, f"预期状态码200，实际{resp.status_code}"
        
        # A级断言：响应Content-Type包含application/json
        assert "application/json" in resp.headers.get("Content-Type", ""), "响应Content-Type应包含application/json"
        
        # 解析响应体
        data = resp.json()
        assert "type" in data, "响应JSON必须包含type字段"
        assert "data" in data, "响应JSON必须包含data字段"
        assert "msg" in data, "响应JSON必须包含msg字段"
        assert data["type"] == "success", "响应type应为success"
        
        # B级断言：响应类型断言（新增标签返回的是标签ID字符串）
        tag_id = data["data"]
        assert isinstance(tag_id, str), "新增标签返回的data应为字符串（标签ID）"
        assert len(tag_id) > 0, "标签ID不应为空"
        
        # 资源清理：删除刚创建的标签
        delete_body = {"_ids": [tag_id]}
        resp_delete = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/deleteAssetTag", json=delete_body)
        # 清理接口允许200/204/404
        assert resp_delete.status_code in (200, 204, 404), f"清理标签{tag_id}失败，状态码{resp_delete.status_code}"

    def test_delete_asset_tag(self, api_client):
        """删除标签-正向：使用有效的标签ID列表批量删除标签，验证删除成功"""
        # 前置步骤1：获取默认标签分组ID
        resp_default = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/getDefaultAssetTagList", json={})
        assert resp_default.status_code == 200
        default_data = resp_default.json()
        assert "data" in default_data and isinstance(default_data["data"], list) and len(default_data["data"]) > 0
        p_id = default_data["data"][0]["_id"]
        
        # 前置步骤2：创建测试标签
        create_body = {
            "pId": p_id,
            "name": "删除测试标签",
            "desc": "用于删除测试"
        }
        resp_create = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/addAssetTag", json=create_body)
        assert resp_create.status_code == 200
        create_data = resp_create.json()
        assert "data" in create_data and isinstance(create_data["data"], str)
        tag_id = create_data["data"]
        
        # 正式测试：删除标签
        delete_body = {"_ids": [tag_id]}
        resp = api_client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/assetTag/deleteAssetTag", json=delete_body)
        
        # A级断言：状态码
        assert resp.status_code == 200, f"预期状态码200，实际{resp.status_code}"
        
        # A级断言：响应Content-Type包含application/json
        assert "application/json" in resp.headers.get("Content-Type", ""), "响应Content-Type应包含application/json"
        
        # 解析响应体
        data = resp.json()
        assert "type" in data, "响应JSON必须包含type字段"
        assert "data" in data, "响应JSON必须包含data字段"
        assert "msg" in data, "响应JSON必须包含msg字段"
        assert data["type"] == "success", "响应type应为success"
        # 验证删除成功消息
        assert data["data"] == "删除成功" or "删除成功" in str(data["data"]), f"删除响应data应为'删除成功'，实际为{data['data']}"
        
        # 资源清理已在测试步骤中完成，无需额外清理