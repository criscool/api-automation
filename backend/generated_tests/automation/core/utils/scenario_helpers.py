"""
场景（chain）测试辅助函数
=========================

由 ScriptGeneratorAgent 的 scenario 分支生成的脚本使用。
设计目标：把 dataIn/dataOut/assert 这些跨步骤通用逻辑沉淀到这里，
让生成的 test 文件保持可读。

约定的引用语法：
- step ref:     "step:N.dataOut.X"        指向第 N 步声明的 dataOut 变量 X
- path 取值:    "response.data.list[]._id" 点路径，[]=遍历数组，[N]=下标，
                 [k=v]=按等值条件取首个匹配项

支持的 dataIn 键形式：
- "field"                 → body 顶层字段
- "field.sub"             → body 嵌套字段
- "field[N]"              → body 数组字段下标
- "body.X"                → 显式声明 body（同 "field"）
- "query.X"               → query 参数
- "pathParams.:id"        → path 参数（: 或 {} 装饰）

支持的 assert 子键：find / notFind / every / equals
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


_STEP_REF_RE = re.compile(r"^step:(\d+)\.dataOut\.(.+)$")
_RESPONSE_PREFIX_RE = re.compile(r"^response\.?")
# 路径 token：字段名 / [] / [*] / [N] / [key=value] / [?(@.field op value)]
# [*] 是 [] 的 JSONPath 别名；[?(@.field=='v')] 支持 == / != 字面值过滤
_PATH_TOKEN_RE = re.compile(
    r"[a-zA-Z_][a-zA-Z0-9_]*"
    r"|\[\*\]"
    r"|\[\]"
    r"|\[\d+\]"
    r"|\[[a-zA-Z_][a-zA-Z0-9_]*=[^\]]+\]"
    r"|\[\?\(@\.[^)]+\)\]"
)
_JSONPATH_FILTER_RE = re.compile(
    r"^\[\?\(@\.([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|!=)\s*('([^']*)'|\"([^\"]*)\"|([^)]+?))\)\]$"
)

# 断言 spec 内 target 取值的 key 优先级：先 ref（动态引用），后 value（字面值）
# xxxRef 取前序 step.dataOut 的值；xxxValue 是字面期望值；
# 末尾 "equals"/"value" 保留对早期格式的兼容（asset-management 风格）
_REF_KEYS = ("equalsRef", "findRef", "notFindRef", "everyRef", "neqRef",
             "gteRef", "lteRef", "gtRef", "ltRef")
_VALUE_KEYS = ("equalsValue", "findValue", "notFindValue", "everyValue",
               "gteValue", "lteValue", "gtValue", "ltValue", "neqValue",
               "equals", "value")


def resolve_step_ref(ref: Any, ctx: Dict[int, Dict[str, Any]]) -> Any:
    """解析 'step:N.dataOut.X' → 在 ctx 中取值；不匹配返回 None。"""
    if not isinstance(ref, str):
        return None
    m = _STEP_REF_RE.match(ref.strip())
    if not m:
        return None
    step_no = int(m.group(1))
    var = m.group(2)
    return ((ctx.get(step_no) or {}).get("dataOut") or {}).get(var)


def resolve_path(obj: Any, path: str) -> Any:
    """按点路径取值，支持 [] / [N] / [k=v]。空路径返回原对象。
    以 'response.' 开头的前缀会被剥掉（response 是 root 别名）。
    """
    if obj is None or not path:
        return obj
    p = _RESPONSE_PREFIX_RE.sub("", path)
    if not p:
        return obj
    tokens = _PATH_TOKEN_RE.findall(p)
    return _walk(obj, tokens)


def _walk(obj: Any, tokens: List[str]) -> Any:
    if obj is None or not tokens:
        return obj
    tok, rest = tokens[0], tokens[1:]
    if tok == "[]" or tok == "[*]":
        if not isinstance(obj, list):
            return None
        return [_walk(item, rest) for item in obj]
    if tok.startswith("[?(") and tok.endswith(")]"):
        # JSONPath filter: [?(@.field == 'value')] / [?(@.field != 1)]
        m = _JSONPATH_FILTER_RE.match(tok)
        if not m or not isinstance(obj, list):
            return None
        field, op = m.group(1), m.group(2)
        # group 4 单引号串 / group 5 双引号串 / group 6 裸字面值（数字/布尔）
        raw_value = m.group(4) if m.group(4) is not None else (
            m.group(5) if m.group(5) is not None else (m.group(6) or "").strip()
        )
        for item in obj:
            if not isinstance(item, dict):
                continue
            field_val = item.get(field)
            if _filter_match(field_val, op, raw_value):
                return _walk(item, rest)
        return None
    if tok.startswith("[") and tok.endswith("]"):
        inner = tok[1:-1]
        if "=" in inner:
            k, v = inner.split("=", 1)
            if not isinstance(obj, list):
                return None
            for item in obj:
                if isinstance(item, dict) and str(item.get(k)) == v:
                    return _walk(item, rest)
            return None
        try:
            idx = int(inner)
        except ValueError:
            return None
        if not isinstance(obj, list) or idx < 0 or idx >= len(obj):
            return None
        return _walk(obj[idx], rest)
    # 字段名
    if not isinstance(obj, dict):
        return None
    return _walk(obj.get(tok), rest)


def _filter_match(field_val: Any, op: str, raw_value: str) -> bool:
    """JSONPath filter 字面值比较。支持 == / !=；字符串与字段原值容差比较。"""
    # 先按原始字符串比较；再尝试数值；再 bool
    candidates: List[Any] = [raw_value]
    try:
        candidates.append(int(raw_value))
    except (ValueError, TypeError):
        pass
    try:
        candidates.append(float(raw_value))
    except (ValueError, TypeError):
        pass
    if raw_value in ("true", "false"):
        candidates.append(raw_value == "true")
    matched = any(field_val == c for c in candidates) or str(field_val) == raw_value
    return matched if op == "==" else not matched


def _pick_first(value: Any) -> Any:
    """递归从嵌套 list 里取第一个非空标量。dict/scalar 原样返回。"""
    if isinstance(value, list):
        for item in value:
            picked = _pick_first(item)
            if picked is not None and picked != "":
                return picked
        return None
    return value


def extract_data_out(
    response_json: Any, data_out_spec: Optional[Dict[str, Dict[str, Any]]]
) -> Dict[str, Any]:
    """根据 dataOut 配置抽取变量，scalar 化（list → 首个非空）。"""
    result: Dict[str, Any] = {}
    for var, spec in (data_out_spec or {}).items():
        if not isinstance(spec, dict):
            continue
        raw = resolve_path(response_json, spec.get("path", ""))
        result[var] = _pick_first(raw) if isinstance(raw, list) else raw
    return result


def apply_data_in(
    body_tmpl: Optional[Dict[str, Any]],
    query_tmpl: Optional[Dict[str, Any]],
    path_tmpl: str,
    data_in: Optional[Dict[str, Dict[str, Any]]],
    ctx: Dict[int, Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """把 body/query/path 模板按 data_in 填好。返回 (body, query, path)。"""
    body = _deep_copy(body_tmpl) if isinstance(body_tmpl, dict) else {}
    query = dict(query_tmpl or {})
    path = path_tmpl or ""

    for key, spec in (data_in or {}).items():
        if not isinstance(spec, dict):
            continue
        ref = spec.get("from")
        optional = bool(spec.get("optional"))
        template = spec.get("template")
        value = resolve_step_ref(ref, ctx) if ref else None
        if value is None:
            if optional:
                continue
            # 不强制 raise；保留模板原值，运行时由接口本身校验
            continue
        if isinstance(template, str) and "${value}" in template:
            value = template.replace("${value}", str(value))

        if key.startswith("pathParams."):
            name = key[len("pathParams."):]
            clean = name.lstrip(":").strip("{}")
            path = path.replace(f":{clean}", str(value)).replace(f"{{{clean}}}", str(value))
        elif key.startswith("query."):
            _set_nested(query, key[len("query."):], value)
        elif key.startswith("body."):
            _set_nested(body, key[len("body."):], value)
        else:
            _set_nested(body, key, value)

    return body, query, path


def render_path(path_tmpl: str, path_params: Optional[Dict[str, Any]]) -> str:
    """单步骤无 dataIn 时，把 path 模板里的 :name / {name} 直接用 path_params 填充。"""
    result = path_tmpl or ""
    for name, value in (path_params or {}).items():
        clean = str(name).lstrip(":").strip("{}")
        result = result.replace(f":{clean}", str(value)).replace(f"{{{clean}}}", str(value))
    return result


def _set_nested(obj: Dict[str, Any], dotted: str, value: Any) -> None:
    """把 obj 按 'a.b[0].c' 路径设置 value。中间路径不存在会按下一 token 类型自动建容器。"""
    if not dotted:
        return
    tokens = _PATH_TOKEN_RE.findall(dotted)
    if not tokens:
        return
    cur: Any = obj
    for i, tok in enumerate(tokens):
        last = i == len(tokens) - 1
        is_index = tok.startswith("[") and tok.endswith("]") and tok != "[]"
        if is_index:
            inner = tok[1:-1]
            try:
                idx = int(inner)
            except ValueError:
                return
            if not isinstance(cur, list):
                return
            while len(cur) <= idx:
                cur.append(None)
            if last:
                cur[idx] = value
            else:
                if cur[idx] is None:
                    nxt = tokens[i + 1]
                    cur[idx] = [] if (nxt.startswith("[") and nxt != "[]") else {}
                cur = cur[idx]
        else:
            if not isinstance(cur, dict):
                return
            if last:
                cur[tok] = value
            else:
                if tok not in cur or cur[tok] is None:
                    nxt = tokens[i + 1]
                    cur[tok] = [] if (nxt.startswith("[") and nxt != "[]") else {}
                cur = cur[tok]


def _deep_copy(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj


def run_assert(
    response_json: Any,
    assert_spec: Optional[Dict[str, Any]],
    ctx: Dict[int, Dict[str, Any]],
    step_no: Optional[int] = None,
) -> None:
    """按 assert_spec 的子键分发到对应断言函数。"""
    if not assert_spec:
        return
    for kind, spec in assert_spec.items():
        if not isinstance(spec, dict):
            continue
        if kind == "find":
            _assert_find(response_json, spec, ctx, expect=True, step_no=step_no)
        elif kind == "notFind":
            _assert_find(response_json, spec, ctx, expect=False, step_no=step_no)
        elif kind == "every":
            _assert_every(response_json, spec, ctx, step_no=step_no)
        elif kind == "equals":
            _assert_equals(response_json, spec, ctx, step_no=step_no, expect_equal=True)
        elif kind in ("neq", "notEquals"):
            _assert_equals(response_json, spec, ctx, step_no=step_no, expect_equal=False)
        elif kind in ("gte", "lte", "gt", "lt"):
            _assert_compare(response_json, spec, ctx, op=kind, step_no=step_no)


def _resolve_target(spec: Dict[str, Any], ctx: Dict[int, Dict[str, Any]]) -> Any:
    for k in _REF_KEYS:
        if k in spec:
            return resolve_step_ref(spec[k], ctx)
    for k in _VALUE_KEYS:
        if k in spec:
            return spec[k]
    return None


def _flatten(value: Any) -> List[Any]:
    out: List[Any] = []
    if isinstance(value, list):
        for v in value:
            out.extend(_flatten(v))
    else:
        out.append(value)
    return out


def _assert_find(resp, spec, ctx, *, expect: bool, step_no):
    in_path = spec.get("in", "")
    target = _resolve_target(spec, ctx)
    actual = resolve_path(resp, in_path)
    if actual is None:
        actual = []
    if not isinstance(actual, list):
        actual = [actual]
    flat = _flatten(actual)
    found = target in flat
    if expect:
        assert found, (
            f"step {step_no}: 期望在 {in_path} 找到 {target!r}，"
            f"实际前5项 {flat[:5]!r}（共 {len(flat)} 项）"
        )
    else:
        assert not found, (
            f"step {step_no}: 期望在 {in_path} 不出现 {target!r}，但出现了"
        )


def _assert_every(resp, spec, ctx, *, step_no):
    in_path = spec.get("in", "")
    target = _resolve_target(spec, ctx)
    actual = resolve_path(resp, in_path)
    if actual is None:
        return  # 空集合视为 vacuously true
    if not isinstance(actual, list):
        actual = [actual]
    flat = _flatten(actual)
    for v in flat:
        assert v == target, (
            f"step {step_no}: every {in_path} 期望全等 {target!r}，"
            f"出现不一致项 {v!r}"
        )


def _assert_equals(resp, spec, ctx, *, step_no, expect_equal: bool = True):
    in_path = spec.get("in", spec.get("path", ""))
    target = _resolve_target(spec, ctx)
    actual = resolve_path(resp, in_path)
    equal = _values_equal(actual, target)
    if expect_equal:
        assert equal, (
            f"step {step_no}: {in_path} 期望 {target!r}，实际 {actual!r}"
        )
    else:
        assert not equal, (
            f"step {step_no}: {in_path} 期望不等于 {target!r}，实际相等"
        )


def _assert_compare(resp, spec, ctx, *, op, step_no):
    in_path = spec.get("in", spec.get("path", ""))
    target = _resolve_target(spec, ctx)
    actual = resolve_path(resp, in_path)
    a_num = _coerce_number(actual)
    t_num = _coerce_number(target)
    if a_num is None or t_num is None:
        raise AssertionError(
            f"step {step_no}: {op} {in_path} 无法转为数值（actual={actual!r}, target={target!r}）"
        )
    if op == "gte":
        ok = a_num >= t_num
    elif op == "lte":
        ok = a_num <= t_num
    elif op == "gt":
        ok = a_num > t_num
    elif op == "lt":
        ok = a_num < t_num
    else:
        raise AssertionError(f"step {step_no}: 未知比较运算符 {op!r}")
    assert ok, (
        f"step {step_no}: {in_path} 期望 {op} {target!r}，实际 {actual!r}"
    )


def _coerce_number(value: Any) -> Optional[float]:
    """把 int / float / 数字字符串统一成 float；其它返回 None。bool 不算数字。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _values_equal(actual: Any, target: Any) -> bool:
    """equals 比较：原值相等优先；两边都能 coerce 成数字且数值相等也算等（容忍 '0' == 0）。"""
    if actual == target:
        return True
    a_num = _coerce_number(actual)
    t_num = _coerce_number(target)
    if a_num is not None and t_num is not None and a_num == t_num:
        return True
    return False
