"""资产清点-软件列表接口测试"""
import pytest
pytestmark = [pytest.mark.asset_software, pytest.mark.api]

class TestAssetSoftwareList:
    """资产清点-软件列表接口测试类"""

    def test_get_software_list(self, api_client):
        """测试软件列表查询的基本功能"""
        payload = {'page': 1, 'per_page': 20, 'query': ''}
        resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getsoftwarelist', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        result = data['data']
        assert isinstance(result, dict)
        assert 'total_page' in result
        assert 'total_num' in result
        assert 'list' in result
        assert isinstance(result['list'], list)
        if len(result['list']) > 0:
            item = result['list'][0]
            assert 'software_name' in item
            assert 'software_version' in item
            assert 'publisher' in item
            assert 'install_number' in item
            assert 'install_rate' in item
            assert 'key' in item
            assert 'software_category' in item
            assert isinstance(item['software_name'], str)
            assert isinstance(item['install_number'], int)

    def test_get_software_info(self, api_client):
        """测试软件终端详情的基本功能"""
        list_payload = {'page': 1, 'per_page': 20, 'query': ''}
        list_resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getsoftwarelist', json=list_payload)
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data['type'] == 'success'
        software_list = list_data['data']['list']
        if len(software_list) > 0:
            query_key = software_list[0]['key']
        else:
            query_key = 'f191789d1a2e81cfd1f86577fdb9f03a'
        payload = {'page': 1, 'per_page': 20, 'query': query_key}
        resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getsoftwareinfo', json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        result = data['data']
        assert isinstance(result, dict)
        assert 'total_page' in result
        assert 'total_num' in result
        assert 'list' in result
        assert isinstance(result['list'], list)
        if len(result['list']) > 0:
            item = result['list'][0]
            assert 'asset_name' in item
            assert 'asset_ip' in item
            assert 'guid' in item
            assert 'network_card' in item
            assert isinstance(item['asset_name'], str)
            assert isinstance(item['network_card'], list)
            if len(item['network_card']) > 0:
                nc = item['network_card'][0]
                assert 'ip' in nc
                assert 'mac' in nc

    def test_select_fields_for_asset(self, api_client):
        """测试终端筛选字段的基本功能"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/selectFieldsForAsset')
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            field_item = result[0]
            assert 'label' in field_item
            assert 'value' in field_item
            assert 'list' in field_item
            assert isinstance(field_item['label'], str)
            assert isinstance(field_item['value'], str)
            assert isinstance(field_item['list'], list)
            if len(field_item['list']) > 0:
                option = field_item['list'][0]
                assert 'label' in option
                assert 'value' in option
                assert 'count' in option
                assert isinstance(option['count'], int)

    def test_select_fields_for_soft(self, api_client):
        """测试软件筛选字段的基本功能"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/selectFieldsForSoft')
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            field_item = result[0]
            assert 'label' in field_item
            assert 'value' in field_item
            assert 'list' in field_item
            assert isinstance(field_item['label'], str)
            assert isinstance(field_item['value'], str)
            assert isinstance(field_item['list'], list)
            if len(field_item['list']) > 0:
                option = field_item['list'][0]
                assert 'label' in option
                assert 'value' in option
                assert 'count' in option
                assert isinstance(option['count'], int)

    def test_get_software_type_asset_summary(self, api_client):
        """测试终端类型统计接口 - 正向用例"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getSoftwareTypeAssetSummary')
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'label' in item
            assert 'total' in item
            assert 'value' in item
            assert isinstance(item['label'], str)
            assert isinstance(item['total'], int)

    def test_get_software_type_software_summary(self, api_client):
        """测试软件类型统计接口 - 正向用例"""
        resp = api_client.get('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getSoftwareTypeSoftwareSummary')
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        result = data['data']
        assert isinstance(result, list)
        if len(result) > 0:
            item = result[0]
            assert 'label' in item
            assert 'total' in item
            assert 'value' in item
            assert isinstance(item['label'], str)
            assert isinstance(item['total'], int)

    def test_post_get_asset_list(self, api_client):
        """测试终端列表查询接口 - 正向用例"""
        request_body = {'page': 1, 'per_page': 20, 'query': ''}
        resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getassetlist', json=request_body)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        result = data['data']
        assert isinstance(result, dict)
        assert 'total_page' in result
        assert 'total_num' in result
        assert 'list' in result
        assert isinstance(result['list'], list)
        if len(result['list']) > 0:
            asset_item = result['list'][0]
            assert 'asset_name' in asset_item
            assert 'asset_ip' in asset_item
            assert 'software_count' in asset_item
            assert 'guid' in asset_item
            assert isinstance(asset_item['asset_name'], str)
            assert isinstance(asset_item['software_count'], int)

    def test_post_get_asset_info(self, api_client):
        """测试终端软件详情接口 - 正向用例"""
        list_resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getassetlist', json={'page': 1, 'per_page': 20, 'query': ''})
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert 'data' in list_data
        assert 'list' in list_data['data']
        asset_list = list_data['data']['list']
        if len(asset_list) > 0:
            query_guid = asset_list[0]['guid']
        else:
            query_guid = '46D51377EC23F7DD6F53C690D3684888'
        request_body = {'page': 1, 'per_page': 20, 'query': query_guid}
        resp = api_client.post('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getassetinfo', json=request_body)
        assert resp.status_code == 200
        data = resp.json()
        assert 'type' in data
        assert data['type'] == 'success'
        assert 'data' in data
        assert 'msg' in data
        result = data['data']
        assert isinstance(result, dict)
        assert 'total_page' in result
        assert 'total_num' in result
        assert 'list' in result
        assert isinstance(result['list'], list)
        if len(result['list']) > 0:
            software_item = result['list'][0]
            assert 'software_name' in software_item
            assert 'software_version' in software_item
            assert 'publisher' in software_item
            assert 'key' in software_item
            assert 'software_category' in software_item
            assert isinstance(software_item['software_name'], str)
            assert isinstance(software_item['software_version'], str)