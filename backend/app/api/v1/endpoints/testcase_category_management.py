"""
用例分类管理 API
- 自动提取：从 ApiInterface 数据推导分类树
- 树维护：增删改移分类节点
- 用例移动：单条/批量移动用例到指定分类
"""
import uuid
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger

from app.models.api_automation import (
    TestCaseCategory,
    TestCase,
    ApiInterface,
)
from app.services.api_automation.category_matcher import (
    auto_classify_all,
    build_category_tree_for_prompt,
)
from app.core.types import AgentTypes
from app.agents.factory import agent_factory, AgentPlatform

router = APIRouter(tags=["用例分类管理"])


# ==================== 请求模型 ====================

class CreateCategoryRequest(BaseModel):
    name: str = Field(..., description="分类名称")
    parent_id: Optional[str] = Field(None, description="父节点 category_id，空则创建根节点")
    description: str = Field("", description="描述")


class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = Field(None, description="新名称")
    parent_id: Optional[str] = Field(None, description="新父节点 category_id，空则移到根")
    sort_order: Optional[int] = Field(None, description="排序值")
    match_rule: Optional[str] = Field(None, description="路径匹配规则(glob)，如 /**/assetbase/knowasset/**")


# ==================== 工具函数 ====================

async def _build_tree_node(cat: TestCaseCategory) -> Dict[str, Any]:
    """递归构建单个树节点，含子节点和用例统计"""
    children = await TestCaseCategory.filter(
        parent=cat, is_active=True
    ).order_by("sort_order", "name").all()

    child_nodes = []
    child_count = 0
    for child in children:
        node = await _build_tree_node(child)
        child_nodes.append(node)
        child_count += node["testcase_count"]

    direct_count = await TestCase.filter(category=cat, is_active=True).count()
    total = direct_count + child_count

    parent_category_id = None
    if cat.parent_id:
        parent_cat = await TestCaseCategory.filter(id=cat.parent_id).first()
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
        "testcase_count": total,
        "direct_testcase_count": direct_count,
        "children": child_nodes,
        "created_at": cat.created_at.isoformat() if cat.created_at else None,
    }


async def _recalc_levels(start_node: TestCaseCategory):
    """递归重算 level：父 level + 1"""
    if start_node.parent_id:
        parent = await TestCaseCategory.filter(id=start_node.parent_id).first()
        new_level = (parent.level + 1) if parent else 0
    else:
        new_level = 0

    if start_node.level != new_level:
        start_node.level = new_level
        await start_node.save(update_fields=["level"])

    children = await TestCaseCategory.filter(parent=start_node, is_active=True).all()
    for child in children:
        await _recalc_levels(child)


# ==================== 自动提取 ====================

async def _extract_meaningful_segments(path: str) -> list:
    """从接口路径提取有意义的分段（去掉通用前缀）"""
    segments = [s for s in path.strip("/").split("/") if s]
    # 尝试识别并去掉插件命名空间前缀
    # 形如: api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/list
    # 去掉通用前缀后返回: assetbase, knowasset, list
    plugin_idx = -1
    for i, seg in enumerate(segments):
        if seg == "plugins" and i + 1 < len(segments):
            plugin_idx = i + 1
            break
    if plugin_idx >= 0 and plugin_idx + 1 < len(segments):
        # 跳过 plugin 名称段 (com.andisec.plugins.xxx)
        return segments[plugin_idx + 1:]
    # fallback: 尝试去掉 api 前缀
    if segments and segments[0] == "api":
        segments = segments[1:]
    # 跳过公认的冗余段
    skip_prefixes = ["v1", "v2", "rest"]
    while segments and segments[0] in skip_prefixes:
        segments = segments[1:]
    return segments


