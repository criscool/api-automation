"""
asset_list API 封装
自动生成 — 请勿手动修改
"""


def query(client, body=None, **kwargs):
    """进程列表查询"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/getlist", json=body, **kwargs)

def filter(client, **kwargs):
    """进程筛选字段"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/selectFieldsForData", **kwargs)

def filter(client, **kwargs):
    """终端筛选字段"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/selectFieldsForAsset", **kwargs)

def query(client, body=None, **kwargs):
    """终端列表查询"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/getassetlist", json=body, **kwargs)

def detail(client, body=None, **kwargs):
    """进程详情"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/getInfo", json=body, **kwargs)

def detail(client, body=None, **kwargs):
    """终端详情"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/KnowAssetSystemProcessResource/getassetinfo", json=body, **kwargs)
