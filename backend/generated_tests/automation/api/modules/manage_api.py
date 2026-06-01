"""
manage API 封装
自动生成 — 请勿手动修改
"""


def module(client, body=None, **kwargs):
    """启用资产"""
    return client.put("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/hangupandstop", json=body, **kwargs)
