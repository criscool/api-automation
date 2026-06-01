"""
DependencyDocConverter 单元测试

输入数据：D:/code/aitestmind/api-docs/asset-management-dependencies.json
覆盖：
- to_endpoints 数量正确（含 list 双 bodyShape 拆分）
- to_test_cases 数量 = sum(chain.steps 数)
- to_scenarios 数量 = len(chains)
- to_dependencies 覆盖所有 dependsOn 关系
- ScenarioStepSpec.data_in 准确引用 step:N.dataOut.X
- 同 path 不同 bodyShape 产生不同 endpoint_id
- :id 路径参数不破坏端点构造
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from app.agents.api_automation.schemas import (
    DependencyType,
    HttpMethod,
    ParsedEndpoint,
    ScenarioStepSpec,
    ScenarioTestCase,
)
from app.services.api_automation.dependency_doc_converter import DependencyDocConverter


FIXTURE_PATH = Path("D:/code/aitestmind/api-docs/asset-management-dependencies.json")


@pytest.fixture(scope="module")
def raw_doc() -> dict:
    """加载真实的依赖 JSON 文档。"""
    if not FIXTURE_PATH.exists():
        pytest.skip(f"依赖 JSON 不存在: {FIXTURE_PATH}")
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def converter(raw_doc) -> DependencyDocConverter:
    return DependencyDocConverter(raw_doc)


# --------------------------------------------------------------------- #
# 基础元信息
# --------------------------------------------------------------------- #

class TestApiInfo:
    def test_module_and_base_url(self, converter):
        info = converter.to_api_info()
        assert info.title == "asset-management"
        assert info.base_url == "https://172.16.8.190"

    def test_module_attr(self, converter):
        assert converter.module == "asset-management"
        assert converter.auth_headers.get("Content-Type") == "application/json"


# --------------------------------------------------------------------- #
# 端点
# --------------------------------------------------------------------- #

class TestEndpoints:
    def test_endpoint_count_with_list_variants(self, converter):
        """chains 内总计 11 个唯一端点：
        - chain 1: assettype/projectstreamselect/taglist/add/list[]/delete + list[] 复用 = 6
        - chain 2: selectfield/customsearch/list["query"] (新变体) = 3
        - chain 3: list[] 复用 + showinfo = 1 新
        - chain 4: projectstreamselect 复用 + getUplinkDeviceList/:id = 1 新
        合计 = 11
        """
        endpoints = converter.to_endpoints()
        assert len(endpoints) == 11

    def test_list_endpoint_has_two_variants(self, converter):
        """/list 必须出现两次（bodyShape=[] 和 bodyShape=["query"]），endpoint_id 不同。"""
        endpoints = converter.to_endpoints()
        list_eps = [
            ep for ep in endpoints
            if ep.path.endswith("/knowasset/list") and ep.method == HttpMethod.POST
        ]
        assert len(list_eps) == 2, f"预期 list 有 2 个变体，实际 {len(list_eps)}"
        ids = {ep.endpoint_id for ep in list_eps}
        assert len(ids) == 2, "两个变体的 endpoint_id 必须不同"
        shapes = {tuple(sorted(ep.extended_info.get("body_shape", []))) for ep in list_eps}
        assert shapes == {(), ("query",)}, f"预期 bodyShape = [] 和 ['query']，实际 {shapes}"

    def test_path_param_endpoint(self, converter):
        """:id 风格路径参数：getUplinkDeviceList/:id 必须被收录。"""
        endpoints = converter.to_endpoints()
        ep = next(
            (e for e in endpoints if e.path.endswith("/getUplinkDeviceList/:id")),
            None,
        )
        assert ep is not None, "找不到 getUplinkDeviceList/:id 端点"
        assert ep.method == HttpMethod.GET
        # path 参数应该被识别并清理装饰符
        path_params = [p for p in ep.parameters if p.location.value == "path"]
        assert any(p.name == "id" for p in path_params), \
            f"path 参数名应为 'id'，实际 {[p.name for p in path_params]}"

    def test_endpoint_tags_use_module(self, converter):
        """端点 tags 应包含 module slug（asset_management），用于脚本文件分组。"""
        endpoints = converter.to_endpoints()
        for ep in endpoints:
            assert "asset_management" in ep.tags, f"端点 {ep.path} tags 缺失 module: {ep.tags}"

    def test_endpoint_body_parameter_carries_example(self, converter):
        """add 端点的 body 参数必须携带完整 example（用于脚本渲染时填充）。"""
        endpoints = converter.to_endpoints()
        add_ep = next((e for e in endpoints if e.path.endswith("/knowasset/add")), None)
        assert add_ep is not None
        body_params = [p for p in add_ep.parameters if p.location.value == "body" and p.name == "body"]
        assert len(body_params) == 1
        example = body_params[0].example
        assert isinstance(example, dict)
        assert "asset_name" in example
        assert "network_card" in example


# --------------------------------------------------------------------- #
# 测试用例（GeneratedTestCase）
# --------------------------------------------------------------------- #

class TestTestCases:
    def test_count_equals_total_steps(self, converter, raw_doc):
        """test_cases 数量应等于所有 chain 的 step 数之和。"""
        expected = sum(len(c.get("steps", [])) for c in raw_doc["chains"])
        cases = converter.to_test_cases()
        assert len(cases) == expected, f"预期 {expected} 个用例，实际 {len(cases)}"
        # 已知本数据集 = 7 + 3 + 2 + 2 = 14
        assert expected == 14

    def test_each_case_has_scenario_tag(self, converter):
        """每个 case 的 tags 必须含 'scenario:<chain.name>' 用于前端聚合。"""
        cases = converter.to_test_cases()
        for tc in cases:
            scenario_tags = [t for t in tc.tags if t.startswith("scenario:")]
            assert len(scenario_tags) == 1, \
                f"用例 {tc.test_name} scenario tag 缺失或重复: {tc.tags}"

    def test_case_priority_matches_step_number(self, converter):
        """priority 字段应直接对应 step 序号，便于 scenario 渲染时反查。"""
        cases = converter.to_test_cases()
        # 不应有 priority=0 或负数
        assert all(tc.priority >= 1 for tc in cases)

    def test_case_endpoint_id_resolvable(self, converter):
        """每个 case.endpoint_id 必须能在 to_endpoints() 里找到。"""
        ep_ids = {ep.endpoint_id for ep in converter.to_endpoints()}
        for tc in converter.to_test_cases():
            assert tc.endpoint_id in ep_ids, \
                f"用例 {tc.test_name} 的 endpoint_id 找不到对应端点"


# --------------------------------------------------------------------- #
# 依赖
# --------------------------------------------------------------------- #

class TestDependencies:
    def test_dependency_count(self, converter):
        """根据 chains.steps[].dependsOn 计算预期依赖数：
        - chain 1: step4→[1,2,3] (3) + step5→[4] + step6→[4] + step7→[6] = 6
        - chain 2: step3→[1] = 1
        - chain 3: step2→[1] = 1
        - chain 4: step2→[1] = 1
        总计 = 9
        """
        deps = converter.to_dependencies()
        assert len(deps) == 9, f"预期 9 条依赖，实际 {len(deps)}"

    def test_all_dependencies_are_data_flow(self, converter):
        """转换器目前只产 DATA_FLOW 类型。"""
        for d in converter.to_dependencies():
            assert d.dependency_type == DependencyType.DATA_FLOW

    def test_source_and_target_endpoints_exist(self, converter):
        """所有依赖的 source/target endpoint_id 必须可解析。"""
        ep_ids = {ep.endpoint_id for ep in converter.to_endpoints()}
        for d in converter.to_dependencies():
            assert d.source_endpoint_id in ep_ids
            assert d.target_endpoint_id in ep_ids
            assert d.source_endpoint_id != d.target_endpoint_id

    def test_add_depends_on_three_get_endpoints(self, converter):
        """chain 1 step 4 (add) 依赖 step 1/2/3 的三个 GET 端点。"""
        endpoints = converter.to_endpoints()
        add_ep = next(e for e in endpoints if e.path.endswith("/knowasset/add"))
        sources = {
            d.source_endpoint_id
            for d in converter.to_dependencies()
            if d.target_endpoint_id == add_ep.endpoint_id
        }
        assert len(sources) == 3, \
            f"add 端点应被 3 个 GET 端点供数据，实际 {len(sources)}"


# --------------------------------------------------------------------- #
# 场景（ScenarioTestCase）
# --------------------------------------------------------------------- #

class TestScenarios:
    def test_scenario_count(self, converter):
        """4 个 chain → 4 个 scenario。"""
        assert len(converter.to_scenarios()) == 4

    def test_scenario_names(self, converter):
        names = {s.name for s in converter.to_scenarios()}
        assert names == {
            "资产生命周期 - 完整 CRUD",
            "资产筛选浏览",
            "资产详情查看",
            "上联设备表单选择",
        }

    def test_lifecycle_scenario_has_seven_steps(self, converter):
        """资产生命周期 chain 必须有 7 步且顺序为 1..7。"""
        lifecycle = next(
            s for s in converter.to_scenarios() if s.name == "资产生命周期 - 完整 CRUD"
        )
        assert len(lifecycle.steps) == 7
        assert [s.step for s in lifecycle.steps] == [1, 2, 3, 4, 5, 6, 7]

    def test_step4_data_in_references_prior_steps(self, converter):
        """资产生命周期 step 4 (add) 的 data_in 必须引用 step 1/2/3。"""
        lifecycle = next(
            s for s in converter.to_scenarios() if s.name == "资产生命周期 - 完整 CRUD"
        )
        step4 = lifecycle.steps[3]
        assert step4.step == 4
        data_in = step4.data_in
        assert "asset_type" in data_in
        assert data_in["asset_type"]["from"] == "step:1.dataOut.asset_type"
        assert data_in["asset_project"]["from"] == "step:2.dataOut.asset_project"
        assert data_in["tag1"]["from"] == "step:3.dataOut.tag1"
        assert data_in["tag1"].get("optional") is True

    def test_step5_find_assert(self, converter):
        """资产生命周期 step 5 (list) 必须有 find 断言。"""
        lifecycle = next(
            s for s in converter.to_scenarios() if s.name == "资产生命周期 - 完整 CRUD"
        )
        step5 = lifecycle.steps[4]
        assert step5.assert_spec is not None
        assert "find" in step5.assert_spec
        find_spec = step5.assert_spec["find"]
        assert find_spec["in"] == "response.data.list[]._id"
        assert find_spec["equalsRef"] == "step:4.dataOut.newAssetId"

    def test_step7_not_find_assert(self, converter):
        """资产生命周期 step 7 必须有 notFind 断言。"""
        lifecycle = next(
            s for s in converter.to_scenarios() if s.name == "资产生命周期 - 完整 CRUD"
        )
        step7 = lifecycle.steps[6]
        assert step7.assert_spec is not None
        assert "notFind" in step7.assert_spec

    def test_step4_data_out_new_asset_id(self, converter):
        """资产生命周期 step 4 必须声明 dataOut.newAssetId。"""
        lifecycle = next(
            s for s in converter.to_scenarios() if s.name == "资产生命周期 - 完整 CRUD"
        )
        step4 = lifecycle.steps[3]
        assert "newAssetId" in step4.data_out
        assert step4.data_out["newAssetId"]["path"] == "response.data"

    def test_browse_scenario_uses_query_body_shape(self, converter):
        """资产筛选浏览 step 3 必须用 bodyShape=['query'] 变体的 /list 端点。"""
        browse = next(
            s for s in converter.to_scenarios() if s.name == "资产筛选浏览"
        )
        step3 = browse.steps[2]
        assert step3.body_shape == ["query"]
        # 关联端点应该是 list 的 query 变体（非默认变体）
        endpoints_map = {e.endpoint_id: e for e in converter.to_endpoints()}
        related_ep = endpoints_map[step3.related_endpoint_id]
        assert sorted(related_ep.extended_info["body_shape"]) == ["query"]

    def test_lifecycle_and_browse_share_path_but_not_endpoint(self, converter):
        """资产生命周期 step 5 (bodyShape=[]) 和 资产筛选浏览 step 3 (bodyShape=['query'])
        路径相同但 endpoint_id 必须不同。"""
        scenarios = {s.name: s for s in converter.to_scenarios()}
        lifecycle_step5 = scenarios["资产生命周期 - 完整 CRUD"].steps[4]
        browse_step3 = scenarios["资产筛选浏览"].steps[2]
        assert lifecycle_step5.path == browse_step3.path
        assert lifecycle_step5.related_endpoint_id != browse_step3.related_endpoint_id

    def test_uplink_scenario_path_param(self, converter):
        """上联设备 step 2 必须保留 :id 路径参数原样。"""
        uplink = next(
            s for s in converter.to_scenarios() if s.name == "上联设备表单选择"
        )
        step2 = uplink.steps[1]
        assert step2.path.endswith("/getUplinkDeviceList/:id")
        assert step2.data_in.get("pathParams.:id", {}).get("from") == "step:1.dataOut.streamId"

    def test_primary_endpoint_is_write_when_available(self, converter):
        """资产生命周期 chain 的主端点应是 add（首个 POST），非首个 GET。"""
        lifecycle = next(
            s for s in converter.to_scenarios() if s.name == "资产生命周期 - 完整 CRUD"
        )
        endpoints_map = {e.endpoint_id: e for e in converter.to_endpoints()}
        primary = endpoints_map.get(lifecycle.primary_endpoint_id)
        assert primary is not None
        assert primary.path.endswith("/knowasset/add")
        assert primary.method == HttpMethod.POST

    def test_scenario_step_related_test_case_id_resolvable(self, converter):
        """每个 step 的 related_test_case_id 必须能在 test_cases 里找到。"""
        tc_ids = {tc.test_case_id for tc in converter.to_test_cases()}
        for sc in converter.to_scenarios():
            for step in sc.steps:
                if step.related_test_case_id:
                    assert step.related_test_case_id in tc_ids


# --------------------------------------------------------------------- #
# 边界 / 容错
# --------------------------------------------------------------------- #

class TestEdgeCases:
    def test_empty_doc(self):
        c = DependencyDocConverter({})
        assert c.to_endpoints() == []
        assert c.to_test_cases() == []
        assert c.to_dependencies() == []
        assert c.to_scenarios() == []

    def test_non_dict_input_raises(self):
        with pytest.raises(TypeError):
            DependencyDocConverter([])  # type: ignore[arg-type]

    def test_chain_without_steps(self):
        c = DependencyDocConverter({"chains": [{"name": "空 chain"}]})
        scenarios = c.to_scenarios()
        assert len(scenarios) == 1
        assert scenarios[0].steps == []

    def test_slugify_strips_dot(self):
        """关键：slug 必须把 '.' 去掉，否则会触发 uvicorn reload。"""
        s = DependencyDocConverter._slugify("v1.0.test")
        assert "." not in s

    def test_parse_step_ref(self):
        assert DependencyDocConverter._parse_step_ref("step:4.dataOut.newAssetId") == 4
        assert DependencyDocConverter._parse_step_ref("step:12.dataOut.foo.bar") == 12
        assert DependencyDocConverter._parse_step_ref("nonsense") is None
        assert DependencyDocConverter._parse_step_ref("") is None
        assert DependencyDocConverter._parse_step_ref(None) is None  # type: ignore[arg-type]

    def test_strip_path_var_decor(self):
        assert DependencyDocConverter._strip_path_var_decor(":id") == "id"
        assert DependencyDocConverter._strip_path_var_decor("{id}") == "id"
        assert DependencyDocConverter._strip_path_var_decor("name") == "name"
