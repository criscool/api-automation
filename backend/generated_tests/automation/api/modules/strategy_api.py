"""
strategy API 封装
自动生成 — 请勿手动修改
"""


def post_strategy_add(client, body=None, **kwargs):
    """新增策略"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/add", json=body, **kwargs)

def list(client, body=None, **kwargs):
    """策略列表"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/list", json=body, **kwargs)

def update(client, body=None, **kwargs):
    """修改策略状态"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/modifyStrategyStatus", json=body, **kwargs)

def delete(client, body=None, **kwargs):
    """删除策略"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/delete", json=body, **kwargs)
