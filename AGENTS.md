# Codex 工作手册 - api-automation 项目

你是这个项目的资深测开工程师。本文档不是代码规范，而是项目知识库 + 决策手册——让你做事前知道项目长什么样、有哪些基础设施可复用、有哪些坑要避开。

---

## 1. 项目定位（一句话）

**AI 多智能体驱动的接口自动化测试平台**：上传 API 文档 → 7 个智能体流水线协作 → 输出可执行的 pytest 脚本 → 执行并生成 Allure 报告。

### 核心数据流

```
用户上传文档（OpenAPI/Swagger/Postman/PDF）
        │
        ▼
ApiDocParserAgent       → 解析为标准化端点
        │
        ▼
ApiAnalyzerAgent        → 分析依赖关系、执行组、安全风险
        │
        ▼
TestCaseGeneratorAgent  → 生成多类型测试用例（正向/负向/边界/安全）
        │
        ▼
ScriptGeneratorAgent    → 生成 pytest 脚本到 generated_tests/testcases/
        │
        ▼
TestExecutorAgent       → 在 generated_tests/ 下执行 pytest
        │
        ▼
ApiDataPersistenceAgent → 落库
        ↘
LogRecorderAgent        → 全程结构化日志（旁路）
```

智能体通信用 AutoGen Core 0.6.4 的 **Topic 发布订阅模式**（`@type_subscription` + `TopicId`），不是直接调用。

---

## 2. 模块速查表（"我要做 X，应该看 Y"）

| 任务 | 必读 / 必改文件 |
|------|---------------|
| 加新智能体 | `app/agents/api_automation/base_api_agent.py`（基类）+ `app/agents/factory.py`（注册）+ `app/core/types.py`（添加 AgentTypes/TopicTypes 枚举） |
| 改智能体 prompt | `app/agents/api_automation/schemas.py` 里的 `AgentPrompts` 类 |
| 改智能体之间的数据结构 | `app/agents/api_automation/schemas.py`（所有 Input/Output 模型） |
| 切换 LLM 模型 | `app/core/agents/llms.py` 里的 `MODEL_CONFIGS` 注册表 + `.env` |
| 加后端 API 路由 | `app/api/v1/endpoints/`，注册到 `app/api/v1/__init__.py` |
| 加业务逻辑 | `app/services/api_automation/` 服务层 |
| 改数据模型 | `app/models/api_automation.py`，注意数据库可能要重建（见第 4 节） |
| 加前端页面 | `frontend/src/views/api-automation/`，路由在同目录 `route.js` |
| 加前端 API 调用 | `frontend/src/api/index.js` |
| 改生成脚本的运行框架 | `generated_tests/automation/`（基础设施，不被 AI 覆盖） |
| 加测试用例（手动） | `generated_tests/testcases/`，然后调 `POST /scripts/register` 注册到前端 |
| 改 RBAC 权限 | `app/core/dependency.py` 的 `DependPermission` |
| 改菜单初始化 | `app/core/init_app.py` 的 `init_menus()` |

---

## 3. 项目特定核心机制

### 3.1 智能体通信（Topic 发布订阅）

智能体不直接调用彼此，而是发布消息到 Topic，订阅方自动接收：

```python
@type_subscription(topic_type=TopicTypes.MY_AGENT.value)
class MyAgent(BaseApiAutomationAgent):
    @message_handler
    async def handle_request(self, message: MyInput, ctx: MessageContext) -> None:
        # 处理逻辑...
        await self.runtime.publish_message(
            NextStageInput(...),
            topic_id=TopicId(type=TopicTypes.NEXT_STAGE.value, source=self.agent_name)
        )
```

新增智能体时必须在 `TopicTypes` 和 `AgentTypes` 枚举里加对应项，并在 `factory.py` 注册类。

### 3.2 LLM 调用与 JSON 提取

LLM 输出不可靠，**必须有 fallback**：

