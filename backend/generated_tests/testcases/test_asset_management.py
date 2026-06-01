"""定时资产学习 接口测试"""
import pytest
pytestmark = [pytest.mark.asset_management, pytest.mark.api]

class TestAssetManagement:
    """资产管理模块接口测试"""

    def test_sync_asset_success(self, api_client):
        """
        TC: efc3b488-6820-4540-9087-5c22fe44c10f
        同步资产-正向-空body请求成功
        """
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/syncAsset')
        assert resp.status_code == 200
        data = resp.json()
        assert 'code' in data, '响应应包含code字段'
        assert data['code'] == 200
        assert 'message' in data, '响应应包含message字段'
        assert '请求成功' in data['message']
        assert 'data' in data

    def test_get_offline_config_success(self, api_client):
        """
        TC: 5f83213c-7177-4be6-8c90-32a2b868dfb8
        获取离线清理配置-正向-空body获取成功
        """
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/getDelOfflineConf')
        assert resp.status_code == 200
        data = resp.json()
        assert data['type'] == 'success'
        assert 'msg' in data
        assert '获取配置成功' in data['msg']
        assert 'data' in data
        inner = data['data']
        assert isinstance(inner, dict)
        assert 'type' in inner or 'time' in inner

    def test_set_offline_cleanup_success(self, api_client):
        """
        TC: eace47e4-1d4f-4e8f-ada1-95c7ab9461c1
        定时离线清理-正向-设置type=1且有效时间
        """
        resp_get = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/getDelOfflineConf')
        assert resp_get.status_code == 200
        original = resp_get.json()
        resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/deleteOfflineAsset', json={'type': 1, 'cycle1': None, 'time': '14:30'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['type'] == 'success'
        assert '离线资产清理配置完成' in data['msg']
        restore = self._build_restore_payload(original)
        resp_restore = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/deleteOfflineAsset', json=restore)
        assert resp_restore.status_code in (200, 204, 404)

    @staticmethod
    def _build_restore_payload(original_config):
        """
        根据获取到的原始配置构造恢复请求体，
        允许使用静态方法，因为不涉及网络请求。
        """
        try:
            inner = original_config.get('data', {})
            if not isinstance(inner, dict):
                raise ValueError('data 不是字典')
            return {'type': inner.get('type', 1), 'cycle1': inner.get('cycle1'), 'time': inner.get('time', '17:53')}
        except Exception:
            return {'type': 1, 'cycle1': None, 'time': '17:53'}

    def test_get_selectfield(self, api_client):
        """测试资产筛选字段接口"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/selectfield')
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data or 'code' in data
        assert 'data' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'label' in item
            assert 'value' in item
            assert 'list' in item
            assert isinstance(item['list'], list)
            if len(item['list']) > 0:
                list_item = item['list'][0]
                assert 'value' in list_item
                assert 'label' in list_item

    def test_post_customsearch(self, api_client):
        """测试自定义搜索接口"""
        request_body = {'page': 1, 'per_page': 11000, 'query': '', 'order': '', 'fullText': ''}
        resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/customsearch', json=request_body)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data or 'code' in data
        assert 'data' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'label' in item
            assert 'value' in item
            assert 'list' in item
            assert isinstance(item['list'], list)
            if len(item['list']) > 0:
                list_item = item['list'][0]
                assert 'value' in list_item
                assert 'label' in list_item
                assert 'total' in list_item
                assert isinstance(list_item['total'], int)

    def test_get_taglist(self, api_client):
        """测试标签列表接口"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/taglist')
        assert resp.status_code == 200
        data = resp.json()
        assert 'data' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'name' in item
            assert 'list' in item
            assert 'fixed_name' in item
            assert isinstance(item['name'], str)
            assert isinstance(item['list'], list)
            assert item['fixed_name'].startswith('tag')
            if len(item['list']) > 0:
                tag_item = item['list'][0]
                assert '_id' in tag_item
                assert 'name' in tag_item
                assert 'pId' in tag_item

    def test_get_assettype(self, api_client):
        """测试资产类型树接口"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/assettype')
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data or 'code' in data
        assert 'data' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'value' in item
            assert 'label' in item
            assert 'children' in item
            assert isinstance(item['value'], int)
            assert isinstance(item['label'], str)
            assert isinstance(item['children'], list)
            if len(item['children']) > 0:
                child = item['children'][0]
                assert 'value' in child
                assert 'label' in child
                assert isinstance(child['value'], int)
                assert isinstance(child['label'], str)

    def test_get_assetattrs(self, api_client):
        """测试资产属性筛选项接口"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/assetattrs')
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data or 'code' in data
        assert 'data' in data
        result = data['data']
        assert isinstance(result, dict)
        expected_keys = ['asset_project', 'asset_stream', 'is_manage', 'asset_level', 'asset_status']
        for key in expected_keys:
            if key in result:
                attr = result[key]
                assert 'name' in attr
                assert 'list' in attr
                assert isinstance(attr['name'], str)
                assert isinstance(attr['list'], list)
                if len(attr['list']) > 0:
                    list_item = attr['list'][0]
                    assert 'value' in list_item
                    assert 'label' in list_item

    def test_get_projectstreamselect(self, api_client):
        """测试项目数据集级联接口"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/projectstreamselect')
        assert resp.status_code == 200
        data = resp.json()
        assert 'data' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'project_id' in item
            assert 'title' in item
            assert 'streams' in item
            assert isinstance(item['project_id'], str)
            assert isinstance(item['title'], str)
            assert isinstance(item['streams'], list)
            if len(item['streams']) > 0:
                stream = item['streams'][0]
                assert 'stream_Id' in stream
                assert 'title' in stream
                assert isinstance(stream['stream_Id'], str)
                assert isinstance(stream['title'], str)

    def test_get_uplink_device_list(self, api_client):
        """测试上联设备列表接口（先获取资产ID再查询上联设备）"""
        list_resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list', json={'page': 1, 'per_page': 20, 'query': '', 'fullText': '', 'order': ''})
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert 'data' in list_data
        asset_list = list_data['data'].get('list', [])
        if len(asset_list) > 0:
            asset_id = asset_list[0]['_id']
            assert asset_id is not None and asset_id != ''
            resp = api_client.get(f'/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/getUplinkDeviceList/{asset_id}')
            assert resp.status_code == 200
            data = resp.json()
            assert 'type' in data or 'code' in data
            assert 'data' in data
            result = data['data']
            assert isinstance(result, list)
            if len(result) > 0:
                device = result[0]
                assert 'label' in device
                assert 'value' in device
                assert isinstance(device['label'], str)
                assert isinstance(device['value'], str)
        else:
            pytest.skip('No assets available to test uplink device list')

    def test_post_asset_list(self, api_client):
        """测试资产列表查询接口"""
        request_body = {'page': 1, 'per_page': 20, 'query': '', 'fullText': '', 'order': ''}
        resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list', json=request_body)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data or 'code' in data
        assert 'data' in data
        result = data['data']
        assert isinstance(result, dict)
        assert 'total_page' in result
        assert 'total_num' in result
        assert 'list' in result
        assert isinstance(result['list'], list)
        if len(result['list']) > 0:
            asset = result['list'][0]
            assert '_id' in asset
            assert 'asset_name' in asset
            assert 'asset_type' in asset
            assert 'device' in asset
            assert 'asset_status' in asset
            assert 'asset_project' in asset
            assert 'create_time' in asset
            assert isinstance(asset['_id'], str)
            assert isinstance(asset['asset_name'], str)
            assert isinstance(asset['device'], str)

    def test_post_add_asset(self, api_client):
        """测试新增资产的基本功能"""
        add_path = '/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/add'
        delete_path = '/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/delete'
        body = {'_id': '', 'network_card': [{'ip': '172.27.18.11', 'mac': ''}], 'asset_name': '添加资产测试', 'mac': '', 'asset_project': '69e0a5f759e44250c045fa63', 'asset_stream': '69e0a62159e44250c045fa9a', 'asset_area': '', 'asset_type': 3, 'asset_subtype': 3001, 'asset_level': 1, 'host_guard': 0, 'host_probe': 0, 'is_manage': 0, 'asset_manufacturer': '', 'asset_model': '', 'asset_director': '', 'asset_director_phone': '', 'asset_os': '', 'asset_longitude': '', 'asset_latitude': '', 'asset_describe': '', 'host_name': '', 'uplink_device': '', 'asset_group': '', 'tag1': '', 'tag2': '', 'tag3': ''}
        resp = api_client.post(add_path, json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert 'data' in data
        assert 'msg' in data
        assert data['type'] == 'success'
        assert data['msg'] == '添加成功'
        assert isinstance(data['data'], str)
        assert len(data['data']) > 0
        created_asset_id = data['data']
        cleanup_resp = api_client.post(delete_path, json={'entities': [created_asset_id]})
        assert cleanup_resp.status_code in (200, 204, 404)

    def test_post_delete_asset(self, api_client):
        """测试删除资产的基本功能"""
        add_path = '/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/add'
        delete_path = '/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/delete'
        add_body = {'_id': '', 'network_card': [{'ip': '172.27.18.12', 'mac': ''}], 'asset_name': '待删除资产测试', 'mac': '', 'asset_project': '69e0a5f759e44250c045fa63', 'asset_stream': '69e0a62159e44250c045fa9a', 'asset_area': '', 'asset_type': 3, 'asset_subtype': 3001, 'asset_level': 1, 'host_guard': 0, 'host_probe': 0, 'is_manage': 0, 'asset_manufacturer': '', 'asset_model': '', 'asset_director': '', 'asset_director_phone': '', 'asset_os': '', 'asset_longitude': '', 'asset_latitude': '', 'asset_describe': '', 'host_name': '', 'uplink_device': '', 'asset_group': '', 'tag1': '', 'tag2': '', 'tag3': ''}
        add_resp = api_client.post(add_path, json=add_body)
        assert add_resp.status_code == 200
        add_data = add_resp.json()
        assert 'data' in add_data
        assert isinstance(add_data['data'], str)
        assert len(add_data['data']) > 0
        created_asset_id = add_data['data']
        delete_body = {'entities': [created_asset_id]}
        resp = api_client.post(delete_path, json=delete_body)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert 'msg' in data
        assert data['type'] == 'success'
        assert data['msg'] == '删除成功'