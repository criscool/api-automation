"""
API自动化智能体数据模型 - 重新设计版本
清晰的数据流转：文档解析 -> 接口分析 -> 测试用例生成 -> 脚本生成

设计原则：
1. 每个智能体有明确的输入输出模型
2. 数据传递简洁高效，避免冗余
3. 命名统一规范，易于理解和维护
4. 支持扩展，便于后续功能增强
"""
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field
import uuid


# ============================================================================
# 基础枚举定义
# ============================================================================

class DocumentFormat(str, Enum):
    """文档格式"""
    AUTO = "auto"
    OPENAPI = "openapi"
    SWAGGER = "swagger"
    POSTMAN = "postman"
    CUSTOM = "custom"
    PDF = "pdf"
    MARKDOWN = "markdown"


class HttpMethod(str, Enum):
    """HTTP方法"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class ParameterLocation(str, Enum):
    """参数位置"""
    QUERY = "query"
    PATH = "path"
    HEADER = "header"
    BODY = "body"
    FORM = "form"
    COOKIE = "cookie"


class DataType(str, Enum):
    """数据类型"""
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class DependencyType(str, Enum):
    """依赖类型"""
    DATA_FLOW = "data_flow"      # 数据流依赖：需要前一个接口的返回数据
    AUTH_TOKEN = "auth_token"    # 认证依赖：需要认证token
    AUTH = "auth"                # 认证依赖：简化版本
    SEQUENCE = "sequence"        # 序列依赖：必须按顺序执行
    BUSINESS = "business"        # 业务依赖：业务逻辑相关
    DATA = "data"                # 数据依赖：数据相关
    FUNCTIONAL = "functional"    # 功能依赖：功能相关
    CONDITIONAL = "conditional"  # 条件依赖：根据条件决定是否执行


class TestCaseType(str, Enum):
    """测试用例类型"""
    POSITIVE = "positive"        # 正向测试
    NEGATIVE = "negative"        # 负向测试
    BOUNDARY = "boundary"        # 边界测试
    SECURITY = "security"        # 安全测试
    PERFORMANCE = "performance"  # 性能测试


class AssertionType(str, Enum):
    """断言类型"""
    STATUS_CODE = "status_code"
    RESPONSE_BODY = "response_body"
    RESPONSE_HEADER = "response_header"
    RESPONSE_TIME = "response_time"
    JSON_SCHEMA = "json_schema"


class LogLevel(str, Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TaskStatus(str, Enum):
    """任务状态"""
    CREATED = "created"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================================
# 1. 文档解析智能体 - 输入输出模型
# ============================================================================

class DocumentParseInput(BaseModel):
    """文档解析输入"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="会话ID")
    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="文档ID")
    file_path: str = Field(..., description="文件路径")
    file_name: str = Field(..., description="文件名")
    file_content: Optional[str] = Field(None, description="文件内容")
    doc_format: DocumentFormat = Field(DocumentFormat.AUTO, description="文档格式")
    parse_options: Dict[str, Any] = Field(default_factory=dict, description="解析选项")


class ApiParameter(BaseModel):
    """API参数"""
    name: str = Field(..., description="参数名称")
    location: ParameterLocation = Field(..., description="参数位置")
    data_type: DataType = Field(..., description="数据类型")
    required: bool = Field(False, description="是否必需")
    description: str = Field("", description="参数描述")
    example: Any = Field(None, description="示例值")
    constraints: Dict[str, Any] = Field(default_factory=dict, description="参数约束")


class ApiResponse(BaseModel):
    """API响应"""
    status_code: str = Field(..., description="状态码")
    description: str = Field("", description="响应描述")
    content_type: str = Field("application/json", description="内容类型")
    response_schema: Dict[str, Any] = Field(default_factory=dict, description="响应结构")
    example: Any = Field(None, description="响应示例")


class ParsedEndpoint(BaseModel):
    """解析后的API端点"""
    endpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="端点ID")
    path: str = Field(..., description="API路径")
    method: HttpMethod = Field(..., description="HTTP方法")
    summary: str = Field("", description="端点摘要")
    description: str = Field("", description="端点描述")
    tags: List[str] = Field(default_factory=list, description="标签")
    parameters: List[ApiParameter] = Field(default_factory=list, description="参数列表")
    responses: List[ApiResponse] = Field(default_factory=list, description="响应列表")
    auth_required: bool = Field(False, description="是否需要认证")
    deprecated: bool = Field(False, description="是否已废弃")

    # 扩展信息字段 - 用于传递更丰富的接口信息给智能体
    extended_info: Dict[str, Any] = Field(default_factory=dict, description="扩展信息")
    raw_data: Dict[str, Any] = Field(default_factory=dict, description="原始数据")
    security_schemes: Dict[str, Any] = Field(default_factory=dict, description="安全方案")
    complexity_score: float = Field(0.0, description="复杂度评分")
    confidence_score: float = Field(0.0, description="置信度评分")

    # 接口分类和标识信息
    interface_name: str = Field("", description="接口名称")
    category: str = Field("", description="接口分类")
    auth_type: str = Field("", description="认证类型")


class ParsedApiInfo(BaseModel):
    """解析后的API信息"""
    title: str = Field(..., description="API标题")
    version: str = Field(..., description="API版本")
    description: str = Field("", description="API描述")
    base_url: str = Field("", description="基础URL")
    contact: Dict[str, str] = Field(default_factory=dict, description="联系信息")
    license: Dict[str, str] = Field(default_factory=dict, description="许可证信息")


