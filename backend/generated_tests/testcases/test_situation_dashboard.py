"""
态势大屏 接口测试
"""
import pytest
import time

pytestmark = [pytest.mark.situation_dashboard, pytest.mark.api]


class TestSituationDashboard:
    """态势大屏模块接口测试"""

    def test_get_alarm_less_skin_config(self, api_client):
        """
        TC: 3b78912d-a2f0-466d-88b1-4c6e7e59c231
        获取告警极简版皮肤配置-正向-请求成功
        """
        # 路径参数 type=0
        resp = api_client.get('/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/less/0')
        assert resp.status_code == 200
        data = resp.json()
        assert data.get('type') == 'success' or data.get('code') == 200

    def test_get_asset_distribution(self, api_client):
        """
        TC: d8f4e2a1-b3c0-455e-99d2-5a1e2f3b4c5d
        获取资产分布数据-正向-请求成功
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        yesterday = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 86400))
        # 探测发现该接口混合使用 snake_case 和 camelCase
        payload = {
            "time_from": yesterday,
            "time_to": now,
            "streamIds": "000000000000000000000001"
        }
        resp = api_client.post(
            '/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/assetDistribution',
            json=payload
        )
        assert resp.status_code == 200, f"期望200, 实际{resp.status_code}, 响应: {resp.text}"
        data = resp.json()
        assert data.get('type') == 'success'

    def test_get_host_distribution(self, api_client):
        """
        TC: a1b2c3d4-e5f6-4a5b-b6c7-d8e9f0a1b2c3
        获取主机分布数据-正向-请求成功
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        yesterday = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 86400))
        payload = {
            "time_from": yesterday,
            "time_to": now,
            "streamIds": "000000000000000000000001"
        }
        resp = api_client.post(
            '/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/hostDistribution',
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get('type') == 'success'

    def test_get_real_time_alarm_summary(self, api_client):
        """
        TC: f1e2d3c4-b5a6-4978-9012-34567890abcd
        获取实时告警统计数据-正向-请求成功
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        yesterday = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 86400))
        # 该接口强制要求 type 字段
        payload = {
            "time_from": yesterday,
            "time_to": now,
            "streamIds": "000000000000000000000001",
            "type": 0
        }
        resp = api_client.post(
            '/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/realTimeAlarmSum',
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get('type') == 'success'
