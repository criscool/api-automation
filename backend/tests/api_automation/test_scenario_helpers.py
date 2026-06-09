"""scenario_helpers 单元测试 — 验证 path 解析 / dataIn 替换 / 断言。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让 from automation.* 能 import 到（不依赖 generated_tests/conftest.py）
_GENERATED_TESTS_DIR = Path(__file__).resolve().parents[2] / "generated_tests"
if str(_GENERATED_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_GENERATED_TESTS_DIR))

from automation.core.utils.scenario_helpers import (  # noqa: E402
    apply_data_in,
    extract_data_out,
    render_path,
    resolve_path,
    resolve_step_ref,
    run_assert,
)


# --------------------------------------------------------------------- #
# resolve_path
# --------------------------------------------------------------------- #

class TestResolvePath:
    def test_simple_field(self):
        assert resolve_path({"a": {"b": 1}}, "a.b") == 1

    def test_strip_response_prefix(self):
        assert resolve_path({"data": "x"}, "response.data") == "x"

    def test_empty_path_returns_obj(self):
        obj = {"a": 1}
        assert resolve_path(obj, "") is obj

    def test_list_iteration(self):
        obj = {"data": [{"v": 1}, {"v": 2}, {"v": 3}]}
        assert resolve_path(obj, "data[].v") == [1, 2, 3]

    def test_list_index(self):
        obj = {"data": [{"v": "a"}, {"v": "b"}]}
        assert resolve_path(obj, "data[0].v") == "a"
        assert resolve_path(obj, "data[1].v") == "b"

    def test_out_of_range_returns_none(self):
        assert resolve_path({"data": [1]}, "data[5]") is None

    def test_filter_by_kv(self):
        obj = {"data": [{"name": "a", "val": 1}, {"name": "b", "val": 2}]}
        assert resolve_path(obj, "data[name=b].val") == 2

    def test_nested_iteration(self):
        obj = {"data": [{"children": [{"v": 1}, {"v": 2}]}, {"children": [{"v": 3}]}]}
        # 两层 [] → [[1, 2], [3]]
        assert resolve_path(obj, "data[].children[].v") == [[1, 2], [3]]

    def test_missing_field_returns_none(self):
        assert resolve_path({"a": 1}, "nonexistent.field") is None

    def test_filter_no_match(self):
        obj = {"data": [{"name": "a"}]}
        assert resolve_path(obj, "data[name=z].any") is None


# --------------------------------------------------------------------- #
# resolve_step_ref
# --------------------------------------------------------------------- #

class TestResolveStepRef:
    def test_resolves_var(self):
        ctx = {1: {"dataOut": {"foo": 42}}}
        assert resolve_step_ref("step:1.dataOut.foo", ctx) == 42

    def test_resolves_dotted_var(self):
        ctx = {2: {"dataOut": {"a.b": "x"}}}
        # var name can have dots
        assert resolve_step_ref("step:2.dataOut.a.b", ctx) == "x"

    def test_invalid_ref_returns_none(self):
        assert resolve_step_ref("not-a-ref", {}) is None
        assert resolve_step_ref(None, {}) is None
        assert resolve_step_ref("", {}) is None

    def test_missing_step_returns_none(self):
        assert resolve_step_ref("step:99.dataOut.foo", {}) is None


# --------------------------------------------------------------------- #
# extract_data_out
# --------------------------------------------------------------------- #

class TestExtractDataOut:
    def test_scalar_path(self):
        resp = {"data": "asset-123"}
        spec = {"newId": {"path": "response.data"}}
        assert extract_data_out(resp, spec) == {"newId": "asset-123"}

    def test_list_picks_first(self):
        resp = {"data": [{"value": 3}, {"value": 4}]}
        spec = {"first_v": {"path": "response.data[].value"}}
        assert extract_data_out(resp, spec) == {"first_v": 3}

    def test_nested_list_picks_first_non_empty(self):
        resp = {"data": [{"children": [{"v": None}, {"v": 7}]}, {"children": [{"v": 8}]}]}
        spec = {"x": {"path": "response.data[].children[].v"}}
        assert extract_data_out(resp, spec) == {"x": 7}

    def test_filtered_path(self):
        resp = {"data": [{"fixed_name": "tag1", "list": [{"_id": "id-1"}, {"_id": "id-2"}]},
                          {"fixed_name": "tag2", "list": [{"_id": "id-3"}]}]}
        spec = {"tag1_first": {"path": "response.data[fixed_name=tag1].list[]._id"}}
        assert extract_data_out(resp, spec) == {"tag1_first": "id-1"}


# --------------------------------------------------------------------- #
# apply_data_in
# --------------------------------------------------------------------- #

class TestApplyDataIn:
    def test_top_level_body_field(self):
        ctx = {1: {"dataOut": {"foo": "abc"}}}
        body, query, path = apply_data_in(
            {"x": 0}, {}, "/api/x",
            {"foo": {"from": "step:1.dataOut.foo"}},
            ctx,
        )
        assert body == {"x": 0, "foo": "abc"}

    def test_body_dotted(self):
        ctx = {1: {"dataOut": {"q": "kw"}}}
        body, _, _ = apply_data_in(
            {"page": 1}, {}, "/x",
            {"body.query": {"from": "step:1.dataOut.q"}},
            ctx,
        )
        assert body == {"page": 1, "query": "kw"}

    def test_body_array_index(self):
        ctx = {4: {"dataOut": {"newAssetId": "ass-1"}}}
        body, _, _ = apply_data_in(
            {"entities": []}, {}, "/del",
            {"entities[0]": {"from": "step:4.dataOut.newAssetId"}},
            ctx,
        )
        assert body == {"entities": ["ass-1"]}

    def test_path_param_colon(self):
        ctx = {1: {"dataOut": {"streamId": "s-9"}}}
        _, _, path = apply_data_in(
            {}, {}, "/api/uplink/:id",
            {"pathParams.:id": {"from": "step:1.dataOut.streamId"}},
            ctx,
        )
        assert path == "/api/uplink/s-9"

    def test_path_param_brace(self):
        ctx = {1: {"dataOut": {"id": "x"}}}
        _, _, path = apply_data_in(
            {}, {}, "/api/foo/{id}/bar",
            {"pathParams.{id}": {"from": "step:1.dataOut.id"}},
            ctx,
        )
        assert path == "/api/foo/x/bar"

    def test_query_field(self):
        ctx = {1: {"dataOut": {"q": "v"}}}
        _, query, _ = apply_data_in(
            {}, {"page": 1}, "/x",
            {"query._id": {"from": "step:1.dataOut.q"}},
            ctx,
        )
        assert query == {"page": 1, "_id": "v"}

    def test_optional_missing_is_skipped(self):
        ctx = {1: {"dataOut": {}}}
        body, _, _ = apply_data_in(
            {"x": 1}, {}, "/x",
            {"foo": {"from": "step:1.dataOut.nope", "optional": True}},
            ctx,
        )
        # foo 不存在 → body 保持原样
        assert body == {"x": 1}

    def test_template_substitution(self):
        ctx = {1: {"dataOut": {"v": 4}}}
        body, _, _ = apply_data_in(
            {"query": ""}, {}, "/x",
            {"body.query": {"template": "asset_type:'${value}'", "from": "step:1.dataOut.v"}},
            ctx,
        )
        assert body == {"query": "asset_type:'4'"}

    def test_does_not_mutate_input(self):
        original = {"x": [1, 2]}
        ctx = {1: {"dataOut": {"v": 99}}}
        apply_data_in(original, {}, "/x",
                      {"new_field": {"from": "step:1.dataOut.v"}}, ctx)
        # 输入 dict 不应被修改
        assert original == {"x": [1, 2]}


# --------------------------------------------------------------------- #
# render_path
# --------------------------------------------------------------------- #

class TestRenderPath:
    def test_colon_style(self):
        assert render_path("/api/:id", {":id": "abc"}) == "/api/abc"

    def test_brace_style(self):
        assert render_path("/api/{id}/sub", {"id": "xy"}) == "/api/xy/sub"


# --------------------------------------------------------------------- #
# run_assert
# --------------------------------------------------------------------- #

class TestRunAssert:
    def test_find_pass(self):
        resp = {"data": {"list": [{"_id": "a"}, {"_id": "b"}]}}
        ctx = {4: {"dataOut": {"newAssetId": "a"}}}
        run_assert(resp,
                   {"find": {"in": "response.data.list[]._id", "equalsRef": "step:4.dataOut.newAssetId"}},
                   ctx, step_no=5)

    def test_find_fail(self):
        resp = {"data": {"list": [{"_id": "x"}]}}
        ctx = {4: {"dataOut": {"newAssetId": "a"}}}
        with pytest.raises(AssertionError):
            run_assert(resp,
                       {"find": {"in": "response.data.list[]._id", "equalsRef": "step:4.dataOut.newAssetId"}},
                       ctx, step_no=5)

    def test_not_find_pass(self):
        resp = {"data": {"list": [{"_id": "x"}]}}
        ctx = {4: {"dataOut": {"newAssetId": "a"}}}
        run_assert(resp,
                   {"notFind": {"in": "response.data.list[]._id", "equalsRef": "step:4.dataOut.newAssetId"}},
                   ctx, step_no=7)

    def test_not_find_fail(self):
        resp = {"data": {"list": [{"_id": "a"}]}}
        ctx = {4: {"dataOut": {"newAssetId": "a"}}}
        with pytest.raises(AssertionError):
            run_assert(resp,
                       {"notFind": {"in": "response.data.list[]._id", "equalsRef": "step:4.dataOut.newAssetId"}},
                       ctx, step_no=7)

    def test_every_pass(self):
        resp = {"data": {"list": [{"asset_type_code": 4}, {"asset_type_code": 4}]}}
        ctx = {1: {"dataOut": {"asset_type_filter": 4}}}
        run_assert(resp,
                   {"every": {"in": "response.data.list[].asset_type_code",
                              "equalsRef": "step:1.dataOut.asset_type_filter"}},
                   ctx, step_no=3)

    def test_every_fail(self):
        resp = {"data": {"list": [{"asset_type_code": 4}, {"asset_type_code": 5}]}}
        ctx = {1: {"dataOut": {"asset_type_filter": 4}}}
        with pytest.raises(AssertionError):
            run_assert(resp,
                       {"every": {"in": "response.data.list[].asset_type_code",
                                  "equalsRef": "step:1.dataOut.asset_type_filter"}},
                       ctx, step_no=3)

    def test_equals_pass(self):
        resp = {"data": {"_id": "asset-1"}}
        ctx = {1: {"dataOut": {"assetId": "asset-1"}}}
        run_assert(resp,
                   {"equals": {"in": "response.data._id", "equalsRef": "step:1.dataOut.assetId"}},
                   ctx, step_no=2)

    def test_equals_fail(self):
        resp = {"data": {"_id": "asset-x"}}
        ctx = {1: {"dataOut": {"assetId": "asset-1"}}}
        with pytest.raises(AssertionError):
            run_assert(resp,
                       {"equals": {"in": "response.data._id", "equalsRef": "step:1.dataOut.assetId"}},
                       ctx, step_no=2)

    def test_empty_spec_is_noop(self):
        # 不抛错即可
        run_assert({"a": 1}, None, {})
        run_assert({"a": 1}, {}, {})


# --------------------------------------------------------------------- #
# 新风格：equalsValue / gteValue / JSONPath filter / [*] 别名
# 对应 strategy-crud-dependencies.json 这种用字面期望值 + 数值比较 + JSONPath 的依赖文件
# --------------------------------------------------------------------- #

class TestEqualsValueStyle:
    """xxxValue 字面期望值（区别于 xxxRef 引用前序步骤）。"""

    def test_equals_value_pass(self):
        resp = {"type": "success"}
        run_assert(resp,
                   {"equals": {"in": "response.type", "equalsValue": "success"}},
                   {}, step_no=7)

    def test_equals_value_fail(self):
        resp = {"type": "error"}
        with pytest.raises(AssertionError):
            run_assert(resp,
                       {"equals": {"in": "response.type", "equalsValue": "success"}},
                       {}, step_no=7)

    def test_equals_value_int(self):
        resp = {"status": 1}
        run_assert(resp,
                   {"equals": {"in": "response.status", "equalsValue": 1}},
                   {}, step_no=8)

    def test_equals_value_number_string_coerce(self):
        # '0' == 0 容差：接口可能返回字符串 '0'，期望写数字 0 也应判等
        resp = {"data": {"total_num": 0}}
        run_assert(resp,
                   {"equals": {"in": "response.data.total_num", "equalsValue": "0"}},
                   {}, step_no=13)
        run_assert(resp,
                   {"equals": {"in": "response.data.total_num", "equalsValue": 0}},
                   {}, step_no=13)


class TestNeqAssertion:
    def test_neq_pass(self):
        resp = {"type": "error"}
        run_assert(resp,
                   {"neq": {"in": "response.type", "equalsValue": "success"}},
                   {}, step_no=1)

    def test_neq_fail(self):
        resp = {"type": "success"}
        with pytest.raises(AssertionError):
            run_assert(resp,
                       {"neq": {"in": "response.type", "equalsValue": "success"}},
                       {}, step_no=1)


class TestCompareAssertions:
    """gte / lte / gt / lt + xxxValue 数值比较。"""

    def test_gte_pass(self):
        resp = {"data": {"total_num": 5}}
        run_assert(resp,
                   {"gte": {"in": "response.data.total_num", "gteValue": 1}},
                   {}, step_no=9)

    def test_gte_equal_boundary(self):
        resp = {"data": {"total_num": 1}}
        run_assert(resp,
                   {"gte": {"in": "response.data.total_num", "gteValue": 1}},
                   {}, step_no=9)

    def test_gte_fail(self):
        resp = {"data": {"total_num": 0}}
        with pytest.raises(AssertionError):
            run_assert(resp,
                       {"gte": {"in": "response.data.total_num", "gteValue": 1}},
                       {}, step_no=9)

    def test_lte_pass(self):
        resp = {"data": {"count": 3}}
        run_assert(resp,
                   {"lte": {"in": "response.data.count", "lteValue": 5}},
                   {}, step_no=1)

    def test_gt_pass(self):
        resp = {"data": {"count": 5}}
        run_assert(resp,
                   {"gt": {"in": "response.data.count", "gtValue": 1}},
                   {}, step_no=1)

    def test_lt_pass(self):
        resp = {"data": {"count": 0}}
        run_assert(resp,
                   {"lt": {"in": "response.data.count", "ltValue": 5}},
                   {}, step_no=1)

    def test_gte_number_string_coerce(self):
        # 接口返回字符串 '5'，期望写 1：能 coerce
        resp = {"data": {"total_num": "5"}}
        run_assert(resp,
                   {"gte": {"in": "response.data.total_num", "gteValue": 1}},
                   {}, step_no=9)

    def test_gte_non_numeric_raises(self):
        # 字符串无法 coerce 成数字 → 明确报错，而不是静默 pass
        resp = {"data": {"total_num": "abc"}}
        with pytest.raises(AssertionError, match="无法转为数值"):
            run_assert(resp,
                       {"gte": {"in": "response.data.total_num", "gteValue": 1}},
                       {}, step_no=9)


class TestJsonPathFilter:
    """[?(@.field op value)] JSONPath filter 子集。"""

    def test_eq_string_single_quote(self):
        obj = {"data": [{"strategy_name": "test新增策略", "_id": "x1", "status": 1},
                         {"strategy_name": "other", "_id": "x2", "status": 2}]}
        assert resolve_path(obj, "data[?(@.strategy_name=='test新增策略')]._id") == "x1"

    def test_eq_string_double_quote(self):
        obj = {"data": [{"k": "v1", "n": 1}, {"k": "v2", "n": 2}]}
        assert resolve_path(obj, 'data[?(@.k=="v2")].n') == 2

    def test_eq_int_literal(self):
        obj = {"data": [{"code": 1, "n": "a"}, {"code": 2, "n": "b"}]}
        assert resolve_path(obj, "data[?(@.code==2)].n") == "b"

    def test_neq_string(self):
        obj = {"data": [{"status": "ok", "v": 1}, {"status": "err", "v": 2}]}
        # 第一个不等于 'err' 的是 status='ok' 项 → v=1
        assert resolve_path(obj, "data[?(@.status!='err')].v") == 1

    def test_no_match_returns_none(self):
        obj = {"data": [{"k": "a"}]}
        assert resolve_path(obj, "data[?(@.k=='z')].any") is None

    def test_filter_then_field_continues(self):
        obj = {"data": [{"value": "rule_type", "list": [{"value": "1"}, {"value": "2"}]},
                         {"value": "other", "list": [{"value": "9"}]}]}
        # 过滤后继续解析 list[0].value
        assert resolve_path(obj, "data[?(@.value=='rule_type')].list[0].value") == "1"

    def test_filter_with_iteration(self):
        obj = {"data": [{"value": "rule_type", "list": [{"value": "1"}, {"value": "2"}]}]}
        # 过滤后 [*] 遍历内部 list
        assert resolve_path(obj, "data[?(@.value=='rule_type')].list[*].value") == ["1", "2"]


class TestStarAlias:
    """[*] 是 [] 的 JSONPath 别名。"""

    def test_star_equals_bracket(self):
        obj = {"data": [{"v": 1}, {"v": 2}]}
        assert resolve_path(obj, "data[*].v") == [1, 2]
        assert resolve_path(obj, "data[].v") == [1, 2]

    def test_extract_data_out_with_star(self):
        resp = {"data": [{"value": 3}, {"value": 4}]}
        spec = {"first_v": {"path": "response.data[*].value"}}
        assert extract_data_out(resp, spec) == {"first_v": 3}


class TestBackwardsCompatOldStyle:
    """老格式（asset-management 风格）保留行为：xxxRef 引用 + 字面 'equals' 也能用。"""

    def test_old_equals_literal_key_still_works(self):
        # 早期格式：在 spec 内用 'equals' 直接放字面值（不区分 ref vs value）
        resp = {"data": {"_id": "asset-1"}}
        run_assert(resp,
                   {"equals": {"in": "response.data._id", "equals": "asset-1"}},
                   {}, step_no=2)

    def test_old_equals_ref_still_works(self):
        resp = {"data": {"_id": "asset-1"}}
        ctx = {1: {"dataOut": {"assetId": "asset-1"}}}
        run_assert(resp,
                   {"equals": {"in": "response.data._id", "equalsRef": "step:1.dataOut.assetId"}},
                   ctx, step_no=2)
