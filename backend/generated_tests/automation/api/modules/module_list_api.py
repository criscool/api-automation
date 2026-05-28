"""
module_list API 封装
自动生成 — 请勿手动修改
"""


def statistics(client, **kwargs):
    """终端类型统计"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getSoftwareTypeAssetSummary", **kwargs)

def statistics(client, **kwargs):
    """软件类型统计"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getSoftwareTypeSoftwareSummary", **kwargs)

def detail(client, body=None, **kwargs):
    """终端软件详情"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getassetinfo", json=body, **kwargs)

def query(client, body=None, **kwargs):
    """终端列表查询"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getassetlist", json=body, **kwargs)

def detail(client, body=None, **kwargs):
    """软件终端详情"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getsoftwareinfo", json=body, **kwargs)

def query(client, body=None, **kwargs):
    """软件列表查询"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/getsoftwarelist", json=body, **kwargs)

def module(client, **kwargs):
    """终端筛选字段"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/selectFieldsForAsset", **kwargs)

def module(client, **kwargs):
    """软件筛选字段"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowassetsoftware/selectFieldsForSoft", **kwargs)
