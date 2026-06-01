"""
alarm_disposal API 封装
自动生成 — 请勿手动修改
"""


def module(client, **kwargs):
    """事件实体类型"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/entity_types", **kwargs)

def search(client, body=None, **kwargs):
    """告警列表搜索"""
    return client.post("/api/plugins/com.andisec.plugins.alarm/events/searchv2", json=body, **kwargs)

def module(client, **kwargs):
    """告警筛选标签"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/alarm/labels", **kwargs)

def module(client, body=None, **kwargs):
    """处置告警"""
    return client.post("/api/plugins/com.andisec.plugins.alarm/events/dispose", json=body, **kwargs)

def detail(client, **kwargs):
    """告警详情"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/detailV2/:id", **kwargs)

def module(client, **kwargs):
    """告警调查类型"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/investigate/type/:id", **kwargs)

def data(client, **kwargs):
    """告警调查聚合数据"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/investigate/:id/aggregation-v1", **kwargs)
