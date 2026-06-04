"""
situation_dashboard API 封装
自动生成 — 请勿手动修改
"""


def screen_alarm(client, **kwargs):
    """态势大屏-告警皮肤"""
    return client.get("/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/less/0", **kwargs)

def screen_asset(client, body=None, **kwargs):
    """态势大屏-资产分布"""
    return client.post("/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/assetDistribution", json=body, **kwargs)

def screen_host(client, body=None, **kwargs):
    """态势大屏-主机分布"""
    return client.post("/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/hostDistribution", json=body, **kwargs)

def screen_alarm(client, body=None, **kwargs):
    """态势大屏-实时告警汇总"""
    return client.post("/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/realTimeAlarmSum", json=body, **kwargs)
