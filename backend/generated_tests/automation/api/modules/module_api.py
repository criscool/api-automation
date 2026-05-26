"""
module API 封装
自动生成 — 请勿手动修改
"""


def modulewebsocketmodule(client, **kwargs):
    """获取WebSocket地址"""
    return client.get("/api/plugins/org.tianxiang.plugins.workflow/workflow/check/getwebsocket", **kwargs)

def module(client, body=None, **kwargs):
    """安全评分"""
    return client.post("/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/safetyScore", json=body, **kwargs)

def module(client, body=None, **kwargs):
    """安全态势"""
    return client.post("/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/safetySituation", json=body, **kwargs)

def module(client, body=None, **kwargs):
    """资产等级漏洞分布"""
    return client.post("/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/getVulnerabilityOfAssetGrade", json=body, **kwargs)

def module(client, body=None, **kwargs):
    """资产区域漏洞分布"""
    return client.post("/api/plugins/com.andisec.situation.zy/Asset/ComprehensiveScreen/getVulnerabilityOfAssetArea", json=body, **kwargs)

def list(client, body=None, **kwargs):
    """资产列表"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list", json=body, **kwargs)

def module(client, body=None, **kwargs):
    """实时告警数量"""
    return client.post("/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/realTimeAlarmNum", json=body, **kwargs)

def module(client, body=None, **kwargs):
    """攻击地图"""
    return client.post("/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/attackMap", json=body, **kwargs)

def module(client, body=None, **kwargs):
    """流量协议信息"""
    return client.post("/api/plugins/com.andisec.situation.zy/Alarm/ComprehensiveScreen/trafficProtocolInfo", json=body, **kwargs)

def search(client, body=None, **kwargs):
    """告警规则搜索"""
    return client.post("/api/plugins/com.andisec.plugins.alarm/events/definitions/search", json=body, **kwargs)

def list(client, **kwargs):
    """告警类型列表"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types", **kwargs)

def create(client, body=None, params=None, **kwargs):
    """创建告警规则"""
    return client.post("/api/plugins/com.andisec.plugins.alarm/events/definitions", json=body, params=params, **kwargs)

def delete(client, **kwargs):
    """删除告警规则"""
    return client.delete("/api/plugins/com.andisec.plugins.alarm/events/definitions/:id", **kwargs)