@router.post("/auto-extract", summary="从接口自动提取分类树")
async def auto_extract_tree(doc_id: Optional[str] = Query(None, description="按文档筛选，不传则全量")):
    """根据 ApiInterface 路径结构自动生成建议分类树"""
    try:
        query = ApiInterface.filter(is_active=True)
        if doc_id:
            from app.models.api_automation import ApiDocument
            doc = await ApiDocument.filter(doc_id=doc_id).first()
            if not doc:
                raise HTTPException(status_code=404, detail="文档不存在")
            query = query.filter(document=doc)

        interfaces = await query.prefetch_related("document").all()
        if not interfaces:
            return {"code": 200, "msg": "无可用接口", "data": {"suggested_tree": [], "uncategorized": []}}

        # 按路径段聚类
        path_groups: Dict[str, Dict] = {}  # key=level0 路径段, value={name, children: {l1: {name, children: {l2: ...}}}}

        for iface in interfaces:
            segs = await _extract_meaningful_segments(iface.path)
            if not segs:
                continue

            l0 = segs[0] if len(segs) > 0 else "__root__"
            l1 = segs[1] if len(segs) > 1 else "__default__"
            l2 = segs[2] if len(segs) > 2 else "__default__"

            if l0 not in path_groups:
                path_groups[l0] = {"name": l0, "apis": [], "children": {}}
            path_groups[l0]["apis"].append(iface)

            if l1 not in path_groups[l0]["children"]:
                path_groups[l0]["children"][l1] = {"name": l1, "apis": [], "children": {}}
            path_groups[l0]["children"][l1]["apis"].append(iface)

            if l2 not in path_groups[l0]["children"][l1]["children"]:
                path_groups[l0]["children"][l1]["children"][l2] = {"name": l2, "apis": []}
            path_groups[l0]["children"][l1]["children"][l2]["apis"].append(iface)

        # 构建建议树
        suggested_tree = []
        for l0_key in sorted(path_groups.keys()):
            l0_data = path_groups[l0_key]
            l0_name = _best_name(l0_data["apis"], l0_data["name"])
            l0_node = {
                "key": f"auto_{uuid.uuid4().hex[:8]}",
                "name": l0_name,
                "level": 0,
                "api_count": len(set(a.interface_id for a in l0_data["apis"])),
                "children": [],
            }

            l0_children = l0_data["children"]
            # L1 只有 __default__ → 叶子节点
            if len(l0_children) == 1 and "__default__" in l0_children:
                l0_node["interface_ids"] = [a.interface_id for a in l0_data["apis"]]
                suggested_tree.append(l0_node)
                continue

            for l1_key in sorted(l0_children.keys()):
                if l1_key == "__default__":
                    continue
                l1_data = l0_children[l1_key]
                l1_name = _best_name(l1_data["apis"], l1_data["name"])
                l1_node = {
                    "key": f"auto_{uuid.uuid4().hex[:8]}",
                    "name": l1_name,
                    "level": 1,
                    "api_count": len(set(a.interface_id for a in l1_data["apis"])),
                    "children": [],
                }

                l2_children = l1_data["children"]
                has_l2 = any(k != "__default__" for k in l2_children)

                if has_l2:
                    for l2_key in sorted(l2_children.keys()):
                        if l2_key == "__default__":
                            continue
                        l2_data = l2_children[l2_key]
                        l2_name = _best_name(l2_data["apis"], l2_data["name"])
                        l1_node["children"].append({
                            "key": f"auto_{uuid.uuid4().hex[:8]}",
                            "name": l2_name,
                            "level": 2,
                            "api_count": len(set(a.interface_id for a in l2_data["apis"])),
                            "interface_ids": [a.interface_id for a in l2_data["apis"]],
                        })
                else:
                    l1_node["interface_ids"] = [a.interface_id for a in l1_data["apis"]]

                l0_node["children"].append(l1_node)

            suggested_tree.append(l0_node)

        return {
            "code": 200,
            "msg": "OK",
            "data": {"suggested_tree": suggested_tree},
            "success": True,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"自动提取分类树失败: {e}")
        raise HTTPException(status_code=500, detail=f"提取失败: {e}")


def _best_name(apis: list, fallback: str) -> str:
    """从接口列表中取最有代表性的名称（优先 tags，其次路径段自身）"""
    if not apis:
        return fallback
    all_tags = []
    for a in apis:
        if a.tags:
            all_tags.extend(a.tags)
    if all_tags:
        from collections import Counter
        tag_counts = Counter(all_tags)
        most_common = tag_counts.most_common(1)
        if most_common:
            return most_common[0][0]
    return fallback


# ==================== 树 CRUD ====================

