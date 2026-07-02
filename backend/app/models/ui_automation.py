"""
UI 自动化相关数据模型（一期）

零回归红线：
- 所有 UI 自动化表以 ui_ 前缀命名，与 API 自动化表（test_scripts/test_cases 等）物理隔离。
- 不与 api_automation.py 中模型建立外键。
- 提供独立的 _ensure_migration_ui_automation_tables() 幂等迁移函数。
"""
from tortoise.models import Model
from tortoise import fields

from app.models.base import BaseModel, TimestampMixin


class UiPageAnalysisResult(BaseModel, TimestampMixin):
    """页面分析结果（截图/文本输入 → AI 分析输出）"""
    analysis_id = fields.CharField(max_length=100, unique=True, description="分析ID", index=True)
    session_id = fields.CharField(max_length=100, description="会话ID", index=True)

    source_type = fields.CharField(max_length=20, description="来源类型: screenshot/text/url")
    source_path = fields.CharField(max_length=500, default="", description="截图路径或URL")
    user_description = fields.TextField(default="", description="用户输入的测试需求描述")

    page_type = fields.CharField(max_length=50, default="", description="识别到的页面类型")
    page_summary = fields.TextField(default="", description="页面说明")
    raw_response = fields.JSONField(default=dict, description="多模态模型原始响应")
    elements = fields.JSONField(default=list, description="识别到的元素清单（结构化）")
    suggested_steps = fields.JSONField(default=list, description="建议的测试步骤")

    from_fallback = fields.BooleanField(default=False, description="是否走了降级路径")
    model_name = fields.CharField(max_length=100, default="", description="使用的模型")

    status = fields.CharField(max_length=20, default="success", description="success/failed")
    error_message = fields.TextField(default="", description="失败原因")

    class Meta:
        table = "ui_page_analysis_results"


class UiPageElement(BaseModel, TimestampMixin):
    """页面元素（视觉模型识别后的结构化拆解）

    与 ui_page_analysis_results.elements JSON 字段并存：
    - JSON 字段保留原始快照，避免反序列化
    - 本表用于按元素 ID/选择器查询、跨页面复用、生成脚本时定位
    通过 analysis_id 关联，不走外键以维持模块物理隔离。
    """
    element_id = fields.CharField(max_length=100, unique=True, description="元素ID", index=True)
    analysis_id = fields.CharField(max_length=100, description="关联分析ID", index=True)

    element_type = fields.CharField(max_length=30, description="button/input/link/text/image/select/...")
    name = fields.CharField(max_length=200, default="", description="元素名称（如按钮文案/输入框 placeholder）")

    selector = fields.CharField(max_length=500, default="", description="主选择器（CSS/XPath/accessibility）")
    selector_type = fields.CharField(max_length=20, default="css", description="css/xpath/role/text")
    fallback_selectors = fields.JSONField(default=list, description="备用选择器列表（容错用）")

    text_content = fields.TextField(default="", description="显示文本")
    attributes = fields.JSONField(default=dict, description="HTML 属性（class/id/role/aria-*/...）")
    bbox = fields.JSONField(default=dict, description="边界框 {x,y,width,height}（多模态视觉定位）")

    order_index = fields.IntField(default=0, description="在页面中的视觉顺序")
    confidence = fields.FloatField(default=1.0, description="识别置信度 0~1")
    interactive = fields.BooleanField(default=False, description="是否可交互")

    class Meta:
        table = "ui_page_elements"


class UiTestScript(BaseModel, TimestampMixin):
    """UI 测试脚本"""
    script_id = fields.CharField(max_length=100, unique=True, description="脚本ID", index=True)
    analysis_id = fields.CharField(max_length=100, default="", description="关联分析ID", index=True)

    name = fields.CharField(max_length=200, description="脚本名称")
    description = fields.TextField(default="", description="脚本描述")
    script_type = fields.CharField(max_length=20, default="playwright", description="playwright/yaml")
    source_type = fields.CharField(max_length=20, default="manual", description="screenshot/text/manual")

    content = fields.TextField(description="脚本内容")
    file_path = fields.CharField(max_length=500, default="", description="脚本相对路径（相对 UI_AUTOMATION_WORKSPACE）")
    tags = fields.JSONField(default=list, description="标签")

    status = fields.CharField(max_length=20, default="draft", description="draft/active/disabled")
    base_url = fields.CharField(max_length=500, default="", description="脚本默认 base_url")

    created_by = fields.CharField(max_length=100, default="", description="创建人")
    category = fields.ForeignKeyField(
        "models.UiTestCaseCategory", null=True, related_name="scripts",
        description="所属分类",
    )

    # 最近一次执行结果（用于脚本管理列表快速展示）—— 每次执行完由 data_persistence_agent 更新
    last_execution_status = fields.CharField(
        max_length=20, default="",
        description="最近一次执行状态: success/failed/timeout/error/interrupted/cancelled"
    )
    last_execution_time = fields.DatetimeField(null=True, description="最近一次执行时间")
    last_execution_id = fields.CharField(
        max_length=100, default="",
        description="最近一次执行的 execution_id（跳转详情用）"
    )

    class Meta:
        table = "ui_test_scripts"