class DocumentParseOutput(BaseModel):
    """文档解析输出 - 增强版本，保留更多信息"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    file_name: str = Field(..., description="文件名")
    doc_format: DocumentFormat = Field(..., description="文档格式")
    api_info: ParsedApiInfo = Field(..., description="API基本信息")
    endpoints: List[ParsedEndpoint] = Field(default_factory=list, description="端点列表")
    parse_errors: List[str] = Field(default_factory=list, description="解析错误")
    parse_warnings: List[str] = Field(default_factory=list, description="解析警告")
    confidence_score: float = Field(0.0, description="解析置信度")
    processing_time: float = Field(0.0, description="处理时间")

    # 新增：扩展信息字段，保留大模型解析的丰富数据
    extended_info: Dict[str, Any] = Field(default_factory=dict, description="扩展信息")
    raw_parsed_data: Dict[str, Any] = Field(default_factory=dict, description="原始解析数据")

    # 新增：质量评估信息
    quality_assessment: Dict[str, Any] = Field(default_factory=dict, description="质量评估")
    testing_recommendations: List[Dict[str, Any]] = Field(default_factory=list, description="测试建议")

    # 新增：错误代码映射
    error_codes: Dict[str, str] = Field(default_factory=dict, description="错误代码说明")

    # 新增：全局配置信息
    global_headers: Dict[str, Any] = Field(default_factory=dict, description="全局请求头")
    security_schemes: Dict[str, Any] = Field(default_factory=dict, description="安全方案")
    servers: List[Dict[str, Any]] = Field(default_factory=list, description="服务器列表")


# ============================================================================
# 2. 接口分析智能体 - 输入输出模型
# ============================================================================

class AnalysisInput(BaseModel):
    """接口分析输入"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    interface_id: Optional[str] = Field(None, description="接口ID")  # 新增：接口ID
    api_info: ParsedApiInfo = Field(..., description="API基本信息")
    endpoints: List[ParsedEndpoint] = Field(..., description="端点列表")
    analysis_options: Dict[str, Any] = Field(default_factory=dict, description="分析选项")


class EndpointDependency(BaseModel):
    """端点依赖关系"""
    dependency_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="依赖ID")
    source_endpoint_id: str = Field(..., description="源端点ID")
    target_endpoint_id: str = Field(..., description="目标端点ID")
    dependency_type: DependencyType = Field(..., description="依赖类型")
    description: str = Field("", description="依赖描述")
    data_mapping: Dict[str, str] = Field(default_factory=dict, description="数据映射关系")
    condition: Optional[str] = Field(None, description="依赖条件")


class ExecutionGroup(BaseModel):
    """执行组"""
    group_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="组ID")
    group_name: str = Field("", description="组名称")  # 改为可选，有默认值
    endpoint_ids: List[str] = Field(default_factory=list, description="端点ID列表")  # 改为可选
    endpoints: List[ParsedEndpoint] = Field(default_factory=list, description="端点对象列表")  # 新增
    execution_order: int = Field(0, description="执行顺序")  # 改为有默认值
    parallel_execution: bool = Field(False, description="是否可并行执行")
    prerequisites: List[str] = Field(default_factory=list, description="前置条件")  # 新增
    description: str = Field("", description="执行组描述")  # 新增


class AnalysisOutput(BaseModel):
    """接口分析输出"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    interface_id: Optional[str] = Field(None, description="接口ID")  # 新增：接口ID
    dependencies: List[EndpointDependency] = Field(default_factory=list, description="依赖关系")
    execution_groups: List[ExecutionGroup] = Field(default_factory=list, description="执行组")
    test_strategy: List[str] = Field(default_factory=list, description="测试策略建议")
    risk_assessment: Dict[str, Any] = Field(default_factory=dict, description="风险评估")
    processing_time: float = Field(0.0, description="处理时间")


# ============================================================================
# 3. 测试用例生成智能体 - 输入输出模型
# ============================================================================

class TestCaseGenerationInput(BaseModel):
    """测试用例生成输入"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    interface_id: Optional[str] = Field(None, description="接口ID")  # 新增：接口ID
    api_info: ParsedApiInfo = Field(..., description="API基本信息")
    endpoints: List[ParsedEndpoint] = Field(..., description="端点列表")
    dependencies: List[EndpointDependency] = Field(default_factory=list, description="依赖关系")
    execution_groups: List[ExecutionGroup] = Field(default_factory=list, description="执行组")
    generation_options: Dict[str, Any] = Field(default_factory=dict, description="生成选项")


class TestDataItem(BaseModel):
    """测试数据项"""
    parameter_name: str = Field(..., description="参数名称")
    test_value: Any = Field(..., description="测试值")
    value_description: str = Field("", description="值描述")


class TestAssertion(BaseModel):
    """测试断言"""
    assertion_type: AssertionType = Field(..., description="断言类型")
    expected_value: Any = Field(..., description="期望值")
    comparison_operator: str = Field("equals", description="比较操作符")
    description: str = Field("", description="断言描述")


