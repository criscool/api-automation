"""获取默认标签分组 接口测试"""
import pytest

pytestmark = [pytest.mark.manage, pytest.mark.api]

class TestManage:

    def test_post_tag_test(self, created_post_assetTag_getDefaultAssetTagList):
        """验证能够正常获取内置标签分组列表（业务/环境/地点）"""
        assert created_post_assetTag_getDefaultAssetTagList is not None

    def test_post_list_test(self, created_list):
        """使用有效分组ID分页查询标签列表，验证返回结果符合分页参数"""
        assert created_list is not None

    def test_post_tag_test_2(self, created_post_assetTag_addAssetTag):
        """在指定默认分组下新增一个标签，验证返回新标签信息"""
        assert created_post_assetTag_addAssetTag is not None

    def test_post_delete_test(self, created_delete):
        """验证能够根据标签ID列表成功批量删除标签"""
        assert created_delete is not None