@router.get("/tree", summary="获取完整分类树（含用例数统计）")
async def get_category_tree(include_empty: bool = Query(True, description="是否包含空节点")):
    """返回完整分类树，每个节点包含子树用例总数"""
    try:
        roots = await TestCaseCategory.filter(
            parent_id__isnull=True, is_active=True
        ).order_by("sort_order", "name").all()

        tree = []
        classified_total = 0
        for root in roots:
            node = await _build_tree_node(root)
            if include_empty or node["testcase_count"] > 0:
                tree.append(node)
                classified_total += node["testcase_count"]

        uncategorized_count = await TestCase.filter(category_id__isnull=True, is_active=True).count()
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
    """创建新分类节点。parent_id 为空则创建根节点。同名同父节点已存在则跳过。"""
    try:
        parent = None
        level = 0
        if req.parent_id:
            parent = await TestCaseCategory.filter(
                category_id=req.parent_id, is_active=True
            ).first()
            if not parent:
                raise HTTPException(status_code=404, detail="父节点不存在")
            level = parent.level + 1

        # 去重：同名同父已存在则直接返回
        existing = await TestCaseCategory.filter(
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

        max_sort = await TestCaseCategory.filter(
            parent=parent, is_active=True
        ).count()

        cat = await TestCaseCategory.create(
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
    """编辑分类名称、父节点或排序"""
    try:
        cat = await TestCaseCategory.filter(
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
                new_parent = await TestCaseCategory.filter(
                    category_id=req.parent_id, is_active=True
                ).first()
                if not new_parent:
                    raise HTTPException(status_code=404, detail="目标父节点不存在")
                # 防止环
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
    """删除分类：子节点上移一级（挂到当前节点的父节点），用例变未分类"""
    try:
        cat = await TestCaseCategory.filter(
            category_id=category_id, is_active=True
        ).first()
        if not cat:
            raise HTTPException(status_code=404, detail="分类不存在")

        # 子节点上移
        cat_parent_id = cat.parent_id
        children = await TestCaseCategory.filter(parent=cat, is_active=True).all()
        for child in children:
            child.parent_id = cat_parent_id
            await child.save()
            await _recalc_levels(child)

        # 用例变未分类
        await TestCase.filter(category=cat).update(category_id=None)

        # 软删除
        cat.is_active = False
        await cat.save()

        return {"code": 200, "msg": "删除成功", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除分类失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")


# ==================== 智能推荐 + 自动归类 ====================

class ApplyRecommendationsRequest(BaseModel):
    """应用推荐规则请求"""
    rules: list = Field(..., description="[{category_id, match_rule}]")


@router.post("/recommend-rules", summary="LLM 智能推荐分类匹配规则")
async def recommend_rules(doc_id: Optional[str] = Query(None, description="按文档筛选接口")):
    """调用 CategoryRuleRecommenderAgent，为分类节点推荐 glob 匹配规则"""
    try:
        # 查全部分类树（扁平化为 prompt 友好格式）
        roots = await TestCaseCategory.filter(
            parent_id__isnull=True, is_active=True
        ).order_by("sort_order", "name").prefetch_related("children").all()
        flat_cats = await build_category_tree_for_prompt(roots)

        # 查全部接口
        query = ApiInterface.filter(is_active=True)
        if doc_id:
            query = query.filter(document__doc_id=doc_id)
        interfaces = await query.all()
        iface_list = [
            {
                "interface_id": i.interface_id,
                "path": i.path,
                "method": i.method.value if hasattr(i.method, "value") else str(i.method),
                "tags": i.tags or [],
                "summary": i.summary or "",
            }
            for i in interfaces
        ]

        # 创建 Agent 并调用
        agent = await agent_factory.create_agent(
            AgentTypes.CATEGORY_RULE_RECOMMENDER.value,
            platform=AgentPlatform.API_AUTOMATION,
        )
        result = await agent.recommend(flat_cats, iface_list, stream=False)

        return {"code": 200, "msg": "OK", "data": result, "success": True}

    except Exception as e:
        logger.error(f"推荐规则失败: {e}")
        raise HTTPException(status_code=500, detail=f"推荐失败: {e}")


@router.post("/apply-recommendations", summary="应用推荐规则到分类节点")
async def apply_recommendations(req: ApplyRecommendationsRequest):
    """将前端确认后的规则批量写入分类节点的 match_rule 字段"""
    try:
        updated = 0
        for item in req.rules:
            cat_id = item.get("category_id")
            rule = item.get("match_rule")
            if not cat_id:
                continue
            cat = await TestCaseCategory.filter(category_id=cat_id, is_active=True).first()
            if cat:
                cat.match_rule = rule if rule else None
                await cat.save(update_fields=["match_rule"])
                updated += 1

        return {"code": 200, "msg": f"已更新 {updated} 个分类", "data": {"updated_count": updated}, "success": True}

    except Exception as e:
        logger.error(f"应用推荐规则失败: {e}")
        raise HTTPException(status_code=500, detail=f"应用失败: {e}")


@router.post("/auto-classify", summary="一键归类：按现有规则匹配所有未分类用例")
async def auto_classify():
    """扫描所有未分类用例，按 match_rule 匹配并更新 category_id"""
    try:
        result = await auto_classify_all()
        return {"code": 200, "msg": f"已归类 {result['classified_count']} 条用例", "data": result, "success": True}

    except Exception as e:
        logger.error(f"一键归类失败: {e}")
        raise HTTPException(status_code=500, detail=f"归类失败: {e}")