class UiTestCaseCategory(BaseModel, TimestampMixin):
    """UI 自动化用例分类树 —— 自引用树形结构，按系统分组展示脚本"""
    category_id = fields.CharField(max_length=100, unique=True, description="分类ID", index=True)
    name = fields.CharField(max_length=200, description="分类名称")
    parent = fields.ForeignKeyField(
        "models.UiTestCaseCategory", null=True, related_name="children",
        description="父节点",
    )
    sort_order = fields.IntField(default=0, description="同级排序")
    level = fields.IntField(default=0, description="层级深度")
    description = fields.TextField(default="", description="描述")
    is_active = fields.BooleanField(default=True, description="是否激活")
    match_rule = fields.CharField(max_length=500, null=True, default=None, description="匹配规则(glob)")

    class Meta:
        table = "ui_testcase_categories"


class UiScriptExecution(BaseModel, TimestampMixin):
    """UI 脚本执行记录"""
    execution_id = fields.CharField(max_length=100, unique=True, description="执行ID", index=True)
    script_id = fields.CharField(max_length=100, description="关联脚本ID", index=True)

    status = fields.CharField(max_length=20, default="pending",
                              description="pending/running/success/failed/timeout/cancelled/interrupted")
    start_time = fields.DatetimeField(null=True, description="开始时间")
    end_time = fields.DatetimeField(null=True, description="结束时间")
    duration_ms = fields.IntField(default=0, description="耗时（毫秒）")
    exit_code = fields.IntField(null=True, description="进程退出码")

    stdout = fields.TextField(default="", description="标准输出")
    stderr = fields.TextField(default="", description="错误输出")
    error_message = fields.TextField(default="", description="错误信息（简短）")

    execution_config = fields.JSONField(default=dict, description="执行配置（环境/超时/录像等）")
    artifact_summary = fields.JSONField(default=dict, description="产物汇总（路径/大小）")

    triggered_by = fields.CharField(max_length=100, default="", description="触发人")

    # 批次关联:空字符串=单独执行,有值=属于某个批次
    batch_id = fields.CharField(max_length=100, default="", description="关联批次ID(空=单独执行)", index=True)

    class Meta:
        table = "ui_script_executions"


class UiTestReport(BaseModel, TimestampMixin):
    """UI 测试报告（HTML 报告归档）"""
    report_id = fields.CharField(max_length=100, unique=True, description="报告ID", index=True)
    execution_id = fields.CharField(max_length=100, description="执行ID", index=True)
    script_id = fields.CharField(max_length=100, description="脚本ID", index=True)

    report_type = fields.CharField(max_length=20, default="playwright", description="playwright/midscene")
    report_url = fields.CharField(max_length=500, default="", description="报告访问 URL（前端 iframe 加载）")
    report_path = fields.CharField(max_length=500, default="", description="报告文件磁盘路径")

    # Allure 报告字段：按需触发生成（前端按钮）
    # 状态机：not_generated → generating → ready / failed → generating (重试) → ...
    allure_report_url = fields.CharField(max_length=500, null=True, description="Allure 报告 URL（按需生成）")
    allure_status = fields.CharField(
        max_length=20, default="not_generated",
        description="not_generated/generating/ready/failed"
    )
    allure_generated_at = fields.DatetimeField(null=True, description="最近一次成功生成时间")
    allure_error = fields.TextField(default="", description="失败原因（截断）")

    summary = fields.JSONField(default=dict, description="报告汇总（用例数/通过数/失败数）")
    passed = fields.IntField(default=0)
    failed = fields.IntField(default=0)
    skipped = fields.IntField(default=0)

    class Meta:
        table = "ui_test_reports"


