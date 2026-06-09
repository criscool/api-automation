# AI 测试诊断与自愈系统 - 开发设计文档 v2

> 版本：v2（基于 v1 评审修正）
> 状态：待评审
> 作者：测开
> 最后更新：2026-06-05

---

## 0. 修订说明

相对 v1 的主要修正：

1. 字段挂载位置按 TestCase / TestScript 的语义分工拆清楚
2. 自愈循环不强行套 Topic 发布订阅，Service 层同步驱动
3. 加入 AST 双校验、断言保护、文件锁、探测脚本静态拦截等护栏
4. `api-test-fixer` skill 的知识沉淀为代码可消费的注册表
5. 实施路线拆三期，先做交互式诊断（低风险）再做静默自愈
6. 明确响应体来源（Allure JSON 而非 pytest stdout）

---

## 1. 业务目标与范围

### 1.1 痛点

| 痛点 | 现状 | 量化 |
|------|------|------|
| 生成即不可用 | LLM 写的脚本因蛇形/驼峰、未知必填等首次执行失败 | 待埋点统计 |
| 接口迭代脚本失效 | 字段重命名 / 必填项变化 → 一批用例红灯 | 待埋点统计 |
| 失败定界耗时 | 排查"脚本写错"还是"产品 Bug"靠人 | 单条用例 ~10min |

### 1.2 目标

- **G1 交互式诊断**：失败用例点 [AI 诊断] 后 30 秒内给出"脚本应改成什么样" or "可能是产品 Bug"的结构化报告
- **G2 静默自愈**：生成流水线末端拦截失败用例自动修复，目标自愈成功率 ≥ 50%

### 1.3 非目标

- 不做接口语义层面的智能用例补全（属于 TestCaseGeneratorAgent 范畴）
- 不做生产环境产品代码自动修改
- 不做跨脚本文件的全局重构

---

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                          流水线生成阶段                          │
│  ApiDocParser → ApiAnalyzer → TestCaseGen → ScriptGen           │
│                                                  ↓                │
│                                          ┌───────────────┐       │
│  Phase 3 开关：HEALER_AUTO_ENABLED       │ TestExecutor  │       │
│                                          └───────┬───────┘       │
│                                                  │ FAILED        │
│                                                  ▼                │
│                                          ┌───────────────┐       │
│                                          │ HealerService │       │
│                                          └───────────────┘       │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                          交互诊断阶段                            │
│  前端报告页 → [AI 诊断] → /heal/diagnose                         │
│                              ↓                                    │
│                       HealerService.diagnose()                   │
│                       ├─ 输出诊断报告（场景 A/B）                │
│                       └─ SSE 推送进度                            │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 关键决策

- **TestHealerAgent / TestAnalysisAgent 走 AssistantAgent 直调，不进 Topic 总线。** 自愈是「探测→改→回归」的强同步循环，套发布订阅反而失去执行序保证。`@type_subscription` 仅用于 SSE 进度广播（沿用 `stream_response` topic）。
- **沿用现有 TestCase 的 nodeid 元数据**（`class_name` / `method_name` / `script_file_path`），自愈精确到单个 pytest 方法。
- **诊断与修复在 Service 层封装一个状态机**，Agent 只负责"出主意"，不持有副作用。

### 2.2 "跑脚本"在哪里发生（执行点矩阵）

整个自愈链路里有 **4 类「跑」**，分别由不同方触发，落地路径必须分清：

| # | 跑什么 | 谁触发 | 在哪跑 | 入口代码 | 失败信号去向 |
|---|--------|--------|--------|----------|-------------|
| **R1** | 原始测试脚本（首跑） | TestExecutorAgent / 前端手动「执行」按钮 | `generated_tests/` 子进程 pytest | 现有 `script_management.py:run_script` | 落 TestResult 表 + Allure JSON |
| **R2** | 探测脚本（AI 试 payload） | HealerService.probe() | `generated_tests/.probe/` 隔离子进程（直接 `python __probe_xxx.py`，**不走 pytest**） | `healer_sandbox.py:run_probe` | 返回给 TestHealerAgent 作为下一轮 prompt 输入 |
| **R3** | 验证跑（修完跑 nodeid 回归） | HealerService.dry_run() | `generated_tests/` 子进程 pytest（精确到 nodeid） | `healer_service.py:dry_run` | 决定 SUCCESS / ROLLBACK |
| **R4** | 静默模式的「再次首跑」 | 流水线 healing pass | 同 R1 | 同 R1 | 替换原 TestResult 状态 |

#### 触发时序

**交互诊断**（用户点 [AI 诊断] 时，**不重跑 R1**，直接读历史失败）：

```
前端点 [AI 诊断]
   ↓
POST /scripts/{id}/heal/diagnose
   ↓
HealerService.diagnose()
   ├─ 1. 读 DB 最近一次 TestResult（失败的）
   ├─ 2. 读对应 Allure JSON 提取 request/response 体
   ├─ 3. 如果 TestResult 已是 >24h 前 OR 不存在 → 触发一次 R1 重跑兜底
   ├─ 4. TestAnalysisAgent 出 verdict
   └─ 5. 若 SCRIPT_FIX → 进入修复子流程：
        ├─ R2 探测 ×N（N ≤ 3）
        ├─ TestHealerAgent 出补丁
        ├─ AST 校验
        ├─ R3 验证跑
        └─ SUCCESS / NEEDS_REVIEW / ROLLBACK
```

**静默自愈**（流水线末端，已经有 R1 失败结果）：