class GeneratedTestCase(BaseModel):
    """生成的测试用例"""
    test_case_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="测试用例ID")
    test_name: str = Field(..., description="测试用例名称")
    endpoint_id: str = Field(..., description="关联端点ID")
    test_type: TestCaseType = Field(..., description="测试类型")
    description: str = Field("", description="测试描述")
    test_data: List[TestDataItem] = Field(default_factory=list, description="测试数据")
    assertions: List[TestAssertion] = Field(default_factory=list, description="断言列表")
    setup_steps: List[str] = Field(default_factory=list, description="前置步骤")
    cleanup_steps: List[str] = Field(default_factory=list, description="清理步骤")
    priority: int = Field(1, description="优先级")
    tags: List[str] = Field(default_factory=list, description="标签")
    display_name_override: Optional[str] = Field(None, description="用户指定的中文用例名，落库时优先于自动派生名")


class TestCaseGenerationOutput(BaseModel):
    """测试用例生成输出"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    interface_id: Optional[str] = Field(None, description="接口ID")  # 新增：接口ID
    test_cases: List[GeneratedTestCase] = Field(default_factory=list, description="测试用例列表")
    coverage_report: Dict[str, Any] = Field(default_factory=dict, description="覆盖度报告")
    generation_summary: Dict[str, Any] = Field(default_factory=dict, description="生成摘要")
    processing_time: float = Field(0.0, description="处理时间")


# ============================================================================
# 4. 脚本生成智能体 - 输入输出模型
# ============================================================================

class ScriptGenerationInput(BaseModel):
    """脚本生成输入"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    interface_id: Optional[str] = Field(None, description="接口ID")
    api_info: ParsedApiInfo = Field(..., description="API基本信息")
    endpoints: List[ParsedEndpoint] = Field(..., description="端点列表")
    test_cases: List[GeneratedTestCase] = Field(..., description="测试用例列表")
    dependencies: List[EndpointDependency] = Field(default_factory=list, description="依赖关系")  # 新增：依赖关系
    execution_groups: List[ExecutionGroup] = Field(default_factory=list, description="执行组")
    generation_options: Dict[str, Any] = Field(default_factory=dict, description="生成选项")
    # 场景测试用例（chain-style）：非空时 ScriptGeneratorAgent 走 scenario 分支；
    # 空时走原有 LLM/fallback 路径，老调用方零感知。
    scenarios: List["ScenarioTestCase"] = Field(default_factory=list, description="场景测试用例")


class GeneratedScript(BaseModel):
    """生成的测试脚本"""
    script_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="脚本ID")
    script_name: str = Field(..., description="脚本名称")
    file_path: str = Field(..., description="文件路径")
    script_content: str = Field(..., description="脚本内容")
    test_case_ids: List[str] = Field(default_factory=list, description="包含的测试用例ID")
    framework: str = Field("pytest", description="测试框架")
    dependencies: List[str] = Field(default_factory=list, description="依赖包")
    execution_order: int = Field(1, description="执行顺序")
    # 用例方法映射：test_case_id -> {class_name, method_name}，用于落库 TestCase + pytest nodeid
    case_method_map: Dict[str, Dict[str, str]] = Field(default_factory=dict, description="用例方法映射")


class ScriptGenerationOutput(BaseModel):
    """脚本生成输出"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    interface_id: Optional[str] = Field(None, description="接口ID")  # 新增：接口ID
    scripts: List[GeneratedScript] = Field(default_factory=list, description="脚本列表")
    config_files: Dict[str, str] = Field(default_factory=dict, description="配置文件")
    requirements_txt: str = Field("", description="依赖文件内容")
    readme_content: str = Field("", description="README内容")
    generation_summary: Dict[str, Any] = Field(default_factory=dict, description="生成摘要")
    processing_time: float = Field(0.0, description="处理时间")


class ScriptPersistenceInput(BaseModel):
    """脚本持久化输入"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    interface_id: str = Field(..., description="接口ID")
    scripts: List[GeneratedScript] = Field(..., description="脚本列表")
    # 用例和端点信息（用于落库 TestCase 表并计算展示名）
    test_cases: List[GeneratedTestCase] = Field(default_factory=list, description="测试用例列表")
    endpoints: List[ParsedEndpoint] = Field(default_factory=list, description="端点列表")
    # 场景测试用例：scenario 子用例落库时按 tags[scenario:xxx]+priority(step_no) 回查 ScenarioStepSpec
    # 写入 TestCase.scenario_step。非 scenario 场景为空，老调用方无感
    scenarios: List["ScenarioTestCase"] = Field(default_factory=list, description="场景测试用例")
    config_files: Dict[str, str] = Field(default_factory=dict, description="配置文件")
    requirements_txt: str = Field("", description="依赖文件内容")
    readme_content: str = Field("", description="README内容")
    generation_summary: Dict[str, Any] = Field(default_factory=dict, description="生成摘要")
    processing_time: float = Field(0.0, description="处理时间")


# ============================================================================
# 5. 测试执行智能体 - 输入输出模型
# ============================================================================

