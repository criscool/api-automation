"""
UI 自动化用例分类管理 API
- 分类树维护：增删改移
- 脚本移动：单条/批量移入分类
- 自动提取：从脚本 base_url 域名建议分类
- 自动归类：按 match_rule 匹配未分类脚本
"""
import uuid
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger

from app.models.ui_automation import UiTestCaseCategory, UiTestScript

router = APIRouter(tags=["UI自动化-用例分类"])


# ==================== 请求模型 ====================

class CreateCategoryRequest(BaseModel):
    name: str = Field(..., description="分类名称")
    parent_id: Optional[str] = Field(None, description="父节点 category_id，空则创建根节点")
    description: str = Field("", description="描述")


class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = Field(None, description="新名称")
    parent_id: Optional[str] = Field(None, description="新父节点 category_id，空则移到根")
    sort_order: Optional[int] = Field(None, description="排序值")
    match_rule: Optional[str] = Field(None, description="域名匹配规则(glob)，如 *172.16.8.190*")


# ==================== 工具函数 ====================

async def _build_tree_node(cat: UiTestCaseCategory) -> Dict[str, Any]:
    """递归构建单个树节点，含子节点和脚本统计"""
    children = await UiTestCaseCategory.filter(
        parent=cat, is_active=True
    ).order_by("sort_order", "name").all()

    child_nodes = []
    child_count = 0
    for child in children:
        node = await _build_tree_node(child)
        child_nodes.append(node)
        child_count += node["script_count"]

    direct_count = await UiTestScript.filter(category=cat).exclude(status="archived").count()
    total = direct_count + child_count

    parent_category_id = None
    if cat.parent_id:
        parent_cat = await UiTestCaseCategory.filter(id=cat.parent_id).first()
        if parent_cat:
            parent_category_id = parent_cat.category_id

    return {
        "category_id": cat.category_id,
        "name": cat.name,
        "level": cat.level,
        "sort_order": cat.sort_order,
        "description": cat.description,
        "match_rule": cat.match_rule,
        "parent_category_id": parent_category_id,
        "script_count": total,
        "direct_script_count": direct_count,
        "children": child_nodes,
        "created_at": cat.created_at.isoformat() if cat.created_at else None,
    }


async def _recalc_levels(start_node: UiTestCaseCategory):
    """递归重算 level：父 level + 1"""
    if start_node.parent_id:
        parent = await UiTestCaseCategory.filter(id=start_node.parent_id).first()
        new_level = (parent.level + 1) if parent else 0
    else:
        new_level = 0

    if start_node.level != new_level:
        start_node.level = new_level
        await start_node.save(update_fields=["level"])

    children = await UiTestCaseCategory.filter(parent=start_node, is_active=True).all()
    for child in children:
        await _recalc_levels(child)


async def _get_category_subtree_ids(category_id: str) -> List[int]:
    """递归获取指定分类及其所有子分类的数据库 id"""
    cat = await UiTestCaseCategory.filter(category_id=category_id, is_active=True).first()
    if not cat:
        return []
    ids = [cat.id]
    children = await UiTestCaseCategory.filter(parent=cat, is_active=True).all()
    for child in children:
        child_ids = await _get_category_subtree_ids(child.category_id)
        ids.extend(child_ids)
    return ids


# ==================== 树 CRUD ====================

@router.get("/tree", summary="获取完整分类树（含脚本数统计）")
async def get_category_tree(include_empty: bool = Query(True, description="是否包含空节点")):
    """返回完整分类树，每个节点包含子树脚本总数"""
    try:
        roots = await UiTestCaseCategory.filter(
            parent_id__isnull=True, is_active=True
        ).order_by("sort_order", "name").all()

        tree = []
        classified_total = 0
        for root in roots:
            node = await _build_tree_node(root)
            if include_empty or node["script_count"] > 0:
                tree.append(node)
                classified_total += node["script_count"]

        uncategorized_count = await UiTestScript.filter(
            category_id__isnull=True
        ).exclude(status="archived").count()
        total_count = classified_total + uncategorized_count

        return {
            "code": 200,
            "msg": "OK",
            "data": {
                "tree": tree,
                "uncategorized_count": uncategorized_count,
                "total_count": total_count,
            },
            "success": True,
        }
    except Exception as e:
        logger.error(f"获取分类树失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取树失败: {e}")


