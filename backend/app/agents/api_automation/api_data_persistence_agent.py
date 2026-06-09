"""
API数据持久化智能体
负责将解析后的接口信息存储到数据库中

核心职责：
1. 接收API文档解析结果
2. 将接口信息存储到数据库
3. 处理参数和响应数据的存储
4. 维护数据的完整性和一致性
"""
import hashlib
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger

from autogen_core import message_handler, type_subscription, MessageContext, TopicId
from tortoise.transactions import in_transaction
from tortoise import Tortoise

from app.agents.api_automation.base_api_agent import BaseApiAutomationAgent
from app.core.types import AgentTypes, TopicTypes
from app.settings.config import settings
from app.models.api_automation import (
    ApiDocument, ApiInterface, ApiParameter as DbApiParameter,
    ApiResponse as DbApiResponse, TestScript, TestCase
)
from app.core.enums import SessionStatus, TestType, TestLevel, Priority
from .schemas import DocumentParseOutput, ParsedEndpoint, ApiParameter, ApiResponse, ScriptPersistenceInput, GeneratedTestCase, TestCaseType


class ApiDataPersistenceInput:
    """数据持久化输入模型"""
    def __init__(self, parse_result: DocumentParseOutput):
        self.session_id = parse_result.session_id
        self.document_id = parse_result.document_id
        self.file_name = parse_result.file_name
        self.doc_format = parse_result.doc_format
        self.api_info = parse_result.api_info
        self.endpoints = parse_result.endpoints
        self.confidence_score = parse_result.confidence_score
        self.processing_time = parse_result.processing_time
        self.extended_info = parse_result.extended_info
        self.raw_parsed_data = parse_result.raw_parsed_data
        self.parse_errors = parse_result.parse_errors
        self.parse_warnings = parse_result.parse_warnings


