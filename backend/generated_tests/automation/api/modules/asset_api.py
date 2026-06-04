"""
asset API 封装
自动生成 — 请勿手动修改
"""


def list(client, body=None, **kwargs):
    """网段列表"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/AssetNetworkSegment/asset/networksegment/entries", json=body, **kwargs)

def filter(client, **kwargs):
    """网段筛选字段"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/AssetNetworkSegment/asset/networksegment/select", **kwargs)

def data(client, **kwargs):
    """网段关联数据"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/AssetNetworkSegment/asset/networksegment/relation", **kwargs)

def add_edit(client, body=None, **kwargs):
    """新增/编辑网段"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/AssetNetworkSegment/asset/networksegment/entry/save", json=body, **kwargs)

def detail(client, body=None, **kwargs):
    """网段关联资产详情"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/AssetNetworkSegment/asset/networksegment/entry", json=body, **kwargs)

def delete(client, body=None, **kwargs):
    """删除网段"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/AssetNetworkSegment/asset/networksegment/entry/delete", json=body, **kwargs)
