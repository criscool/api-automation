"""
分类规则推荐智能体
根据分类树结构 + 接口列表，利用 LLM 为每个分类节点推荐路径匹配规则(glob)
"""
from typing import Dict, List, Any, Optional
from loguru import logger

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.types import AgentTypes


class CategoryRuleRecommenderAgent(BaseApiAutomationAgent):
    """分类规则推荐智能体 — 独立 Agent，不参与流水线 Topic 管道"""

    def __init__(self, **kwargs):
        super().__init__(
            agent_type=AgentTypes.CATEGORY_RULE_RECOMMENDER,
            **kwargs
        )

    async def recommend(
        self,
        categories: List[Dict[str, Any]],
        interfaces: List[Dict[str, Any]],
        stream: bool = True,
    ) -> Dict[str, Any]:
        """
        核心方法：输入分类树 + 接口列表 → LLM 推理 → 输出推荐规则

        Args:
            categories: [{category_id, name, path: "资产/资产清点", level, has_children}]
            interfaces: [{interface_id, path, method, tags, summary}]
            stream: 是否流式推送进度

        Returns:
            {"recommendations": [{category_id, category_path, match_rule, matched_count, sample_paths}]}
        """
        try:
            await self._send_message("正在分析接口路径与分类的对应关系...", "info")

            prompt = self._build_prompt(categories, interfaces)
            result_content = await self._run_assistant_agent(prompt, stream=stream)

            if not result_content:
                logger.warning("LLM 返回空内容，使用 fallback")
                return await self._fallback_recommend(categories, interfaces)

            parsed = self._extract_json_from_content(result_content)
            if not parsed or not isinstance(parsed, list):
                logger.warning("LLM 返回格式异常，使用 fallback")
                return await self._fallback_recommend(categories, interfaces)

            await self._send_message(f"已生成 {len(parsed)} 条推荐规则", "success")
            return {"recommendations": parsed}

        except Exception as e:
            logger.error(f"推荐规则失败: {e}", exc_info=True)
            return await self._fallback_recommend(categories, interfaces)

    def _build_prompt(
        self, categories: List[Dict[str, Any]], interfaces: List[Dict[str, Any]]
    ) -> str:
        cats_json = self._format_categories(categories)
        ifaces_json = self._format_interfaces(interfaces)

        return f"""你是一位 API 测试架构师。请为每个分类节点推荐路径匹配规则(glob 表达式)。

## 分类树结构
{cats_json}

## 全部接口列表（共 {len(interfaces)} 个）
{ifaces_json}

## 规则要求
1. match_rule 是 glob 表达式，用于匹配接口的 path 字段
2. 示例：
   - /**/assetbase/knowasset/** → 匹配 path 中包含 assetbase/knowasset 的接口
   - /**/Alarm/** → 匹配 path 中包含 Alarm 的接口
   - /**/UnKnowAsset/** → 匹配 path 中包含 UnKnowAsset 的接口
3. 优先为叶子节点推荐规则，父节点有子节点覆盖的则不推荐
4. 用接口的 path 段作为主要匹配依据，tags 和 summary 辅助验证
5. 同一接口不应命中两个叶子节点的规则（最长前缀优先由程序处理）
6. 对于纯容器节点（没有直接接口归属），match_rule 留空

## 输出格式
严格输出 JSON 数组，每个元素包含：
[
  {{
    "category_id": "分类ID",
    "category_path": "分类路径（如 资产管理/资产清点）",
    "match_rule": "/**/路径段/**",
    "matched_count": 匹配到的接口数量,
    "sample_paths": ["示例路径1", "示例路径2"]
  }}
]

只输出 JSON 数组，不要加 markdown 代码块或其他说明文字。"""

    def _format_categories(self, categories: List[Dict[str, Any]]) -> str:
        lines = []
        for c in categories:
            indent = "  " * c.get("level", 0)
            leaf = " [叶子]" if not c.get("has_children") else ""
            existing = f' (已有规则: {c["match_rule"]})' if c.get("match_rule") else ""
            lines.append(f'{indent}- {c["name"]} | id={c["category_id"]} | path={c.get("path", "")}{leaf}{existing}')
        return "\n".join(lines)

    def _format_interfaces(self, interfaces: List[Dict[str, Any]]) -> str:
        lines = []
        for iface in interfaces[:200]:  # 限制数量避免 prompt 过长
            tags = iface.get("tags") or []
            tags_str = ", ".join(tags) if tags else "无"
            summary = iface.get("summary", "") or ""
            lines.append(
                f'{iface["method"]} {iface["path"]} | tags=[{tags_str}] | summary={summary[:60]}'
            )
        if len(interfaces) > 200:
            lines.append(f"... 还有 {len(interfaces) - 200} 个接口")
        return "\n".join(lines)

    async def _fallback_recommend(
        self, categories: List[Dict[str, Any]], interfaces: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """LLM 失败时的确定性 fallback：按 tags 关键词匹配"""
        logger.info("使用 fallback 规则推荐（tags 关键词匹配）")
        recommendations = []

        for cat in categories:
            if cat.get("match_rule") or not cat.get("name"):
                continue

            # 在接口 tags 中查找包含分类名称的接口
            matched = []
            for iface in interfaces:
                iface_tags = [t.lower() for t in (iface.get("tags") or [])]
                if any(cat["name"].lower() in t or t in cat["name"].lower() for t in iface_tags):
                    matched.append(iface)

            if matched:
                # 取这些接口 path 的公共前缀段
                path_segs = []
                for m in matched:
                    segs = [s for s in m["path"].strip("/").split("/") if s]
                    # 跳过通用前缀 (api, plugins, com.xxx)
                    clean = [s for s in segs if not s.startswith("com.") and s not in ("api", "plugins", "v1", "v2")]
                    if clean:
                        path_segs.append("/".join(clean[:3]))

                most_common = max(set(path_segs), key=path_segs.count) if path_segs else ""
                rule = f"/**/{most_common}/**" if most_common else ""

                recommendations.append({
                    "category_id": cat["category_id"],
                    "category_path": cat.get("path", cat["name"]),
                    "match_rule": rule,
                    "matched_count": len(matched),
                    "sample_paths": [m["path"] for m in matched[:3]],
                })

        await self._send_message(f"Fallback 生成 {len(recommendations)} 条推荐规则", "warning")
        return {"recommendations": recommendations}
