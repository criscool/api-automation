"""
反模式注册表 - 接口自动化测试修复领域的项目知识

来源：api-test-fixer/references/api_patterns.md
作用：作为 TestHealerAgent / TestAnalysisAgent 的 system prompt 上下文，
      使 LLM 知道本项目接口的特殊命名习惯与已知"坑"。

新发现的坑请在 KNOWN_ANTIPATTERNS 中追加，prompt 会自动消费。
"""
from typing import Dict, List


KNOWN_ANTIPATTERNS: List[Dict[str, str]] = [
    {
        "id": "snake_camel_mix_situation",
        "module": "态势大屏",
        "rule": "time_from / time_to 用蛇形，但 streamIds 用驼峰",
        "fix_hint": "命名风格混用，尝试两种命名都发一遍探测；不要无脑统一",
    },
    {
        "id": "asset_underscore_id",
        "module": "资产",
        "rule": "资产相关接口 _id 字段带下划线前缀，但 network_name 是标准蛇形",
        "fix_hint": "资产模块 ID 字段固定写 _id，非 id",
    },
    {
        "id": "delete_modify_need_id",
        "module": "通用",
        "rule": "删除/修改接口通常需要 _id 或 id 字段",
        "fix_hint": "缺主键字段是 400 报错的常见原因",
    },
    {
        "id": "realtime_alarm_sum_type_required",
        "endpoint_pattern": "/realTimeAlarmSum",
        "module": "告警",
        "rule": "统计类接口强制要求 type 字段（int 类型）",
        "fix_hint": "缺 type 字段会 400，payload 至少补 type=1",
    },
    {
        "id": "asset_open_close_need_stime_etime",
        "module": "资产启停",
        "rule": "强制要求 stime 和 etime 字符串",
        "fix_hint": "时间字段必填，且必须是字符串而非时间戳",
    },
    {
        "id": "response_style_code_msg",
        "module": "通用",
        "rule": "响应风格 A：{'code': 200, 'msg': 'OK', 'data': ...}",
        "fix_hint": "断言 resp.json()['code'] == 200",
    },
    {
        "id": "response_style_type_success",
        "module": "通用",
        "rule": "响应风格 B：{'type': 'success', 'msg': '成功', 'data': ...}",
        "fix_hint": "断言 resp.json()['type'] == 'success'，注意不是 'code'",
    },
    {
        "id": "asset_write_result_string",
        "module": "资产",
        "rule": "资产模块部分接口直接返回 MongoDB WriteResult 字符串而非 JSON",
        "fix_hint": "断言用正则匹配或子串包含校验，不要尝试 resp.json()",
    },
    {
        "id": "delete_204_no_body",
        "module": "通用",
        "rule": "DELETE 成功可能返回 200 带 JSON，也可能返回 204 无响应体",
        "fix_hint": "断言 status_code in (200, 204)；不要硬编码 == 200 且解析 body",
    },
    {
        "id": "stream_ids_string_not_list",
        "module": "态势大屏",
        "rule": "字段名是 streamIds 看似复数，但后端要求传字符串而非列表",
        "fix_hint": "用逗号分隔的字符串 'id1,id2'，不是 ['id1', 'id2']",
    },
    {
        "id": "strategy_add_required_fields",
        "module": "策略",
        "rule": "策略新增接口 body 有 5 个必填字符串: frequency / time / hour / deadline / description，服务端报 Null 时通常一次只报第一个，实际 5 个都缺",
        "fix_hint": "payload 补齐 frequency='', time='', hour='', deadline='', description=''（空字符串即可）",
    },
]


def render_digest(max_items: int = 0) -> str:
    """
    将注册表渲染为人类可读 + LLM 友好的摘要片段，供 prompt 嵌入。

    Args:
        max_items: 最大输出条目数，0 表示全量

    Returns:
        Markdown 格式的摘要文本
    """
    items = KNOWN_ANTIPATTERNS if max_items <= 0 else KNOWN_ANTIPATTERNS[:max_items]

    lines = ["# 本项目接口的已知陷阱（必读）", ""]
    by_module: Dict[str, List[Dict[str, str]]] = {}
    for it in items:
        by_module.setdefault(it.get("module", "通用"), []).append(it)

    for module, group in by_module.items():
        lines.append(f"## {module}")
        for it in group:
            ep = it.get("endpoint_pattern")
            scope = f"（适用接口模式：`{ep}`）" if ep else ""
            lines.append(f"- **[{it['id']}]** {it['rule']}{scope}")
            lines.append(f"  - 修复提示：{it['fix_hint']}")
        lines.append("")

    return "\n".join(lines).strip()


def find_matching_patterns(
    endpoint_path: str = "",
    module_hint: str = "",
    error_text: str = "",
) -> List[Dict[str, str]]:
    """
    根据失败上下文找出可能命中的反模式条目，用于优先级提示。

    Args:
        endpoint_path: 失败接口路径
        module_hint: 模块提示（从脚本路径推断，如 "asset" / "alarm"）
        error_text: 错误文本（响应体或 pytest 输出片段）

    Returns:
        命中的反模式条目列表
    """
    matches = []
    for it in KNOWN_ANTIPATTERNS:
        ep = it.get("endpoint_pattern", "")
        module = it.get("module", "")

        hit = False
        if ep and ep in endpoint_path:
            hit = True
        if module_hint and module and module_hint in module.lower():
            hit = True
        if "Null" in error_text and "_id" in it.get("rule", ""):
            hit = True

        if hit:
            matches.append(it)
    return matches