@type_subscription(topic_type=TopicTypes.API_DATA_PERSISTENCE.value)
class ApiDataPersistenceAgent(BaseApiAutomationAgent):
    """
    API数据持久化智能体
    
    负责将API文档解析结果存储到数据库中，
    包括接口信息、参数、响应等详细数据。
    """

    def __init__(self, model_client_instance=None, agent_config=None, **kwargs):
        """初始化API数据持久化智能体"""
        super().__init__(
            agent_type=AgentTypes.API_DATA_PERSISTENCE,
            model_client_instance=model_client_instance,
            **kwargs
        )

        self.agent_config = agent_config or {}

        # 持久化统计指标
        self.persistence_metrics = {
            "total_documents_processed": 0,
            "total_interfaces_stored": 0,
            "total_parameters_stored": 0,
            "total_responses_stored": 0,
            "successful_saves": 0,
            "failed_saves": 0
        }

        logger.info(f"API数据持久化智能体初始化完成: {self.agent_name}")

    @message_handler
    async def handle_persistence_request(
        self,
        message: DocumentParseOutput,
        ctx: MessageContext
    ) -> None:
        """处理数据持久化请求 - 主要入口点"""
        start_time = datetime.now()
        self.persistence_metrics["total_documents_processed"] += 1

        try:
            logger.info(f"开始存储API数据: {message.file_name}")

            # 确保数据库连接
            await self._ensure_database_connection()

            # 创建输入对象
            persistence_input = ApiDataPersistenceInput(message)

            # 在事务中执行数据存储
            async with in_transaction() as conn:
                # 1. 更新或创建API文档记录
                document = await self._update_api_document(persistence_input, conn)
                
                # 2. 存储接口信息
                interfaces = await self._store_interfaces(document, persistence_input, conn)
                
                # 3. 存储参数信息
                await self._store_parameters(interfaces, persistence_input, conn)
                
                # 4. 存储响应信息
                await self._store_responses(interfaces, persistence_input, conn)

            # 更新统计指标
            processing_time = (datetime.now() - start_time).total_seconds()
            self.persistence_metrics["successful_saves"] += 1
            self.persistence_metrics["total_interfaces_stored"] += len(message.endpoints)
            self._update_metrics("data_persistence", True, processing_time)

            logger.info(f"API数据存储完成: {message.file_name}, 接口数: {len(message.endpoints)}")

        except Exception as e:
            self.persistence_metrics["failed_saves"] += 1
            self._update_metrics("data_persistence", False)
            error_info = self._handle_common_error(e, "data_persistence")
            logger.error(f"API数据存储失败: {error_info}")

    @message_handler
    async def handle_script_persistence_request(
        self,
        message: ScriptPersistenceInput,
        ctx: MessageContext
    ) -> None:
        """
        处理脚本持久化请求 - 优化版

        关键说明：
        - message.interface_id 是业务ID (VARCHAR类型)，用于查找ApiInterface记录
        - TestScript.interface 是外键字段，关联到ApiInterface.id (BIGINT类型)
        - ORM会自动处理外键关联，无需手动设置ID值
        """
        start_time = datetime.now()

        try:
            logger.info(f"开始存储脚本数据: interface_id={message.interface_id}, 脚本数量={len(message.scripts)}")

            # 确保数据库连接
            await self._ensure_database_connection()

            # 在事务中执行脚本存储
            async with in_transaction() as conn:
                # 1. 获取文档信息
                document = await ApiDocument.filter(doc_id=message.document_id).using_db(conn).first()
                if not document:
                    logger.error(f"文档不存在: {message.document_id}")
                    raise ValueError(f"Document not found: {message.document_id}")

                # 2. 获取接口信息 - 使用interface_id（业务ID）查找
                interface = await ApiInterface.filter(
                    interface_id=message.interface_id  # 这是VARCHAR类型的业务ID
                ).using_db(conn).first()

                if not interface:
                    logger.error(f"接口不存在: {message.interface_id}")
                    raise ValueError(f"Interface not found: {message.interface_id}")

                logger.debug(f"找到接口: {interface.name} (ID: {interface.id}, interface_id: {interface.interface_id})")

                # 3. 存储脚本信息
                stored_scripts = []
                for script in message.scripts:
                    # 跳过 conftest.py：它是 fixture 共享文件，已写入磁盘，
                    # 不应作为可执行测试脚本入库
                    if (script.file_path or "").endswith("conftest.py") or script.script_name == "conftest.py":
                        logger.info(f"跳过 conftest.py 持久化: {script.script_name}")
                        continue

                    # 检查是否已存在相同的脚本
                    existing_script = await TestScript.filter(
                        script_id=script.script_id
                    ).using_db(conn).first()

                    if existing_script:
                        # 更新现有脚本
                        await self._update_existing_script(existing_script, script, interface, message, conn)
                        stored_scripts.append(existing_script)
                        logger.info(f"更新脚本: {script.script_id}")
                    else:
                        # 创建新脚本
                        new_script = await self._create_new_script(script, interface, document, message, conn)
                        stored_scripts.append(new_script)
                        logger.info(f"创建脚本: {script.script_id}")

                # 4. 更新接口的脚本统计信息
                await self._update_interface_script_stats(interface, stored_scripts, conn)

                # 5. 落库 TestCase（用例维度），用于"用例管理"页面
                if message.test_cases:
                    await self._store_test_cases(message, document, conn)

            # 更新统计指标
            processing_time = (datetime.now() - start_time).total_seconds()
            self._update_metrics("script_persistence", True, processing_time)

            logger.info(f"脚本存储完成: interface_id={message.interface_id}, 脚本数量={len(message.scripts)}")

        except Exception as e:
            self._update_metrics("script_persistence", False)
            error_info = self._handle_common_error(e, "script_persistence")
            logger.error(f"脚本存储失败: {error_info}")
            raise

    async def _update_api_document(
        self, 
        persistence_input: ApiDataPersistenceInput, 
        conn
    ) -> ApiDocument:
        """更新或创建API文档记录"""
        try:
            # 尝试获取现有文档
            document = await ApiDocument.filter(
                doc_id=persistence_input.document_id
            ).using_db(conn).first()

            if document:
                # 更新现有文档
                document.api_info = {
                    "title": persistence_input.api_info.title,
                    "version": persistence_input.api_info.version,
                    "description": persistence_input.api_info.description,
                    "base_url": persistence_input.api_info.base_url,
                    "contact": persistence_input.api_info.contact,
                    "license": persistence_input.api_info.license
                }
                document.endpoints_count = len(persistence_input.endpoints)
                document.confidence_score = persistence_input.confidence_score
                document.processing_time = persistence_input.processing_time
                document.parse_errors = persistence_input.parse_errors
                document.parse_warnings = persistence_input.parse_warnings
                document.parse_status = SessionStatus.COMPLETED
                document.updated_at = datetime.now()
                
                await document.save(using_db=conn)
                logger.info(f"更新API文档记录: {document.doc_id}")
            else:
                # 创建新文档记录
                document = await ApiDocument.create(
                    doc_id=persistence_input.document_id,
                    session_id=persistence_input.session_id,
                    file_name=persistence_input.file_name,
                    file_path="",
                    doc_format=persistence_input.doc_format.value,
                    api_info={
                        "title": persistence_input.api_info.title,
                        "version": persistence_input.api_info.version,
                        "description": persistence_input.api_info.description,
                        "base_url": persistence_input.api_info.base_url,
                        "contact": persistence_input.api_info.contact,
                        "license": persistence_input.api_info.license
                    },
                    endpoints_count=len(persistence_input.endpoints),
                    confidence_score=persistence_input.confidence_score,
                    processing_time=persistence_input.processing_time,
                    parse_errors=persistence_input.parse_errors,
                    parse_warnings=persistence_input.parse_warnings,
                    parse_status=SessionStatus.COMPLETED,
                    using_db=conn
                )
                logger.info(f"创建API文档记录: {document.doc_id}")

            return document

        except Exception as e:
            logger.error(f"更新API文档记录失败: {str(e)}")
            raise

    @staticmethod
    def compute_dedup_fingerprint(method: str, path: str, parameters: list = None) -> str:
        """计算去重指纹: method + path 的 MD5"""
        raw = f"{method.upper()}|{path}"
        return hashlib.md5(raw.encode()).hexdigest()

    async def _store_interfaces(
        self,
        document: ApiDocument,
        persistence_input: ApiDataPersistenceInput,
        conn
    ) -> Dict[str, ApiInterface]:
        """存储接口信息（含跨文档去重检测）"""
        interfaces = {}

        try:
            # 删除当前文档的旧接口记录（文档内更新）
            await ApiInterface.filter(document=document).using_db(conn).delete()

            # 计算所有新接口的指纹
            fingerprint_map: Dict[str, ParsedEndpoint] = {}
            for endpoint in persistence_input.endpoints:
                fp = self.compute_dedup_fingerprint(
                    endpoint.method.value if hasattr(endpoint.method, 'value') else endpoint.method,
                    endpoint.path,
                    endpoint.parameters
                )
                fingerprint_map[fp] = endpoint

            # 查询其他文档中是否存在相同指纹的活跃接口
            existing_fps = set()
            if fingerprint_map:
                existing_interfaces = await ApiInterface.filter(
                    dedup_fingerprint__in=list(fingerprint_map.keys()),
                    is_active=True,
                ).exclude(document=document).using_db(conn).all()

                for ei in existing_interfaces:
                    existing_fps.add(ei.dedup_fingerprint)

            # 分离：无冲突接口 vs 冲突接口
            duplicates = []
            for fp, endpoint in fingerprint_map.items():
                if fp in existing_fps:
                    # 查出已有接口的关键信息
                    existing = await ApiInterface.filter(
                        dedup_fingerprint=fp, is_active=True
                    ).exclude(document=document).using_db(conn).select_related("document").first()
                    duplicates.append({
                        "fingerprint": fp,
                        "method": endpoint.method.value if hasattr(endpoint.method, 'value') else endpoint.method,
                        "path": endpoint.path,
                        "new_name": endpoint.summary or f"{endpoint.method} {endpoint.path}",
                        "new_endpoint_id": endpoint.endpoint_id,
                        "existing_interface_id": existing.interface_id if existing else None,
                        "existing_name": existing.name if existing else None,
                        "existing_document_name": existing.document.file_name if existing and existing.document else None,
                    })
                else:
                    # 无冲突，直接写库
                    interface = await ApiInterface.create(
                        interface_id=endpoint.endpoint_id,
                        document=document,
                        endpoint_id=endpoint.endpoint_id,
                        name=endpoint.summary or f"{endpoint.method} {endpoint.path}",
                        path=endpoint.path,
                        method=endpoint.method,
                        summary=endpoint.summary,
                        description=endpoint.description,
                        api_title=persistence_input.api_info.title,
                        api_version=persistence_input.api_info.version,
                        base_url=persistence_input.api_info.base_url,
                        tags=endpoint.tags,
                        auth_required=endpoint.auth_required,
                        is_deprecated=endpoint.deprecated,
                        confidence_score=persistence_input.confidence_score,
                        extended_info=endpoint.extended_info or persistence_input.extended_info,
                        raw_data=endpoint.raw_data or persistence_input.raw_parsed_data,
                        dedup_fingerprint=fp,
                        using_db=conn
                    )
                    interfaces[endpoint.endpoint_id] = interface
                    logger.debug(f"存储接口: {interface.name}")

            # 把重复信息暂存到文档的 extended_info 中，供前端轮询时获取
            if duplicates:
                doc_extended = document.extra_data or {}
                doc_extended["pending_duplicates"] = duplicates
                # 同时暂存冲突接口的原始数据，供后续 resolve 时使用
                pending_endpoints = {}
                for fp, endpoint in fingerprint_map.items():
                    if fp in existing_fps:
                        pending_endpoints[fp] = endpoint.model_dump(mode="json")
                doc_extended["pending_endpoints"] = pending_endpoints
                document.extra_data = doc_extended
                await document.save(using_db=conn)
                logger.info(f"检测到 {len(duplicates)} 个重复接口，已暂存待用户确认")

            logger.info(f"存储接口信息完成，直接写入 {len(interfaces)} 个，重复待确认 {len(duplicates)} 个")
            return interfaces

        except Exception as e:
            logger.error(f"存储接口信息失败: {str(e)}")
            raise

    async def _store_parameters(
        self, 
        interfaces: Dict[str, ApiInterface], 
        persistence_input: ApiDataPersistenceInput, 
        conn
    ) -> None:
        """存储参数信息"""
        try:
            total_parameters = 0
            
            for endpoint in persistence_input.endpoints:
                interface = interfaces.get(endpoint.endpoint_id)
                if not interface:
                    continue
                
                # 删除现有参数记录
                await DbApiParameter.filter(interface=interface).using_db(conn).delete()
                
                for param in endpoint.parameters:
                    example_value = param.example
                    if example_value is not None:
                        if isinstance(example_value, (dict, list)):
                            example_str = json.dumps(example_value, ensure_ascii=False)
                        else:
                            example_str = str(example_value)
                    else:
                        example_str = None

                    await DbApiParameter.create(
                        parameter_id=str(uuid.uuid4()),
                        interface=interface,
                        name=param.name,
                        location=param.location.value,
                        data_type=param.data_type.value,
                        required=param.required,
                        description=param.description,
                        example=example_str,
                        schema=param.constraints.get("schema", {}),
                        constraints=param.constraints,
                        using_db=conn
                    )
                    total_parameters += 1

            self.persistence_metrics["total_parameters_stored"] += total_parameters
            logger.info(f"存储参数信息完成，共 {total_parameters} 个参数")

        except Exception as e:
            logger.error(f"存储参数信息失败: {str(e)}")
            raise

    async def _store_responses(
        self, 
        interfaces: Dict[str, ApiInterface], 
        persistence_input: ApiDataPersistenceInput, 
        conn
    ) -> None:
        """存储响应信息"""
        try:
            total_responses = 0
            
            for endpoint in persistence_input.endpoints:
                interface = interfaces.get(endpoint.endpoint_id)
                if not interface:
                    continue

                # 删除现有响应记录
                await DbApiResponse.filter(interface=interface).using_db(conn).delete()

                response_headers_map = endpoint.extended_info.get("response_headers", {}) if endpoint.extended_info else {}

                for response in endpoint.responses:
                    await DbApiResponse.create(
                        response_id=str(uuid.uuid4()),
                        interface=interface,
                        status_code=response.status_code,
                        description=response.description,
                        content_type=response.content_type,
                        response_schema=response.response_schema,
                        example=response.example,
                        headers=response_headers_map.get(response.status_code, {}),
                        using_db=conn
                    )
                    total_responses += 1

            self.persistence_metrics["total_responses_stored"] += total_responses
            logger.info(f"存储响应信息完成，共 {total_responses} 个响应")

        except Exception as e:
            logger.error(f"存储响应信息失败: {str(e)}")
            raise

    @staticmethod
    def _derive_case_display_name(test_case: GeneratedTestCase, endpoint: ParsedEndpoint) -> str:
        """计算用例展示名：优先用 endpoint.description，按 test_type 加后缀区分。"""
        base = ""
        if endpoint:
            base = (endpoint.description or "").strip() or (endpoint.summary or "").strip()
            if not base:
                method_str = endpoint.method.value if hasattr(endpoint.method, "value") else str(endpoint.method)
                base = f"{method_str} {endpoint.path}"
        if not base:
            base = (test_case.test_name or "").strip() or "未命名用例"

        type_value = test_case.test_type.value if hasattr(test_case.test_type, "value") else str(test_case.test_type)
        suffix_map = {
            "positive":    "",
            "negative":    "（异常）",
            "boundary":    "（边界）",
            "security":    "（安全）",
            "performance": "（性能）",
        }
        suffix = suffix_map.get(type_value, "")
        return f"{base}{suffix}"

    @staticmethod
    def _map_test_type(tc_type) -> "TestType":
        """schema 的 TestCaseType -> 数据库 TestType"""
        value = tc_type.value if hasattr(tc_type, "value") else str(tc_type)
        mapping = {
            "performance": TestType.PERFORMANCE,
            "security":    TestType.SECURITY,
        }
        return mapping.get(value, TestType.FUNCTIONAL)

    @staticmethod
    def _map_priority(p) -> "Priority":
        """schema 的 int 优先级 -> 数据库 Priority 枚举"""
        if isinstance(p, int):
            return {1: Priority.P0, 2: Priority.P1, 3: Priority.P2, 4: Priority.P3}.get(p, Priority.P2)
        return Priority.P2

    @staticmethod
    def _extract_assert_items(assert_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """ScenarioStepSpec.assert_spec → 紧凑断言列表。每个 kind 子键 → 一条。"""
        if not isinstance(assert_spec, dict):
            return []
        items: List[Dict[str, Any]] = []
        for kind, spec in assert_spec.items():
            if not isinstance(spec, dict):
                continue
            in_path = spec.get("in") or spec.get("path") or ""
            expected: Dict[str, Any] = {}
            for k in ("equalsRef", "findRef", "notFindRef", "everyRef", "neqRef",
                      "gteRef", "lteRef", "gtRef", "ltRef"):
                if k in spec:
                    expected = {"ref": spec[k]}
                    break
            if not expected:
                for k in ("equalsValue", "findValue", "notFindValue", "everyValue",
                          "gteValue", "lteValue", "gtValue", "ltValue", "neqValue",
                          "equals", "value"):
                    if k in spec:
                        expected = {"value": spec[k]}
                        break
            items.append({"kind": kind, "in": in_path, "expected": expected})
        return items

    @classmethod
    def _build_scenario_flow_summary(cls, sc) -> Dict[str, Any]:
        """ScenarioTestCase → flow_summary（scenario 类型）"""
        steps_out: List[Dict[str, Any]] = []
        asserts_out: List[Dict[str, Any]] = []
        for step in (sc.steps or []):
            method = step.method.value if hasattr(step.method, "value") else str(step.method)
            steps_out.append({
                "no": int(step.step),
                "method": method,
                "path": str(step.path or ""),
                "purpose": str(step.purpose or ""),
            })
            for item in cls._extract_assert_items(step.assert_spec or {}):
                item["step_no"] = int(step.step)
                asserts_out.append(item)
        primary_action = ""
        if steps_out:
            first = steps_out[0]
            primary_action = f"[{first['no']}] {first['method']} {first['path']}"
            if first['purpose']:
                primary_action += f" · {first['purpose']}"
        return {
            "kind": "scenario",
            "chain_name": str(sc.name or ""),
            "step_count": len(steps_out),
            "assertion_count": len(asserts_out),
            "primary_action": primary_action,
            "steps": steps_out,
            "assertions": asserts_out,
        }

    @staticmethod
    def _build_single_flow_summary(cases: List[Any], interface: ApiInterface) -> Dict[str, Any]:
        """普通脚本 → flow_summary（single 类型）：聚合该脚本下所有用例的断言。"""
        method = interface.method.value if hasattr(interface.method, "value") else str(interface.method)
        path = str(interface.path or "")
        asserts_out: List[Dict[str, Any]] = []
        for c in cases:
            for a in (getattr(c, "assertions", None) or []):
                if hasattr(a, "model_dump"):
                    a_dict = a.model_dump()
                elif isinstance(a, dict):
                    a_dict = a
                else:
                    continue
                asserts_out.append({
                    "kind": str(a_dict.get("comparison_operator") or "equals"),
                    "in": str(a_dict.get("assertion_type") or ""),
                    "expected": {"value": a_dict.get("expected_value")},
                    "desc": str(a_dict.get("description") or ""),
                })
        return {
            "kind": "single",
            "chain_name": None,
            "step_count": 1,
            "assertion_count": len(asserts_out),
            "primary_action": f"{method} {path}".strip(),
            "steps": [{"no": 1, "method": method, "path": path, "purpose": ""}],
            "assertions": asserts_out,
        }

    @classmethod
    def _build_script_flow_summary(
        cls,
        script,
        interface: ApiInterface,
        message: "ScriptPersistenceInput",
    ) -> Dict[str, Any]:
        """根据脚本封装的 case 集合决定 flow_summary 类型。

        - 命中 scenario：steps/assertions 来自整条 chain
        - 普通脚本：从该脚本下所有用例的 assertions 聚合，steps=1
        """
        case_ids = set((script.case_method_map or {}).keys())
        cases_by_id = {c.test_case_id: c for c in (message.test_cases or [])}
        related_cases = [cases_by_id[cid] for cid in case_ids if cid in cases_by_id]

        scenarios_by_name = {sc.name: sc for sc in (getattr(message, "scenarios", None) or [])}
        for c in related_cases:
            for tag in (getattr(c, "tags", None) or []):
                if isinstance(tag, str) and tag.startswith("scenario:"):
                    chain_name = tag[len("scenario:"):]
                    sc = scenarios_by_name.get(chain_name)
                    if sc:
                        return cls._build_scenario_flow_summary(sc)

        return cls._build_single_flow_summary(related_cases, interface)

    async def _store_test_cases(
        self,
        message: ScriptPersistenceInput,
        document: ApiDocument,
        conn,
    ) -> None:
        """将本次生成的测试用例落库（TestCase 表），按 endpoint+class::method 维度判重。"""
        try:
            ep_by_id = {ep.endpoint_id: ep for ep in (message.endpoints or [])}

            # 汇总所有脚本的 case_method_map（key: test_case_id -> {class_name, method_name, file_path}）
            case_method_full: Dict[str, Dict[str, str]] = {}
            for script in (message.scripts or []):
                file_path = script.file_path or ""
                for tc_id, mp in (script.case_method_map or {}).items():
                    full = {
                        "class_name": mp.get("class_name") or "",
                        "method_name": mp.get("method_name") or "",
                        "file_path": file_path,
                    }
                    case_method_full[tc_id] = full

            for tc in (message.test_cases or []):
                endpoint = ep_by_id.get(tc.endpoint_id)
                if not endpoint:
                    logger.debug(f"用例 {tc.test_case_id} 找不到对应 endpoint，跳过落库")
                    continue

                # 找到对应的 ApiInterface 行（interface_id == endpoint.endpoint_id）
                api_interface = await ApiInterface.filter(
                    interface_id=endpoint.endpoint_id,
                    document=document,
                ).using_db(conn).first()
                if not api_interface:
                    logger.debug(f"用例 {tc.test_case_id} 找不到对应 ApiInterface(interface_id={endpoint.endpoint_id})，跳过")
                    continue

                mp = case_method_full.get(tc.test_case_id, {})
                class_name = mp.get("class_name") or ""
                method_name = mp.get("method_name") or ""
                script_file_path = mp.get("file_path") or ""

                display_name = self._derive_case_display_name(tc, endpoint)
                description = (tc.description or endpoint.description or "").strip()
                test_type_db = self._map_test_type(tc.test_type)
                priority_db = self._map_priority(tc.priority)

                # 判重：document + endpoint(interface) + class_name + method_name
                existing = None
                if class_name and method_name:
                    existing = await TestCase.filter(
                        document=document,
                        endpoint=api_interface,
                        class_name=class_name,
                        method_name=method_name,
                    ).using_db(conn).first()

                if existing:
                    existing.name = display_name
                    existing.description = description
                    existing.test_type = test_type_db
                    existing.test_level = TestLevel.INTEGRATION
                    existing.priority = priority_db
                    existing.test_data = [td.model_dump() if hasattr(td, "model_dump") else td for td in (tc.test_data or [])]
                    existing.assertions = [a.model_dump() if hasattr(a, "model_dump") else a for a in (tc.assertions or [])]
                    existing.tags = list(getattr(tc, "tags", []) or [])
                    existing.script_file_path = script_file_path or existing.script_file_path
                    existing.generation_session_id = message.session_id
                    existing.is_active = True
                    await existing.save(using_db=conn)
                    logger.debug(f"更新 TestCase: {display_name} ({class_name}::{method_name})")
                else:
                    test_case = await TestCase.create(
                        test_id=tc.test_case_id,
                        document=document,
                        endpoint=api_interface,
                        name=display_name,
                        description=description,
                        test_type=test_type_db,
                        test_level=TestLevel.INTEGRATION,
                        priority=priority_db,
                        test_data=[td.model_dump() if hasattr(td, "model_dump") else td for td in (tc.test_data or [])],
                        assertions=[a.model_dump() if hasattr(a, "model_dump") else a for a in (tc.assertions or [])],
                        setup_steps=[],
                        teardown_steps=[],
                        dependencies=[],
                        tags=list(getattr(tc, "tags", []) or []),
                        timeout=30,
                        retry_count=0,
                        class_name=class_name or None,
                        method_name=method_name or None,
                        script_file_path=script_file_path or None,
                        generated_by="AI",
                        generation_session_id=message.session_id,
                        is_active=True,
                        using_db=conn,
                    )
                    logger.debug(f"创建 TestCase: {display_name} ({class_name}::{method_name})")

                    # 自动分类：按接口 path 匹配分类规则
                    try:
                        from app.services.api_automation.category_matcher import auto_assign_category
                        await auto_assign_category(test_case, api_interface)
                    except Exception as classify_err:
                        logger.debug(f"自动分类跳过: {classify_err}")

            logger.info(f"TestCase 落库完成: 共处理 {len(message.test_cases or [])} 个用例")
        except Exception as e:
            logger.error(f"TestCase 落库失败: {str(e)}", exc_info=True)
            # 不抛异常，避免影响脚本落库主流程

    async def _update_existing_script(
        self,
        existing_script: TestScript,
        script,
        interface: ApiInterface,
        message: ScriptPersistenceInput,
        conn
    ) -> None:
        """更新现有脚本 - 优化版"""
        try:
            # 更新脚本基本信息
            existing_script.name = script.script_name
            existing_script.description = f"为接口 {interface.name} ({interface.method.value} {interface.path}) 生成的测试脚本"
            existing_script.file_name = f"{script.script_name}.py"

            # 更新脚本内容
            existing_script.content = script.script_content
            existing_script.file_path = script.file_path

            # 更新技术信息
            existing_script.framework = script.framework
            existing_script.dependencies = script.dependencies or []
            existing_script.requirements = message.requirements_txt

            # 更新关联信息（确保关联正确）
            existing_script.interface = interface  # 重新设置关联，确保正确
            existing_script.document = await ApiDocument.filter(doc_id=message.document_id).using_db(conn).first()

            # 更新创建信息
            existing_script.generation_session_id = message.session_id
            existing_script.generated_by = "AI"
            existing_script.updated_at = datetime.now()

            # 更新状态信息
            existing_script.status = "ACTIVE"
            existing_script.is_executable = True
            existing_script.is_active = True

            # 重新计算执行流摘要（脚本内容或断言可能变化）
            existing_script.flow_summary = self._build_script_flow_summary(script, interface, message)

            await existing_script.save(using_db=conn)
            logger.debug(f"脚本更新成功: {script.script_id}")

        except Exception as e:
            logger.error(f"更新脚本失败: {script.script_id}, 错误: {str(e)}")
            raise

    async def _create_new_script(
        self,
        script,
        interface: ApiInterface,
        document: ApiDocument,
        message: ScriptPersistenceInput,
        conn
    ) -> TestScript:
        """创建新脚本 - 优化版"""
        try:
            new_script = await TestScript.create(
                # 基本信息
                script_id=script.script_id,
                name=script.script_name,
                description=f"为接口 {interface.name} ({interface.method.value} {interface.path}) 生成的测试脚本",
                file_name=f"{script.script_name}.py",

                # 关联字段 - 使用外键对象，ORM会自动处理ID映射
                interface=interface,  # 这会自动设置interface_id为interface.id (BIGINT)
                document=document,    # 这会自动设置document_id为document.id (BIGINT)

                # 脚本内容
                content=script.script_content,
                file_path=script.file_path,

                # 技术信息
                framework=script.framework,
                language="python",
                version="1.0",

                # 依赖信息
                dependencies=script.dependencies or [],
                requirements=message.requirements_txt,

                # 执行配置
                timeout=300,  # 默认5分钟超时
                retry_count=3,  # 默认重试3次
                parallel_execution=True,

                # 状态信息
                status="ACTIVE",
                is_executable=True,

                # 创建信息
                generated_by="AI",
                generation_session_id=message.session_id,

                # 质量评估
                code_quality_score="A",
                test_coverage_score=0.0,
                complexity_score=0.0,

                # 状态管理
                is_active=True,

                # 执行流摘要：脚本对应 chain 或 endpoint 的 steps/asserts 完整结构
                flow_summary=self._build_script_flow_summary(script, interface, message),

                using_db=conn
            )

            logger.debug(f"脚本创建成功: {script.script_id} -> 接口ID: {interface.id}")
            return new_script

        except Exception as e:
            logger.error(f"创建脚本失败: {script.script_id}, 错误: {str(e)}")
            raise



    async def _update_interface_script_stats(
        self,
        interface: ApiInterface,
        scripts: List[TestScript],
        conn
    ) -> None:
        """更新接口的脚本统计信息"""
        try:
            # 统计该接口的脚本数量
            script_count = await TestScript.filter(
                interface=interface,
                is_active=True
            ).using_db(conn).count()

            # 更新接口的脚本统计信息
            interface.test_script_count = script_count
            interface.last_script_generation_time = datetime.now()
            await interface.save(using_db=conn)

            logger.debug(f"接口 {interface.name} 的脚本统计更新完成，当前脚本数: {script_count}")

        except Exception as e:
            logger.error(f"更新接口脚本统计失败: {str(e)}")
            # 不抛出异常，避免影响主流程

    async def validate_script_interface_relationships(self) -> Dict[str, Any]:
        """验证脚本和接口关系的数据一致性"""
        logger.info("开始验证脚本和接口关系...")

        try:
            # 查询所有脚本
            scripts = await TestScript.all().prefetch_related('interface', 'document')

            validation_results = {
                'total_scripts': len(scripts),
                'valid_relationships': 0,
                'invalid_relationships': 0,
                'missing_interface': 0,
                'missing_document': 0,
                'errors': []
            }

            for script in scripts:
                try:
                    # 验证接口关系
                    if script.interface:
                        # 验证接口是否存在且有效
                        interface_exists = await ApiInterface.filter(id=script.interface.id).exists()
                        if interface_exists:
                            validation_results['valid_relationships'] += 1
                            logger.debug(f"脚本 {script.script_id} 接口关联正常: {script.interface.interface_id}")
                        else:
                            validation_results['invalid_relationships'] += 1
                            validation_results['errors'].append(
                                f"脚本 {script.script_id} 关联的接口不存在 (interface_id: {script.interface.id})"
                            )
                    else:
                        validation_results['missing_interface'] += 1
                        validation_results['errors'].append(f"脚本 {script.script_id} 没有关联接口")

                    # 验证文档关系
                    if not script.document:
                        validation_results['missing_document'] += 1
                        validation_results['errors'].append(f"脚本 {script.script_id} 没有关联文档")

                except Exception as e:
                    validation_results['invalid_relationships'] += 1
                    validation_results['errors'].append(f"脚本 {script.script_id} 验证失败: {str(e)}")

            # 计算统计信息
            validation_results['success_rate'] = (
                validation_results['valid_relationships'] / validation_results['total_scripts'] * 100
                if validation_results['total_scripts'] > 0 else 0
            )

            logger.info(f"验证完成: {validation_results}")
            return validation_results

        except Exception as e:
            logger.error(f"验证脚本接口关系失败: {str(e)}")
            return {
                'error': str(e),
                'total_scripts': 0,
                'valid_relationships': 0,
                'invalid_relationships': 0,
                'errors': [f"验证过程失败: {str(e)}"]
            }

    def get_persistence_metrics(self) -> Dict[str, Any]:
        """获取持久化统计指标"""
        return {
            **self.persistence_metrics,
            **self.common_metrics
        }
