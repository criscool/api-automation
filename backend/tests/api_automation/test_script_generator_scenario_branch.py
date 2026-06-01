"""ScriptGeneratorAgent 的 scenario 分支渲染冒烟测试。

不启动智能体 runtime，只测纯函数：DependencyDocConverter → _build_scenario_scripts
→ 渲染出的脚本能被 ast.parse 通过 + 关键字段存在。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.agents.api_automation.schemas import ScenarioTestCase
from app.agents.api_automation.script_generator_agent import ScriptGeneratorAgent
from app.services.api_automation.dependency_doc_converter import DependencyDocConverter


FIXTURE_PATH = Path("D:/code/aitestmind/api-docs/asset-management-dependencies.json")


@pytest.fixture(scope="module")
def raw_doc() -> dict:
    if not FIXTURE_PATH.exists():
        pytest.skip(f"依赖 JSON 不存在: {FIXTURE_PATH}")
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def converter(raw_doc) -> DependencyDocConverter:
    return DependencyDocConverter(raw_doc)


@pytest.fixture(scope="module")
def agent() -> ScriptGeneratorAgent:
    """构造 agent 但不真正连 LLM/runtime —— 只用纯函数方法。"""
    # ScriptGeneratorAgent.__init__ 会调用 _initialize_assistant_agent，
    # 但本测试只需要 _build_scenario_scripts / _render_scenario_script，
    # 走 __new__ + 手动注入最小属性以绕过 LLM 初始化
    a = ScriptGeneratorAgent.__new__(ScriptGeneratorAgent)
    a.agent_name = "test_script_generator"
    return a


# --------------------------------------------------------------------- #
# 整体生成
# --------------------------------------------------------------------- #

class TestBuildScenarioScripts:
    def test_one_script_per_scenario(self, agent, converter):
        scenarios = converter.to_scenarios()
        endpoints = converter.to_endpoints()
        test_cases = converter.to_test_cases()

        result = agent._build_scenario_scripts(scenarios, endpoints, test_cases)
        assert result["generation_method"] == "scenario_template"
        assert result["confidence_score"] == 1.0
        assert len(result["scripts"]) == len(scenarios) == 4

    def test_scripts_are_syntactically_valid_python(self, agent, converter):
        scenarios = converter.to_scenarios()
        endpoints = converter.to_endpoints()
        test_cases = converter.to_test_cases()

        result = agent._build_scenario_scripts(scenarios, endpoints, test_cases)
        for script in result["scripts"]:
            try:
                ast.parse(script["script_content"])
            except SyntaxError as e:
                pytest.fail(
                    f"{script['script_name']} 语法错误: {e}\n"
                    f"---\n{script['script_content']}\n---"
                )

    def test_file_paths_in_testcases_dir(self, agent, converter):
        result = agent._build_scenario_scripts(
            converter.to_scenarios(), converter.to_endpoints(), converter.to_test_cases()
        )
        for s in result["scripts"]:
            assert s["file_path"].startswith("testcases/")
            assert s["script_name"].startswith("test_scenario_")
            assert s["script_name"].endswith(".py")

    def test_test_case_ids_collected(self, agent, converter):
        """每个 scenario 脚本的 test_case_ids 应等于其 step 数（除非缺 case）。"""
        result = agent._build_scenario_scripts(
            converter.to_scenarios(), converter.to_endpoints(), converter.to_test_cases()
        )
        # 总 case 数应为 14
        total_ids = sum(len(s["test_case_ids"]) for s in result["scripts"])
        assert total_ids == 14


# --------------------------------------------------------------------- #
# 单脚本内容
# --------------------------------------------------------------------- #

class TestRenderedScriptContent:
    @pytest.fixture(scope="class")
    def scripts_by_name(self, agent, converter):
        scenarios = converter.to_scenarios()
        result = agent._build_scenario_scripts(
            scenarios, converter.to_endpoints(), converter.to_test_cases()
        )
        return {s["script_name"]: s["script_content"] for s in result["scripts"]}

    def test_lifecycle_script_has_seven_step_blocks(self, scripts_by_name):
        # 资产生命周期对应的脚本
        candidates = [n for n in scripts_by_name if "zi_chan" in n or "asset" in n.lower() or "crud" in n.lower()]
        # 4 个 scenario 应该有 4 个文件；这里只需要找出 7 步那个
        lifecycle_content = None
        for content in scripts_by_name.values():
            if "step 7" in content and "step 1" in content:
                lifecycle_content = content
                break
        assert lifecycle_content, "找不到 7 步生命周期脚本"
        # 校验 step 1..7 都出现
        for n in range(1, 8):
            assert f"step {n}:" in lifecycle_content, f"step {n} 块缺失"

    def test_imports_scenario_helpers(self, scripts_by_name):
        for name, content in scripts_by_name.items():
            assert "from automation.core.utils.scenario_helpers import" in content, \
                f"{name} 未导入 scenario_helpers"
            assert "apply_data_in" in content
            assert "extract_data_out" in content
            assert "run_assert" in content

    def test_uses_api_client_fixture(self, scripts_by_name):
        for name, content in scripts_by_name.items():
            assert "def test_chain(self, api_client):" in content, \
                f"{name} 未使用 api_client fixture"

    def test_has_pytestmark(self, scripts_by_name):
        for name, content in scripts_by_name.items():
            assert "pytestmark =" in content
            assert "pytest.mark.scenario" in content

    def test_path_param_chain_uses_render_path(self, scripts_by_name):
        """上联设备 chain step 2 应使用 :id 路径参数 → 渲染为 render_path 或 apply_data_in。"""
        # 找 uplink chain 对应脚本（其 path 含 getUplinkDeviceList）
        for content in scripts_by_name.values():
            if "getUplinkDeviceList" in content:
                # 该 step 2 用 dataIn pathParams.:id；apply_data_in 内部处理 :id 替换
                assert "pathParams.:id" in content
                return
        pytest.fail("找不到 uplink chain 脚本")

    def test_lifecycle_assert_blocks(self, scripts_by_name):
        """生命周期 step 5 / step 7 应输出 find / notFind 断言。"""
        for content in scripts_by_name.values():
            if "step 7" in content and "step 1" in content:
                assert "'find'" in content or '"find"' in content
                assert "'notFind'" in content or '"notFind"' in content
                return
        pytest.fail("找不到生命周期脚本")

    def test_path_param_with_data_in_override_keeps_template(self, scripts_by_name):
        """关键：path_params 若被 dataIn 接管，render_path 不应被传入示例描述，
        否则中文描述会被替换进 URL，运行时 apply_data_in 找不到 :id 占位符。"""
        for content in scripts_by_name.values():
            if "getUplinkDeviceList" not in content:
                continue
            # 找到 step 2 块（紧邻 getUplinkDeviceList）
            idx = content.find("getUplinkDeviceList")
            block_start = content.rfind("# ============ step", 0, idx)
            block_end = content.find("# ============ step", idx + 1)
            if block_end < 0:
                block_end = len(content)
            block = content[block_start:block_end]
            # 必须传空 dict 给 render_path（说明 :id 没被预渲染掉）
            assert "render_path('/api/plugins/com.andisec.plugins.assetbase/assetbase/knowasset/getUplinkDeviceList/:id', {})" in block, \
                f"path_params 未被过滤，render_path 收到非空字典：\n{block}"
            return
        pytest.fail("找不到 uplink chain 脚本")
