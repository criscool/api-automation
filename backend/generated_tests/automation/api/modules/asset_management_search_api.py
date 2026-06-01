"""
asset_management_search API 封装
自动生成 — 请勿手动修改
"""


def detail(client, params=None, **kwargs):
    """资产详情"""
    return client.get("/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/showinfo", params=params, **kwargs)
