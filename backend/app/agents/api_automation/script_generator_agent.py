"""
脚本生成智能体 — 框架集成版本

核心职责：
1. 将测试用例转换为复用已有 pytest 框架的测试脚本
2. 生成 API Module 封装文件（确定性，不用 LLM）
3. 区分有依赖/无依赖接口，生成对应的 fixture 链或独立测试方法
4. 输出到 generated_tests/testcases/ 目录

数据流：ScriptGenerationInput -> 脚本生成 -> ScriptGenerationOutput
"""
import json
import re
import uuid
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path

from autogen_core import message_handler, type_subscription, MessageContext, TopicId
from loguru import logger

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.types import AgentTypes, TopicTypes

from .schemas import (
    ScriptGenerationInput, ScriptGenerationOutput, GeneratedScript,
    GeneratedTestCase, ParsedEndpoint, TestCaseType, AgentPrompts,
    EndpointDependency, DependencyType,
    ScenarioTestCase, ScenarioStepSpec
)
from .script_merger import merge_pytest_scripts


@type_subscription(topic_type=TopicTypes.TEST_SCRIPT_GENERATOR.value)
class ScriptGeneratorAgent(BaseApiAutomationAgent):
    """
    脚本生成智能体 — 框架集成版本

    生成的脚本复用 generated_tests/ 下的 pytest 框架：
    - 使用 api_client fixture（BaseClient，自动带 auth + base_url）
    - 使用 login_session fixture（AuthSession，session 级别登录）
    - 有依赖关系的接口通过 fixture 链传递数据
    - 无依赖关系的接口生成独立测试方法
    """

    def __init__(self, model_client_instance=None, agent_config=None, **kwargs):
        super().__init__(
            agent_type=AgentTypes.TEST_SCRIPT_GENERATOR,
            model_client_instance=model_client_instance,
            **kwargs
        )

        self.agent_config = agent_config or {}
        self._initialize_assistant_agent()

        self.generation_metrics = {
            "total_generations": 0,
            "successful_generations": 0,
            "failed_generations": 0,
            "total_scripts_generated": 0,
            "total_test_methods_generated": 0
        }

        self.generation_config = {
            "framework": "pytest",
            "enable_allure": True,
            "code_style": "pep8"
        }

        self.output_dir = Path("./generated_tests")
        self.testcases_dir = self.output_dir / "testcases"
        self.modules_dir = self.output_dir / "automation" / "api" / "modules"
        self.output_dir.mkdir(exist_ok=True)

        logger.info(f"脚本生成智能体初始化完成: {self.agent_name}")

    # =========================================================================
    # 主入口
    # =========================================================================

    @message_handler
    async def handle_script_generation_request(
        self,
        message: ScriptGenerationInput,
        ctx: MessageContext
    ) -> None:
        """处理脚本生成请求"""
        start_time = datetime.now()
        self.generation_metrics["total_generations"] += 1

        # 隔离模式：每次上传生成唯一后缀，避免覆盖已存在的同名脚本
        isolated = (message.generation_options or {}).get("isolated_mode", False)
        self._run_suffix = uuid.uuid4().hex[:8] if isolated else ""

        try:
            logger.info(
                f"开始生成测试脚本: document_id={message.document_id}, "
                f"interface_id={getattr(message, 'interface_id', None)}, "
                f"测试用例数量: {len(message.test_cases)}, "
                f"端点数量: {len(message.endpoints)}, "
                f"依赖关系数量: {len(getattr(message, 'dependencies', []))}"
            )

            await self._log_operation_start(
                message.session_id,
                "script_generation",
                {
                    "document_id": message.document_id,
                    "interface_id": getattr(message, 'interface_id', None),
                    "test_cases_count": len(message.test_cases),
                    "endpoints_count": len(message.endpoints),
                    "dependencies_count": len(getattr(message, 'dependencies', []))
                }
            )

            # 1. 生成 API Module 文件（确定性）
            await self._log_operation_progress(
                message.session_id, "script_generation", "生成 API Module 封装"
            )
            api_module_info = self._generate_api_module(message.endpoints)

            # 2. 选择生成路径：
            #    - 有 scenarios（来自依赖 JSON 旁路）→ 走模板渲染，不调 LLM
            #    - 否则走原流水线（LLM + fallback）
            scenarios = getattr(message, "scenarios", None) or []
            if scenarios:
                await self._log_operation_progress(
                    message.session_id, "script_generation",
                    "scenario 模板渲染（跳过 LLM）",
                    {"scenarios_count": len(scenarios)}
                )
                generation_result = self._build_scenario_scripts(
                    scenarios, message.endpoints, message.test_cases
                )
            else:
                await self._log_operation_progress(
                    message.session_id, "script_generation", "智能生成测试脚本"
                )
                generation_result = await self._intelligent_generate_scripts(
                    message.api_info,
                    message.endpoints,
                    message.test_cases,
                    getattr(message, 'dependencies', []),
                    message.execution_groups,
                    message.generation_options
                )

            # 3. 构建脚本对象
            await self._log_operation_progress(
                message.session_id, "script_generation", "构建脚本对象",
                {"scripts_count": len(generation_result.get("scripts", []))}
            )
            scripts = self._build_script_objects(
                generation_result.get("scripts", []), message.test_cases
            )

            # 4. 构建输出
            generation_summary = self._generate_summary(scripts, generation_result)

            output = ScriptGenerationOutput(
                session_id=message.session_id,
                document_id=message.document_id,
                interface_id=getattr(message, 'interface_id', None),
                scripts=scripts,
                config_files={},
                requirements_txt="",
                readme_content="",
                generation_summary=generation_summary,
                processing_time=(datetime.now() - start_time).total_seconds()
            )

            # 5. 更新指标
            self.generation_metrics["successful_generations"] += 1
            self.generation_metrics["total_scripts_generated"] += len(scripts)
            self.generation_metrics["total_test_methods_generated"] += sum(
                len(script.test_case_ids) for script in scripts
            )
            self._update_metrics("script_generation", True, output.processing_time)

            # 6. 保存文件
            await self._log_operation_progress(
                message.session_id, "script_generation", "保存生成文件"
            )
            await self._save_generated_files(output)

            # 7. 发送到持久化智能体
            await self._log_operation_progress(
                message.session_id, "script_generation", "发送到数据持久化智能体"
            )
            await self._send_to_persistence_agent(output, message, ctx)

            await self._log_operation_complete(
                message.session_id, "script_generation",
                {"scripts_count": len(scripts), "processing_time": output.processing_time}
            )

            logger.info(f"脚本生成完成: {message.document_id}, 生成脚本数: {len(scripts)}")

        except Exception as e:
            self.generation_metrics["failed_generations"] += 1
            self._update_metrics("script_generation", False)
            error_info = self._handle_common_error(e, "script_generation")
            await self._log_operation_error(message.session_id, "script_generation", e)
            logger.error(f"脚本生成失败: {error_info}")

    # =========================================================================
    # API Module 生成（确定性，不用 LLM）
    # =========================================================================

    def _generate_api_module(self, endpoints: List[ParsedEndpoint]) -> Dict[str, Any]:
        """
        为端点生成 API Module 封装文件。
        返回 {module_name: str, functions: List[str], file_path: str}
        """
        if not endpoints:
            return {"module_name": "", "functions": [], "file_path": ""}

        tags = []
        for ep in endpoints:
            if ep.tags:
                tags.extend(ep.tags)
        module_name = self._sanitize_name(tags[0] if tags else "general")

        if module_name == "login":
            return {"module_name": "login", "functions": [], "file_path": ""}

        self.modules_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.modules_dir / f"{module_name}_api.py"

        functions = []
        function_codes = []

        for ep in endpoints:
            func_name = self._endpoint_to_function_name(ep)
            method_lower = ep.method.value.lower()
            path = ep.path

            has_body = method_lower in ("post", "put", "patch")
            has_params = any(
                p.location.value == "query" for p in ep.parameters
            )

            params = ["client"]
            if has_body:
                params.append("body=None")
            if has_params:
                params.append("params=None")
            params.append("**kwargs")

            params_str = ", ".join(params)

            call_args = []
            if has_body:
                call_args.append("json=body")
            if has_params:
                call_args.append("params=params")
            call_args.append("**kwargs")
            call_args_str = ", ".join(call_args)

            summary = ep.summary or f"{ep.method.value} {ep.path}"
            code = f'''def {func_name}({params_str}):
    """{summary}"""
    return client.{method_lower}("{path}", {call_args_str})'''

            function_codes.append(code)
            functions.append(f"{func_name}({params_str})")

        if file_path.exists():
            logger.info(f"API Module 已存在，跳过: {file_path}")
        else:
            module_content = f'''"""
{module_name} API 封装
自动生成 — 请勿手动修改
"""


{chr(10).join(chr(10).join([code, ""]) for code in function_codes)}'''

            file_path.write_text(module_content, encoding='utf-8')
            logger.info(f"已生成 API Module: {file_path}")

        return {
            "module_name": module_name,
            "functions": functions,
            "file_path": str(file_path)
        }

    # =========================================================================
    # Scenario 模板渲染（依赖 JSON 旁路：不调 LLM）
    # =========================================================================

    def _build_scenario_scripts(
        self,
        scenarios: List[ScenarioTestCase],
        endpoints: List[ParsedEndpoint],
        test_cases: List[GeneratedTestCase],
    ) -> Dict[str, Any]:
        """每个 scenario → 一个 testcases/test_scenario_<slug>.py 脚本。"""
        scripts: List[Dict[str, Any]] = []
        ep_by_id = {ep.endpoint_id: ep for ep in endpoints}
        for sc in scenarios:
            if not sc.steps:
                logger.warning(f"scenario 无步骤，跳过: {sc.name}")
                continue
            script_name, content = self._render_scenario_script(sc, ep_by_id)
            if not content:
                continue
            tc_ids = [s.related_test_case_id for s in sc.steps if s.related_test_case_id]
            scripts.append({
                "script_name": script_name,
                "file_path": f"testcases/{script_name}",
                "script_content": content,
                "test_case_ids": tc_ids,
                "framework": "pytest",
                "dependencies": ["pytest"],
                "execution_order": 1,
            })
        return {
            "scripts": scripts,
            "confidence_score": 1.0,
            "generation_method": "scenario_template",
        }

    def _render_scenario_script(
        self,
        sc: ScenarioTestCase,
        ep_by_id: Dict[str, ParsedEndpoint],
    ) -> Tuple[str, str]:
        """渲染单个 scenario 脚本：一个 class + 一个 test_chain 方法。
        返回 (script_name, content, class_name)。"""
        import pprint

        slug = self._sanitize_name(sc.name)
        script_name = self._suffix_name(f"test_scenario_{slug}.py")
        class_name = "TestScenario" + "".join(w.capitalize() for w in slug.split("_") if w)
        if not class_name or class_name == "TestScenario":
            class_name = "TestScenarioChain"

        # marker：取 module slug（如 asset_management），跳过 "scenario" 字符串
        marker_tag = next(
            (t for t in sc.tags if t and t != "scenario"),
            None,
        )
        marker_tag = self._sanitize_name(marker_tag) if marker_tag else "scenario"

        def lit(obj: Any) -> str:
            """把 Python 对象格式化为可嵌入源码的字面量（处理中文 + 缩进）。"""
            return pprint.pformat(obj, indent=4, width=100, sort_dicts=False)

        lines: List[str] = []
        # ---- 文件头 ----
        lines.append(f'"""{sc.name}（场景测试，自动生成）')
        if sc.description:
            lines.append("")
            lines.append(sc.description)
        lines.append('"""')
        lines.append("import pytest")
        lines.append("")
        lines.append("from automation.core.utils.scenario_helpers import (")
        lines.append("    apply_data_in,")
        lines.append("    extract_data_out,")
        lines.append("    render_path,")
        lines.append("    run_assert,")
        lines.append(")")
        lines.append("")
        lines.append(f"pytestmark = [pytest.mark.{marker_tag}, pytest.mark.scenario]")
        lines.append("")
        lines.append("")
        lines.append(f"class {class_name}:")
        lines.append(f'    """{sc.name}"""')
        lines.append("")
        lines.append("    def test_chain(self, api_client):")
        method_doc = sc.description or sc.name
        lines.append(f'        """{method_doc}"""')
        lines.append("        ctx: dict = {}")
        lines.append("")

        for step in sc.steps:
            method_lower = step.method.value.lower()
            purpose = (step.purpose or "").replace("\n", " ")[:60]
            lines.append(f"        # ============ step {step.step}: {purpose} ============")

            body_lit = lit(step.body or {})
            query_lit = lit(step.query or {})

            # 规范化 data_in：统一将 "path.:xxx" 转为 "pathParams.xxx"
            # 依赖分析工具可能沿用 URL 的 :var 写法，生成器统一纠正
            raw_data_in = step.data_in or {}
            normalized_data_in: Dict[str, Dict[str, Any]] = {}
            for k, v in raw_data_in.items():
                m = re.match(r"^path\.:(.+)$", k)
                normalized_data_in[f"pathParams.{m.group(1)}" if m else k] = v

            # pathParams 由 dataIn 提供运行时值时，剔除示例值
            data_in_path_keys: set = {
                k[len("pathParams."):].lstrip(":").strip("{}")
                for k in normalized_data_in.keys()
                if isinstance(k, str) and k.startswith("pathParams.")
            }
            filtered_path_params = {
                k: v for k, v in (step.path_params or {}).items()
                if str(k).lstrip(":").strip("{}") not in data_in_path_keys
            }
            path_params_lit = lit(filtered_path_params)
            data_in_lit = lit(normalized_data_in)

            # apply_data_in 返回 (body, query, path)
            lines.append("        body, query, path = apply_data_in(")
            lines.append(self._indent_literal(body_lit, 12) + ",")
            lines.append(self._indent_literal(query_lit, 12) + ",")
            lines.append(f"            render_path({step.path!r}, {path_params_lit}),")
            lines.append(self._indent_literal(data_in_lit, 12) + ",")
            lines.append("            ctx,")
            lines.append("        )")

            # HTTP 调用：GET / DELETE 走 query；POST/PUT/PATCH 同时支持 body+query
            if method_lower == "get":
                lines.append("        resp = api_client.get(path, params=query or None)")
            elif method_lower == "delete":
                lines.append("        resp = api_client.delete(path, params=query or None)")
            elif method_lower in ("post", "put", "patch"):
                lines.append(
                    f"        resp = api_client.{method_lower}("
                    f"path, json=body, params=query or None)"
                )
            else:
                lines.append(
                    f"        resp = api_client.request({method_lower.upper()!r}, "
                    f"path, json=body, params=query or None)"
                )

            lines.append(
                f"        assert resp.status_code == 200, "
                f'f"step {step.step} status={{resp.status_code}}, body={{resp.text[:200]}}"'
            )
            lines.append("        resp_json = resp.json() if resp.content else {}")

            if step.data_out:
                data_out_lit = lit(step.data_out)
                lines.append(
                    f"        ctx[{step.step}] = {{'dataOut': extract_data_out("
                    f"resp_json, {data_out_lit})}}"
                )
            else:
                lines.append(f"        ctx.setdefault({step.step}, {{'dataOut': {{}}}})")

            if step.assert_spec:
                assert_lit = lit(step.assert_spec)
                lines.append(
                    f"        run_assert(resp_json, {assert_lit}, ctx, step_no={step.step})"
                )

            lines.append("")

        content = "\n".join(lines) + "\n"
        return script_name, content

    @staticmethod
    def _indent_literal(literal: str, indent: int) -> str:
        """把多行字面量整体缩进 indent 个空格。第一行也加。"""
        prefix = " " * indent
        lines = literal.splitlines()
        if not lines:
            return prefix
        return "\n".join(prefix + ln for ln in lines)

    # =========================================================================
    # LLM 智能生成
    # =========================================================================

    async def _intelligent_generate_scripts(
        self,
        api_info,
        endpoints: List[ParsedEndpoint],
        test_cases: List[GeneratedTestCase],
        dependencies: List = None,
        execution_groups=None,
        generation_options: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """使用 LLM 智能生成测试脚本"""
        try:
            dependencies = dependencies or []
            execution_groups = execution_groups or []
            generation_options = generation_options or {}

            api_info_str = json.dumps({
                "title": api_info.title,
                "version": api_info.version,
                "description": api_info.description,
                "base_url": api_info.base_url
            }, indent=2, ensure_ascii=False)

            endpoints_info = self._format_endpoints_for_generation(endpoints)
            test_cases_info = self._format_test_cases_for_generation(test_cases)
            dependencies_info = self._format_dependencies_for_generation(dependencies)
            groups_info = self._format_execution_groups_for_generation(execution_groups)
            options_info = json.dumps(generation_options, indent=2, ensure_ascii=False)

            task_prompt = AgentPrompts.SCRIPT_GENERATOR_TASK_PROMPT.format(
                api_info=api_info_str,
                endpoints=endpoints_info,
                test_cases=test_cases_info,
                dependencies=dependencies_info,
                execution_groups=groups_info,
                generation_options=options_info
            )

            # LLM 调用加超时保护，避免请求挂起拖死整个分析流程
            llm_timeout = (generation_options or {}).get("llm_timeout", 180)
            try:
                result_content = await asyncio.wait_for(
                    self._run_assistant_agent(task_prompt),
                    timeout=llm_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(f"LLM 调用超时（{llm_timeout}s），使用 fallback 生成")
                return await self._fallback_generate_scripts(endpoints, test_cases, dependencies)

            if result_content:
                parsed_data = self._extract_json_from_content(result_content)
                if parsed_data:
                    return parsed_data

            logger.warning("LLM 生成失败，使用 fallback 生成方法")
            return await self._fallback_generate_scripts(endpoints, test_cases, dependencies)

        except Exception as e:
            logger.error(f"智能脚本生成失败: {str(e)}")
            return await self._fallback_generate_scripts(endpoints, test_cases, dependencies)

    # =========================================================================
    # Fallback 生成（确定性模板）
    # =========================================================================

    async def _fallback_generate_scripts(
        self,
        endpoints: List[ParsedEndpoint],
        test_cases: List[GeneratedTestCase],
        dependencies: List = None
    ) -> Dict[str, Any]:
        """备用脚本生成 — 生成框架集成脚本（test 文件 + 可选 conftest.py）"""
        try:
            dependencies = dependencies or []
            independent_eps, dependent_groups = self._classify_by_dependency(
                endpoints, dependencies
            )

            test_content, conftest_content = self._generate_framework_script_template(
                endpoints, test_cases, dependencies,
                independent_eps, dependent_groups
            )

            script_name = self._derive_script_name(endpoints)

            scripts = []

            # 业务 fixture 共享层（仅在有依赖时输出）
            if conftest_content:
                scripts.append({
                    "script_name": "conftest.py",
                    "file_path": "testcases/conftest.py",
                    "script_content": conftest_content,
                    "test_case_ids": [],
                    "framework": "pytest",
                    "dependencies": ["pytest"],
                    "execution_order": 0
                })

            scripts.append({
                "script_name": script_name,
                "file_path": f"testcases/{script_name}",
                "script_content": test_content,
                "test_case_ids": [tc.test_case_id for tc in test_cases],
                "framework": "pytest",
                "dependencies": ["pytest"],
                "execution_order": 1
            })

            return {
                "scripts": scripts,
                "confidence_score": 0.7,
                "generation_method": "fallback"
            }

        except Exception as e:
            logger.error(f"备用脚本生成失败: {str(e)}")
            return {"scripts": [], "confidence_score": 0.3}

    def _generate_framework_script_template(
        self,
        endpoints: List[ParsedEndpoint],
        test_cases: List[GeneratedTestCase],
        dependencies: List,
        independent_eps: List[ParsedEndpoint],
        dependent_groups: List[Dict]
    ) -> Tuple[str, str]:
        """生成框架集成脚本模板。

        返回 (test_content, conftest_content)：
        - test_content: testcases/test_xxx.py 内容（只含 imports + pytestmark + class）
        - conftest_content: testcases/conftest.py 内容（业务 fixture 共享层）；无 fixture 时为空串
        """
        tags = set()
        for ep in endpoints:
            for tag in ep.tags:
                tags.add(self._sanitize_name(tag))

        marker_tag = list(tags)[0] if tags else "api"
        class_name = self._derive_class_name(endpoints)

        lines = []

        # 1. 文件头
        title = endpoints[0].summary if endpoints else "API"
        lines.append(f'"""{title} 接口测试"""')
        lines.append("import pytest")
        lines.append("")
        lines.append(f"pytestmark = [pytest.mark.{marker_tag}, pytest.mark.api]")
        lines.append("")

        # 2. 业务 fixture 输出到独立 conftest_content（不嵌入 test 文件）
        fixture_code = self._generate_fixture_chain(dependent_groups, endpoints, test_cases)
        conftest_content = ""
        if fixture_code:
            conftest_content = "\n".join([
                '"""共享业务 fixture（由 ScriptGeneratorAgent 自动生成 + 合并）"""',
                "import pytest",
                "",
                "",
                fixture_code,
            ])

        # 3. 测试类
        lines.append(f"class {class_name}:")
        lines.append("")

        used_names: set = set()

        # 3.1 独立接口的测试方法
        for ep in independent_eps:
            ep_cases = [tc for tc in test_cases if tc.endpoint_id == ep.endpoint_id]
            if not ep_cases:
                ep_cases = [self._create_default_test_case(ep)]
            for tc in ep_cases:
                method_code = self._generate_test_method(tc, ep, used_names)
                lines.append(method_code)
                lines.append("")

        # 3.2 依赖链的测试方法
        for group in dependent_groups:
            group_eps = group["endpoints"]
            group_deps = group.get("dependencies", [])
            ep_by_id = {ep.endpoint_id: ep for ep in group_eps}

            # 资源消费者（DELETE/GET-by-id/PUT-by-id）→ 资源创建者（POST 等）的反向映射
            creator_of: Dict[str, ParsedEndpoint] = {}
            for dep in group_deps:
                src = ep_by_id.get(dep.source_endpoint_id)
                tgt = ep_by_id.get(dep.target_endpoint_id)
                if src and tgt and src.method.value.lower() in ("post", "put", "patch"):
                    creator_of.setdefault(tgt.endpoint_id, src)

            for ep in group_eps:
                method_lower = ep.method.value.lower()
                if method_lower in ("post", "put", "patch"):
                    fixture_ep = ep
                else:
                    fixture_ep = creator_of.get(ep.endpoint_id) or ep
                fixture_name = self._endpoint_to_fixture_name(fixture_ep)

                ep_cases = [tc for tc in test_cases if tc.endpoint_id == ep.endpoint_id]
                if not ep_cases:
                    ep_cases = [self._create_default_test_case(ep)]

                for tc in ep_cases:
                    method_code = self._generate_dependent_test_method(
                        tc, ep, fixture_name, used_names
                    )
                    lines.append(method_code)
                    lines.append("")

        # 如果测试类为空，添加占位方法
        class_body = "\n".join(lines)
        if f"class {class_name}:" in class_body and "def test_" not in class_body.split(f"class {class_name}:")[1]:
            lines.append("    def test_placeholder(self, api_client):")
            lines.append('        """占位测试"""')
            lines.append("        pass")
            lines.append("")

        return "\n".join(lines), conftest_content

    # =========================================================================
    # 依赖分类
    # =========================================================================

    def _classify_by_dependency(
        self,
        endpoints: List[ParsedEndpoint],
        dependencies: List
    ) -> Tuple[List[ParsedEndpoint], List[Dict]]:
        """
        将端点分为独立和有依赖两组。
        过滤掉 AUTH 类型依赖（框架已处理认证）。
        """
        non_auth_deps = [
            dep for dep in dependencies
            if not self._is_auth_dependency(dep)
        ]

        dependent_ep_ids: Set[str] = set()
        for dep in non_auth_deps:
            dependent_ep_ids.add(dep.source_endpoint_id)
            dependent_ep_ids.add(dep.target_endpoint_id)

        ep_map = {ep.endpoint_id: ep for ep in endpoints}

        independent_eps = [
            ep for ep in endpoints if ep.endpoint_id not in dependent_ep_ids
        ]

        dependent_endpoints = [
            ep for ep in endpoints if ep.endpoint_id in dependent_ep_ids
        ]

        dependent_groups = []
        if dependent_endpoints:
            sorted_eps = self._topological_sort(dependent_endpoints, non_auth_deps)
            dependent_groups.append({
                "endpoints": sorted_eps,
                "dependencies": non_auth_deps
            })

        return independent_eps, dependent_groups

    def _is_auth_dependency(self, dep) -> bool:
        """判断是否为认证类型依赖"""
        dep_type = dep.dependency_type
        if hasattr(dep_type, 'value'):
            dep_type = dep_type.value
        return dep_type in ("auth", "auth_token", DependencyType.AUTH.value, DependencyType.AUTH_TOKEN.value)

    def _topological_sort(
        self,
        endpoints: List[ParsedEndpoint],
        dependencies: List
    ) -> List[ParsedEndpoint]:
        """按依赖关系拓扑排序"""
        ep_map = {ep.endpoint_id: ep for ep in endpoints}
        in_degree = {ep.endpoint_id: 0 for ep in endpoints}
        adj = {ep.endpoint_id: [] for ep in endpoints}

        for dep in dependencies:
            src = dep.source_endpoint_id
            tgt = dep.target_endpoint_id
            if src in adj and tgt in in_degree:
                adj[src].append(tgt)
                in_degree[tgt] += 1

        queue = [eid for eid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            eid = queue.pop(0)
            if eid in ep_map:
                result.append(ep_map[eid])
            for neighbor in adj.get(eid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        for ep in endpoints:
            if ep not in result:
                result.append(ep)

        return result

    # =========================================================================
    # Fixture 链生成
    # =========================================================================

    def _infer_delete_path(
        self, post_ep: ParsedEndpoint, all_endpoints: List[ParsedEndpoint]
    ) -> Optional[str]:
        """推断与 POST 端点对应的 DELETE 路径模板。

        例：post_ep.path = "/api/alarm-rule"
        在 all_endpoints 中寻找 method=DELETE 且 path 形如 "/api/alarm-rule/{id}"
        或 "/api/alarm-rule/:id" 的端点，返回该 path 模板。
        找不到返回 None（无法清理）。
        """
        post_path = post_ep.path.rstrip("/")
        var_pattern = re.compile(r"^(\{[^/{}]+\}|:[A-Za-z_][A-Za-z0-9_]*)$")
        for ep in all_endpoints:
            if ep.method.value.upper() != "DELETE":
                continue
            ep_path = ep.path
            if not ep_path.startswith(post_path + "/"):
                continue
            remainder = ep_path[len(post_path) + 1:]
            if var_pattern.match(remainder):
                return ep_path
        return None

    def _generate_fixture_chain(
        self,
        dependent_groups: List[Dict],
        endpoints: List[ParsedEndpoint],
        test_cases: List[GeneratedTestCase]
    ) -> str:
        """生成 fixture 链代码（yield + teardown 自动清理）"""
        if not dependent_groups:
            return ""

        lines = []
        prev_fixture_name = None

        for group in dependent_groups:
            sorted_eps = group["endpoints"]
            deps = group["dependencies"]

            for i, ep in enumerate(sorted_eps):
                method_lower = ep.method.value.lower()
                if method_lower not in ("post", "put", "patch"):
                    continue

                fixture_name = self._endpoint_to_fixture_name(ep)
                func_name = self._endpoint_to_function_name(ep)

                params = ["api_client"]
                if prev_fixture_name:
                    params.append(prev_fixture_name)
                params_str = ", ".join(params)

                summary = ep.summary or f"{ep.method.value} {ep.path}"

                test_data = self._get_test_data_for_endpoint(ep, test_cases)

                lines.append("@pytest.fixture")
                lines.append(f"def {fixture_name}({params_str}):")
                lines.append(f'    """{summary}"""')

                if method_lower in ("post", "put", "patch"):
                    body_str = json.dumps(test_data, ensure_ascii=False) if test_data else "{}"
                    if prev_fixture_name:
                        lines.append(f"    resp = api_client.{method_lower}(")
                        lines.append(f'        f"{ep.path}",')
                        lines.append(f"        json={body_str}")
                        lines.append(f"    )")
                    else:
                        lines.append(f'    resp = api_client.{method_lower}("{ep.path}", json={body_str})')
                else:
                    lines.append(f'    resp = api_client.{method_lower}("{ep.path}")')

                lines.append("    assert resp.status_code == 200")
                lines.append("    data = resp.json()")
                lines.append('    assert "data" in data')
                lines.append('    resource_id = data["data"].get("id") or data["data"].get("session_id")')
                lines.append("    assert resource_id is not None")

                # 推断 DELETE 路径：有则 yield + teardown 清理；无则保持 return（无法清理）
                delete_path = self._infer_delete_path(ep, endpoints) if method_lower == "post" else None
                if delete_path:
                    rendered_delete = self._render_path_with_fixture(delete_path, "resource_id")
                    lines.append("")
                    lines.append("    yield resource_id")
                    lines.append("")
                    lines.append("    # teardown: 容忍 404（资源已被测试方法删除是预期场景）")
                    lines.append(f"    cleanup_resp = api_client.delete({rendered_delete})")
                    lines.append("    assert cleanup_resp.status_code in (200, 204, 404), \\")
                    lines.append('        f"清理失败 id={resource_id}, status={cleanup_resp.status_code}"')
                else:
                    lines.append("    return resource_id")

                lines.append("")
                lines.append("")

                prev_fixture_name = fixture_name

        return "\n".join(lines)

    # =========================================================================
    # 测试方法生成
    # =========================================================================

    def _generate_test_method(
        self, test_case: GeneratedTestCase, endpoint: ParsedEndpoint,
        used_names: set = None,
    ) -> str:
        """生成独立接口的测试方法"""
        method_lower = endpoint.method.value.lower()
        method_name = self._sanitize_method_name(test_case.test_name, method_lower, used_names)
        path = endpoint.path
        description = test_case.description or f"{endpoint.method.value} {path}"
        is_negative = test_case.test_type in (TestCaseType.NEGATIVE, TestCaseType.BOUNDARY, TestCaseType.SECURITY)

        lines = []
        lines.append(f"    def {method_name}(self, api_client):")
        lines.append(f'        """{description}"""')

        test_data = {}
        for td in test_case.test_data:
            key = td.parameter_name.replace("-", "_")
            test_data[key] = td.test_value

        has_body = method_lower in ("post", "put", "patch")
        has_query = any(p.location.value == "query" for p in endpoint.parameters)

        if has_body and not test_data and not is_negative:
            test_data = self._extract_body_example(endpoint)

        if has_body and test_data:
            body_str = json.dumps(test_data, ensure_ascii=False, indent=12)
            lines.append(f"        resp = api_client.{method_lower}(")
            lines.append(f'            "{path}",')
            lines.append(f"            json={body_str}")
            lines.append(f"        )")
        elif has_query and test_data:
            params_str = json.dumps(test_data, ensure_ascii=False)
            lines.append(f'        resp = api_client.{method_lower}("{path}", params={params_str})')
        else:
            lines.append(f'        resp = api_client.{method_lower}("{path}")')

        if is_negative:
            lines.append("        assert resp.status_code in [400, 422, 403, 404]")
        else:
            lines.append("        assert resp.status_code == 200")
            lines.append("        data = resp.json()")
            lines.append('        assert "data" in data')

            if method_lower == "get":
                lines.append('        result = data["data"]')
                lines.append("        assert result is not None")
            elif method_lower in ("post", "put", "patch") and test_data:
                lines.append('        result = data["data"]')
                lines.append("        assert isinstance(result, dict)")
                first_key = list(test_data.keys())[0] if test_data else None
                if first_key:
                    original_key = first_key.replace("_", "-") if "-" in test_case.test_data[0].parameter_name else first_key
                    lines.append(f'        assert result.get("{original_key}") == "{test_data[first_key]}"')

        return "\n".join(lines)

    def _generate_dependent_test_method(
        self, test_case: GeneratedTestCase, endpoint: ParsedEndpoint,
        fixture_name: str, used_names: set = None,
    ) -> str:
        """生成依赖链中的测试方法"""
        method_lower = endpoint.method.value.lower()
        method_name = self._sanitize_method_name(test_case.test_name, method_lower, used_names)
        path = endpoint.path
        description = test_case.description or f"{endpoint.method.value} {path}"

        path_call = self._render_path_with_fixture(path, fixture_name)

        lines = []

        if method_lower in ("post", "put", "patch"):
            lines.append(f"    def {method_name}(self, {fixture_name}):")
            lines.append(f'        """{description}"""')
            lines.append(f"        assert {fixture_name} is not None")
        elif method_lower == "get":
            lines.append(f"    def {method_name}(self, api_client, {fixture_name}):")
            lines.append(f'        """{description}"""')
            lines.append(f'        resp = api_client.get({path_call})')
            lines.append("        assert resp.status_code == 200")
            lines.append("        data = resp.json()")
            lines.append('        assert "data" in data')
            lines.append('        detail = data["data"]')
            lines.append(f'        assert str(detail.get("id", "")) == str({fixture_name})')
        elif method_lower == "delete":
            lines.append(f"    def {method_name}(self, api_client, {fixture_name}):")
            lines.append(f'        """{description}"""')
            lines.append(f'        resp = api_client.delete({path_call})')
            lines.append("        assert resp.status_code == 200")
        else:
            lines.append(f"    def {method_name}(self, api_client, {fixture_name}):")
            lines.append(f'        """{description}"""')
            lines.append(f'        resp = api_client.{method_lower}({path_call})')
            lines.append("        assert resp.status_code == 200")

        return "\n".join(lines)

    def _render_path_with_fixture(self, path: str, fixture_name: str) -> str:
        """将带路径变量的 path 渲染为 f-string，没有变量则追加 /{fixture_name}。"""
        import re
        brace_pattern = re.compile(r"\{[^/{}]+\}")
        colon_pattern = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")

        if brace_pattern.search(path):
            rendered = brace_pattern.sub(f"{{{fixture_name}}}", path, count=1)
            return f'f"{rendered}"'
        if colon_pattern.search(path):
            rendered = colon_pattern.sub(f"{{{fixture_name}}}", path, count=1)
            return f'f"{rendered}"'
        return f'f"{path}/{{{fixture_name}}}"'

    # =========================================================================
    # 格式化方法（数据 → LLM prompt 文本）
    # =========================================================================

    def _format_endpoints_for_generation(self, endpoints: List[ParsedEndpoint]) -> str:
        formatted_endpoints = []
        for endpoint in endpoints:
            endpoint_info = {
                "id": endpoint.endpoint_id,
                "path": endpoint.path,
                "method": endpoint.method.value,
                "summary": endpoint.summary,
                "tags": endpoint.tags,
                "auth_required": endpoint.auth_required,
                "parameters": [
                    {
                        "name": param.name,
                        "location": param.location.value,
                        "type": param.data_type.value,
                        "required": param.required,
                        "description": param.description,
                        "example": param.example,
                        "constraints": param.constraints or {},
                    }
                    for param in endpoint.parameters
                ],
                "responses": [
                    {
                        "status_code": resp.status_code,
                        "description": resp.description,
                        "response_schema": resp.response_schema,
                        "example": resp.example,
                    }
                    for resp in endpoint.responses
                ]
            }
            formatted_endpoints.append(endpoint_info)
        return json.dumps(formatted_endpoints, indent=2, ensure_ascii=False, default=str)

    def _format_test_cases_for_generation(self, test_cases: List[GeneratedTestCase]) -> str:
        formatted_cases = []
        for case in test_cases:
            case_info = {
                "test_id": case.test_case_id,
                "test_name": case.test_name,
                "endpoint_id": case.endpoint_id,
                "test_type": case.test_type.value,
                "description": case.description,
                "test_data": [
                    {
                        "parameter_name": data.parameter_name,
                        "test_value": data.test_value,
                        "value_description": data.value_description
                    }
                    for data in case.test_data
                ],
                "assertions": [
                    {
                        "assertion_type": assertion.assertion_type.value,
                        "expected_value": assertion.expected_value,
                        "comparison_operator": assertion.comparison_operator,
                        "description": assertion.description
                    }
                    for assertion in case.assertions
                ],
                "setup_steps": case.setup_steps,
                "cleanup_steps": case.cleanup_steps,
                "priority": case.priority,
                "tags": case.tags
            }
            formatted_cases.append(case_info)
        return json.dumps(formatted_cases, indent=2, ensure_ascii=False)

    def _format_dependencies_for_generation(self, dependencies) -> str:
        if not dependencies:
            return "[]"
        formatted_deps = []
        for dep in dependencies:
            dep_info = {
                "source_endpoint_id": dep.source_endpoint_id,
                "target_endpoint_id": dep.target_endpoint_id,
                "dependency_type": dep.dependency_type.value if hasattr(dep.dependency_type, 'value') else str(dep.dependency_type),
                "description": dep.description,
                "data_mapping": dep.data_mapping
            }
            formatted_deps.append(dep_info)
        return json.dumps(formatted_deps, indent=2, ensure_ascii=False)

    def _format_execution_groups_for_generation(self, execution_groups) -> str:
        formatted_groups = []
        for group in execution_groups:
            group_info = {
                "group_name": group.group_name,
                "endpoint_ids": group.endpoint_ids,
                "execution_order": group.execution_order,
                "parallel_execution": group.parallel_execution
            }
            formatted_groups.append(group_info)
        return json.dumps(formatted_groups, indent=2, ensure_ascii=False)

    # =========================================================================
    # 构建脚本对象
    # =========================================================================

    def _build_script_objects(
        self,
        scripts_data: List[Dict[str, Any]],
        test_cases: List[GeneratedTestCase]
    ) -> List[GeneratedScript]:
        scripts = []
        for script_data in scripts_data:
            try:
                file_path = script_data.get("file_path", "test_api.py")
                if not file_path.startswith("testcases/"):
                    file_path = f"testcases/{file_path}"

                script = GeneratedScript(
                    script_name=script_data.get("script_name", "test_api.py"),
                    file_path=file_path,
                    script_content=script_data.get("script_content", ""),
                    test_case_ids=script_data.get("test_case_ids", []),
                    framework=script_data.get("framework", "pytest"),
                    dependencies=script_data.get("dependencies", []),
                    execution_order=script_data.get("execution_order", 1)
                )
                scripts.append(script)
            except Exception as e:
                logger.warning(f"构建脚本对象失败: {str(e)}")
                continue
        return scripts

    # =========================================================================
    # 文件保存
    # =========================================================================

    async def _save_generated_files(self, output: ScriptGenerationOutput):
        """保存生成的文件到磁盘。

        若目标文件已存在（如多份 JSON 文档生成同名脚本 test_alarm.py），
        通过 AST 合并将新内容合入现有文件，避免直接覆盖。
        """
        try:
            self.testcases_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"开始保存生成文件，脚本数: {len(output.scripts)}, "
                        f"目标目录: {self.testcases_dir}")

            if not output.scripts:
                logger.warning("output.scripts 为空，没有任何文件需要保存")
                return

            for script in output.scripts:
                # 文件统一保存到 testcases/ 目录
                # script.file_path 可能是 "test_alarm.py" 或 "testcases/test_alarm.py"
                file_name = Path(script.file_path).name
                script_path = self.testcases_dir / file_name
                script_path.parent.mkdir(parents=True, exist_ok=True)

                logger.info(f"保存脚本: name={script.script_name}, "
                            f"file_path={script.file_path}, "
                            f"实际写入={script_path}, "
                            f"内容长度={len(script.script_content)}")

                if not script.script_content:
                    logger.warning(f"脚本内容为空，跳过: {script_path}")
                    continue

                if script_path.exists():
                    is_conftest = file_name == "conftest.py"
                    if is_conftest or not self._run_suffix:
                        # conftest.py 始终合并；非隔离模式也合并
                        try:
                            existing_source = script_path.read_text(encoding='utf-8')
                            merged = merge_pytest_scripts(existing_source, script.script_content)
                            script_path.write_text(merged, encoding='utf-8')
                            logger.info(f"已合并到现有文件: {script_path}")
                        except Exception as merge_err:
                            logger.warning(f"AST 合并失败，覆盖写入 {script_path}: {merge_err}")
                            script_path.write_text(script.script_content, encoding='utf-8')
                    else:
                        # 隔离模式 + 非 conftest → 覆盖写入新文件（已有后缀保证不冲突）
                        script_path.write_text(script.script_content, encoding='utf-8')
                        logger.info(f"隔离模式覆盖写入: {script_path}")
                else:
                    script_path.write_text(script.script_content, encoding='utf-8')
                    logger.info(f"已保存测试脚本: {script_path}")

            logger.info(f"测试脚本已保存到: {self.testcases_dir}")

        except Exception as e:
            logger.error(f"保存生成文件失败: {str(e)}", exc_info=True)

    # =========================================================================
    # 持久化
    # =========================================================================

    async def _send_to_persistence_agent(
        self, output: ScriptGenerationOutput,
        message: ScriptGenerationInput, ctx: MessageContext
    ):
        """发送脚本到数据持久化智能体"""
        try:
            from .schemas import ScriptPersistenceInput

            # conftest.py 是 fixture 共享层，写入磁盘即可；
            # 不应作为 TestScript 入库（否则会出现在"脚本管理"列表里，且无法被独立执行）
            persisted_scripts = [
                s for s in output.scripts
                if not (s.file_path or "").endswith("conftest.py")
                and s.script_name != "conftest.py"
            ]

            # 反向解析每个脚本的 case -> (class_name, method_name) 映射
            for script in persisted_scripts:
                try:
                    script.case_method_map = self._extract_case_method_map(
                        script.script_content,
                        [tc for tc in message.test_cases if tc.test_case_id in (script.test_case_ids or [])] or message.test_cases,
                        message.endpoints,
                    )
                except Exception as map_err:
                    logger.warning(f"提取 case_method_map 失败 ({script.script_name}): {map_err}")
                    script.case_method_map = {}

            persistence_input = ScriptPersistenceInput(
                session_id=output.session_id,
                document_id=output.document_id,
                interface_id=message.interface_id,
                scripts=persisted_scripts,
                test_cases=message.test_cases,
                endpoints=message.endpoints,
                scenarios=list(getattr(message, "scenarios", None) or []),
                config_files=output.config_files,
                requirements_txt=output.requirements_txt,
                readme_content=output.readme_content,
                generation_summary=output.generation_summary,
                processing_time=output.processing_time
            )

            await self.runtime.publish_message(
                persistence_input,
                topic_id=TopicId(type=TopicTypes.API_DATA_PERSISTENCE.value, source=self.agent_name)
            )

            logger.info(f"已发送脚本到数据持久化智能体: {output.document_id}")

        except Exception as e:
            logger.error(f"发送脚本到数据持久化智能体失败: {str(e)}")

    def _extract_case_method_map(
        self,
        script_content: str,
        test_cases: List[GeneratedTestCase],
        endpoints: List[ParsedEndpoint],
    ) -> Dict[str, Dict[str, str]]:
        """从生成的脚本源码反向解析 test_case_id -> {class_name, method_name}。

        策略：
        1. AST 遍历 ClassDef -> FunctionDef，收集 (class_name, method_name, FunctionDef)
        2. 用 AST 提取每个方法体内所有 api_client.xxx(URL, ...) 调用的 URL（字面量 + 变量回溯）
        3. 多候选打分匹配 endpoint：方法名命中 path tail 优先，最后一个 URL 作为 tie-break
        4. 同 endpoint 下的 test_cases 按出现顺序消费 endpoint 对应的 methods
        """
        import ast

        if not script_content:
            return {}

        try:
            tree = ast.parse(script_content)
        except SyntaxError as e:
            logger.warning(f"AST 解析失败，case_method_map 为空: {e}")
            return {}

        # 收集所有 (class_name, method_name, FunctionDef) 按出现顺序
        all_methods: List[Tuple[str, str, ast.FunctionDef]] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef) and sub.name.startswith("test_"):
                        all_methods.append((node.name, sub.name, sub))

        if not all_methods:
            return {}

        # scenario 链路脚本：单个 test_chain 方法覆盖 N 个 step，所有 case 共享同一方法
        if "pytest.mark.scenario" in script_content and len(all_methods) == 1:
            cls, mth, _ = all_methods[0]
            logger.info(f"scenario 模式：{len(test_cases)} 个 case 全部映射到 {cls}.{mth}")
            return {tc.test_case_id: {"class_name": cls, "method_name": mth} for tc in test_cases}

        # AST 工具：从方法体提取所有 api_client.xxx(URL, ...) 调用的 URL 字面量
        # 处理三种情况：直接字符串字面量、本地变量回溯（var = "URL"）、f-string 取字面部分
        def extract_method_urls(func: ast.FunctionDef) -> List[str]:
            var_to_str: Dict[str, str] = {}
            for stmt in ast.walk(func):
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    tgt = stmt.targets[0]
                    if (isinstance(tgt, ast.Name)
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)):
                        var_to_str[tgt.id] = stmt.value.value
            urls: List[str] = []
            for stmt in ast.walk(func):
                if (isinstance(stmt, ast.Call)
                    and isinstance(stmt.func, ast.Attribute)
                    and isinstance(stmt.func.value, ast.Name)
                    and stmt.func.value.id == "api_client"
                    and stmt.args):
                    a0 = stmt.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        urls.append(a0.value)
                    elif isinstance(a0, ast.Name) and a0.id in var_to_str:
                        urls.append(var_to_str[a0.id])
                    elif isinstance(a0, ast.JoinedStr):
                        # 取直到第一个变量插值之前的所有 Constant 段
                        # 例如 f"/api/foo/{id}/bar" → "/api/foo/"，可与 ep.path "/api/foo/:id" 匹配
                        parts_str: List[str] = []
                        for p in a0.values:
                            if isinstance(p, ast.Constant) and isinstance(p.value, str):
                                parts_str.append(p.value)
                            else:
                                break
                        s = "".join(parts_str)
                        if s:
                            urls.append(s)
            return urls

        # 路径参数正则：同时识别 OpenAPI 风格 `{xxx}` 和 Express/Flask 风格 `:xxx`
        _path_var_re = re.compile(r"(\{[^}]+\}|:[A-Za-z_][A-Za-z0-9_]*).*$")

        def path_tail(p: str) -> str:
            stripped = _path_var_re.sub("", p).rstrip("/")
            parts = [seg for seg in stripped.split("/") if seg]
            return parts[-1].lower() if parts else ""

        def url_matches_endpoint(url: str, ep: ParsedEndpoint) -> bool:
            if ep.path == url:
                return True
            stripped = _path_var_re.sub("", ep.path).rstrip("/")
            return bool(stripped and url.startswith(stripped))

        def find_best_endpoint(func: ast.FunctionDef, method_name: str) -> Optional[ParsedEndpoint]:
            urls = extract_method_urls(func)
            if not urls:
                return None
            candidates: List[ParsedEndpoint] = []
            seen: set = set()
            for url in urls:
                for ep in endpoints:
                    if ep.endpoint_id in seen:
                        continue
                    if url_matches_endpoint(url, ep):
                        candidates.append(ep)
                        seen.add(ep.endpoint_id)
            if not candidates:
                return None
            if len(candidates) == 1:
                return candidates[0]
            # 对方法名和 path tail 做 normalize 比较：去掉所有非字母数字字符并 lower
            # 这样 method 是 snake_case（test_get_uplink_device_list）也能匹配
            # path tail 是 camelCase（getUplinkDeviceList）的端点
            def _norm(s: str) -> str:
                return re.sub(r"[^a-z0-9]", "", s.lower())
            mn_norm = _norm(method_name)
            first_url = urls[0]  # 主操作 URL，不是验证用的最后一个
            scored: List[Tuple[int, ParsedEndpoint]] = []
            for ep in candidates:
                score = 0
                tail_norm = _norm(path_tail(ep.path))
                if tail_norm and tail_norm in mn_norm:
                    score += 100
                if url_matches_endpoint(first_url, ep):
                    score += 10
                scored.append((score, ep))
            scored.sort(key=lambda x: -x[0])
            return scored[0][1]

        # method index -> endpoint_id（每个 method 找最佳 endpoint，不再因为 break 早退）
        method_to_ep: Dict[int, str] = {}
        for idx, (_, mname, func_node) in enumerate(all_methods):
            ep = find_best_endpoint(func_node, mname)
            if ep:
                method_to_ep[idx] = ep.endpoint_id

        ep_method_indices: Dict[str, List[int]] = {}
        for idx, ep_id in method_to_ep.items():
            ep_method_indices.setdefault(ep_id, []).append(idx)

        case_method_map: Dict[str, Dict[str, str]] = {}
        from collections import defaultdict
        cases_by_ep: Dict[str, List[GeneratedTestCase]] = defaultdict(list)
        for tc in test_cases:
            cases_by_ep[tc.endpoint_id].append(tc)

        for ep_id, ep_cases in cases_by_ep.items():
            method_idxs = ep_method_indices.get(ep_id, [])
            for i, tc in enumerate(ep_cases):
                if i < len(method_idxs):
                    cls, mth, _ = all_methods[method_idxs[i]]
                else:
                    if method_idxs:
                        cls, mth, _ = all_methods[method_idxs[0]]
                    else:
                        continue
                case_method_map[tc.test_case_id] = {"class_name": cls, "method_name": mth}

        return case_method_map

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _sanitize_name(self, name: str) -> str:
        """将中文/特殊字符处理为合法 Python 标识符"""
        if not name:
            return "general"
        result = re.sub(r'[^a-zA-Z0-9_一-鿿]', '_', name)
        result = re.sub(r'[一-鿿]+', lambda m: self._chinese_to_pinyin(m.group()), result)
        result = re.sub(r'_+', '_', result).strip('_').lower()
        if not result or not result[0].isalpha():
            result = f"m_{result}"
        return result

    def _chinese_to_pinyin(self, text: str) -> str:
        """中文转拼音（简化映射 + fallback）"""
        mapping = {
            # 通用
            "用户": "user", "系统": "system", "登录": "login", "注册": "register",
            "订单": "order", "商品": "product", "支付": "payment", "菜单": "menu",
            "角色": "role", "权限": "permission", "部门": "department", "组织": "organization",
            "文件": "file", "上传": "upload", "下载": "download", "导入": "import_data",
            "导出": "export_data", "查询": "query", "搜索": "search", "统计": "statistics",
            "报表": "report", "日志": "log", "配置": "config", "设置": "setting",
            "通知": "notification", "消息": "message", "审批": "approval", "流程": "workflow",
            "项目": "project", "任务": "task", "资源": "resource", "接口": "interface",
            "数据": "data", "管理": "manage", "列表": "list", "详情": "detail",
            "创建": "create", "修改": "update", "删除": "delete", "会话": "session",
            # 安全/告警领域
            "告警": "alarm", "事件": "event", "定义": "definition", "规则": "rule",
            "筛选": "filter", "标签": "tag", "类型": "type", "等级": "level",
            "危险": "danger", "威胁": "threat", "攻击": "attack", "漏洞": "vulnerability",
            "处置": "disposal", "工单": "ticket", "白名单": "whitelist", "黑名单": "blacklist",
            "阻断": "block", "隔离": "isolate", "还原": "restore", "忽略": "ignore",
            "复制": "copy", "模板": "template", "调度": "schedule", "状态": "status",
            "来源": "source", "置信度": "confidence", "映射": "mapping", "全量": "all",
            "分页": "page", "排序": "sort", "字段": "field", "参数": "param",
            "详细": "detail", "基础": "basic", "信息": "info", "概览": "overview",
            "大屏": "screen", "综合": "comprehensive", "态势": "situation", "地图": "map",
            "流量": "traffic", "协议": "protocol", "资产": "asset", "主机": "host",
            "设备": "device", "软件": "software", "端口": "port", "补丁": "patch",
            "漏洞": "vul", "挂起": "suspend", "停止": "stop", "清点": "inventory",
            "学习": "learn", "进度": "progress", "未知": "unknown", "新增": "add",
            "编辑": "edit", "批量": "batch", "单个": "single", "验证": "verify",
            "测试": "test", "发送": "send", "接收": "receive", "保存": "save",
            "取消": "cancel", "确认": "confirm", "刷新": "refresh", "重置": "reset",
            "启用": "enable", "禁用": "disable", "上架": "online", "下架": "offline",
            "同步": "sync", "异步": "async", "导入": "import", "导出": "export",
            "获取": "get", "设置": "set", "分配": "assign", "回收": "revoke",
        }
        for cn, en in mapping.items():
            if cn in text:
                return en
        return "module"

    def _endpoint_to_function_name(self, endpoint: ParsedEndpoint) -> str:
        """端点转函数名"""
        method = endpoint.method.value.lower()
        path_parts = [p for p in endpoint.path.split("/") if p and not p.startswith("{")]
        path_name = "_".join(path_parts[-2:]) if len(path_parts) >= 2 else "_".join(path_parts)
        path_name = re.sub(r'[^a-zA-Z0-9_]', '_', path_name).strip('_')

        if endpoint.summary:
            summary_name = self._sanitize_name(endpoint.summary)
            if len(summary_name) > 3:
                return summary_name

        return f"{method}_{path_name}" if path_name else f"{method}_endpoint"

    def _endpoint_to_fixture_name(self, endpoint: ParsedEndpoint) -> str:
        """端点转 fixture 名"""
        func_name = self._endpoint_to_function_name(endpoint)
        return f"created_{func_name}" if not func_name.startswith("created_") else func_name

    def _sanitize_method_name(self, name: str, method: str = "", used_names: set = None) -> str:
        """测试方法名清洗，融入 HTTP method 前缀并自动去重。

        Args:
            name: 原始中文/混合名称
            method: HTTP 方法（get/post/put/delete/patch）
            used_names: 已占用方法名集合，用于自动追加 _2/_3 后缀去重
        """
        name = re.sub(r'[^a-zA-Z0-9_一-鿿]', '_', name)
        name = re.sub(r'[一-鿿]+', lambda m: self._chinese_to_pinyin(m.group()), name)
        name = re.sub(r'_+', '_', name).strip('_').lower()
        if not name.startswith("test_"):
            name = f"test_{name}"
        # 融入 HTTP method
        if method and method not in name:
            name = name.replace("test_", f"test_{method}_")

        if used_names is not None:
            base = name
            counter = 2
            while name in used_names:
                name = f"{base}_{counter}"
                counter += 1
            used_names.add(name)

        return name

    def _derive_script_name(self, endpoints: List[ParsedEndpoint]) -> str:
        """从端点推导脚本文件名（隔离模式加后缀避免覆盖旧文件）"""
        if not endpoints:
            return self._suffix_name("test_api_automation.py")

        tags = []
        for ep in endpoints:
            tags.extend(ep.tags)
        if tags:
            name = self._sanitize_name(tags[0])
            return self._suffix_name(f"test_{name}.py")

        path_parts = endpoints[0].path.strip("/").split("/")
        if len(path_parts) >= 2:
            name = self._sanitize_name(path_parts[-1])
            return self._suffix_name(f"test_{name}.py")

        return self._suffix_name("test_api_automation.py")

    def _suffix_name(self, base: str) -> str:
        """隔离模式下给文件名加后缀，如 test_strategy.py → test_strategy_a1b2c3d4.py"""
        if not self._run_suffix:
            return base
        stem, ext = base.rsplit(".", 1)
        return f"{stem}_{self._run_suffix}.{ext}"

    def _derive_class_name(self, endpoints: List[ParsedEndpoint]) -> str:
        """从端点推导测试类名"""
        if not endpoints:
            return "TestApiAutomation"
        tags = []
        for ep in endpoints:
            tags.extend(ep.tags)
        if tags:
            name = self._sanitize_name(tags[0])
            return f"Test{''.join(w.capitalize() for w in name.split('_'))}"

        return "TestApiAutomation"

    def _get_test_data_for_endpoint(
        self, endpoint: ParsedEndpoint, test_cases: List[GeneratedTestCase]
    ) -> Dict[str, Any]:
        """获取端点的测试数据。优先使用正向用例的 test_data，否则回退到 body 参数的 example。"""
        for tc in test_cases:
            if tc.endpoint_id == endpoint.endpoint_id and tc.test_type == TestCaseType.POSITIVE:
                data = {}
                for td in tc.test_data:
                    data[td.parameter_name] = td.test_value
                if data:
                    return data
        return self._extract_body_example(endpoint)

    def _extract_body_example(self, endpoint: ParsedEndpoint) -> Dict[str, Any]:
        """从端点 body 参数中提取 example，作为兜底测试数据。"""
        body_params = [p for p in endpoint.parameters if p.location.value == "body"]
        if not body_params:
            return {}

        single = body_params[0]
        if len(body_params) == 1 and single.name in ("body", "payload", "data") and isinstance(single.example, dict):
            return single.example

        data: Dict[str, Any] = {}
        for p in body_params:
            if p.example is not None and p.example != "":
                data[p.name] = p.example
        return data

    def _create_default_test_case(self, endpoint: ParsedEndpoint) -> GeneratedTestCase:
        """为没有用例的端点创建默认测试用例"""
        method = endpoint.method.value.lower()
        summary = endpoint.summary or endpoint.path

        return GeneratedTestCase(
            test_name=f"test_{method}_{self._sanitize_name(summary)}",
            endpoint_id=endpoint.endpoint_id,
            test_type=TestCaseType.POSITIVE,
            description=f"正向测试: {summary}",
            test_data=[],
            assertions=[],
            priority=1,
            tags=endpoint.tags
        )

    def _generate_summary(
        self, scripts: List[GeneratedScript], generation_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "total_scripts": len(scripts),
            "total_test_methods": sum(len(script.test_case_ids) for script in scripts),
            "generation_method": generation_result.get("generation_method", "intelligent"),
            "confidence_score": generation_result.get("confidence_score", 0.8),
            "framework": self.generation_config["framework"],
            "script_mode": "framework_integrated",
            "features_enabled": {
                "allure_reporting": self.generation_config["enable_allure"],
                "framework_fixtures": True,
                "fixture_chain": True,
                "cross_environment": True
            }
        }

    def get_generation_statistics(self) -> Dict[str, Any]:
        base_stats = self.get_common_statistics()
        base_stats.update({
            "generation_metrics": self.generation_metrics,
            "generation_config": self.generation_config,
            "avg_scripts_per_generation": (
                self.generation_metrics["total_scripts_generated"] /
                max(self.generation_metrics["successful_generations"], 1)
            ),
            "avg_methods_per_script": (
                self.generation_metrics["total_test_methods_generated"] /
                max(self.generation_metrics["total_scripts_generated"], 1)
            )
        })
        return base_stats