class UiExecutionArtifact(BaseModel, TimestampMixin):
    """执行产物（截图/视频/trace/日志）"""
    artifact_id = fields.CharField(max_length=100, unique=True, description="产物ID", index=True)
    execution_id = fields.CharField(max_length=100, description="执行ID", index=True)

    artifact_type = fields.CharField(max_length=30, description="screenshot/video/trace/html_report/log")
    file_path = fields.CharField(max_length=500, description="磁盘绝对路径")
    file_url = fields.CharField(max_length=500, default="", description="对外访问 URL")
    file_size = fields.IntField(default=0, description="文件大小（字节）")
    expires_at = fields.DatetimeField(null=True, description="过期时间（清理任务参考）")

    class Meta:
        table = "ui_execution_artifacts"


class UiBatchExecution(BaseModel, TimestampMixin):
    """UI 批量执行记录 — 将多个脚本执行归入一个批次"""
    batch_id = fields.CharField(max_length=100, unique=True, description="批次ID", index=True)

    name = fields.CharField(max_length=200, default="", description="批次名称")
    status = fields.CharField(
        max_length=20, default="pending",
        description="pending/running/completed/partial_failed/cancelled/error"
    )

    # 汇总统计(实时更新)
    total_scripts = fields.IntField(default=0, description="批次内脚本总数")
    completed_count = fields.IntField(default=0, description="已完成数(success+failed+timeout)")
    success_count = fields.IntField(default=0)
    failed_count = fields.IntField(default=0)
    timeout_count = fields.IntField(default=0)
    cancelled_count = fields.IntField(default=0)
    safety_blocked_count = fields.IntField(default=0)

    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    duration_ms = fields.IntField(default=0)

    triggered_by = fields.CharField(max_length=100, default="")

    # 对标 UiScriptExecution.execution_config:
    # POST /batches 时存入 {script_ids, timeout_seconds, extra_env, session_id},
    # _kickoff_batch_execution 从 DB 读出后还原 UiBatchExecutionInput
    execution_config = fields.JSONField(default=dict, description="批次配置(script_ids/session_id/超时等)")
    error_message = fields.TextField(default="", description="错误信息（简短）")

    # Allure 批次汇总报告字段：按需触发，逻辑同 UiTestReport.allure_*
    batch_allure_report_url = fields.CharField(max_length=500, null=True, description="批次级 Allure 汇总报告 URL")
    batch_allure_status = fields.CharField(
        max_length=20, default="not_generated",
        description="not_generated/generating/ready/failed"
    )
    batch_allure_generated_at = fields.DatetimeField(null=True, description="最近一次成功生成时间")
    batch_allure_error = fields.TextField(default="", description="失败原因（截断）")

    class Meta:
        table = "ui_batch_executions"


class UiRecordingSession(BaseModel, TimestampMixin):
    """录制会话（Playwright codegen / Test Agents 共用）

    流程：
    1. 用户在前端发起录制 → 后端起 playwright codegen 子进程 → 弹出浏览器
    2. 用户在浏览器中操作 → 关闭后子进程退出，原始脚本落到 raw_script_path
    3. AI 后处理（注入 fixture 头、改裸 selector、加注释）→ 写入 generated_ui_tests/scripts/
    4. 落 UiTestScript（source_type="recorded"），final_script_id 反向关联
    """
    session_id = fields.CharField(max_length=100, unique=True, description="录制会话ID(uuid)", index=True)
    name = fields.CharField(max_length=200, description="录制名称(同时作为脚本文件名)")
    source = fields.CharField(max_length=20, default="codegen", description="codegen / test_agents")
    target_url = fields.CharField(max_length=500, description="录制目标 URL")
    storage_state_path = fields.CharField(max_length=500, default="", description="登录态文件相对路径(.auth/user.json)")

    status = fields.CharField(
        max_length=20, default="idle",
        description="idle/recording/postprocessing/ready/failed/cancelled",
        index=True,
    )
    raw_script_path = fields.CharField(max_length=500, default="", description="录制原始脚本相对路径")
    final_script_id = fields.CharField(max_length=100, default="", description="关联 ui_test_scripts.script_id", index=True)

    duration_ms = fields.IntField(default=0, description="录制耗时(关闭窗口前)毫秒")
    error_message = fields.TextField(default="", description="失败原因")

    # 预留 test_agents 方案用：plan_markdown / goal_description / plan_approved_at
    metadata = fields.JSONField(default=dict, description="附加元数据(test_agents 阶段会扩展)")

    created_by = fields.CharField(max_length=100, default="", description="发起人")

    class Meta:
        table = "ui_recording_sessions"