class TestExecutionInput(BaseModel):
    """测试执行输入"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    scripts: List[GeneratedScript] = Field(..., description="要执行的脚本列表")
    execution_config: Dict[str, Any] = Field(default_factory=dict, description="执行配置")
    environment: str = Field("test", description="执行环境")
    parallel: bool = Field(False, description="是否并行执行")
    max_workers: int = Field(1, description="最大并发数")


class TestResult(BaseModel):
    """单个测试结果"""
    test_id: str = Field(..., description="测试ID")
    test_name: str = Field(..., description="测试名称")
    status: str = Field(..., description="执行状态")  # passed, failed, skipped, error
    duration: float = Field(0.0, description="执行时间(秒)")
    error_message: Optional[str] = Field(None, description="错误信息")
    failure_reason: Optional[str] = Field(None, description="失败原因")
    stdout: str = Field("", description="标准输出")
    stderr: str = Field("", description="标准错误")
    assertions: List[Dict[str, Any]] = Field(default_factory=list, description="断言结果")


class ScriptExecutionResult(BaseModel):
    """脚本执行结果"""
    script_id: str = Field(..., description="脚本ID")
    script_name: str = Field(..., description="脚本名称")
    status: str = Field(..., description="执行状态")  # success, failed, error
    start_time: datetime = Field(..., description="开始时间")
    end_time: datetime = Field(..., description="结束时间")
    duration: float = Field(0.0, description="执行时间(秒)")
    test_results: List[TestResult] = Field(default_factory=list, description="测试结果列表")
    total_tests: int = Field(0, description="总测试数")
    passed_tests: int = Field(0, description="通过测试数")
    failed_tests: int = Field(0, description="失败测试数")
    skipped_tests: int = Field(0, description="跳过测试数")
    error_tests: int = Field(0, description="错误测试数")
    coverage_report: Dict[str, Any] = Field(default_factory=dict, description="覆盖率报告")


class TestExecutionOutput(BaseModel):
    """测试执行输出"""
    session_id: str = Field(..., description="会话ID")
    document_id: str = Field(..., description="文档ID")
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="执行ID")
    overall_status: str = Field(..., description="总体状态")  # success, failed, partial
    start_time: datetime = Field(..., description="开始时间")
    end_time: datetime = Field(..., description="结束时间")
    total_duration: float = Field(0.0, description="总执行时间(秒)")
    script_results: List[ScriptExecutionResult] = Field(default_factory=list, description="脚本执行结果")
    summary: Dict[str, Any] = Field(default_factory=dict, description="执行摘要")
    reports: Dict[str, str] = Field(default_factory=dict, description="测试报告")
    artifacts: List[str] = Field(default_factory=list, description="生成的文件列表")
    processing_time: float = Field(0.0, description="处理时间")


# ============================================================================
# 智能体提示词模板 - 专业化设计
# ============================================================================

class AgentPrompts:
    """智能体提示词模板集合"""

    # 1. 文档解析智能体提示词
    DOCUMENT_PARSER_SYSTEM_PROMPT = """你是一个专业的API文档解析专家，具备以下核心能力：

1. **多格式文档解析**：精通OpenAPI/Swagger、Postman Collection、PDF等格式
2. **智能信息提取**：准确识别API端点、参数、响应结构
3. **数据标准化**：将不同格式的文档统一转换为标准结构
4. **质量评估**：对解析结果进行置信度评估

## 解析任务要求：
- 提取API基本信息（标题、版本、描述、基础URL）
- 识别所有API端点及其详细信息
- 分析参数类型、约束条件和示例值
- 提取响应格式和状态码定义
- 识别认证要求和安全配置

## 输出格式：
严格按照JSON格式输出，包含完整的API信息和端点列表。
确保数据结构清晰、字段完整、类型正确。"""

    DOCUMENT_PARSER_TASK_PROMPT = """请解析以下API文档内容：

## 文档信息
- 文件名：{file_name}
- 格式：{doc_format}

## 文档内容
{document_content}

## 解析要求
1. 提取API基本信息（标题、版本、描述、基础URL等）
2. 识别所有API端点，包括：
   - 路径和HTTP方法
   - 参数列表（查询参数、路径参数、请求体等）
   - 响应定义（状态码、响应结构、示例）
   - 认证要求
3. 分析参数约束和验证规则
4. 提取示例数据和默认值

请按照标准JSON格式输出解析结果，确保数据完整性和准确性。"""

    # 2. 接口分析智能体提示词
    API_ANALYZER_SYSTEM_PROMPT = """你是一个API依赖关系分析专家，专门负责：

1. **依赖关系识别**：分析API端点之间的数据流和调用依赖
2. **执行顺序规划**：确定最优的测试执行顺序
3. **风险评估**：识别潜在的测试风险和注意事项
4. **策略建议**：提供专业的测试策略建议

## 分析维度：
- **数据流依赖**：识别需要前置接口返回数据的端点
- **认证依赖**：识别需要认证token的端点
- **序列依赖**：识别必须按特定顺序执行的端点
- **条件依赖**：识别基于条件判断的依赖关系

## 输出要求：
提供清晰的依赖关系图和执行计划，确保测试的可靠性和效率。"""

    API_ANALYZER_TASK_PROMPT = """请分析以下API端点的依赖关系：

## API基本信息
{api_info}

## 端点列表
{endpoints}

## 分析任务
1. **依赖关系分析**：
   - 识别数据流依赖（哪些接口需要其他接口的返回数据）
   - 识别认证依赖（哪些接口需要先获取认证token）
   - 识别序列依赖（哪些接口必须按特定顺序执行）
   - 识别条件依赖（基于业务逻辑的依赖关系）

2. **执行计划制定**：
   - 将端点分组，确定执行顺序
   - 识别可并行执行的端点组
   - 制定数据传递方案

3. **风险评估**：
   - 识别潜在的测试风险点
   - 提供风险缓解建议

4. **测试策略建议**：
   - 推荐测试覆盖策略
   - 提供性能测试建议