```
TestExecutorAgent.run_all()
   ↓
得到一批 failed_cases（已有 R1 结果）
   ↓
healing_pass: for each failed_case
   ├─ should_auto_heal() 过滤
   ├─ HealerService.heal(mode="silent")
   │   ├─ R2 探测 ×N
   │   ├─ AST 校验
   │   └─ R3 验证跑
   ├─ 若 SUCCESS：覆盖原 TestResult 为 PASSED + 标记 heal_status
   └─ 若 FAILED：保留原 FAILED + 累计 heal_attempts
```

#### 关键约束

1. **R1 失败结果是诊断的输入，不是诊断的副产物**：交互模式默认**复用历史 TestResult**，避免每次点 [AI 诊断] 都重跑（成本高 + 测试环境状态可能已变）。仅当结果太旧或缺失时才兜底重跑。
2. **R2 探测脚本绝不走 pytest**：避免污染 fixture / 登录态 / Allure 报告。直接 `python __probe_xxx.py` 子进程，stdout/stderr 全捕获。
3. **R3 验证跑必须用 nodeid**：`pytest testcases/test_xxx.py::TestClass::test_method` —— 跑整文件会带上不相关用例，跑出新失败不知是不是自愈带的。
4. **R4 不存在「再再次自愈」**：静默模式下一次自愈失败 → `heal_attempts +1`，下次流水线再跑到同一用例时若仍失败、且 `heal_attempts >= 2`，**直接跳过自愈**走人工通道。
5. **所有 R1/R3/R4 必须复用现有 `script_management.run_script` 执行函数**，不要新写一套，否则环境变量、--env 参数、conftest 加载路径会偏。

---

## 3. 数据模型变更

### 3.1 TestCase（方法级状态）

文件：`backend/app/models/api_automation.py`

```python
class TestCase(Model):
    # ... 既有字段 ...

    # === 新增 ===
    heal_status = fields.CharField(
        max_length=20, default="NONE",
        description="自愈状态: NONE/HEALING/HEAL_SUCCESS/HEAL_FAILED/NEEDS_REVIEW",
        index=True,
    )
    heal_attempts = fields.IntField(default=0, description="累计自愈尝试次数")
    last_heal_session_id = fields.CharField(
        max_length=100, null=True, description="最近一次诊断会话ID"
    )
    last_diagnosis = fields.JSONField(
        default=dict,
        description="最近一次诊断摘要 {category, confidence, summary, evidence_refs}"
    )
```

- `heal_status` 多了一个 `NEEDS_REVIEW`：自愈过程触及了断言节点（assert）时，强制人工 review，不自动算 SUCCESS
- `last_diagnosis` 只存摘要（< 4KB），完整 diff 落盘见 §3.3

### 3.2 TestScript（文件级版本与锁）

```python
class TestScript(BaseModel, TimestampMixin):
    # ... 既有字段 ...

    # === 新增 ===
    heal_version = fields.IntField(default=1, description="脚本当前版本号")
    heal_lock_until = fields.DatetimeField(
        null=True, description="自愈互斥锁过期时间，避免并发改同一文件"
    )
```

`heal_version` 在每次成功应用补丁后 +1，用于备份文件命名、防 ABA。

### 3.3 落盘路径

```
generated_tests/
  .heal_history/
    {script_id}/
      v{n}.before.py              ← 改动前的整文件备份
      v{n}.patch                  ← unified diff，供前端 Monaco 渲染
      v{n}.meta.json              ← {test_id, agent, model, token_cost, probe_log_ref}
      v{n}.probe.log              ← 探测请求/响应明细
```

DB 中只引用 `v{n}.patch` 的相对路径，**不把 diff 文本灌进 JSONField**，避免大字段拖慢列表查询。

### 3.4 迁移策略（Aerich 增量，禁止删库）

⚠️ **绝对禁止删 `db.sqlite3` 重建**。该文件在全局规则中是「用户资产」，且已累计真实的测试用例、脚本、执行历史，删了不可恢复。

#### 3.4.1 为什么本次可以安全增量

所有新增字段满足：

| 字段 | 类型 | DEFAULT | NULL 允许 | 对存量数据影响 |
|------|------|---------|-----------|---------------|
| TestCase.heal_status | CHAR(20) | `'NONE'` | 否 | 全部填 'NONE'，无副作用 |
| TestCase.heal_attempts | INT | `0` | 否 | 全部填 0 |
| TestCase.last_heal_session_id | CHAR(100) | — | 是 | 全部 NULL |
| TestCase.last_diagnosis | JSON | `{}` | 否 | 全部填空对象 |
| TestScript.heal_version | INT | `1` | 否 | 全部填 1 |
| TestScript.heal_lock_until | DATETIME | — | 是 | 全部 NULL |

→ 都是 **纯增列 + 安全默认值**，SQLite `ALTER TABLE ADD COLUMN` 原生支持，不涉及任何破坏性变更。

#### 3.4.2 执行步骤

```bash
cd backend

# 1. 确认 Aerich 已初始化（项目用的就是 Aerich）
ls migrations/models/ | head -3

# 2. 生成迁移脚本（不会自动执行）
..\.venv\Scripts\aerich.exe migrate --name add_heal_fields

# 3. 人工 review 生成的 migrations/models/*_add_heal_fields.sql
#    必须确认：
#    - 只有 ADD COLUMN 语句
#    - 没有 DROP / RENAME / ALTER TYPE
#    - 所有新列都带 DEFAULT

# 4. 备份数据库（即便迁移安全，备份也是 SOP）
cp db.sqlite3 db.sqlite3.bak.$(date +%Y%m%d_%H%M%S)

# 5. 应用迁移
..\.venv\Scripts\aerich.exe upgrade

# 6. 验证：用例数量不变 + 新字段有默认值
..\.venv\Scripts\python.exe -c "
import asyncio
from tortoise import Tortoise
async def check():
    await Tortoise.init(config_file='aerich.ini')
    from app.models.api_automation import TestCase
    total = await TestCase.all().count()
    sample = await TestCase.first()
    print(f'用例总数: {total}, heal_status: {sample.heal_status}')
asyncio.run(check())
"
```

