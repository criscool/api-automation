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