```python
result_content = await self._run_assistant_agent(prompt)
parsed = self._extract_json_from_content(result_content)  # 基类方法，处理 markdown 包裹、注释、不规范 JSON
if not parsed:
    return await self._fallback_generate(...)  # 走确定性逻辑
```

LLM 客户端必须通过工厂获取，不要直接 `OpenAIChatCompletionClient(...)`：

```python
from app.core.agents.llms import get_model_client
self.model_client = get_model_client("deepseek")
```

### 3.3 流式响应（前端实时进度）

智能体处理过程中要给前端推送进度，用 `StreamMessage`：

```python
await self._send_message(
    content="正在解析文档...",
    message_type="info",
    region=MessageRegion.PROCESS,
)
```

底层走 SSE（`sse-starlette`），前端订阅 `stream_response` topic 拿到流式输出。

### 3.4 配置三层

```
.env                              → 敏感信息（API Key、AES_KEY）
app/core/config.py (Pydantic)     → 应用级类型化配置
app/config/api_automation_config.yaml → 智能体行为、超时、报告路径
```

新增配置项优先放 Pydantic Settings，不要散落在代码里。

### 3.5 RBAC（接口级，不是 action 级）

权限是在 router 注册时统一加的：

```python
v1_router.include_router(my_router, prefix="/my", dependencies=[DependPermission])
```

不存在 `verify_permission("agent:read")` 这种细粒度。要保护就加 `dependencies=[DependPermission]`，不需要保护就不加。

### 3.6 统一响应结构

后端所有接口返回 `{code, msg, data, success}` 四件套：

```python
return {
    "code": 200,
    "msg": "OK",
    "data": {...},
    "success": True,
}
```

异常通过 `HTTPException` 抛出，自定义异常在 `app/core/exceptions.py`。

---

## 4. 已知陷阱（先看再改）

### ❌ 数据库和模型不同步

项目历史问题：`api_automation.py` 的模型多次修改，但 SQLite 表结构没跟上，会出现 `no column named xxx` 报错。

- **开发环境处理**：删 `db.sqlite3` + `migrations/`，重启后端会按最新模型重建（种子数据自动恢复）
- **生产环境处理**：用 Aerich 写迁移脚本

修改模型字段前先确认现有 DB 是否同步。

### ❌ marker-pdf 与 autogen-core 的 pillow 冲突

`autogen-core==0.6.4` 要 `pillow>=11`，`marker-pdf` 所有版本要 `pillow<11`，**无法共存**。

当前 `requirements.txt` 已注释掉 `marker-pdf`，PDF 解析功能暂不可用。如要启用，只能：
- 单独建虚拟环境跑 marker-pdf 做 PDF→Markdown 转换
- 或等上游放宽约束

### ❌ DeepSeek API Key 失效

`.env` 里 `DEEPSEEK_API_KEY` 失效会导致所有智能体在调用 LLM 时 401 报错。**所有智能体都要支持 fallback 路径**（`_fallback_generate_*`），不能完全依赖 LLM。

### ❌ PowerShell 中文请求体乱码

PowerShell 默认编码不是 UTF-8，`Invoke-RestMethod` 发中文会变 `??????` 入库。正确方式：

```powershell
$body = @{...} | ConvertTo-Json
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod -Uri ... -ContentType "application/json; charset=utf-8" -Body $bytes
```

### ❌ generated_tests/ 里有两套脚本

- 旧的 `api_test_xxx/test_api_automation.py`：自包含单文件（fixture 内嵌），是 ScriptGeneratorAgent 改造前的产物
- 新的 `testcases/test_*.py`：依赖 `automation/` 基础框架（统一 fixture、登录、客户端）

新脚本必须放 `testcases/`，不要再生成自包含模式。

### ❌ 智能体启动卡死

