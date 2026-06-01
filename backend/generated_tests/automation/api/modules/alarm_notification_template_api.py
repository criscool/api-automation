"""
alarm_notification_template API 封装
自动生成 — 请勿手动修改
"""


def notification(client, params=None, **kwargs):
    """告警通知列表"""
    return client.get("/api/plugins/com.andisec.plugins.alarm/events/notifications", params=params, **kwargs)

def notification(client, body=None, **kwargs):
    """创建告警通知模板"""
    return client.post("/api/plugins/com.andisec.plugins.alarm/events/notifications", json=body, **kwargs)

def notification(client, body=None, **kwargs):
    """测试告警通知"""
    return client.post("/api/plugins/com.andisec.plugins.alarm/events/notifications/:id/test", json=body, **kwargs)

def notification(client, **kwargs):
    """删除告警通知"""
    return client.delete("/api/plugins/com.andisec.plugins.alarm/events/notifications/:id", **kwargs)
