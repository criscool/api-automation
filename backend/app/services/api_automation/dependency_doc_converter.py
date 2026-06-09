"""
预分析依赖 JSON 转换器
=====================

将外部工具（如 ai-testmind）产出的依赖分析 JSON 转换为 ScriptGenerationInput
所需的数据结构，让 ScriptGeneratorAgent 可以跳过 ApiAnalyzer / TestCaseGenerator
两个智能体，走 scenario 模板渲染分支生成 pytest 脚本。

输入示例：D:/code/aitestmind/api-docs/asset-management-dependencies.json

核心映射规则
------------
- chains[].steps[].endpoint            → ParsedEndpoint（同 path 不同 bodyShape 拆分）
- chains[].steps[]                     → GeneratedTestCase（用于 TestCase 入库）
- chains[].steps[].dependsOn + dataIn  → EndpointDependency（DATA_FLOW）
- chains[]                             → ScenarioTestCase（驱动 scenario 分支）

设计要点
--------
1. 同一 (method, path, frozenset(body_shape)) 视为一个 ParsedEndpoint
   —— 处理 /list 的 bodyShape=[] vs ["query"] 双变体
2. 转换过程纯字段映射，不调用 LLM，不依赖网络
3. exampleValue 仅作 fallback；运行时优先按 data_in.from 链拉取实际值
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from app.agents.api_automation.schemas import (
    ApiParameter,
    ApiResponse,
    DataType,
    DependencyType,
    EndpointDependency,
    GeneratedTestCase,
    HttpMethod,
    ParameterLocation,
    ParsedApiInfo,
    ParsedEndpoint,
    ScenarioStepSpec,
    ScenarioTestCase,
    TestCaseType,
)


# (method, path, frozenset(body_shape)) → ParsedEndpoint 的去重键
EndpointKey = Tuple[str, str, FrozenSet[str]]

# 匹配 dataIn.from 中的 "step:N.dataOut.X"（X 也可以是任意非空字符串，含下划线）
_STEP_REF_RE = re.compile(r"^step:(\d+)\.dataOut\.(.+)$")


class DependencyDocConverter:
    """依赖 JSON 文档 → ScriptGenerationInput 所需各组件的转换器。

    用法::

        converter = DependencyDocConverter(doc_dict)
        api_info  = converter.to_api_info()
        endpoints = converter.to_endpoints()
        cases     = converter.to_test_cases()
        deps      = converter.to_dependencies()
        scenarios = converter.to_scenarios()
    """

    def __init__(self, doc: Dict[str, Any]):
        if not isinstance(doc, dict):
            raise TypeError(f"依赖 JSON 必须是 dict，得到 {type(doc).__name__}")
        self.doc = doc
        self.module: str = str(doc.get("module") or "api")
        self.base_url: str = str(doc.get("baseUrl") or "")
        self.auth_headers: Dict[str, Any] = dict(doc.get("auth") or {})

        # 端点缓存：以 (method, path, frozenset(body_shape)) 为 key 去重
        self._endpoint_cache: Dict[EndpointKey, ParsedEndpoint] = {}
        # path → 默认端点（bodyShape=[]）的快查表，用于 dependencies[] 的 from/to 匹配
        # 同 path 有多 bodyShape 时按出现顺序保留首个
        self._endpoint_by_path: Dict[Tuple[str, str], ParsedEndpoint] = {}

        # to_test_cases / to_scenarios 结果缓存：保证多次调用返回相同的 UUID
        # （否则 ScenarioStepSpec.related_test_case_id 会与新生成的 case_id 对不上）
        self._test_cases_cache: Optional[List[GeneratedTestCase]] = None
        self._scenarios_cache: Optional[List[ScenarioTestCase]] = None

        # 一次性预处理所有 chains[].steps[].endpoint，填充缓存
        self._collect_endpoints()

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    def to_api_info(self) -> ParsedApiInfo:
        """ParsedApiInfo：API 元信息（标题/baseUrl/全局头）。"""
        return ParsedApiInfo(
            title=self.module,
            version="1.0",
            description=f"由依赖 JSON 转换生成（source={self.doc.get('sourceFile', '')}）",
            base_url=self.base_url,
        )

    def to_endpoints(self) -> List[ParsedEndpoint]:
        """所有去重后的端点列表（同 path 不同 bodyShape 视为不同端点）。"""
        return list(self._endpoint_cache.values())

    def to_test_cases(self) -> List[GeneratedTestCase]:
        """每个 chain → 一个 GeneratedTestCase（整条链折叠成 1 条用例）。

        关联到 chain 的 primary_endpoint，tags 含 `scenario:<chain.name>`。
        前端"用例管理"页一个 chain 显示为一条用例；脚本管理的
        steps/asserts 摘要由 TestScript.flow_summary 承载（持久化时写入）。

        结果被缓存：GeneratedTestCase.test_case_id 用 uuid4 默认值，
        多次调用必须返回同一批对象，否则 ScenarioStepSpec.related_test_case_id
        会引用到不存在的 UUID。
        """
        if self._test_cases_cache is not None:
            return self._test_cases_cache

        cases: List[GeneratedTestCase] = []
        for chain in self.doc.get("chains", []) or []:
            chain_name = str(chain.get("name") or "")
            chain_desc = str(chain.get("description") or "")
            steps = chain.get("steps", []) or []

            # 主端点：取 chain 内第一个写操作；都没有就退化为第一 step 的端点
            primary_ep_id: Optional[str] = None
            first_ep_id: Optional[str] = None
            for raw_step in steps:
                ep = self._endpoint_for_step(raw_step)
                if ep is None:
                    continue
                if first_ep_id is None:
                    first_ep_id = ep.endpoint_id
                method = str((raw_step.get("endpoint") or {}).get("method", "GET")).upper()
                if primary_ep_id is None and method in ("POST", "PUT", "PATCH", "DELETE"):
                    primary_ep_id = ep.endpoint_id
            primary_ep_id = primary_ep_id or first_ep_id
            if primary_ep_id is None:
                continue  # chain 里一个有效端点都没有，跳过

            test_name = f"test_scenario_{self._slugify(chain_name)}"
            description = chain_desc or chain_name or test_name
            cases.append(
                GeneratedTestCase(
                    test_name=test_name,
                    endpoint_id=primary_ep_id,
                    test_type=TestCaseType.POSITIVE,
                    description=description,
                    test_data=[],
                    assertions=[],
                    priority=1,
                    tags=[f"scenario:{chain_name}", "scenario"] if chain_name else ["scenario"],
                )
            )
        self._test_cases_cache = cases
        return cases

    def to_dependencies(self) -> List[EndpointDependency]:
        """chains[].steps[].dependsOn + dataIn → EndpointDependency 列表。

        优先用 chains 内部的 dependsOn（与具体 chain 上下文绑定，更精确），
        若 chain 内某步无 dependsOn 但顶层 dependencies[] 有匹配 from/to，
        也补一条 SEQUENCE 依赖兜底。
        """
        deps: List[EndpointDependency] = []
        # 每个 chain 内部 step 序号 → endpoint_id 的映射
        for chain in self.doc.get("chains", []) or []:
            step_to_ep: Dict[int, str] = {}
            for step in chain.get("steps", []) or []:
                ep = self._endpoint_for_step(step)
                if ep:
                    step_to_ep[int(step.get("step") or 0)] = ep.endpoint_id

            for step in chain.get("steps", []) or []:
                cur_no = int(step.get("step") or 0)
                cur_ep_id = step_to_ep.get(cur_no)
                if not cur_ep_id:
                    continue

                # 1) dependsOn 显式数组
                for src_no in step.get("dependsOn", []) or []:
                    src_ep_id = step_to_ep.get(int(src_no))
                    if src_ep_id and src_ep_id != cur_ep_id:
                        deps.append(
                            EndpointDependency(
                                source_endpoint_id=src_ep_id,
                                target_endpoint_id=cur_ep_id,
                                dependency_type=DependencyType.DATA_FLOW,
                                description=f"chain={chain.get('name','')} step{src_no}→step{cur_no}",
                                data_mapping=self._extract_data_mapping(step.get("dataIn", {})),
                            )
                        )

                # 2) dataIn.from 反推（多数情况已被 dependsOn 覆盖，这里补漏）
                for field, ref in (step.get("dataIn", {}) or {}).items():
                    if not isinstance(ref, dict):
                        continue
                    src_no = self._parse_step_ref(ref.get("from", ""))
                    if src_no is None:
                        continue
                    src_ep_id = step_to_ep.get(src_no)
                    if not src_ep_id or src_ep_id == cur_ep_id:
                        continue
                    # 避免与 dependsOn 重复
                    already = any(
                        d.source_endpoint_id == src_ep_id and d.target_endpoint_id == cur_ep_id
                        for d in deps
                    )
                    if not already:
                        deps.append(
                            EndpointDependency(
                                source_endpoint_id=src_ep_id,
                                target_endpoint_id=cur_ep_id,
                                dependency_type=DependencyType.DATA_FLOW,
                                description=f"chain={chain.get('name','')} dataIn.{field}",
                                data_mapping={field: ref.get("from", "")},
                            )
                        )
        return deps

    def to_scenarios(self) -> List[ScenarioTestCase]:
        """所有 chain → ScenarioTestCase 列表（每个 chain 对应一个测试方法）。

        结果被缓存：ScenarioTestCase.scenario_id 用 uuid4 默认值，
        多次调用必须返回同一批对象。
        """
        if self._scenarios_cache is not None:
            return self._scenarios_cache
        # chain_name → 该 chain 对应的（唯一）test_case_id
        # 1 chain = 1 GeneratedTestCase 后所有 step 共享同一个 case_id
        case_index: Dict[str, str] = {}
        for tc in self.to_test_cases():
            for tag in tc.tags:
                if tag.startswith("scenario:"):
                    case_index[tag[len("scenario:") :]] = tc.test_case_id
                    break

        scenarios: List[ScenarioTestCase] = []
        for chain in self.doc.get("chains", []) or []:
            chain_name = str(chain.get("name") or "")
            steps: List[ScenarioStepSpec] = []
            primary_ep_id: Optional[str] = None

            for raw_step in chain.get("steps", []) or []:
                ep = self._endpoint_for_step(raw_step)
                if ep is None:
                    continue
                step_no = int(raw_step.get("step") or 0)
                endpoint_block = raw_step.get("endpoint", {}) or {}
                request_block = endpoint_block.get("request", {}) or {}

                step_spec = ScenarioStepSpec(
                    step=step_no,
                    purpose=str(raw_step.get("purpose") or ""),
                    method=HttpMethod(str(endpoint_block.get("method", "GET")).upper()),
                    path=str(endpoint_block.get("path") or ""),
                    path_params=dict(request_block.get("pathParams") or {}),
                    query=dict(request_block.get("query") or {}),
                    body=dict(request_block.get("body") or {}),
                    body_shape=[str(s) for s in (endpoint_block.get("bodyShape") or [])],
                    response_example=dict(
                        (endpoint_block.get("response") or {}).get("example") or {}
                    ),
                    data_in=dict(raw_step.get("dataIn") or {}),
                    data_out=dict(raw_step.get("dataOut") or {}),
                    assert_spec=raw_step.get("assert"),
                    depends_on=[int(x) for x in (raw_step.get("dependsOn") or [])],
                    related_endpoint_id=ep.endpoint_id,
                    related_test_case_id=case_index.get(chain_name),
                )
                steps.append(step_spec)

                # 主端点：选 chain 内第一个写操作（POST/PUT/PATCH/DELETE）；
                # 都没有就退化为第一个 step 的端点
                if primary_ep_id is None and step_spec.method.value.upper() in (
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                ):
                    primary_ep_id = ep.endpoint_id

            if primary_ep_id is None and steps:
                primary_ep_id = steps[0].related_endpoint_id

            scenarios.append(
                ScenarioTestCase(
                    name=chain_name,
                    description=str(chain.get("description") or ""),
                    steps=steps,
                    tags=[self._slugify(self.module), "scenario"],
                    primary_endpoint_id=primary_ep_id,
                )
            )
        self._scenarios_cache = scenarios
        return scenarios

    # ------------------------------------------------------------------ #
    # 内部：端点收集与查找
    # ------------------------------------------------------------------ #

    def _collect_endpoints(self) -> None:
        """遍历所有 chains[].steps[].endpoint 收集去重后的 ParsedEndpoint。"""
        for chain in self.doc.get("chains", []) or []:
            for step in chain.get("steps", []) or []:
                self._endpoint_for_step(step)  # 副作用：写入 _endpoint_cache

    def _endpoint_for_step(self, step: Dict[str, Any]) -> Optional[ParsedEndpoint]:
        """从 step 获取/创建对应的 ParsedEndpoint。同步维护缓存。"""
        endpoint_block = (step or {}).get("endpoint") or {}
        method = str(endpoint_block.get("method") or "").upper().strip()
        path = str(endpoint_block.get("path") or "").strip()
        if not method or not path:
            return None
        body_shape = frozenset(str(s) for s in (endpoint_block.get("bodyShape") or []))
        key: EndpointKey = (method, path, body_shape)

        cached = self._endpoint_cache.get(key)
        if cached:
            return cached

        ep = self._build_endpoint(endpoint_block, method, path, body_shape)
        self._endpoint_cache[key] = ep
        # 维护 path 默认端点（用于顶层 dependencies[].from/to 的兜底匹配）
        path_key = (method, path)
        if path_key not in self._endpoint_by_path:
            self._endpoint_by_path[path_key] = ep
        return ep

    def _build_endpoint(
        self,
        endpoint_block: Dict[str, Any],
        method: str,
        path: str,
        body_shape: FrozenSet[str],
    ) -> ParsedEndpoint:
        """从依赖 JSON 的 endpoint 块构造 ParsedEndpoint。"""
        name = str(endpoint_block.get("name") or "")
        description = str(endpoint_block.get("description") or "")
        request_block = endpoint_block.get("request") or {}
        response_block = endpoint_block.get("response") or {}

        parameters = self._build_parameters(request_block, body_shape)
        responses = self._build_responses(response_block)

        # tag 用 module 名（如 "asset-management"），让脚本按 module 落到独立文件
        tag = self._slugify(self.module)

        return ParsedEndpoint(
            path=path,
            method=HttpMethod(method),
            summary=name,
            description=description,
            tags=[tag] if tag else [],
            parameters=parameters,
            responses=responses,
            auth_required=True,
            interface_name=name,
            category=tag,
            extended_info={
                "body_shape": sorted(body_shape),
                "module": self.module,
                "source": "dependency-doc",
            },
        )

    def _build_parameters(
        self, request_block: Dict[str, Any], body_shape: FrozenSet[str]
    ) -> List[ApiParameter]:
        """构造 ApiParameter 列表（query / path / body 三类）。"""
        params: List[ApiParameter] = []

        # path 参数（依赖 JSON 里通常形如 {":id": "数据集 stream_Id..."}）
        for raw_name, example in (request_block.get("pathParams") or {}).items():
            clean_name = self._strip_path_var_decor(str(raw_name))
            params.append(
                ApiParameter(
                    name=clean_name,
                    location=ParameterLocation.PATH,
                    data_type=self._infer_data_type(example),
                    required=True,
                    description=str(example) if not isinstance(example, (dict, list)) else "",
                    example=example,
                )
            )

        # query 参数
        for k, v in (request_block.get("query") or {}).items():
            params.append(
                ApiParameter(
                    name=str(k),
                    location=ParameterLocation.QUERY,
                    data_type=self._infer_data_type(v),
                    required=True,
                    description="",
                    example=v,
                )
            )

        # body：把整个对象作为单个 body 参数（example=整个 dict），
        # 同时把 body_shape 标识的字段单独追加为必填参数，便于下游识别
        body = request_block.get("body") or {}
        if isinstance(body, dict) and body:
            params.append(
                ApiParameter(
                    name="body",
                    location=ParameterLocation.BODY,
                    data_type=DataType.OBJECT,
                    required=True,
                    description="完整请求体",
                    example=body,
                )
            )
            for field_name in body_shape:
                if field_name in body:
                    params.append(
                        ApiParameter(
                            name=str(field_name),
                            location=ParameterLocation.BODY,
                            data_type=self._infer_data_type(body[field_name]),
                            required=True,
                            description=f"bodyShape 标识必填字段",
                            example=body[field_name],
                        )
                    )

        return params

    def _build_responses(self, response_block: Dict[str, Any]) -> List[ApiResponse]:
        """构造 ApiResponse 列表（依赖 JSON 通常只给一个 200 示例）。"""
        if not response_block:
            return []
        status_code = str(response_block.get("status") or 200)
        return [
            ApiResponse(
                status_code=status_code,
                description="success",
                content_type="application/json",
                response_schema={},
                example=response_block.get("example"),
            )
        ]

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_step_ref(ref: str) -> Optional[int]:
        """解析 'step:N.dataOut.X' → N；不匹配返回 None。"""
        if not isinstance(ref, str):
            return None
        m = _STEP_REF_RE.match(ref.strip())
        return int(m.group(1)) if m else None

    @staticmethod
    def _extract_data_mapping(data_in: Dict[str, Any]) -> Dict[str, str]:
        """dataIn → {目标字段: 'step:N.dataOut.X'} 形式的扁平映射。"""
        mapping: Dict[str, str] = {}
        for field, ref in (data_in or {}).items():
            if isinstance(ref, dict) and isinstance(ref.get("from"), str):
                mapping[str(field)] = ref["from"]
        return mapping

    @staticmethod
    def _strip_path_var_decor(name: str) -> str:
        """去掉路径参数的装饰：':id' → 'id'，'{id}' → 'id'。"""
        s = name.strip()
        if s.startswith(":"):
            s = s[1:]
        elif s.startswith("{") and s.endswith("}"):
            s = s[1:-1]
        return s

    @staticmethod
    def _infer_data_type(value: Any) -> DataType:
        """根据 Python 值推断 DataType。"""
        if isinstance(value, bool):
            return DataType.BOOLEAN
        if isinstance(value, int):
            return DataType.INTEGER
        if isinstance(value, float):
            return DataType.NUMBER
        if isinstance(value, list):
            return DataType.ARRAY
        if isinstance(value, dict):
            return DataType.OBJECT
        return DataType.STRING

    @staticmethod
    def _slugify(name: str) -> str:
        """中英文名 → 合法标识符片段（小写、下划线分隔）。
        注意：必须把 '.' 也清掉，避免命中 [[project-uvicorn-reload-pyext-trap]]。
        """
        if not name:
            return ""
        # 把任何非字母/数字/下划线/中文 替换成下划线
        s = re.sub(r"[^A-Za-z0-9_一-鿿]", "_", name)
        s = re.sub(r"_+", "_", s).strip("_").lower()
        return s
