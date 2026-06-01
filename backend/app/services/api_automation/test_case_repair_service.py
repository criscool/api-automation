"""
TestCase 脚本映射修复服务
修复 class_name / method_name / script_file_path 为空的 TestCase 记录，
通过 AST 解析已有脚本文件反向匹配。
"""
import ast
import re
from collections import defaultdict
from typing import List, Dict, Optional

from loguru import logger
from tortoise import connections

from app.models.api_automation import TestCase, TestScript


def _is_scenario_script(content: str) -> bool:
    """检测是否为场景脚本（依赖 JSON 生成的）"""
    return "from automation.core.utils.scenario_helpers import" in content


def _extract_methods_from_script(content: str) -> List[Dict]:
    """从脚本源码按顺序提取所有 test_ 方法信息。

    返回: [{class_name, method_name, urls: [str]}]
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    methods = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for sub in node.body:
            if not isinstance(sub, ast.FunctionDef) or not sub.name.startswith("test_"):
                continue
            methods.append({
                "class_name": node.name,
                "method_name": sub.name,
                "urls": _extract_urls_from_method(sub),
            })
    return methods


def _extract_urls_from_method(func: ast.FunctionDef) -> List[str]:
    """从方法体提取 api_client.xxx() 调用的 URL 字面量。"""
    # 收集变量赋值: var = "string"
    var_to_str: Dict[str, str] = {}
    for stmt in ast.walk(func):
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)):
            var_to_str[stmt.targets[0].id] = stmt.value.value

    urls: List[str] = []
    for stmt in ast.walk(func):
        if not (isinstance(stmt, ast.Call)
                and isinstance(stmt.func, ast.Attribute)
                and isinstance(stmt.func.value, ast.Name)
                and stmt.func.value.id == "api_client"
                and stmt.args):
            continue
        a0 = stmt.args[0]
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            urls.append(a0.value)
        elif isinstance(a0, ast.Name) and a0.id in var_to_str:
            urls.append(var_to_str[a0.id])
        elif isinstance(a0, ast.JoinedStr):
            parts: List[str] = []
            for p in a0.values:
                if isinstance(p, ast.Constant) and isinstance(p.value, str):
                    parts.append(p.value)
                else:
                    break
            s = "".join(parts)
            if s:
                urls.append(s)
    return urls


_path_var_re = re.compile(r"(\{[^}]+\}|:[A-Za-z_][A-Za-z0-9_]*).*$")


def _url_matches_path(url: str, ep_path: str) -> bool:
    """URL 字面量是否匹配 endpoint path"""
    if ep_path == url:
        return True
    stripped = _path_var_re.sub("", ep_path).rstrip("/")
    return bool(stripped and url.startswith(stripped))


def _match_methods_to_endpoint_ids(
    methods: List[Dict],
    ep_paths: Dict[str, str],  # endpoint_id -> path
) -> Dict[str, List[int]]:
    """将方法按 endpoint_id 分组。

    返回: {endpoint_id: [method_index, ...]}
    未匹配到的方法不包含在结果中。
    """
    result: Dict[str, List[int]] = defaultdict(list)
    for i, m in enumerate(methods):
        for url in m["urls"]:
            for ep_id, ep_path in ep_paths.items():
                if _url_matches_path(url, ep_path):
                    result[ep_id].append(i)
                    break
            else:
                continue
            break
    return result


async def repair_test_case_mapping(
    test_case_ids: Optional[List[str]] = None,
) -> Dict:
    """修复 TestCase 的脚本映射。

    Args:
        test_case_ids: 指定要修复的 test_case_id 列表，为 None 则修复所有缺失映射的用例。

    Returns:
        {repaired: int, skipped: int, errors: [{test_case_id, reason}]}
    """
    conn = connections.get("default")

    # 查询需要修复的用例
    if test_case_ids:
        cases = await (
            TestCase
            .filter(test_id__in=test_case_ids)
            .using_db(conn)
            .prefetch_related("endpoint")
        )
    else:
        cases = await (
            TestCase
            .filter(class_name__isnull=True)
            .using_db(conn)
            .prefetch_related("endpoint")
        )

    if not cases:
        return {"repaired": 0, "skipped": 0, "errors": []}

    # 按 interface_id 分组需要修复的用例
    cases_by_iface: Dict[str, List] = defaultdict(list)
    for tc in cases:
        if tc.endpoint:
            cases_by_iface[tc.endpoint.interface_id].append(tc)

    # 批量查询脚本
    scripts = await TestScript.filter(
        interface_id__in=list(cases_by_iface.keys()),
        is_active=True,
    ).using_db(conn)

    scripts_by_iface: Dict[str, List[TestScript]] = defaultdict(list)
    for s in scripts:
        scripts_by_iface[s.interface_id].append(s)

    repaired = 0
    skipped = 0
    errors: List[Dict] = []

    for iface_id, iface_cases in cases_by_iface.items():
        iface_scripts = scripts_by_iface.get(iface_id, [])
        if not iface_scripts:
            for tc in iface_cases:
                errors.append({
                    "test_case_id": tc.test_id,
                    "reason": f"接口 {iface_id} 没有关联的 TestScript",
                })
                skipped += len(iface_cases)
            continue

        # 用第一个匹配的脚本（一个接口通常只有一个脚本）
        for script in iface_scripts:
            content = script.content or ""
            methods = _extract_methods_from_script(content)
            if not methods:
                continue

            file_path = script.file_path or ""

            if _is_scenario_script(content):
                # 场景脚本：所有用例映射到唯一方法
                m = methods[0]
                for tc in iface_cases:
                    tc.class_name = m["class_name"]
                    tc.method_name = m["method_name"]
                    tc.script_file_path = file_path or None
                    await tc.save(
                        using_db=conn,
                        update_fields=["class_name", "method_name", "script_file_path"],
                    )
                    repaired += 1
                    logger.debug(
                        f"修复(场景) TestCase {tc.test_id}: "
                        f"{m['class_name']}::{m['method_name']}"
                    )
                break

            # 标准脚本：按 endpoint 分组匹配
            # 构建 endpoint_id → path 映射
            ep_paths = {}
            for tc in iface_cases:
                if tc.endpoint and tc.endpoint.endpoint_id not in ep_paths:
                    ep_paths[tc.endpoint.endpoint_id] = tc.endpoint.path

            # 将方法按 endpoint 分组
            ep_method_indices = _match_methods_to_endpoint_ids(methods, ep_paths)

            # 按 endpoint 分组 test cases
            cases_by_ep: Dict[str, List] = defaultdict(list)
            for tc in iface_cases:
                if tc.endpoint:
                    cases_by_ep[tc.endpoint.endpoint_id].append(tc)

            for ep_id, ep_cases in cases_by_ep.items():
                method_idxs = ep_method_indices.get(ep_id, [])
                for i, tc in enumerate(ep_cases):
                    if i < len(method_idxs):
                        m = methods[method_idxs[i]]
                    elif method_idxs:
                        # 同 endpoint 下方法不够 → 复用最后一个
                        m = methods[method_idxs[-1]]
                    else:
                        # 没有任何方法匹配此 endpoint → 顺序分配
                        all_matched_idxs = []
                        for idxs in ep_method_indices.values():
                            all_matched_idxs.extend(idxs)
                        unmatched = [
                            j for j in range(len(methods))
                            if j not in all_matched_idxs
                        ]
                        # 用未匹配方法中第一个，或最后一个方法
                        idx = unmatched[0] if unmatched else len(methods) - 1
                        m = methods[idx]
                        ep_method_indices.setdefault(ep_id, []).append(idx)

                    tc.class_name = m["class_name"]
                    tc.method_name = m["method_name"]
                    tc.script_file_path = file_path or None
                    await tc.save(
                        using_db=conn,
                        update_fields=["class_name", "method_name", "script_file_path"],
                    )
                    repaired += 1
                    logger.debug(
                        f"修复 TestCase {tc.test_id}: "
                        f"{m['class_name']}::{m['method_name']} → {file_path}"
                    )
            break  # 只使用第一个有效脚本

    logger.info(
        f"TestCase 映射修复完成: repaired={repaired}, "
        f"skipped={skipped}, errors={len(errors)}"
    )
    return {"repaired": repaired, "skipped": skipped, "errors": errors}