请输出详细的分析结果，包括依赖关系、执行组和测试策略。"""

    # 3. 测试用例生成智能体提示词
    TEST_CASE_GENERATOR_SYSTEM_PROMPT = """你是一个测试用例设计专家，专精于API测试用例的设计和生成：

1. **全面测试覆盖**：设计正向、负向、边界、安全等多种类型的测试用例
2. **数据驱动测试**：为每个测试用例生成合适的测试数据
3. **断言设计**：设计准确有效的测试断言
4. **场景化测试**：基于业务场景设计端到端测试用例

## 测试用例类型：
- **正向测试**：验证正常业务流程
- **负向测试**：验证异常处理和错误响应
- **边界测试**：测试参数边界值和极限情况
- **安全测试**：验证权限控制和数据安全
- **性能测试**：验证响应时间和并发处理

## 设计原则：
- 测试用例应具备独立性和可重复性
- 测试数据应覆盖各种场景和边界情况
- 断言应准确验证预期结果
- 优先级设置应合理，便于测试执行规划"""

    TEST_CASE_GENERATOR_TASK_PROMPT = """请为以下API端点生成全面的测试用例：

## API基本信息
{api_info}

## 端点信息
{endpoints}

## 依赖关系
{dependencies}

## 执行组信息
{execution_groups}

## 生成要求
1. **测试用例设计**：
   # [NOTE] 只生成正向用例。如需恢复多类型（正向/负向/边界/安全），改回下面这行：
   - 为每个端点生成正向测试用例
   - 正向测试：验证正常功能和业务流程

2. **测试数据生成**：
   - 为每个测试用例生成合适的测试数据
   - 考虑参数约束和业务规则
   - 包含有效数据、无效数据和边界数据
   - **重要：测试值必须是有效的JSON值，不能包含JavaScript表达式或函数调用**

3. **断言设计**：
   - 设计准确的状态码断言
   - 设计响应体结构和内容断言
   - 设计响应头和性能断言

4. **依赖处理**：
   - 处理端点间的数据依赖关系
   - 设计前置步骤和清理步骤

**重要：请严格按照以下JSON格式返回结果，不要包含任何额外的文本、说明或markdown标记：**

**JSON格式要求：**
- 所有字符串值必须用双引号包围
- 测试值必须是有效的JSON值，不能包含JavaScript表达式（如 "a".repeat(320)）
- 对于长字符串，请直接生成完整的字符串值
- 数字值不要用引号包围
- 确保JSON语法完全正确，没有多余的逗号

```json
{{
  "test_cases": [
    {{
      "test_name": "测试用例名称",
      "endpoint_id": "端点ID",
      "test_type": "positive|negative|boundary|security|performance",
      "description": "测试用例描述",
      "test_data": [
        {{
          "parameter_name": "参数名",
          "test_value": "测试值（必须是有效的JSON值，不能是JavaScript表达式）",
          "value_description": "值描述"
        }}
      ],
      "assertions": [
        {{
          "assertion_type": "status_code|response_body|response_header|response_time",
          "expected_value": "期望值",
          "comparison_operator": "equals|contains|greater_than|less_than",
          "description": "断言描述"
        }}
      ],
      "setup_steps": ["前置步骤1", "前置步骤2"],
      "cleanup_steps": ["清理步骤1", "清理步骤2"],
      "priority": 1,
      "tags": ["标签1", "标签2"]
    }}
  ],
  "generation_method": "intelligent",
  "confidence_score": 0.9
}}
```

请确保返回有效的JSON格式，去掉所有markdown标记和额外说明。

**特别注意：**
- 对于超长字符串测试值（如320字符的邮箱），请直接生成完整的字符串，不要使用JavaScript的repeat()函数
- 示例：使用 "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa@example.com" 而不是 "a".repeat(320) + "@example.com"
- 所有测试值都必须是有效的JSON字面量"""

    # 4. 脚本生成智能体提示词
    SCRIPT_GENERATOR_SYSTEM_PROMPT = """你是测试脚本生成器，输出的脚本运行在已有 pytest 框架中。

## 正确的脚本示例（无依赖关系）

```python
\"\"\"用户管理接口测试\"\"\"
import pytest

pytestmark = [pytest.mark.user, pytest.mark.api]


class TestUserApi:

    def test_get_user_list(self, api_client):
        \"\"\"正向：获取用户列表\"\"\"
        resp = api_client.get("/api/system/users", params={"page": 1, "size": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        result = data["data"]
        assert isinstance(result, list)
        if len(result) > 0:
            assert "id" in result[0]
            assert "username" in result[0]

    def test_create_user(self, api_client):
        \"\"\"正向：创建用户\"\"\"
        resp = api_client.post("/api/system/users", json={
            "username": "test_user",
            "email": "test@example.com"
        })
        assert resp.status_code == 200
        created = resp.json()["data"]
        assert created["username"] == "test_user"
        assert created["email"] == "test@example.com"

    def test_create_user_missing_field(self, api_client):
        \"\"\"负向：缺少必填字段\"\"\"
        resp = api_client.post("/api/system/users", json={})
        assert resp.status_code in [400, 422]
```

## 正确的脚本示例（有依赖关系 — fixture 输出到 conftest.py 跨文件共享）

**当存在依赖关系时，业务 fixture 必须输出到 `testcases/conftest.py`，test 文件只保留测试类。**
这样其他 test 文件需要相同前置资源时可以直接引用，避免重复定义。

