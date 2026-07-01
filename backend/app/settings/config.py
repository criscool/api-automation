import os
import typing

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # pydantic-settings v2: 必须显式声明才会去读 .env;
    # 没声明的话只读 os.environ,.env 里写的 DOUBAO_* / UI_MIDSCENE_* / UI_* 全部失效。
    # 用绝对路径,避免后端 cwd 不在 backend/ 时找不到 .env。
    model_config = SettingsConfigDict(
        env_file=os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)),
            ".env",
        ),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    VERSION: str = "0.1.0"
    APP_TITLE: str = "Vue FastAPI Admin"
    PROJECT_NAME: str = "Vue FastAPI Admin"
    APP_DESCRIPTION: str = "Description"

    CORS_ORIGINS: typing.List = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: typing.List = ["*"]
    CORS_ALLOW_HEADERS: typing.List = ["*"]

    DEBUG: bool = True

    PROJECT_ROOT: str = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    BASE_DIR: str = os.path.abspath(os.path.join(PROJECT_ROOT, os.pardir))
    LOGS_ROOT: str = os.path.join(BASE_DIR, "app/logs")
    SECRET_KEY: str = "3488a63e1765035d386f05409663f55c83bfae3b3c61a932744b20ad14244dcf"  # openssl rand -hex 32
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 day
    TORTOISE_ORM: dict = {
        "connections": {
            # SQLite configuration
            "default": {
                "engine": "tortoise.backends.sqlite",
                "credentials": {"file_path": f"{BASE_DIR}/db.sqlite3"},  # Path to SQLite database file
            },
            # MySQL/MariaDB configuration
            # Install with: tortoise-orm[asyncmy]
            # "mysql": {
            #     "engine": "tortoise.backends.mysql",
            #     "credentials": {
            #         "host": "localhost",  # Database host address
            #         "port": 3306,  # Database port
            #         "user": "yourusername",  # Database username
            #         "password": "yourpassword",  # Database password
            #         "database": "yourdatabase",  # Database name
            #     },
            # },
            # PostgreSQL configuration
            # Install with: tortoise-orm[asyncpg]
            # "postgres": {
            #     "engine": "tortoise.backends.asyncpg",
            #     "credentials": {
            #         "host": "localhost",  # Database host address
            #         "port": 5432,  # Database port
            #         "user": "yourusername",  # Database username
            #         "password": "yourpassword",  # Database password
            #         "database": "yourdatabase",  # Database name
            #     },
            # },
            # MSSQL/Oracle configuration
            # Install with: tortoise-orm[asyncodbc]
            # "oracle": {
            #     "engine": "tortoise.backends.asyncodbc",
            #     "credentials": {
            #         "host": "localhost",  # Database host address
            #         "port": 1433,  # Database port
            #         "user": "yourusername",  # Database username
            #         "password": "yourpassword",  # Database password
            #         "database": "yourdatabase",  # Database name
            #     },
            # },
            # SQLServer configuration
            # Install with: tortoise-orm[asyncodbc]
            # "sqlserver": {
            #     "engine": "tortoise.backends.asyncodbc",
            #     "credentials": {
            #         "host": "localhost",  # Database host address
            #         "port": 1433,  # Database port
            #         "user": "yourusername",  # Database username
            #         "password": "yourpassword",  # Database password
            #         "database": "yourdatabase",  # Database name
            #     },
            # },
        },
        "apps": {
            "models": {
                "models": ["app.models", "app.models.api_automation", "app.models.ui_automation", "aerich.models"],
                "default_connection": "default",
            },
        },
        "use_tz": False,  # Whether to use timezone-aware datetimes
        "timezone": "Asia/Shanghai",  # Timezone setting
    }
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # ============================================================
    # UI 自动化模块配置（追加，不影响现有 API 自动化）
    # 零回归红线：UI_AUTOMATION_ENABLED=False 时整个模块停用
    # ============================================================
    UI_AUTOMATION_ENABLED: bool = True
    UI_AUTOMATION_WORKSPACE: str = os.path.join(BASE_DIR, "generated_ui_tests")
    UI_ARTIFACT_DIR: str = os.path.join(BASE_DIR, "generated_ui_tests", "reports")
    UI_PLAYWRIGHT_TIMEOUT: int = 120  # 单个 test 用例的超时（秒），透传给 playwright.config.ts 的 timeout
    # 整个 `npx playwright test` 子进程的总超时（秒），用于 Popen.communicate(timeout=...)。
    # 必须 >= setup 用例 + 所有业务 test 之和 + npm/Node 启动 overhead；
    # 默认 600s 对应 setup 最坏 3 分钟 + 业务 5 分钟 + 启动 1 分钟，单 test 翻车不会拖死整个进程
    # 之前一个值同时控两边时,setup 慢就会把业务 test 时间挤掉甚至直接被杀
    UI_PLAYWRIGHT_SUBPROCESS_TIMEOUT: int = 600
    UI_LLM_CALL_TIMEOUT: int = 60  # UI Agent 内部 AssistantAgent 单次 LLM 调用超时（秒），超时走 fallback
    # 降级演练开关：True 时 PageAnalyzer / UiScriptGenerator 直接走本地模板，不调 LLM
    # QA 用来验证"模型不可用 → 基础脚本模板"路径，不需要真断网
    UI_AUTOMATION_FORCE_FALLBACK: bool = False
    # 排查开关:True 时 PageAnalyzer 不再走兜底,LLM 失败/JSON 解析失败直接抛异常
    # 用于定位 fallback 根因(401/404/超时/JSON 不合规等),平时保持 False
    UI_AUTOMATION_DISABLE_FALLBACK: bool = False
    UI_HEADLESS: bool = True  # 服务器必须 True
    UI_BASE_URL: str = ""  # 被测应用 base url，留空时由脚本自带
    UI_VIDEO_MODE: str = "retain-on-failure"  # off / on / retain-on-failure
    UI_TRACE_MODE: str = "retain-on-failure"
    UI_MAX_VIDEO_SIZE_MB: int = 50
    UI_MAX_CONCURRENT_EXECUTIONS: int = 2
    UI_BATCH_MAX_CONCURRENT: int = 3  # 批次内脚本并发数，默认 3
    UI_ARTIFACT_RETENTION_DAYS: int = 7
    UI_KEEP_LATEST_SUCCESS_REPORTS: int = 20

    # UI 自动化 Allure 报告：True=执行结束后异步自动生成（默认）；False=仅前端按钮触发。
    # 自动生成不阻塞执行完成事件，前端进详情看到 generating 状态会自动轮询。
    UI_AUTO_GENERATE_ALLURE: bool = True

    # MidScene.js 在子进程内通过 OPENAI_* / MIDSCENE_MODEL_NAME 读取 LLM 配置。
    # 这里允许在 .env 单独配 UI_MIDSCENE_*；若留空,execution_service 会回退到 DOUBAO_*。
    UI_MIDSCENE_API_KEY: str = ""
    UI_MIDSCENE_BASE_URL: str = ""
    UI_MIDSCENE_MODEL_NAME: str = ""

    # 子进程登录凭证(helpers/auth.ts 的 loginAsDefault 走这三个变量)
    UI_LOGIN_URL: str = ""
    UI_LOGIN_USERNAME: str = ""
    UI_LOGIN_PASSWORD: str = ""

    # ============================================================
    # UI 录制（Playwright codegen）配置
    # 录制本质需要 GUI（人工在浏览器里操作）—— 不能在 headless 服务器跑,
    # 仅适用于"后端跟前端跑同一台机器"或"远程开发机"的部署模式
    # ============================================================
    UI_RECORDING_ENABLED: bool = True
    UI_RECORDING_MODE: str = "local"  # "local" | "remote"
    # 录制原始产物落点(相对 UI_AUTOMATION_WORKSPACE):recordings/{session_id}.spec.ts
    UI_RECORDING_RAW_SUBDIR: str = "recordings"
    # 单次录制最长时长（秒）—— 超时强杀子进程,默认 30 分钟
    UI_RECORDING_TIMEOUT: int = 1800
    # 默认 storage state 文件相对路径(留空 = 不预登录,从登录页开始录)
    UI_RECORDING_DEFAULT_STORAGE_STATE: str = ".auth/user.json"
    # AI 后处理超时(LLM 优化录制产物)
    UI_RECORDING_POSTPROCESS_TIMEOUT: int = 60

    # 多模态 LLM（豆包视觉）
    DOUBAO_API_KEY: str = ""
    DOUBAO_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    DOUBAO_VISION_MODEL: str = "doubao-1-5-vision-pro-32k-250115"

    # ============================================================
    # crawl4ai 集成(2026-06-17 引入)
    # 用途:Live URL 页面分析 + 录制前预抓 DOM 字典辅助后处理 selector
    # 集成方式:主 venv 直接 import(0.8.8 已放宽 pillow 约束,与 autogen-core 0.6.4 兼容)
    # 零回归红线:UI_CRAWL4AI_ENABLED=False 或 import 失败 → 走原有 fallback,不影响现有功能
    # ============================================================
    UI_CRAWL4AI_ENABLED: bool = True
    UI_CRAWL4AI_TIMEOUT: int = 60  # 单次 crawl4ai 抓取超时(秒)
    UI_CRAWL4AI_PREFETCH_DEFAULT: bool = False  # 录制时是否默认勾选预抓
    UI_CRAWL4AI_PAGE_DICT_DIR: str = os.path.join(BASE_DIR, "generated_ui_tests", "page_dicts")
    # SPA 页面框架 mount 等待秒数。Vue/React 路由切换后 DOM 不会立刻出来,
    # domcontentloaded 触发时根节点常常还是空的,这里固定等几秒再跑 JS 提取器
    UI_CRAWL4AI_SPA_DELAY: int = 3


settings = Settings()
