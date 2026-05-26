"""
pytest 脚本 AST 合并器

用途：当 ScriptGeneratorAgent 写入 testcases/test_xxx.py 时，
若目标文件已存在（例如多份 JSON 文档生成同名脚本），通过 AST 合并将新内容
合入现有文件，避免直接覆盖。

合并规则：
- module docstring：以新文件为准；若新文件无 docstring，保留旧的
- imports（Import/ImportFrom）：按 unparse 文本去重，保留并集
- 模块级命名节点（FunctionDef/AsyncFunctionDef/ClassDef）：
    * 同名 ClassDef → 递归合并 class body
    * 其他同名节点 → 以新文件为准（fixture/函数定义都按 new wins）
    * 仅旧文件有 → 保留
- 模块级未命名语句（如 pytestmark = ...）：按 unparse 文本去重
- 类内方法：同名 → new wins；旧独有 → 保留

输出顺序：以新文件的节点顺序为骨架，旧独有节点追加在后。

若任一源码 SyntaxError，回退到"新覆盖旧"（与原行为一致）。
"""
import ast
from typing import List, Optional


def merge_pytest_scripts(existing_source: str, new_source: str) -> str:
    """合并两个 pytest 脚本源码。返回合并后的源码字符串。"""
    try:
        existing_tree = ast.parse(existing_source)
        new_tree = ast.parse(new_source)
    except SyntaxError:
        return new_source

    merged_body = _merge_body(existing_tree.body, new_tree.body)
    module = ast.Module(body=merged_body, type_ignores=[])
    return ast.unparse(module)


def _is_import(node: ast.AST) -> bool:
    return isinstance(node, (ast.Import, ast.ImportFrom))


def _is_docstring(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _named(node: ast.AST) -> Optional[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    return None


def _merge_body(existing: List[ast.AST], new: List[ast.AST]) -> List[ast.AST]:
    """合并两个 body（模块级或类级通用）。"""
    result: List[ast.AST] = []

    # 1. docstring（仅 body[0] 位置）
    e_has_doc = bool(existing) and _is_docstring(existing[0])
    n_has_doc = bool(new) and _is_docstring(new[0])
    e_start = 1 if e_has_doc else 0
    n_start = 1 if n_has_doc else 0

    if n_has_doc:
        result.append(new[0])
    elif e_has_doc:
        result.append(existing[0])

    existing_rest = existing[e_start:]
    new_rest = new[n_start:]

    # 2. imports：按 unparse 文本去重，旧的在前
    existing_imports = [n for n in existing_rest if _is_import(n)]
    new_imports = [n for n in new_rest if _is_import(n)]
    seen_imports = set()
    for imp in existing_imports + new_imports:
        key = ast.unparse(imp).strip()
        if key not in seen_imports:
            seen_imports.add(key)
            result.append(imp)

    # 3. 其他节点
    existing_other = [n for n in existing_rest if not _is_import(n)]
    new_other = [n for n in new_rest if not _is_import(n)]

    existing_named_map = {}
    for n in existing_other:
        name = _named(n)
        if name:
            existing_named_map[name] = n

    new_names = set()
    for n in new_other:
        name = _named(n)
        if name:
            new_names.add(name)

    seen_unnamed = set()

    # 3a. 以新文件为骨架
    for n in new_other:
        name = _named(n)
        if name:
            if (
                name in existing_named_map
                and isinstance(n, ast.ClassDef)
                and isinstance(existing_named_map[name], ast.ClassDef)
            ):
                result.append(_merge_class(existing_named_map[name], n))
            else:
                result.append(n)
        else:
            key = ast.unparse(n).strip()
            if key not in seen_unnamed:
                seen_unnamed.add(key)
                result.append(n)

    # 3b. 追加旧独有节点
    for n in existing_other:
        name = _named(n)
        if name:
            if name not in new_names:
                result.append(n)
        else:
            key = ast.unparse(n).strip()
            if key not in seen_unnamed:
                seen_unnamed.add(key)
                result.append(n)

    return result


def _merge_class(existing_cls: ast.ClassDef, new_cls: ast.ClassDef) -> ast.ClassDef:
    """合并同名 class：基类/装饰器以新为准，body 递归合并。"""
    new_cls.body = _merge_body(existing_cls.body, new_cls.body)
    if not new_cls.body:
        new_cls.body = [ast.Pass()]
    return new_cls