### 文件 1：testcases/conftest.py（业务 fixture 共享层）

```python
\"\"\"共享业务 fixture\"\"\"
import pytest


@pytest.fixture
def created_resource(api_client):
    \"\"\"前置：创建资源；teardown 自动清理\"\"\"
    resp = api_client.post("/api/resources", json={"name": "test_resource"})
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    resource_id = data["data"]["id"]
    assert resource_id is not None

    yield resource_id

    # teardown: 容忍 404（资源已被测试方法删除是预期场景）
    cleanup_resp = api_client.delete(f"/api/resources/{resource_id}")
    assert cleanup_resp.status_code in (200, 204, 404), \\
        f"清理失败 id={resource_id}, status={cleanup_resp.status_code}"
```

### 文件 2：testcases/test_resource.py（仅含测试类，引用 conftest 中的 fixture）

```python
\"\"\"资源管理流程测试\"\"\"
import pytest

pytestmark = [pytest.mark.resource, pytest.mark.api]


class TestResourceFlow:

    def test_create_resource(self, created_resource):
        \"\"\"验证创建成功，返回有效 ID（fixture 已断言并 teardown 会清理）\"\"\"
        assert created_resource is not None

    def test_get_resource_detail(self, api_client, created_resource):
        \"\"\"查询刚创建的资源，验证数据一致性\"\"\"
        resp = api_client.get(f"/api/resources/{created_resource}")
        assert resp.status_code == 200
        detail = resp.json()["data"]
        assert detail["id"] == created_resource
        assert detail["name"] == "test_resource"

    def test_delete_resource(self, api_client, created_resource):
        \"\"\"删除资源（fixture teardown 会再尝试 DELETE，404 已被容忍）\"\"\"
        resp = api_client.delete(f"/api/resources/{created_resource}")
        assert resp.status_code == 200
```

**关键说明**：
- fixture 在 conftest.py 中用 `yield` 而非 `return`，`yield` 之后是 teardown 代码
- teardown 中 DELETE 必须容忍 `200/204/404` 三种状态码（404 = 资源已被测试方法删除）
- test 文件中不重复定义业务 fixture，直接通过参数引用

## 以下写法是错误的，绝对不能出现

```python
# ❌ 错误1：硬编码URL
API_BASE_URL = "http://localhost:8000"

# ❌ 错误2：自定义api_client fixture
@pytest.fixture
def api_client():
    session = requests.Session()
    return session

# ❌ 错误3：直接import requests发请求
import requests
response = requests.get("http://...")

# ❌ 错误4：定义工具函数
def make_request(client, method, path, **kwargs):
    ...

# ❌ 错误5：变量名含连字符
access-token = "xxx"  # 应该用 access_token

# ❌ 错误6：空断言
assert resp is not None  # 无意义

# ❌ 错误7：只断言状态码不验证响应内容
def test_create(self, api_client):
    resp = api_client.post("/api/users", json={"name": "test"})
    assert resp.status_code == 200  # 缺少响应内容断言

# ❌ 错误8：fixture 返回未验证的数据
@pytest.fixture
def created_item(api_client):
    resp = api_client.post("/api/items", json={"name": "test"})
    return resp.json().get("data", {}).get("id")  # 没有 assert 就 return
```"""

    SCRIPT_GENERATOR_TASK_PROMPT = """请基于以下信息生成 pytest 测试脚本。

## 输入数据

### API 基本信息
{api_info}

### 端点列表
{endpoints}

### 测试用例
{test_cases}

### 依赖关系
{dependencies}

### 执行组
{execution_groups}

### 生成选项
{generation_options}

## 生成规则

### 脚本结构（必须严格按此顺序）
1. 文件头文档字符串（一行，用三个双引号包裹：模块名称接口测试）
2. `import pytest`（仅此一行 import，禁止 import requests 等其他库）
3. `pytestmark = [pytest.mark.模块标签, pytest.mark.api]`（模块标签从端点的 tags 提取）
4. 如果 dependencies 不为空：定义 @pytest.fixture 链（仅用于步骤间传数据）
5. 测试类 `class TestXxx:`（类名从 API 标题或模块名派生）
6. 测试方法 `def test_xxx(self, api_client, ...):`

### HTTP 请求写法（只允许以下 4 种，path 不含域名）
- `api_client.get(path, params={{...}})`
- `api_client.post(path, json={{...}})`
- `api_client.put(path, json={{...}})`
- `api_client.delete(path)`

### 请求体字段构造（极其重要）
- POST/PUT/PATCH 的 `json={{...}}` 必须严格使用文档中 body 参数的字段名和示例值
- 端点的 parameters 中 `location == "body"` 的参数携带了 `example` 字段（dict）
  - 正向用例：直接复用 example 的字段名和值；不允许凭空臆造 name/description/enabled 等通用字段
  - 负向用例：基于 example 构造无效场景（缺字段/类型错误/超长），不能丢弃文档定义的字段结构
- 如果 parameter 携带 `constraints`（enum / min / max），按约束生成合理值
- 严禁使用 `{{"name": "test", "enabled": true}}` 这种与文档无关的样板数据

