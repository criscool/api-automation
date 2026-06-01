"""
search API 封装
自动生成 — 请勿手动修改
"""


def list(client, body=None, **kwargs):
    """未知资产列表"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/UnKnowAsset/unknowasset/entries", json=body, **kwargs)

def module(client, **kwargs):
    """未知资产筛选字段"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/UnKnowAsset/selectfield", **kwargs)