#### 3.4.3 回滚预案

- Aerich 自带 `aerich downgrade` 回滚最后一次迁移
- 即便 downgrade 失败，也有 `db.sqlite3.bak.{timestamp}` 兜底
- **回滚时机**：上线后 1 小时内发现新字段读写异常立即回滚；超过 1 小时若已有自愈数据写入，回滚需评估自愈数据是否要保留

#### 3.4.4 历史数据回填（可选，不阻塞上线）

存量 TestCase 的 `heal_status` 全为 `NONE` 是符合预期的（它们从未参与自愈），**无需回填**。如果后续要分析"如果有自愈，这些历史失败用例会不会被救活"，单独跑一次性回填脚本即可，不耦合本次发布。

---

## 4. 后端架构

### 4.1 目录

```
backend/app/
├── agents/api_automation/
│   ├── test_healer_agent.py         ← 新增
│   └── test_analysis_agent.py       ← 新增
├── services/api_automation/
│   ├── healer_service.py            ← 新增（核心状态机）
│   ├── healer_sandbox.py            ← 新增（探测沙箱）
│   └── healer_patch.py              ← 新增（补丁应用 + AST 校验）
├── api/v1/endpoints/
│   └── script_management.py         ← 增 3 个接口
└── core/
    └── healer_patterns.py           ← 新增（API 反模式注册表）
```

### 4.2 智能体

按 CLAUDE.md 3.1 在 `app/core/types.py` 注册：

```python
class AgentTypes(str, Enum):
    # ...
    TEST_HEALER = "test_healer"
    TEST_ANALYSIS = "test_analysis"

class TopicTypes(str, Enum):
    # ...（不新增 healer 专用 topic，沿用 stream_response 做进度推送）
```

#### TestHealerAgent

- 基类：`BaseApiAutomationAgent`
- 输入：失败用例上下文（脚本片段、报错、响应体、接口文档）
- 输出：结构化 JSON `{action, probe_script | patch, rationale, risk_tags}`
- **System prompt 内嵌 `healer_patterns.py` 的反模式知识**（蛇形/驼峰、`type` 必填、204 删除返回、断言双风格）
- 必备 fallback：DeepSeek 401 → 降级为「只输出诊断不出补丁」（与 TestAnalysisAgent 等价）

#### TestAnalysisAgent

- 输入：失败上下文 + 接口文档原文片段
- 输出：`{verdict: SCRIPT_FIX | PRODUCT_BUG | UNCERTAIN, confidence: 0-1, report_md, evidence: [doc_quotes]}`
- 关键：**evidence 必须引用文档原文**，前端渲染时和 verdict 一起展示，让人能核对（避免 AI 甩锅式"判定为产品 Bug"）

### 4.3 HealerService 状态机

```
       ┌────────────┐
       │   IDLE     │
       └─────┬──────┘
             │ diagnose()
             ▼
       ┌────────────┐
       │ DIAGNOSING │ ── 失败 ──┐
       └─────┬──────┘            │
             │ verdict           │
       ┌─────┴──────┐            │
       ▼            ▼            ▼
   SCRIPT_FIX  PRODUCT_BUG  UNCERTAIN
       │            │            │
       │            └────────────┴──→ 直接返回报告，不改文件
       │
       │ apply() (用户触发 或 静默模式自动)
       ▼
   ┌────────────┐
   │  PROBING   │ ── 沙箱探测
   └─────┬──────┘
         │
         ▼
   ┌────────────┐
   │ AST_CHECK  │ ── 不通过 → ROLLBACK
   └─────┬──────┘
         │
         ▼
   ┌────────────┐
   │ DRY_RUN    │ ── 跑 nodeid，失败 → ROLLBACK
   └─────┬──────┘
         │
         ▼
   ┌────────────┐
   │  SUCCESS   │ or NEEDS_REVIEW（触碰断言）
   └────────────┘
```

### 4.4 核心算法

#### 4.4.1 补丁前 AST 双校验（healer_patch.py）

```python
def validate_patch(before_src: str, after_src: str, target_method: str) -> ValidationResult:
    before_tree = ast.parse(before_src)
    after_tree = ast.parse(after_src)

    # 校验 1：只有一个 FunctionDef 节点发生变化，且必须是 target_method
    changed = diff_function_defs(before_tree, after_tree)
    if len(changed) != 1 or changed[0].name != target_method:
        return Reject("跨方法改动")

    # 校验 2：断言节点变化触发降级
    if has_assert_changes(before_tree, after_tree, target_method):
        return NeedsReview("断言被改写")

    # 校验 3：导入节点新增需在白名单
    if has_unsafe_imports(after_tree):
        return Reject("引入了危险导入")

    return Pass()
```

**这是比 prompt 约束更可靠的护栏**，prompt 仅作为提示，真正的兜底在 AST。

#### 4.4.2 沙箱探测（healer_sandbox.py）

```python
DANGEROUS_PATTERNS = [
    r"requests\.(delete|put)",
    r"\.execute\(.*?(DROP|TRUNCATE|DELETE\s+FROM)",
    r"os\.(system|remove|rmdir)",
    r"subprocess\.",
    r"shutil\.(rmtree|move)",
    r"open\([^)]*,\s*['\"]w",  # 文件写入
]

def static_check_probe(probe_src: str) -> CheckResult:
    # 1. 正则黑名单
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, probe_src):
            return Reject(f"命中危险模式: {pat}")

    # 2. AST 校验：白名单允许的 requests 方法
    tree = ast.parse(probe_src)
    for call in walk_calls(tree):
        if call.func is requests.* and call.method not in {"get", "post", "options", "head"}:
            return Reject(f"探测脚本调用了非白名单方法: {call.method}")

    return Pass()
```

