"""
初始化用例分类结构并自动归类
用法：python init_categories.py
"""
import asyncio
import uuid
from tortoise import Tortoise
from app.settings.config import settings


CATEGORY_TREE = [
    {
        "name": "告警",
        "match_rule": "**/com.andisec.plugins.alarm/**",
        "children": [
            {
                "name": "告警规则管理",
                "match_rule": "**/events/definitions/**",
            },
            {
                "name": "告警处置",
                "match_rule": "**/events/searchv2**",
            },
            {
                "name": "告警通知模板",
                "match_rule": "**/events/notifications/**",
            },
        ],
    },
    {
        "name": "资产管理",
        "match_rule": "**/com.andisec.plugins.assetbase/**",
        "children": [
            {
                "name": "资产清单",
                "match_rule": "**/knowasset/**",
            },
            {
                "name": "未知资产",
                "match_rule": "**/UnKnowAsset/**",
            },
            {
                "name": "标签管理",
                "match_rule": "**/assetTag/**",
            },
            {
                "name": "变更记录",
                "match_rule": "**/changeRecord/**",
            },
        ],
    },
]


async def create_category(name, match_rule, parent=None, level=0, sort_order=0):
    from app.models.api_automation import TestCaseCategory
    existing = await TestCaseCategory.filter(name=name, parent=parent, is_active=True).first()
    if existing:
        print(f"  {'  ' * level}[已存在] {name}")
        return existing
    cat = await TestCaseCategory.create(
        category_id=str(uuid.uuid4()),
        name=name,
        match_rule=match_rule or "",
        parent=parent,
        level=level,
        sort_order=sort_order,
        is_active=True,
    )
    print(f"  {'  ' * level}[创建] {name}  (rule: {match_rule})")
    return cat


async def auto_classify():
    """按 match_rule 自动归类所有用例"""
    from app.models.api_automation import TestCaseCategory, TestCase
    import fnmatch

    categories = await TestCaseCategory.filter(is_active=True).all()
    # 只用叶子节点（有 match_rule 的）做匹配
    leaf_cats = [c for c in categories if c.match_rule]

    test_cases = await TestCase.filter(is_active=True).all()
    classified = 0
    for tc in test_cases:
        # 从关联接口获取 path
        path = ""
        if tc.endpoint_id:
            from app.models.api_automation import ApiInterface
            iface = await ApiInterface.filter(id=tc.endpoint_id).first()
            if iface:
                path = iface.path or ""

        if not path:
            continue

        # 找最深匹配的分类（level 最大的）
        best = None
        for cat in leaf_cats:
            rule = cat.match_rule
            if rule and fnmatch.fnmatch(path, rule):
                if best is None or cat.level > best.level:
                    best = cat

        if best and tc.category_id != best.id:
            tc.category = best
            await tc.save(update_fields=["category_id"])
            classified += 1

    print(f"\n自动归类完成：{classified} 条用例已归类")


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)

    print("创建分类结构...")
    for i, root_def in enumerate(CATEGORY_TREE):
        root = await create_category(
            root_def["name"], root_def.get("match_rule", ""),
            parent=None, level=0, sort_order=i
        )
        for j, child_def in enumerate(root_def.get("children", [])):
            await create_category(
                child_def["name"], child_def.get("match_rule", ""),
                parent=root, level=1, sort_order=j
            )

    print("\n开始自动归类用例...")
    await auto_classify()

    await Tortoise.close_connections()
    print("\n完成！刷新前端用例管理页面查看结果。")


if __name__ == "__main__":
    asyncio.run(main())
