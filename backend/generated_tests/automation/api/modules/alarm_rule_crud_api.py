"""
alarm_rule_crud API 封装
自动生成 — 请勿手动修改
"""


def module(client, **kwargs):
    """告警规则筛选标签"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions/alarm/types", **kwargs)

def detail(client, **kwargs):
    """事件定义详情"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions/:id/with-context", **kwargs)

def module(client, body=None, params=None, **kwargs):
    """复制告警事件定义"""
    return client.post("/api/plugins/com.andisec.plugins.alarm/events/definitions", json=body, params=params, **kwargs)

def list(client, params=None, **kwargs):
    """事件定义列表"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/definitions", params=params, **kwargs)

def delete(client, **kwargs):
    """删除事件定义"""
    return client.delete("/api/plugins/com.andisec.plugins.alarm/events/definitions/:id", **kwargs)