### 依赖关系处理
- 如果 dependencies 为空：所有测试方法互相独立，都只依赖 api_client
- 如果 dependencies 不为空：
  1. **业务 fixture 必须输出到 `testcases/conftest.py`**，而不是写在 test 文件里
     - 输出的 scripts 数组需同时包含 conftest.py 和 test_xxx.py 两个 entry
     - test 文件中只保留 `class TestXxx` 和测试方法，**禁止**重复定义业务 fixture
  2. 按 source_endpoint_id → target_endpoint_id 的顺序建立 fixture 链
  3. 链的第一步定义为 @pytest.fixture，通过 api_client 创建资源
  4. fixture 内必须先 assert 验证成功，**再用 `yield`（而非 `return`）返回**资源 ID
  5. yield 之后是 teardown 代码：DELETE 资源，状态码断言用白名单 `(200, 204, 404)`
     - 404 是预期场景（资源已被测试方法删除），不视为失败
  6. 后续步骤的 fixture 依赖前一步的 fixture
  7. 如果 dependencies 中有 data_mapping，按映射关系从源接口响应中取值
  8. 忽略 dependency_type 为 "auth" 或 "auth_token" 的依赖（框架已处理认证）

### 资源清理规则（极其重要）
- 任何 POST/PUT/PATCH 类**正向**测试方法，在测试结束前必须清理自己创建的资源，二选一：
  - **方式 A（推荐，有依赖时）**：用 conftest.py 中的 fixture，fixture 的 teardown 会自动清理
  - **方式 B（独立测试时）**：测试方法体最后一行手动 DELETE 资源，断言用白名单 `(200, 204, 404)`
- 负向测试方法（资源根本没创建成功）无需清理

### 断言规则

#### A级 — 所有接口必须有
- 状态码断言：`assert resp.status_code == 200`（正向）或 `assert resp.status_code in [400, 422]`（负向）
- 响应结构断言：根据端点的 responses 中的 response_schema，验证关键字段存在
  ```python
  data = resp.json()
  assert "data" in data
  ```

#### B级 — 正向用例必须有（在 A级 基础上追加）
- 响应类型断言：从 response_schema 推断类型
  ```python
  result = data["data"]
  assert isinstance(result, list)  # 列表接口
  assert isinstance(result, dict)  # 详情接口
  ```
- 请求-响应一致性断言：POST/PUT 请求体中的值应在响应中回显
  ```python
  resp = api_client.post("/api/users", json={{"name": "test_user"}})
  created = resp.json()["data"]
  assert created["name"] == "test_user"
  ```
- 列表接口的元素断言：
  ```python
  if len(result) > 0:
      assert "id" in result[0]
  ```

#### C级 — 依赖链必须有（在 A/B级 基础上追加）
- 引用完整性断言：查询返回的 ID 应与创建时一致
  ```python
  assert detail["id"] == created_resource
  ```
- 数据一致性断言：创建时的字段值在后续查询中应保持一致
  ```python
  assert detail["name"] == "test_resource"
  ```
- 更新后验证：更新操作后响应应反映新值
  ```python
  assert updated["name"] == "updated_name"
  ```

#### 断言禁止事项
- 禁止自定义 validate_xxx / assert_xxx 工具函数
- 禁止 `assert resp is not None`（无意义）
- 禁止只断言状态码不验证响应内容（DELETE 等无响应体的接口除外）
- fixture 中 return 前必须有 assert 验证有效性

## 输出格式

严格按以下 JSON 格式返回，不要在 JSON 外添加任何 markdown 标记或说明文字：

**当有依赖关系时**，scripts 数组需同时包含 conftest.py（业务 fixture 共享层）和 test_xxx.py（测试类）两个 entry：

```json
{{
  "scripts": [
    {{
      "script_name": "conftest.py",
      "file_path": "testcases/conftest.py",
      "script_content": "包含所有业务 fixture 的 conftest.py 内容",
      "test_case_ids": [],
      "framework": "pytest",
      "dependencies": ["pytest"],
      "execution_order": 0
    }},
    {{
      "script_name": "test_模块名.py",
      "file_path": "testcases/test_模块名.py",
      "script_content": "仅含测试类和测试方法，不重复定义 fixture",
      "test_case_ids": ["测试用例ID列表"],
      "framework": "pytest",
      "dependencies": ["pytest"],
      "execution_order": 1
    }}
  ],
  "confidence_score": 0.9,
  "generation_method": "intelligent"
}}
```

**当无依赖关系时**（dependencies 为空），只输出 test_xxx.py 一个 entry，POST/PUT/PATCH 正向测试方法体末尾自带 DELETE 清理。

## 最终检查

