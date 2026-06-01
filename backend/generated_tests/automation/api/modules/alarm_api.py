"""
alarm API 封装
自动生成 — 请勿手动修改
"""


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
