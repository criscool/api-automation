"""
strategy_crud API 封装
自动生成 — 请勿手动修改
"""


def filter(client, **kwargs):
    """策略筛选字段"""
    return client.get("/api/plugins/com.andisec.plugins.strategy/strategy/selectfield", **kwargs)

def search(client, **kwargs):
    """搜索对象数据"""
    return client.get("/api/plugins/com.andisec.plugins.strategy/strategy/searchObjectData", **kwargs)

def list(client, body=None, **kwargs):
    """策略类型列表"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/strategyType/list", json=body, **kwargs)

def list(client, body=None, **kwargs):
    """网络列表"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/networkList", json=body, **kwargs)

def list(client, body=None, **kwargs):
    """开放端口列表"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/openPortList", json=body, **kwargs)

def list_whitelist(client, body=None, **kwargs):
    """策略模板列表（端口白名单）"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategyTemplate/list", json=body, **kwargs)

def post_strategy_add(client, body=None, **kwargs):
    """新增策略"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/add", json=body, **kwargs)

def list_add(client, body=None, **kwargs):
    """策略列表（新增后刷新）"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/list", json=body, **kwargs)

def list_search(client, body=None, **kwargs):
    """策略列表（全文搜索）"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/list", json=body, **kwargs)

def update(client, body=None, **kwargs):
    """修改策略状态"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/modifyStrategyStatus", json=body, **kwargs)

def delete(client, body=None, **kwargs):
    """删除策略"""
    return client.post("/api/plugins/com.andisec.plugins.strategy/strategy/delete", json=body, **kwargs)
