"""
asset_management API 封装
自动生成 — 请勿手动修改
"""


def module(client, body=None, **kwargs):
    """新增资产"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/add", json=body, **kwargs)

def delete(client, body=None, **kwargs):
    """删除资产"""
    return client.post("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/delete", json=body, **kwargs)