class UiImageLibrary(BaseModel, TimestampMixin):
    """图片库（截图复用资源池）

    设计目标：
    - 把上传的截图作为独立资源管理，供"页面分析/脚本生成"等场景跨次复用
    - SHA256 查重：同图二次上传命中已有记录，不重复落盘
    - reference_count 防止误删被引用的图片
    - 与 ui_page_analysis_results.source_path 双轨并存：旧分析继续走文件路径，新分析可走 image_id
    """
    image_id = fields.CharField(max_length=100, unique=True, description="图片ID(uuid)", index=True)
    sha256 = fields.CharField(max_length=64, unique=True, description="文件 SHA256(查重)", index=True)

    original_name = fields.CharField(max_length=255, default="", description="用户上传时的原始文件名")
    file_path = fields.CharField(max_length=500, description="磁盘绝对路径")
    thumbnail_path = fields.CharField(max_length=500, default="", description="缩略图路径(320x240)")
    file_size = fields.IntField(default=0, description="文件大小(字节)")
    mime_type = fields.CharField(max_length=50, default="image/png", description="MIME 类型")

    width = fields.IntField(default=0, description="原图宽度")
    height = fields.IntField(default=0, description="原图高度")

    title = fields.CharField(max_length=200, default="", description="用户标题(可选)")
    description = fields.TextField(default="", description="用户描述(可选)")
    tags = fields.JSONField(default=list, description="标签列表")
    page_type = fields.CharField(max_length=50, default="", description="页面类型(用于筛选)", index=True)

    reference_count = fields.IntField(default=0, description="被分析任务引用次数")
    last_used_at = fields.DatetimeField(null=True, description="最近被引用时间")

    uploaded_by = fields.CharField(max_length=100, default="", description="上传人")

    # 预留扩展：后续接视觉 embedding 时挂 Chroma 等向量库的 ID
    embedding_id = fields.CharField(max_length=100, default="", description="向量索引ID(预留)")

    class Meta:
        table = "ui_image_library"


