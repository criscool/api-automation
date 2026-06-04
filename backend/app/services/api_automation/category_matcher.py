"""
分类匹配服务 — 确定性的 glob 路径匹配逻辑
不依赖 LLM，供流水线和 API 端点复用
"""
import fnmatch
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger

from app.models.api_automation import TestCaseCategory, TestCase, ApiInterface


def glob_match(rule: str, path: str) -> bool:
    """glob 匹配，支持 ** 跨段通配"""
    path_norm = path.strip("/").lower()
    rule_norm = rule.strip("/").lower()
    return fnmatch.fnmatch(path_norm, rule_norm)


async def get_category_rules() -> List[Tuple[TestCaseCategory, str]]:
    """获取所有有匹配规则的活跃分类（rule, 规则路径段数）"""
    cats = await TestCaseCategory.filter(
        match_rule__not_isnull=True, is_active=True
    ).all()
    return [(cat, cat.match_rule) for cat in cats if cat.match_rule]


async def match_category_for_path(path: str) -> Optional[TestCaseCategory]:
    """为单个接口路径匹配最佳分类（最长前缀优先）"""
    rules = await get_category_rules()
    if not rules:
        return None

    best_cat = None
    best_score = -1
    for cat, rule in rules:
        if glob_match(rule, path):
            score = rule.count("/")
            if score > best_score:
                best_score = score
                best_cat = cat

    return best_cat


async def auto_assign_category(test_case, api_interface) -> bool:
    """为单个 TestCase 自动分配分类。返回 True 表示已分类"""
    if not api_interface or not api_interface.path:
        return False

    cat = await match_category_for_path(api_interface.path)
    if cat:
        test_case.category_id = cat.id
        await test_case.save(update_fields=["category_id"])
        return True
    return False


async def auto_classify_all() -> Dict[str, Any]:
    """全量一键归类：扫描所有未分类用例，按规则匹配并更新"""
    try:
        rules = await get_category_rules()
        if not rules:
            return {"classified_count": 0, "skipped_count": 0, "message": "无可用规则"}

        # 查所有未分类的活跃用例
        uncategorized = await TestCase.filter(
            category_id__isnull=True, is_active=True
        ).prefetch_related("endpoint").all()

        classified = 0
        skipped = 0
        details = []

        for tc in uncategorized:
            endpoint = tc.endpoint
            if not endpoint or not endpoint.path:
                skipped += 1
                continue

            cat = await match_category_for_path(endpoint.path)
            if cat:
                tc.category_id = cat.id
                await tc.save(update_fields=["category_id"])
                classified += 1
                details.append({
                    "test_id": tc.test_id,
                    "name": tc.name,
                    "path": endpoint.path,
                    "category_id": cat.category_id,
                    "category_name": cat.name,
                })

        logger.info(f"一键归类完成: {classified} 已分类, {len(uncategorized) - classified - skipped} 未匹配")
        return {
            "classified_count": classified,
            "skipped_count": skipped,
            "unmatched_count": len(uncategorized) - classified - skipped,
            "total_uncategorized": len(uncategorized),
            "details": details[:100],  # 最多返回前 100 条明细
        }

    except Exception as e:
        logger.error(f"一键归类失败: {e}", exc_info=True)
        raise


async def build_category_tree_for_prompt(categories) -> List[Dict[str, Any]]:
    """将分类树扁平化为 prompt 友好的格式"""
    from app.models.api_automation import TestCaseCategory
    result = []

    async def walk(nodes, parent_path=""):
        for n in nodes:
            path = f"{parent_path}/{n.name}" if parent_path else n.name
            if hasattr(n, 'children'):
                children = await TestCaseCategory.filter(parent=n, is_active=True).all()
            else:
                children = n.get("children") or []
            has_children = bool(children)
            result.append({
                "category_id": n.category_id if hasattr(n, 'category_id') else n.get("category_id"),
                "name": n.name if hasattr(n, 'name') else n.get("name"),
                "path": path,
                "level": n.level if hasattr(n, 'level') else n.get("level", 0),
                "has_children": has_children,
                "match_rule": n.match_rule if hasattr(n, 'match_rule') else n.get("match_rule"),
            })
            if has_children:
                await walk(children, path)

    await walk(categories)
    return result