智能体初始化（连 LLM、初始化 runtime）可能因网络超时卡住整个后端启动。`app/__init__.py` 的 `lifespan` 已用 `asyncio.wait_for(..., timeout=10)` 包裹，新增初始化逻辑也必须加超时。

---

## 5. 技术栈红线

| 层 | 必用 | 严禁 |
|----|------|------|
| 前端框架 | Vue 3（Composition API + `<script setup>`） | Vue 2 / React / 其他 |
| 前端语言 | JavaScript | TypeScript（项目没配 ts，硬加会破坏构建） |
| 前端构建 | Vite 4 | Webpack / Rollup |
| 前端组件 | Naive UI | Element Plus / Ant Design / Tailwind |
| Pinia | Options Store | Setup Store（项目所有 store 都是 Options 写法） |
| 后端框架 | FastAPI + Uvicorn | Flask / Django |
| 后端 ORM | Tortoise（异步） | SQLAlchemy / Django ORM |
| 日志 | `loguru.logger` | Python 标准 `logging` |
| AI 框架 | AutoGen Core 0.6.4 | 0.2.x 的 `UserProxyAgent`/`GroupChat` 老语法 |
| LLM 客户端 | OpenAI 兼容协议（DeepSeek、通义、Ollama 都走这个） | 各家原生 SDK |
| 测试框架 | pytest + Allure | unittest |

---

## 6. generated_tests/ 测试框架分层

```
generated_tests/
├── conftest.py                  ← 全局入口，加载配置 + 注册 fixture
├── pytest.ini                   ← markers、日志、testpaths
├── .env                         ← AES_KEY / AES_IV
├── automation/                  ← 【基础设施层 - 不被 AI 覆盖】
│   ├── core/
│   │   ├── config/              ← YAML 配置 + 多环境（test/staging/prod）
│   │   ├── auth/                ← AuthSession 单例 + AES 加密
│   │   ├── fixtures/            ← auth_session / login_session / api_client
│   │   └── utils/path.py
│   └── api/
│       ├── client/base_client.py   ← 自动注入 token 的 HTTP 客户端
│       └── modules/login_api.py    ← 登录接口封装
├── testcases/                   ← 【测试用例层】
│   ├── test_login.py            ← 手动封装的用例
│   └── test_xxx.py              ← AI 生成的用例（写入 testcases/）
└── testdata/api_test_data.yml
```

### 脚本两种来源

| 来源 | `generated_by` | 触发方式 |
|------|---------------|---------|
| AI 生成 | `AI` | 文档工作流走完流水线，自动写入 `testcases/` 并入库 |
| 手动封装 | `MANUAL` | 写好 `testcases/test_xxx.py` 后，调 `POST /api/v1/scripts/register` 注册到数据库 |

两种脚本前端"脚本管理"页面统一展示，执行命令统一为：

```bash
cd generated_tests && python -m pytest testcases/test_xxx.py --env test -v
```

由后端 `POST /scripts/{script_id}/run` 接口同步触发。

---

## 7. DoD 检查清单（精简版）

提交代码前自查：

- [ ] **异步整洁**：所有 Tortoise / 智能体 / HTTP 调用都 `await`
- [ ] **LLM 有 fallback**：调 LLM 的地方有 `_fallback_*` 路径
- [ ] **超时保护**：长任务用 `asyncio.wait_for(..., timeout=N)`
- [ ] **统一响应**：后端返回 `{code, msg, data, success}`
- [ ] **日志用 loguru**：`from loguru import logger`，可写中文
- [ ] **不踩 marker-pdf 坑**：不要随便加回 `marker-pdf`
- [ ] **路由权限位置正确**：保护接口注册在带 `dependencies=[DependPermission]` 的 router 下
- [ ] **数据库变更确认**：改模型字段后说明是否需要删 db 重建
- [ ] **没引入 TS / Setup Store / 非 Naive UI 组件**
- [ ] **AutoGen 用 0.6.x API**：`@type_subscription` / `@message_handler` / `TopicId`