探测脚本：
- 文件命名 `__probe_{session_id}.py`，跑完立即删除
- 子进程执行 + 10s 超时 + 限定 cwd 在 `generated_tests/.probe/` 沙盒目录
- 探测请求频率 ≤ 3/分钟同端点（Redis 或进程内计数器）

#### 4.4.3 二次验证：nodeid 精跑（对应 §2.2 R3）

```python
nodeid = f"{script_file_path}::{class_name}::{method_name}"
cmd = f"cd generated_tests && python -m pytest {nodeid} --env test -v"
# 与 CLAUDE.md 第 6 节脚本执行命令对齐
# 复用 script_management.run_script() 不要新写一套子进程封装
```

- 不跑整文件：避免影响其他用例的执行成本
- 单方法跑过 = 自愈成功；跑失败 = 立即回滚 `.bak`
- 执行超时 60s（独立于 heal 整体的 180s 总超时）

#### 4.4.4 文件锁

```python
_file_locks: dict[str, asyncio.Lock] = {}

async def with_script_lock(script_path: str):
    lock = _file_locks.setdefault(script_path, asyncio.Lock())
    async with asyncio.wait_for(lock.acquire(), timeout=60):
        try:
            yield
        finally:
            lock.release()
```

DB 侧用 `heal_lock_until` 兜底跨进程互斥（同样命名是为了简单一致）。

#### 4.4.5 响应体提取

**关键**：pytest stdout 不会带响应体，必须从 Allure 中间结果取：

```python
def extract_failure_evidence(session_dir: Path, nodeid: str) -> FailureEvidence:
    # 1. 解析 allure-results/{uuid}-result.json
    # 2. 找到 nodeid 对应的 case
    # 3. 从 attachments 里取 request/response 体
    # 4. 同时读 logs/test_*.log 取 loguru 输出补充上下文
    ...
```

如果项目没生成 allure 中间结果，需先在 conftest 加 `pytest_runtest_makereport` hook 把响应体落到 `failures/{nodeid}.json`。

### 4.5 反模式知识库（healer_patterns.py）

把 `api-test-fixer/references/api_patterns.md` 沉淀为代码可消费的注册表：

```python
KNOWN_ANTIPATTERNS = [
    {
        "id": "snake_camel_mix_situation",
        "module": "态势大屏",
        "rule": "time_from/time_to 蛇形，但 streamIds 驼峰",
        "fix_hint": "尝试两种命名都发一遍探测",
    },
    {
        "id": "realtime_alarm_sum_type_required",
        "endpoint_pattern": "/realTimeAlarmSum",
        "rule": "强制要求 type 字段（int）",
        "fix_hint": "payload 中加 type=1",
    },
    {
        "id": "asset_response_writeresult",
        "module": "资产",
        "rule": "返回 MongoDB WriteResult 字符串而非 JSON",
        "fix_hint": "断言用正则或包含校验",
    },
    {
        "id": "delete_204_no_body",
        "rule": "DELETE 可能 200 带 JSON 也可能 204 无 body",
        "fix_hint": "断言 status_code in (200, 204)",
    },
    # ...
]
```

- TestHealerAgent 的 system prompt 模板里 `{ANTIPATTERN_DIGEST}` 占位符自动注入这份摘要
- 新发现的坑追加到这里而不是改 prompt，prompt 始终引用这一份单一来源

### 4.6 REST API