async def _ensure_migration_ui_testcase_categories():
    """免删库增量迁移：创建 ui_testcase_categories 表 + ui_test_scripts.category_id 列（幂等）"""
    from tortoise import connections
    conn = connections.get("default")

    # 1. 建表
    try:
        await conn.execute_script("""CREATE TABLE IF NOT EXISTS ui_testcase_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id VARCHAR(100) NOT NULL UNIQUE,
            name VARCHAR(200) NOT NULL,
            parent_id INTEGER REFERENCES ui_testcase_categories(id),
            sort_order INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            match_rule VARCHAR(500),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
    except Exception as e:
        raise

    # 2. 加列（幂等）
    try:
        await conn.execute_script(
            "ALTER TABLE ui_test_scripts ADD COLUMN category_id INTEGER REFERENCES ui_testcase_categories(id)"
        )
    except Exception as e:
        if "duplicate column" not in str(e).lower() and "duplicate column name" not in str(e).lower():
            raise


async def _ensure_migration_ui_automation_tables():
    """免删库增量迁移：建立 UI 自动化相关表（幂等）

    零回归保障：
    - 仅 CREATE TABLE IF NOT EXISTS，不动任何已有表
    - 表名全部 ui_ 前缀，与 API 自动化表无冲突
    """
    from tortoise import connections
    conn = connections.get("default")

    ddl_statements = [
        """CREATE TABLE IF NOT EXISTS ui_page_analysis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id VARCHAR(100) NOT NULL UNIQUE,
            session_id VARCHAR(100) NOT NULL,
            source_type VARCHAR(20) NOT NULL,
            source_path VARCHAR(500) NOT NULL DEFAULT '',
            user_description TEXT NOT NULL DEFAULT '',
            page_type VARCHAR(50) NOT NULL DEFAULT '',
            page_summary TEXT NOT NULL DEFAULT '',
            raw_response TEXT NOT NULL DEFAULT '{}',
            elements TEXT NOT NULL DEFAULT '[]',
            suggested_steps TEXT NOT NULL DEFAULT '[]',
            from_fallback INTEGER NOT NULL DEFAULT 0,
            model_name VARCHAR(100) NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'success',
            error_message TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_page_analysis_session ON ui_page_analysis_results (session_id)",

        """CREATE TABLE IF NOT EXISTS ui_page_elements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            element_id VARCHAR(100) NOT NULL UNIQUE,
            analysis_id VARCHAR(100) NOT NULL,
            element_type VARCHAR(30) NOT NULL,
            name VARCHAR(200) NOT NULL DEFAULT '',
            selector VARCHAR(500) NOT NULL DEFAULT '',
            selector_type VARCHAR(20) NOT NULL DEFAULT 'css',
            fallback_selectors TEXT NOT NULL DEFAULT '[]',
            text_content TEXT NOT NULL DEFAULT '',
            attributes TEXT NOT NULL DEFAULT '{}',
            bbox TEXT NOT NULL DEFAULT '{}',
            order_index INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 1.0,
            interactive INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_page_elements_analysis ON ui_page_elements (analysis_id)",
        "CREATE INDEX IF NOT EXISTS idx_ui_page_elements_type ON ui_page_elements (element_type)",

        """CREATE TABLE IF NOT EXISTS ui_test_scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id VARCHAR(100) NOT NULL UNIQUE,
            analysis_id VARCHAR(100) NOT NULL DEFAULT '',
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            script_type VARCHAR(20) NOT NULL DEFAULT 'playwright',
            source_type VARCHAR(20) NOT NULL DEFAULT 'manual',
            content TEXT NOT NULL,
            file_path VARCHAR(500) NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            base_url VARCHAR(500) NOT NULL DEFAULT '',
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_test_scripts_analysis ON ui_test_scripts (analysis_id)",

        """CREATE TABLE IF NOT EXISTS ui_script_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id VARCHAR(100) NOT NULL UNIQUE,
            script_id VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            exit_code INTEGER,
            stdout TEXT NOT NULL DEFAULT '',
            stderr TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            execution_config TEXT NOT NULL DEFAULT '{}',
            artifact_summary TEXT NOT NULL DEFAULT '{}',
            triggered_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_script_executions_script ON ui_script_executions (script_id)",

        """CREATE TABLE IF NOT EXISTS ui_test_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id VARCHAR(100) NOT NULL UNIQUE,
            execution_id VARCHAR(100) NOT NULL,
            script_id VARCHAR(100) NOT NULL,
            report_type VARCHAR(20) NOT NULL DEFAULT 'playwright',
            report_url VARCHAR(500) NOT NULL DEFAULT '',
            report_path VARCHAR(500) NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '{}',
            passed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_test_reports_execution ON ui_test_reports (execution_id)",

        """CREATE TABLE IF NOT EXISTS ui_execution_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id VARCHAR(100) NOT NULL UNIQUE,
            execution_id VARCHAR(100) NOT NULL,
            artifact_type VARCHAR(30) NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            file_url VARCHAR(500) NOT NULL DEFAULT '',
            file_size INTEGER NOT NULL DEFAULT 0,
            expires_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_execution_artifacts_exec ON ui_execution_artifacts (execution_id)",

        """CREATE TABLE IF NOT EXISTS ui_image_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id VARCHAR(100) NOT NULL UNIQUE,
            sha256 VARCHAR(64) NOT NULL UNIQUE,
            original_name VARCHAR(255) NOT NULL DEFAULT '',
            file_path VARCHAR(500) NOT NULL,
            thumbnail_path VARCHAR(500) NOT NULL DEFAULT '',
            file_size INTEGER NOT NULL DEFAULT 0,
            mime_type VARCHAR(50) NOT NULL DEFAULT 'image/png',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            title VARCHAR(200) NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            page_type VARCHAR(50) NOT NULL DEFAULT '',
            reference_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMP,
            uploaded_by VARCHAR(100) NOT NULL DEFAULT '',
            embedding_id VARCHAR(100) NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_image_library_sha256 ON ui_image_library (sha256)",
        "CREATE INDEX IF NOT EXISTS idx_ui_image_library_page_type ON ui_image_library (page_type)",
        "CREATE INDEX IF NOT EXISTS idx_ui_image_library_last_used ON ui_image_library (last_used_at)",

        """CREATE TABLE IF NOT EXISTS ui_recording_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(100) NOT NULL UNIQUE,
            name VARCHAR(200) NOT NULL,
            source VARCHAR(20) NOT NULL DEFAULT 'codegen',
            target_url VARCHAR(500) NOT NULL,
            storage_state_path VARCHAR(500) NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'idle',
            raw_script_path VARCHAR(500) NOT NULL DEFAULT '',
            final_script_id VARCHAR(100) NOT NULL DEFAULT '',
            duration_ms INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_by VARCHAR(100) NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_recording_sessions_status ON ui_recording_sessions (status)",
        "CREATE INDEX IF NOT EXISTS idx_ui_recording_sessions_final_script ON ui_recording_sessions (final_script_id)",

        # ====================================================================
        # 批次执行相关
        # ====================================================================
        """CREATE TABLE IF NOT EXISTS ui_batch_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id VARCHAR(100) NOT NULL UNIQUE,
            name VARCHAR(200) NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            total_scripts INTEGER NOT NULL DEFAULT 0,
            completed_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            timeout_count INTEGER NOT NULL DEFAULT 0,
            cancelled_count INTEGER NOT NULL DEFAULT 0,
            safety_blocked_count INTEGER NOT NULL DEFAULT 0,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            triggered_by VARCHAR(100) NOT NULL DEFAULT '',
            execution_config TEXT NOT NULL DEFAULT '{}',
            error_message TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ui_batch_exec_status ON ui_batch_executions (status)",
        "ALTER TABLE ui_script_executions ADD COLUMN batch_id VARCHAR(100) NOT NULL DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS idx_ui_script_exec_batch ON ui_script_executions (batch_id)",
    ]

    for ddl in ddl_statements:
        try:
            await conn.execute_script(ddl)
        except Exception as ddl_err:
            # ALTER TABLE ADD COLUMN 在列已存在时会抛 duplicate column,
            # SQLite 不支持 IF NOT EXISTS 语法, 幂等处理
            err_msg = str(ddl_err).lower()
            if "duplicate column" in err_msg or "duplicate column name" in err_msg:
                pass
            else:
                raise