输出前逐条验证：
1. script_content 中没有 `import requests`
2. script_content 中没有 `API_BASE_URL` 或 `base_url =`
3. script_content 中没有自定义 api_client fixture
4. test 文件 script_content 中有 `pytestmark = [`
5. 所有变量名不含连字符 `-`
6. file_path 以 `testcases/` 开头
7. 每个正向用例有响应内容断言
8. 每个 fixture 在 yield/return 前有 assert
9. **若 dependencies 非空**：业务 fixture 必须在 conftest.py 中定义，test 文件不重复定义同名 fixture
10. **若 dependencies 非空**：fixture 用 `yield` 而非 `return`，yield 后有 teardown 清理代码
11. **teardown 中 DELETE** 的状态码断言用白名单 `(200, 204, 404)`，禁止只断言 `== 200`
12. **POST/PUT/PATCH 正向测试方法**（独立、无 fixture 链场景）末尾必须显式 DELETE 清理
如有任何一条不满足，修正后再输出。"""


# ============================================================================
# 日志记录相关消息类型
# ============================================================================

class LogRecordRequest(BaseModel):
    """日志记录请求"""
    session_id: str = Field(..., description="会话ID")
    source: str = Field(..., description="日志来源（智能体名称）")
    level: LogLevel = Field(LogLevel.INFO, description="日志级别")
    message: str = Field(..., description="日志消息")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")

    # 可选的扩展字段
    request_id: Optional[str] = Field(None, description="请求ID")
    user_id: Optional[str] = Field(None, description="用户ID")
    operation: Optional[str] = Field(None, description="操作类型")
    execution_time: Optional[float] = Field(None, description="执行时间")
    memory_usage: Optional[float] = Field(None, description="内存使用")
    cpu_usage: Optional[float] = Field(None, description="CPU使用")
    error_code: Optional[str] = Field(None, description="错误代码")
    error_type: Optional[str] = Field(None, description="错误类型")
    stack_trace: Optional[str] = Field(None, description="堆栈跟踪")
    tags: List[str] = Field(default_factory=list, description="标签")
    category: Optional[str] = Field(None, description="分类")


class LogRecordResponse(BaseModel):
    """日志记录响应"""
    session_id: str = Field(..., description="会话ID")
    log_id: str = Field(..., description="日志ID")
    status: str = Field(..., description="记录状态")
    timestamp: datetime = Field(..., description="时间戳")


class TaskStatusUpdateRequest(BaseModel):
    """任务状态更新请求"""
    session_id: str = Field(..., description="会话ID")
    interface_id: str = Field(..., description="接口ID")
    status: TaskStatus = Field(..., description="任务状态")
    progress: float = Field(0.0, description="进度百分比")
    current_step: str = Field("", description="当前步骤")
    error_message: Optional[str] = Field(None, description="错误信息")
    result_data: Dict[str, Any] = Field(default_factory=dict, description="结果数据")


class TaskStatusUpdateResponse(BaseModel):
    """任务状态更新响应"""
    session_id: str = Field(..., description="会话ID")
    interface_id: str = Field(..., description="接口ID")
    status: TaskStatus = Field(..., description="任务状态")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


# ============================================================================
# 场景测试用例（chain-style）- 非破坏式扩展
# 对应预分析依赖 JSON（如 asset-management-dependencies.json）里的 chains[].steps[]，
# 让 ScriptGeneratorAgent 走"模板渲染"分支生成多步骤测试方法，绕过 LLM。
# ============================================================================

class ScenarioStepSpec(BaseModel):
    """场景内的单个步骤 — 对应依赖 JSON 中 chains[].steps[]"""
    step: int = Field(..., description="步骤序号（从 1 开始）")
    purpose: str = Field("", description="步骤目的（中文描述）")
    method: HttpMethod = Field(..., description="HTTP 方法")
    path: str = Field(..., description="API 路径（含 :id 或 {id} 路径参数）")
    path_params: Dict[str, Any] = Field(default_factory=dict, description="路径参数 {var_name: example_value}")
    query: Dict[str, Any] = Field(default_factory=dict, description="query 参数模板")
    body: Union[Dict[str, Any], str] = Field(default_factory=dict, description="请求体模板（dict 或纯字符串）")
    body_shape: List[str] = Field(default_factory=list, description="bodyShape 标识（区分同 path 的多变体）")
    response_example: Dict[str, Any] = Field(default_factory=dict, description="响应示例（用于生成默认断言）")
    # 形如 {"asset_type": {"from": "step:1.dataOut.asset_type", "optional": false, "template": null}}
    data_in: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="入参引用 → 前序步骤 dataOut")
    # 形如 {"newAssetId": {"path": "response.data", "exampleValue": "..."}}
    data_out: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="出参提取规则")
    # 形如 {"find"|"notFind"|"every"|"equals": {"in": "response.data.list[]._id", "equalsRef": "step:4.dataOut.newAssetId"}}
    assert_spec: Optional[Dict[str, Any]] = Field(None, description="断言规格")
    depends_on: List[int] = Field(default_factory=list, description="依赖的前序步骤 step 序号")
    related_endpoint_id: Optional[str] = Field(None, description="关联的 ParsedEndpoint.endpoint_id")
    related_test_case_id: Optional[str] = Field(None, description="关联的 GeneratedTestCase.test_case_id")
    expected_status: int = Field(200, description="期望的 HTTP 状态码（来自依赖 JSON 的 endpoint.response.status，默认 200）")


class ScenarioTestCase(BaseModel):
    """场景测试用例 — 一个 chain ⇒ 一个测试方法"""
    scenario_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="场景ID")
    name: str = Field(..., description="场景名称（来自 chain.name）")
    description: str = Field("", description="场景描述")
    steps: List[ScenarioStepSpec] = Field(default_factory=list, description="顺序步骤列表")
    tags: List[str] = Field(default_factory=list, description="标签（用于 pytest mark）")
    primary_endpoint_id: Optional[str] = Field(None, description="主端点ID（用于 TestCase 入库时挂载）")
    en_slug: Optional[str] = Field(None, description="英文 snake_case slug，用于脚本文件名（来自用户输入的 LLM 翻译）")


# 解析 ScriptGenerationInput / ScriptPersistenceInput 上的前向引用 "ScenarioTestCase"
ScriptGenerationInput.model_rebuild()
ScriptPersistenceInput.model_rebuild()