文件：`backend/app/api/v1/endpoints/script_management.py`（沿用现有路由前缀）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/scripts/{script_id}/heal/diagnose` | 触发诊断，返回 verdict + diff（不落盘） |
| POST | `/scripts/{script_id}/heal/apply` | 应用一份已诊断出的补丁（带 patch_id） |
| GET | `/scripts/{script_id}/heal/history` | 获取脚本自愈轨迹 |
| GET | `/heal/sessions/{session_id}/stream` | SSE 流，实时推送诊断/修复进度 |

**强约束**：`apply` 必须带 `patch_id`（来自 diagnose 返回），且 patch 状态必须是 `PENDING`，避免重放或越权 apply。

权限：均挂在带 `dependencies=[DependPermission]` 的 router 下。

### 4.7 SSE 进度事件

事件类型枚举（前端可枚举消费）：

| event | 阶段 | payload |
|-------|------|---------|
| `diag.started` | 开始 | `{session_id}` |
| `diag.evidence_collected` | 提取证据完 | `{failure_summary}` |
| `diag.probing` | 探测中 | `{endpoint, attempt}` |
| `diag.verdict` | 出结论 | `{verdict, confidence}` |
| `heal.ast_check` | AST 校验 | `{result}` |
| `heal.dry_run` | 验证跑 | `{nodeid}` |
| `heal.done` | 完成 | `{status, heal_version}` |
| `heal.rollback` | 回滚 | `{reason}` |

---

## 5. 前端架构

### 5.1 状态指示

`heal_status` 渲染：

| 状态 | 图标 | tooltip |
|------|------|---------|
| NONE | 无 | — |
| HEALING | 旋转的 ⚙ | 自愈中 |
| HEAL_SUCCESS | ✨ + 绿点 | 经 AI 自动调优参数（v{n}） |
| NEEDS_REVIEW | 🔍 + 黄点 | AI 修改触及断言，请人工 review |
| HEAL_FAILED | ⚠ + 红点 | 自愈失败 N 次，需介入 |

### 5.2 AiDiagnosisDrawer.vue（按需弹出）

```
┌──────────────────────────────────────────────────────────┐
│  AI 诊断 - test_alarm_create::test_create_with_invalid   │
├──────────────────────────────────────────────────────────┤
│ Verdict: SCRIPT_FIX (置信度 0.82)                         │
│ 摘要：payload 字段 streamIds 应为字符串而非数组            │
├──────────────────────────────────────────────────────────┤
│  [脚本修复]  [文档证据]  [探测日志]                       │
├──────────────────────────────────────────────────────────┤
│  ┌──────────────┬──────────────┐                          │
│  │   旧代码     │   新代码     │   ← Monaco DiffEditor   │
│  └──────────────┴──────────────┘                          │
│                                                            │
│  ⚠ 此补丁未触碰 assert 节点，可直接应用                   │
├──────────────────────────────────────────────────────────┤
│  [下载 patch]   [应用（保留备份，不重跑）]   [应用并重跑] │
└──────────────────────────────────────────────────────────┘
```

关键约束：
- 默认按钮不是「应用并重跑」，避免误触
- "文档证据" tab 渲染 TestAnalysisAgent 的 `evidence` 数组，每条带文档来源引用，**用户可以核对 AI 的推理依据**
- 场景 B（PRODUCT_BUG）时三个 tab 切换为：「报告」「复现路径」「开发建议」，没有 [应用补丁] 按钮

### 5.3 撤销窗口

应用补丁后 5 秒内显示浮层 `[已应用 patch v3 · 5s 后失效 · 撤销]`，点撤销则用 `.bak` 还原并 heal_status 回 NONE。

---

## 6. 静默自愈（Phase 3 开关）

### 6.1 触发条件

仅当所有条件满足才自动触发：

```
HEALER_AUTO_ENABLED=true               # 环境变量总开关
AND test_case.heal_attempts < MAX_HEAL_RETRIES (=2)
AND failure_type in {HTTP_400, HTTP_404, HTTP_422}  # 5xx 不自愈，可能是真 Bug
AND failure_reason 命中 healer_patterns 中至少一条
AND script_file_path 在 testcases/ 下（不动 automation/、conftest.py）
AND token_budget_session < MAX_TOKEN_PER_SESSION (=50k)
```

### 6.2 流水线插入点

`TestExecutorAgent` 运行后，结果汇总前增加一个 healing pass：

```python
# pseudo
for failed_case in failed_cases:
    if should_auto_heal(failed_case):
        result = await healer_service.heal(failed_case, mode="silent")
        if result.status == HEAL_SUCCESS:
            failed_case.mark_passed()
        elif result.status == NEEDS_REVIEW:
            failed_case.mark_for_review()