@router.post("", summary="创建分类节点")
@router.post("/", summary="创建分类节点", include_in_schema=False)
async def create_category(req: CreateCategoryRequest):
    """创建新分类节点。parent_id 为空则创建根节点。同名同父已存在则跳过。"""
    try:
        parent = None
        level = 0
        if req.parent_id:
            parent = await UiTestCaseCategory.filter(
                category_id=req.parent_id, is_active=True
            ).first()
            if not parent:
                raise HTTPException(status_code=404, detail="父节点不存在")
            level = parent.level + 1

        # 去重：同名同父已存在则直接返回
        existing = await UiTestCaseCategory.filter(
            name=req.name, parent=parent, is_active=True
        ).first()
        if existing:
            return {
                "code": 200,
                "msg": "已存在，跳过创建",
                "data": {
                    "category_id": existing.category_id,
                    "name": existing.name,
                    "level": existing.level,
                    "sort_order": existing.sort_order,
                },
                "success": True,
            }

        max_sort = await UiTestCaseCategory.filter(
            parent=parent, is_active=True
        ).count()

        cat = await UiTestCaseCategory.create(
            category_id=str(uuid.uuid4()),
            name=req.name,
            parent=parent,
            sort_order=max_sort,
            level=level,
            description=req.description,
        )

        return {
            "code": 200,
            "msg": "创建成功",
            "data": {
                "category_id": cat.category_id,
                "name": cat.name,
                "level": cat.level,
                "sort_order": cat.sort_order,
            },
            "success": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建分类失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败: {e}")


@router.put("/{category_id}", summary="编辑分类")
async def update_category(category_id: str, req: UpdateCategoryRequest):
    """编辑分类名称、父节点、排序或匹配规则"""
    try:
        cat = await UiTestCaseCategory.filter(
            category_id=category_id, is_active=True
        ).first()
        if not cat:
            raise HTTPException(status_code=404, detail="分类不存在")

        if req.name is not None:
            cat.name = req.name
        if req.sort_order is not None:
            cat.sort_order = req.sort_order
        if req.match_rule is not None:
            cat.match_rule = req.match_rule if req.match_rule else None

        parent_changed = False
        if req.parent_id is not None:
            if req.parent_id:
                new_parent = await UiTestCaseCategory.filter(
                    category_id=req.parent_id, is_active=True
                ).first()
                if not new_parent:
                    raise HTTPException(status_code=404, detail="目标父节点不存在")
                if new_parent.id == cat.id:
                    raise HTTPException(status_code=400, detail="不能将自己作为父节点")
                cat.parent_id = new_parent.id
            else:
                cat.parent_id = None
            parent_changed = True

        await cat.save()

        if parent_changed:
            await _recalc_levels(cat)

        return {"code": 200, "msg": "更新成功", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"编辑分类失败: {e}")
        raise HTTPException(status_code=500, detail=f"编辑失败: {e}")


@router.delete("/{category_id}", summary="删除分类")
async def delete_category(category_id: str):
    """删除分类：子节点上移一级，脚本变未分类"""
    try:
        cat = await UiTestCaseCategory.filter(
            category_id=category_id, is_active=True
        ).first()
        if not cat:
            raise HTTPException(status_code=404, detail="分类不存在")

        cat_parent_id = cat.parent_id
        children = await UiTestCaseCategory.filter(parent=cat, is_active=True).all()
        for child in children:
            child.parent_id = cat_parent_id
            await child.save()
            await _recalc_levels(child)

        await UiTestScript.filter(category=cat).update(category_id=None)

        cat.is_active = False
        await cat.save()

        return {"code": 200, "msg": "删除成功", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除分类失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")


# ==================== 自动提取 ====================

@router.post("/auto-extract", summary="从现有脚本 base_url 自动建议分类树")
async def auto_extract_tree():
    """根据 UiTestScript 的 base_url 域名自动生成建议分类树"""
    try:
        scripts = await UiTestScript.filter(is_active=True).exclude(status="archived").all()
        if not scripts:
            return {"code": 200, "msg": "无可用脚本", "data": {"suggested_tree": [], "uncategorized": []}}

        # 按 base_url 提取域名分组
        from urllib.parse import urlparse
        from collections import defaultdict

        domain_groups: Dict[str, List[UiTestScript]] = defaultdict(list)
        for s in scripts:
            url = (s.base_url or "").strip()
            if not url:
                key = "__no_base_url__"
            else:
                try:
                    parsed = urlparse(url)
                    key = parsed.netloc or parsed.hostname or url
                except Exception:
                    key = url
            domain_groups[key].append(s)

        suggested_tree = []
        for domain, group in sorted(domain_groups.items()):
            if domain == "__no_base_url__":
                continue
            node = {
                "key": f"auto_{uuid.uuid4().hex[:8]}",
                "name": _best_domain_name(domain),
                "level": 0,
                "script_count": len(group),
                "domain": domain,
                "sample_scripts": [s.name for s in group[:3]],
            }
            suggested_tree.append(node)

        no_url_count = len(domain_groups.get("__no_base_url__", []))

        return {
            "code": 200,
            "msg": "OK",
            "data": {
                "suggested_tree": suggested_tree,
                "no_base_url_count": no_url_count,
            },
            "success": True,
        }
    except Exception as e:
        logger.error(f"自动提取分类树失败: {e}")
        raise HTTPException(status_code=500, detail=f"提取失败: {e}")


def _best_domain_name(domain: str) -> str:
    """从域名提取可读名称，如 172.16.8.190 → 资产管理系统"""
    # 直接用域名本身，用户可手动改名
    return domain


# ==================== 自动归类 ====================

@router.post("/auto-classify", summary="一键归类：按 match_rule 匹配所有未分类脚本")
async def auto_classify():
    """扫描所有未分类脚本，按分类的 match_rule 匹配并归类"""
    try:
        import fnmatch

        # 获取所有有 match_rule 的分类
        categories = await UiTestCaseCategory.filter(
            is_active=True, match_rule__not_isnull=True
        ).exclude(match_rule="").all()

        if not categories:
            return {
                "code": 200,
                "msg": "没有配置匹配规则的分类",
                "data": {"classified_count": 0, "details": []},
                "success": True,
            }

        uncategorized = await UiTestScript.filter(
            category_id__isnull=True
        ).exclude(status="archived").all()

        classified = 0
        details = []
        for script in uncategorized:
            rule_matched = None
            for cat in categories:
                if cat.match_rule and fnmatch.fnmatch(
                    script.base_url or "", cat.match_rule
                ):
                    rule_matched = cat
                    break
            if rule_matched:
                script.category = rule_matched
                await script.save(update_fields=["category_id"])
                classified += 1
                details.append({
                    "script_name": script.name,
                    "category_name": rule_matched.name,
                    "match_rule": rule_matched.match_rule,
                })

        return {
            "code": 200,
            "msg": f"已归类 {classified} 个脚本",
            "data": {"classified_count": classified, "details": details[:50]},
            "success": True,
        }
    except Exception as e:
        logger.error(f"一键归类失败: {e}")
        raise HTTPException(status_code=500, detail=f"归类失败: {e}")