async def _ensure_migration_ui_allure_fields():
    """免删库增量迁移：UiTestReport / UiBatchExecution 加 Allure 相关字段。

    幂等：每列单独 SELECT 探测，存在则跳过；不存在才 ALTER TABLE ADD COLUMN。
    """
    from tortoise import connections
    conn = connections.get("default")

    migrations = [
        # ui_test_reports
        ("ui_test_reports", "allure_report_url",
         "ALTER TABLE ui_test_reports ADD COLUMN allure_report_url VARCHAR(500)"),
        ("ui_test_reports", "allure_status",
         "ALTER TABLE ui_test_reports ADD COLUMN allure_status VARCHAR(20) NOT NULL DEFAULT 'not_generated'"),
        ("ui_test_reports", "allure_generated_at",
         "ALTER TABLE ui_test_reports ADD COLUMN allure_generated_at TIMESTAMP"),
        ("ui_test_reports", "allure_error",
         "ALTER TABLE ui_test_reports ADD COLUMN allure_error TEXT NOT NULL DEFAULT ''"),
        # ui_batch_executions
        ("ui_batch_executions", "batch_allure_report_url",
         "ALTER TABLE ui_batch_executions ADD COLUMN batch_allure_report_url VARCHAR(500)"),
        ("ui_batch_executions", "batch_allure_status",
         "ALTER TABLE ui_batch_executions ADD COLUMN batch_allure_status VARCHAR(20) NOT NULL DEFAULT 'not_generated'"),
        ("ui_batch_executions", "batch_allure_generated_at",
         "ALTER TABLE ui_batch_executions ADD COLUMN batch_allure_generated_at TIMESTAMP"),
        ("ui_batch_executions", "batch_allure_error",
         "ALTER TABLE ui_batch_executions ADD COLUMN batch_allure_error TEXT NOT NULL DEFAULT ''"),
    ]

    for table, column, ddl in migrations:
        try:
            await conn.execute_query(f"SELECT {column} FROM {table} LIMIT 1")
        except Exception:
            await conn.execute_script(ddl)


async def _ensure_migration_ui_script_last_execution():
    """免删库增量迁移：UiTestScript 加 last_execution_* 3 字段。

    用于脚本管理列表快速展示最近一次执行结果（避免每行都反查 UiScriptExecution）。
    """
    from tortoise import connections
    conn = connections.get("default")

    migrations = [
        ("ui_test_scripts", "last_execution_status",
         "ALTER TABLE ui_test_scripts ADD COLUMN last_execution_status VARCHAR(20) NOT NULL DEFAULT ''"),
        ("ui_test_scripts", "last_execution_time",
         "ALTER TABLE ui_test_scripts ADD COLUMN last_execution_time TIMESTAMP"),
        ("ui_test_scripts", "last_execution_id",
         "ALTER TABLE ui_test_scripts ADD COLUMN last_execution_id VARCHAR(100) NOT NULL DEFAULT ''"),
    ]

    for table, column, ddl in migrations:
        try:
            await conn.execute_query(f"SELECT {column} FROM {table} LIMIT 1")
        except Exception:
            await conn.execute_script(ddl)