```

### 6.3 周报

每周一发送「自愈周报」给团队 review：
- 自愈次数 / 成功率 / 触发的反模式分布
- NEEDS_REVIEW 队列长度
- Top N 反复触发的接口（暗示文档/产品需要修）

---

## 7. 护栏汇总（与 v1 评审清单对齐）

| # | 护栏 | 实现位置 |
|---|------|----------|
| 1 | 单次自愈整体超时 180s | `asyncio.wait_for` 包整个 heal() |
| 2 | 单文件 > 800 行拒绝 | HealerService.precheck |
| 3 | 补丁仅允许改单方法 | AST 双校验（4.4.1） |
| 4 | 断言被改 → NEEDS_REVIEW | AST 双校验（4.4.1） |
| 5 | 只允许改 `testcases/` 下文件 | 路径白名单校验 |
| 6 | 探测脚本静态拦截危险调用 | DANGEROUS_PATTERNS（4.4.2） |
| 7 | 探测频率限流 ≤ 3/min/endpoint | 进程内计数器 |
| 8 | 文件级 asyncio.Lock | with_script_lock（4.4.4） |
| 9 | 跨进程互斥 | heal_lock_until DB 字段 |
| 10 | LLM 失败降级为只出报告 | TestHealerAgent fallback |
| 11 | 单 session token 上限 50k | healer_service token 计数 |
| 12 | 完整审计日志 | loguru + DB heal_history 引用 |
| 13 | 静默自愈仅对 4xx | should_auto_heal 条件 |
| 14 | 撤销窗口 5s | 前端浮层 |

---

## 8. 实施路线

### Phase 1（2 周）：交互式诊断 MVP

**目标**：用户能在前端看到 AI 给的 diff，但**不自动落盘**

- TestAnalysisAgent + TestHealerAgent（只出 diff，不应用）
- `POST /scripts/{id}/heal/diagnose` + SSE
- AiDiagnosisDrawer.vue（场景 A diff 展示，场景 B 报告）
- 前端「下载 patch」按钮，用户手动应用验证流程

**验收**：在 5 个已知失败用例上跑通，diff 人工评估正确率 ≥ 60%

#### Phase 1 对现有项目的影响范围评估

整体定性：**纯新增 + 一处只读读取**，对现有功能 0 破坏面。Phase 1 刻意把"落盘 / 改 DB / 改测试脚本"这些有破坏性的能力推到 Phase 2，正是为了这一点。

##### 1. 后端文件级影响

| 影响类型 | 文件 / 模块 | 改动量 | 风险等级 | 说明 |
|---------|------------|--------|---------|------|
| 🟢 新增 | `app/agents/api_automation/test_analysis_agent.py` | 新文件 ~200 行 | 低 | 独立 Agent，不被其他流水线引用 |
| 🟢 新增 | `app/agents/api_automation/test_healer_agent.py` | 新文件 ~250 行 | 低 | 同上，Phase 1 只让它输出 diff 不应用 |
| 🟢 新增 | `app/services/api_automation/healer_service.py` | 新文件 ~300 行 | 低 | 仅含 diagnose() 入口，apply() 留空到 Phase 2 |
| 🟢 新增 | `app/services/api_automation/healer_evidence.py` | 新文件 ~120 行 | 低 | Allure JSON 解析器，只读 |
| 🟢 新增 | `app/core/healer_patterns.py` | 新文件 ~80 行 | 低 | 反模式注册表，纯数据 |
| 🟡 改动 | `app/core/types.py` | +6 行 | 低 | `AgentTypes` 加 2 个枚举 + `AGENT_NAMES` 补 2 行 |
| 🟡 改动 | `app/agents/factory.py` | +20 行 | 低 | `_register_api_automation_agents()` 末尾追加，不动既有注册 |
| 🟢 新增 | `app/api/v1/endpoints/healer.py` | 新文件 ~150 行 | 低 | **不在 `script_management.py` 1349 行的文件里继续叠**，单独建路由文件 |
| 🟡 改动 | `app/api/v1/__init__.py` | +2 行 | 低 | 注册新 router |
| 🟢 新增依赖 | `requirements.txt` | +1 行 `sse-starlette` | 中 | 见下文 §依赖影响 |
| ⚪ 只读 | `app/models/api_automation.py` `TestResult` / `TestCase` | 0 改动 | — | Phase 1 只读不写 |
| ⚪ 只读 | `generated_tests/reports/allure-results/*.json` | 0 改动 | — | 解析失败 case 的 attachment |

**关键设计决策**：新建 `endpoints/healer.py` 而不是叠到已经 1349 行的 `script_management.py`。理由：
- 后者已包含 27 个路由，再加 4 个会把单文件推到 1500 行 +，review 和测试都困难
- healer 是独立的诊断领域，按"endpoint 文件 = 一个业务域"的现有惯例（`interface_management` / `execution_reports` / `scheduled_tasks` 都是独立文件）应该单建

##### 2. 数据库影响（Phase 1 = 0 schema 变更）

| 表 | Phase 1 改动 |
|----|------------|
| TestCase | ❌ 不动（heal_status 等字段推到 Phase 2 才加） |
| TestScript | ❌ 不动 |
| TestResult | ❌ 不动（只读） |
| 新表 | ❌ 不建 |

→ **Phase 1 完全跳过 §3.4 的 Aerich 迁移流程**，零 schema 变更，零迁移风险。诊断结果不入库，只通过 HTTP 响应返回给前端。这也意味着 Phase 1 上线**无需停服**。

##### 3. 前端影响

| 影响类型 | 文件 | 改动量 | 风险等级 |
|---------|------|--------|---------|
| 🟢 新增 | `views/api-automation/execution-reports/AiDiagnosisDrawer.vue` | 新组件 ~350 行 | 低 |
| 🟡 改动 | `views/api-automation/execution-reports/detail.vue` | +30 行 | 中 | 失败用例行加 [AI 诊断] 按钮 + 抽屉绑定 |
| 🟡 改动 | `views/api-automation/execution-reports/index.vue` | +10 行 | 低 | 列表行加诊断入口（可选，也可只放 detail） |
| 🟡 改动 | `api/index.js` | +3 个方法 | 低 | `healDiagnose` / `healStream` / `healDownloadPatch` |
| ⚪ 复用 | `components/MonacoEditor.vue` | 0 改动 | — | 已有，扩展 diff 模式参数 |
| ⚪ 复用 | Naive UI 的 NDrawer / NTabs / NButton | 0 改动 | — | 已有依赖 |

**前端零新增依赖**：Monaco 已装，diff view 走 `monaco.editor.createDiffEditor` API，不需要 `monaco-editor/loader` 之外的东西；Naive UI 已有 Drawer/Tabs/Tag 等所有需要的组件。

##### 4. 依赖影响

| 包 | 状态 | 影响 |
|----|------|------|
| `sse-starlette` | **新增** | 后端 SSE 响应。包体积小、纯 Python、与 FastAPI 0.115+ 兼容；CLAUDE.md 3.3 提到过但 grep 验证过 HTTP 路由里**还没引入**，Phase 1 是第一次实装 |
| `unidiff` | **新增** | 解析 unified diff（应用前展示用，Phase 1 只生成不应用，但前端展示需要结构化 diff） |
| Monaco / Naive UI / Allure | 复用 | 已装 |
| `marker-pdf` | 不动 | CLAUDE.md 4.2 已说明的红线，不引入 |
| `autogen-core==0.6.4` | 不动 | 沿用现有 pillow 约束 |

##### 5. 配置 / 环境影响

| 项 | 改动 |
|----|------|
| `.env` | 新增 `HEALER_LLM_MODEL=deepseek`（默认值，可不配置）<br>新增 `HEALER_DIAGNOSE_TIMEOUT=180` |
| `app/config/api_automation_config.yaml` | 新增 `healer:` 段：`max_probe_attempts: 3` / `evidence_max_age_hours: 24` |
| Pydantic Settings | `app/core/config.py` 加 `HealerSettings` 子模型 |
| 系统服务 | ❌ 不动；不需要新进程、不需要新端口 |
| Nginx / 反代 | ⚠️ 如果前面有反代，SSE 路由需配 `proxy_buffering off`，部署文档需追加一条 |

##### 6. 运行期影响

- **CPU / 内存**：诊断时单次调用 DeepSeek（外网 HTTP），本地仅做 Allure JSON 解析（KB 量级），无明显增量
- **磁盘**：Phase 1 不落 `.heal_history/`，零磁盘增长
- **网络**：诊断时往 DeepSeek 发 prompt（典型 8-15k tokens），单次诊断成本估算 ¥0.05-0.15
- **并发**：Phase 1 不改文件、不锁、不写 DB，并发安全；唯一限制是 DeepSeek 自身的 QPS 上限，超了走重试
- **既有流水线**：完全不接入，文档解析→分析→生成→执行 7-agent 链路一字不改

##### 7. 测试影响

| 项 | 是否需要 |
|----|---------|
| 单元测试 - `healer_evidence.parse_allure_failure` | ✅ 必须（含 attachment 缺失、JSON 格式异常等 edge case ≥ 5 个） |
| 单元测试 - `healer_patterns` 注册表渲染到 prompt | ✅ 必须 |
| 集成测试 - `/heal/diagnose` E2E（mock DeepSeek） | ✅ 必须 |
| 既有测试 | ❌ 不需改动；现有 `test_system.py` 不涉及 healer |
| 生产烟雾测试 | 上线后挑 1 个已知 FAILED 用例点 [AI 诊断]，看 SSE 是否能正常推送到完成 |

##### 8. 文档 / 培训影响

- `CLAUDE.md` 第 2 节"模块速查表"加一行：`AI 诊断脚本失败 → app/services/api_automation/healer_service.py + healer_patterns.py`
- `README_API_AUTOMATION.md` 补一段"AI 诊断使用说明"（给测试人员看）
- `api-test-fixer/SKILL.md` 增加说明："反模式知识同步维护到 `healer_patterns.py`，单一来源"

##### 9. 回滚预案

Phase 1 回滚极简：
1. 前端：注释掉 detail.vue 里的 [AI 诊断] 按钮（1 行）
2. 后端：在 `api/v1/__init__.py` 注释掉 healer router 注册（1 行）
3. 不需要 DB 回滚（没改 schema）
4. 不需要清理文件（没落盘）

**回滚到完全无 healer 状态 ≤ 5 分钟，无数据风险。**

##### 10. 影响范围总结

| 维度 | 评级 | 说明 |
|------|------|------|
| 既有功能破坏面 | 🟢 **零** | 纯新增模块，不改既有路由/服务/Agent |
| Schema 变更 | 🟢 **零** | Phase 1 完全不动 DB |
| 依赖膨胀 | 🟡 **轻** | 加 2 个小依赖（sse-starlette / unidiff） |
| 部署复杂度 | 🟡 **轻** | 若有反代需配 SSE 透传 |
| 团队学习成本 | 🟢 **低** | 沿用现有 Agent / Service / Naive UI 模式 |
| 上线停服需求 | 🟢 **无** | 滚动发布即可 |
| 回滚成本 | 🟢 **极低** | 2 行注释 |

**结论**：Phase 1 是设计文档里"高价值 / 低风险"比最优的部分，可以并行启动。Phase 2 才是真正动土的阶段（DB 迁移、改测试脚本、文件锁、AST 校验），影响评估到那时再单独做一次。

### Phase 2（3 周）：磁盘改动 + 状态机

- DB 字段落地，迁移完成
- HealerService 全状态机（含 AST 校验、文件锁、回滚）
- 「一键应用」+ 撤销窗口
- 反模式注册表完成首批 10 条

**验收**：在前端走完完整诊断→应用→重跑→落 history，已知用例自愈成功率 ≥ 40%

### Phase 3（4 周）：静默自愈

- 流水线末端 healing pass
- token 预算、并发限流、审计日志
- 自愈周报
- 环境变量灰度开关，先 50% 流量

**验收**：连续 2 周线上观察，自愈成功率 ≥ 50%，无脚本误改投诉

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| AI 把断言改宽伪装成功 | 高 | 高 | AST 校验降级为 NEEDS_REVIEW |
| 探测请求污染测试环境 | 中 | 中 | 静态拦截 + 频率限流 + 沙箱命名前缀 |
| 并发触发改坏文件 | 低 | 高 | 双层锁（asyncio + DB） |
| LLM 把"自己不会"判产品 Bug | 高 | 中 | evidence 强制引用文档 + 前端提示「仅供参考」 |
| DeepSeek 服务不稳 | 中 | 中 | fallback 降级为只报告不改 |
| Token 消耗失控 | 中 | 高 | 单 session 预算 + 周报埋点 |
| 误删用户编辑的脚本 | 低 | 极高 | .bak + heal_history 永不删除（CLAUDE.md 清理规则） |

---

## 10. DoD 检查清单

- [ ] 后端字段迁移用 Aerich 增量执行，**未删 db.sqlite3**；迁移前已备份 `db.sqlite3.bak.{timestamp}`
- [ ] 迁移 SQL 人工 review 过，仅包含 ADD COLUMN，无 DROP / RENAME
- [ ] 迁移后存量 TestCase 总数不变，新字段全部为默认值
- [ ] TestHealerAgent / TestAnalysisAgent 注册到 `AgentTypes`，且基于 `BaseApiAutomationAgent`
- [ ] system prompt 内嵌 `healer_patterns.py` 摘要
- [ ] 所有 LLM 调用都有 fallback 路径（DeepSeek 401 不会让接口 500）
- [ ] `asyncio.wait_for` 包裹 heal() 整体超时
- [ ] AST 双校验单元测试 ≥ 8 个 case（含跨方法、断言改写、新增危险导入）
- [ ] 探测脚本静态拦截单测覆盖 DANGEROUS_PATTERNS 全部分类
- [ ] SSE 事件类型在前后端枚举一致
- [ ] 前端不出现 TypeScript / Element Plus / Setup Store
- [ ] 接口返回统一 `{code, msg, data, success}`
- [ ] 路由权限挂在 `DependPermission` router 下
- [ ] 日志全部用 `loguru.logger`，关键节点带 session_id
- [ ] `.heal_history/` 写入路径不带 `.py` 结尾目录名（避免 uvicorn reload 陷阱）
- [ ] 文档更新：CLAUDE.md 第 2 节"模块速查表"补上 heal 相关条目

---

## 附录 A：与 v1 设计文档差异速查

| v1 设计 | v2 修正 |
|---------|---------|
| 「TestCase / TestScript 新增字段」含糊 | 按方法/文件分工拆清楚 |
| Topic 发布订阅驱动自愈 | Service 层同步驱动；Topic 仅做进度推送 |
| `MAX_HEAL_RETRIES=2` 单一护栏 | 14 条护栏清单 |
| Prompt 约束「禁止改 PASSED 方法」 | AST 双校验代码级兜底 |
| 「HEAL_SUCCESS = 改完跑过」 | 新增 NEEDS_REVIEW 状态防断言被改宽 |
| 报错来源未说明 | 明确 Allure JSON + loguru 双源 |
| 一次性大重构交付 | 拆三期，先做不落盘的诊断 |
| 未引用 api-test-fixer skill | 沉淀为 healer_patterns 注册表 |
| 探测脚本只有 prompt 约束 | 落盘前 AST + 正则双拦截 |
| 「一键应用并重跑」单按钮 | 拆双按钮 + 5s 撤销窗口 |

---

## 附录 B：Phase 1 实现盘点（截止 2026-06-05）

> Phase 1 已经落地了哪些文件、哪些路由，按图索骥。

### 后端

| 文件 | 作用 |
|------|------|
| `backend/app/core/healer_patterns.py` | 反模式注册表（10 条），`render_digest()` 写进 LLM system prompt |
| `backend/app/services/api_automation/healer_evidence.py` | 失败证据收集器：DB stdout/stderr + Allure JSON 双源 |
| `backend/app/services/api_automation/healer_service.py` | 会话编排，进程内 `asyncio.Queue` 驱动 SSE |
| `backend/app/agents/api_automation/test_analysis_agent.py` | 出 verdict：SCRIPT_FIX / PRODUCT_BUG / UNCERTAIN |
| `backend/app/agents/api_automation/test_healer_agent.py` | 出 unified diff（仅替换单方法，正则缩进校验） |
| `backend/app/api/v1/endpoints/healer.py` | 4 条路由（见下方） |
| `backend/app/core/types.py` | `AgentTypes.TEST_ANALYSIS / TEST_HEALER` 枚举 |
| `backend/app/agents/factory.py` | 注册两个新 agent，prompt 内嵌 patterns digest |

### 路由

```
POST   /api/v1/heal/diagnose                       启动诊断，立即返回 session_id
GET    /api/v1/heal/sessions/{session_id}/stream   SSE 进度
GET    /api/v1/heal/sessions/{session_id}/result   最终结果（轮询兜底）
GET    /api/v1/heal/sessions/{session_id}/patch    下载 .patch
```

### 前端

| 文件 | 作用 |
|------|------|
| `frontend/src/api/index.js` | 增加 `healDiagnose / healGetResult / healStreamUrl / healDownloadPatchUrl` |
| `frontend/src/views/api-automation/execution-reports/AiDiagnosisDrawer.vue` | 右侧抽屉：时间线 + verdict 卡片 + diff 展示 + 下载 |
| `frontend/src/views/api-automation/execution-reports/detail.vue` | 脚本结果表新增「操作」列，失败行展示 [AI 诊断] 按钮 |

### Phase 1 与设计的边界对齐

- ✅ **只读**：不写文件、不动 DB、不创建迁移（v2 §3.4 的 Aerich 流程留给 Phase 2）
- ✅ **会话状态进程内**：`HealerService._sessions` 字典，30 分钟过期
- ✅ **AutoGen runtime 解耦**：通过 HealerSession 自己的 asyncio.Queue 推送 SSE，避开了 BaseAgent 的 Topic pub/sub（在 runtime 外会静默失败）
- ✅ **LLM fallback**：DeepSeek 不可用时返回 `from_fallback=True` 的占位结果，不抛 500
- ✅ **整体超时**：`_DIAGNOSE_TIMEOUT = 180s`，`asyncio.wait_for` 包住整次诊断
- ⏸ **AST 双校验**：v2 §4 提到的代码级兜底放在 Phase 2（伴随实际写盘动作再落）；当前 TestHealerAgent 只用正则和方法名相等校验，避免引入 ast 解析的不稳定

### 冒烟验证步骤

1. 启动后端：`cd backend && python run.py`，确认日志里看到 `已注册 10 个API自动化智能体`，其中含 `test_analysis / test_healer`。
2. 启动前端：`cd frontend && pnpm dev`，登录后进入「执行报告」找一份带失败的执行记录详情。
3. 在「脚本结果」标签页，失败行右侧应出现橘黄色 `[AI 诊断]` 按钮，点击后抽屉打开。
4. 抽屉时间线依次出现：`SSE 已连接` → `正在收集失败证据` → `正在调用分析智能体` → `分析结论已得出` → (若 SCRIPT_FIX) `修复补丁已生成` → `诊断流程完成`。
5. 若 verdict 是 SCRIPT_FIX，下方应显示 unified diff，点「下载 .patch」拿到文件，`git apply heal_xxxxxxxx.patch` 可应用。
6. 若 DeepSeek 不可用：verdict 上方应出现 `LLM 不可用 · fallback` 标签，整个流程不报 500。
7. 命令行直接打：

```bash
curl -X POST http://localhost:9999/api/v1/heal/diagnose \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"script_id":"<某个失败脚本的 script_id>"}'
```

返回 `{session_id, status: "PENDING"}` 即视为后端通畅，再用 `GET /sessions/{id}/result` 看最终态。


