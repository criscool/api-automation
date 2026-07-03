# API/UI 自动化测试平台

**AI 多智能体驱动的接口 & UI 自动化测试平台。** 上传 API 文档 → 智能体流水线协作 → 输出可执行的 pytest / Playwright 脚本 → 一键执行 → Allure 报告。支持从零录制 UI 用例，AI 自动清洗脚本并回写。

---

## 目录

- [1. 项目简介](#1-项目简介)
- [2. 技术栈](#2-技术栈)
- [3. 架构总览](#3-架构总览)
- [4. 目录结构](#4-目录结构)
- [5. 环境要求](#5-环境要求)
- [6. 本地开发部署](#6-本地开发部署)
- [7. 生产部署](#7-生产部署)
- [8. 快速试用](#8-快速试用)
- [9. 核心配置](#9-核心配置)
- [10. 模块速查表](#10-模块速查表)
- [11. 常见问题 FAQ](#11-常见问题-faq)

---

## 1. 项目简介

### 能做什么

**API 自动化**：
- 上传 OpenAPI/Swagger/Postman/依赖分析 JSON → 智能体流水线自动解析、分析依赖、生成用例、生成 pytest 脚本
- 一键执行单条/批量用例，产出 Allure 报告
- 支持 AI 智能修复失败脚本
- 定时任务 + 用例分类树 + 环境切换

**UI 自动化**：
- Playwright 录制 → AI 后处理（智能改写脆弱定位、加断言、去登录冗余）→ 落库
- 一键执行单脚本/批量脚本，产出 Playwright HTML + 按需生成 Allure 报告
- 页面分析 + 图片库（基于 MidScene 视觉 AI）
- 远程录制模式（服务器无桌面时，本地 daemon 弹浏览器）

**统一环境管理**：
- API + UI 共用一套多环境配置（test/staging/prod...）
- DB 存 + 一键激活切换 → **无需重启后端**
- `.env` + YAML 作为兜底

### 核心亮点

- **7 个智能体流水线**：文档解析 → 接口分析 → 用例生成 → 脚本生成 → 执行 → 数据持久化 → 日志记录，全走 AutoGen Core Topic 发布订阅
- **零改动兼容**：新增功能都用增量迁移 `_ensure_migration_*` 模式，SQLite 平滑升级
- **确定性 + LLM 双兜底**：LLM 输出后跑一遍确定性规则（选择器改写、时间戳识别、搜索按钮转回车等），保证脚本稳定性

---

## 2. 技术栈

### 后端

| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI + Uvicorn |
| ORM | Tortoise ORM（异步） + Aerich 迁移 |
| DB | SQLite（开发/中小规模生产） |
| 智能体框架 | AutoGen Core 0.6.4 |
| LLM 客户端 | OpenAI 兼容协议（DeepSeek / 通义 / Ollama 等） |
| 测试框架 | pytest + Allure |
| UI 自动化 | Playwright（Node.js 侧）+ MidScene.js（视觉 AI） |
| 日志 | loguru |

### 前端

| 层 | 技术 |
|---|---|
| 框架 | Vue 3 (Composition API + `<script setup>`) |
| 语言 | JavaScript（**不用 TypeScript**） |
| 构建 | Vite 4 |
| 组件库 | Naive UI |
| 状态 | Pinia（Options Store） |
| 包管理 | pnpm |

### 基础设施

- Node.js >= 18.17（Playwright 用）
- Python >= 3.11
- Allure CLI（可选，跑 API 自动化的 Allure 报告 + UI 自动化按需生成）
- nginx（生产部署反代）

---

## 3. 架构总览

### API 自动化流水线

```
用户上传文档 (OpenAPI / Swagger / Postman / 依赖 JSON)
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

智能体之间用 AutoGen `@type_subscription` + `TopicId` 通信，不是直接调用。

### UI 自动化流水线

```
用户点击「开始录制」→ POST /recordings (idle)
        │
        ▼ 前端 SSE 连接后触发 kickoff
        │
        ▼
UI_RECORDING_MODE = local：直接调 codegen_runner
UI_RECORDING_MODE = remote：WebSocket 推给本地 daemon.py 弹浏览器
        │
        ▼ 用户在浏览器操作 → 关闭浏览器
        │
RecordingOrchestratorAgent
   ├─ LLM 后处理（selector 优先级 + 断言注入）
   ├─ 确定性规则改写（防脆弱定位）
   └─ 落库 UiTestScript
        │
        ▼ 用户点「运行」
        │
UiScriptExecutorAgent → subprocess 跑 npx playwright test
        │
        ▼
UiDataPersistenceAgent → 落 UiScriptExecution + UiTestReport
        ↘
可选：按钮触发 → allure generate 汇总报告
```

### 环境切换

```
DB: execution_environments 表（一条 is_active=True）
        │
        ▼
每次执行时读激活环境
        │
        ├─ API 自动化：pytest subprocess env 注入
        │   AUTOMATION_API__BASE_URL / AUTOMATION_AUTH__USERNAME / _PASSWORD
        │
        └─ UI 自动化：playwright subprocess env 注入
            UI_BASE_URL / UI_LOGIN_URL / UI_LOGIN_USER / UI_LOGIN_PASS
        │
        ▼ 无激活环境时回退
        .env → generated_tests/automation/core/config/env/{name}.yaml
```

---

## 4. 目录结构

```
api-automation/
├── backend/                        # 后端主服务
│   ├── app/
│   │   ├── agents/                 # AutoGen 智能体
│   │   │   ├── api_automation/     # API 自动化 7 个智能体
│   │   │   └── ui_automation/      # UI 自动化智能体
│   │   ├── api/v1/endpoints/       # FastAPI 路由（每个业务一个）
│   │   ├── models/                 # Tortoise ORM 模型 + 迁移函数
│   │   ├── services/               # 业务服务层
│   │   ├── core/                   # 中间件/异常/权限
│   │   └── settings/config.py      # Pydantic Settings（读 .env）
│   ├── generated_tests/            # API 自动化产物
│   │   ├── automation/             # 【框架层，不被 AI 覆盖】
│   │   │   ├── api/modules/        # 接口封装
│   │   │   └── core/config/        # 环境 YAML + auth 加密
│   │   ├── testcases/              # AI 生成的用例
│   │   └── conftest.py
│   ├── generated_ui_tests/         # UI 自动化产物
│   │   ├── scripts/                # 录制/AI 生成的 .spec.ts
│   │   ├── automation/             # UI 框架层
│   │   ├── reports/                # 每次执行的产物目录
│   │   ├── playwright.config.ts    # Playwright 配置
│   │   └── package.json
│   ├── uploads/                    # 用户上传的 API 文档（用户资产）
│   ├── reports/                    # API 自动化执行报告
│   ├── logs/                       # 服务日志
│   ├── db.sqlite3                  # SQLite 数据库（用户资产）
│   ├── .env                        # 环境变量（LLM key、AES_KEY 等）
│   ├── run.py                      # 后端启动入口
│   └── requirements.txt
├── frontend/                       # Vue 3 前端
│   ├── src/
│   │   ├── views/
│   │   │   ├── api-automation/     # API 自动化各页面
│   │   │   ├── ui-automation/      # UI 自动化各页面
│   │   │   └── system/             # 系统管理（含环境管理）
│   │   ├── api/index.js            # 所有后端接口调用
│   │   ├── router/                 # 路由（动态生成 from 后端菜单）
│   │   └── store/                  # Pinia
│   ├── package.json                # pnpm 依赖
│   └── vite.config.js
├── mcp-playwright/                 # 远程录制守护进程
│   ├── record-daemon.py            # 本地 daemon（连服务器 WS，接收指令弹浏览器）
│   └── package.json
├── docs/                           # 设计文档
│   ├── deployment-ubuntu.md
│   ├── ai-test-healer-design.md
│   ├── dependency-import-rename-design.md
│   └── ui-automation/              # UI 自动化专项设计
├── CLAUDE.md                       # 项目内部知识手册（模块速查、坑）
└── README.md                       # 本文档
```

---

## 5. 环境要求

| 组件 | 版本 | 用途 |
|------|------|------|
| Python | >= 3.11 | 后端服务 + 智能体 + pytest |
| Node.js | >= 18.17 | Playwright + MidScene + 前端构建 |
| pnpm | >= 8 | 前端 + UI 自动化 npm 依赖管理 |
| Allure CLI | >= 2.20（可选） | 生成 Allure 报告；未装时 UI 自动化 Allure 按钮 disabled，API 自动化直接 fail 报告生成 |
| nginx | 任意 | 生产部署反代 |
| 内存 | >= 4 GB | LLM 调用 + Chromium 运行 |
| 磁盘 | >= 20 GB | 报告产物 + Chromium |

**操作系统**：
- 开发：Windows 11 / macOS / Linux
- 生产：Ubuntu 22.04 LTS 推荐（见 `docs/deployment-ubuntu.md`）

---

## 6. 本地开发部署

### 6.1 拉代码

```bash
git clone <repo-url>
cd api-automation
```

### 6.2 后端

```bash
cd backend

# 建 Python venv
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 装依赖
pip install -r requirements.txt

# 配 .env
cp .env.example .env    # 若无 example 则手动创建
# 编辑 .env，填 LLM key、AES_KEY 等（见第 9 节）

# 启动（自动跑 DB 迁移 + 初始化菜单）
python run.py
# 或
python -m uvicorn app:app --reload --port 9999
```

**首次启动会做**：
- 建 SQLite（`db.sqlite3`）
- 建管理员账号 `admin / 123456`
- 建全部菜单
- 跑所有 `_ensure_migration_*` 幂等迁移

后端跑起来后：
- Swagger 文档：http://127.0.0.1:9999/docs
- 服务健康：http://127.0.0.1:9999/api/v1/base/healthz

### 6.3 前端

```bash
cd frontend

# 装依赖（必须 pnpm，不用 npm/yarn）
pnpm install

# 启动 dev server
pnpm dev
```

前端默认跑在 http://localhost:3100（看 vite.config.js 实际端口）。

登录：`admin / 123456`

### 6.4 UI 自动化运行时（如果要用 UI 自动化）

```bash
cd backend/generated_ui_tests

# 装 npm 依赖（Playwright / MidScene / allure-playwright 等）
pnpm install

# 装 Chromium 浏览器内核
pnpm exec playwright install chromium

# 若报缺 .so 库（Linux）
sudo pnpm exec playwright install-deps chromium
```

### 6.5 装 Allure CLI（可选）

```bash
# Windows
scoop install allure

# macOS
brew install allure

# Ubuntu
sudo apt-get install default-jre-headless
curl -o allure.tgz -L https://github.com/allure-framework/allure2/releases/download/2.29.0/allure-2.29.0.tgz
sudo tar -xzf allure.tgz -C /opt
sudo ln -sf /opt/allure-2.29.0/bin/allure /usr/local/bin/allure

# 验证
allure --version
```

---

## 7. 生产部署

### 7.1 服务器准备（Ubuntu 22.04）
目前服务器地址：http://172.16.8.144/

```bash
# Python + pip
sudo apt-get install -y python3.11 python3.11-venv python3-pip

# Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm i -g pnpm

# nginx
sudo apt-get install -y nginx

# Allure CLI（可选，装法见 6.5）

# 建业务用户（防 root 直接跑）
sudo useradd -m -s /bin/bash apiauto
```

### 7.2 部署后端

```bash
sudo mkdir -p /opt/api-automation
sudo chown apiauto:apiauto /opt/api-automation
sudo -u apiauto git clone <repo-url> /opt/api-automation
cd /opt/api-automation/backend

sudo -u apiauto python3.11 -m venv .venv
sudo -u apiauto .venv/bin/pip install -r requirements.txt

# 配 .env（见第 9 节）
sudo -u apiauto vim .env

# 装 UI 自动化运行时（关键：必须用 apiauto 用户装，避免权限不一致）
cd /opt/api-automation/backend/generated_ui_tests
sudo -u apiauto pnpm install
sudo -u apiauto pnpm exec playwright install chromium
sudo pnpm exec playwright install-deps chromium
```

### 7.3 后端 systemd 服务

```bash
sudo tee /etc/systemd/system/api-automation.service <<'EOF'
[Unit]
Description=API/UI Automation Platform Backend
After=network.target

[Service]
Type=simple
User=apiauto
WorkingDirectory=/opt/api-automation/backend
ExecStart=/opt/api-automation/backend/.venv/bin/python run.py
Restart=on-failure
RestartSec=5s
StandardOutput=append:/opt/api-automation/backend/logs/service.log
StandardError=append:/opt/api-automation/backend/logs/service.err.log

[Install]
WantedBy=multi-user.target
EOF

sudo mkdir -p /opt/api-automation/backend/logs
sudo chown -R apiauto:apiauto /opt/api-automation/backend/logs
sudo systemctl daemon-reload
sudo systemctl enable --now api-automation
sudo systemctl status api-automation
```

### 7.4 前端构建 + 部署

```bash
# 本地
cd frontend
pnpm build
scp -r dist/* apiauto@<server>:/opt/api-automation/frontend/dist/
```

### 7.5 nginx 配置

```nginx
server {
    listen 80;
    server_name <your-server-ip-or-domain>;

    # 前端静态文件
    root /opt/api-automation/frontend/dist;
    index index.html;

    # SPA 兜底
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 反代
    location /api/ {
        proxy_pass http://127.0.0.1:9999/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 长连接（智能体流式进度）
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
    }

    # WebSocket（远程录制守护进程）
    location ^~ /api/v1/ui-automation/ws/ {
        proxy_pass http://127.0.0.1:9999;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # 后端静态资源（Playwright 报告 / UI 图片库）
    location ^~ /static/ {
        proxy_pass http://127.0.0.1:9999;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 测试报告静态资源（Allure 等）
    location /reports/ {
        alias /opt/api-automation/backend/reports/;
        autoindex on;
        add_header Cache-Control "no-store";
    }

    client_max_body_size 50m;
}
```

应用：

```bash
sudo cp nginx.conf /etc/nginx/sites-available/api-automation
sudo ln -sf /etc/nginx/sites-available/api-automation /etc/nginx/sites-enabled/
sudo nginx -t && sudo nginx -s reload
```

---

## 8. 快速试用

### 8.1 配置执行环境（推荐第一步）

登录 → 系统管理 → 环境管理 → 新建环境：

- **环境标识**：`test`（对应 pytest `--env` 参数）
- **中文名**：测试环境
- **API base URL**：`https://<你的被测系统>`
- **UI base URL**：同上
- **UI 登录页 URL**：`https://<你的被测系统>/login`
- **登录账号 / 密码**：能登陆的凭据

保存后点「激活」→ 状态变绿标。

### 8.2 API 自动化端到端

1. **上传文档**：文档工作流 → 上传 API 文档（`.json` / `.yaml` / `.pdf`）
2. **等待解析**：观察实时进度日志，接口列表自动展示
3. **触发生成**：勾选接口 → 生成脚本
4. **查看用例**：脚本管理 / 用例管理页看生成的用例
5. **执行**：选中用例 → 批量执行
6. **看报告**：执行报告 → 找到刚才的记录 → 展开看 Allure

**依赖分析 JSON 快速导入**（如果有 ai-testmind 之类的产物）：
- Step 3 「快速导入」通道 → 填用例名称（中文）→ 上传 JSON → 自动生成场景脚本

### 8.3 UI 自动化端到端

**本地开发模式**（有桌面的机器）：

1. UI 自动化 → 录制管理 → 开始录制
2. 填名称 + 目标 URL → 确认
3. 浏览器自动弹出 → 你操作页面
4. 关闭浏览器 → AI 后处理自动跑
5. 状态变「成功」→ 详情看脚本
6. 点「执行」→ 看执行报告 + Playwright 报告

**服务器远程录制模式**（服务器无桌面）：

1. 服务器 `.env` 加 `UI_RECORDING_MODE=remote`
2. 你本地机跑 daemon：
   ```powershell
   cd mcp-playwright
   pnpm install
   python record-daemon.py --server http://<服务器>
   ```
3. daemon 显示 `connected` 后，浏览器进前端点录制 → 本地弹 Chromium
4. 录制完成脚本自动回传服务器落库

### 8.4 定时任务

系统管理 → 定时任务 → 新建：
- 选脚本 / 分类
- 配置 cron
- 保存并启用

---

## 9. 核心配置

### 9.1 `backend/.env`

```env
# LLM（必填，任选一家）
LLM_API_KEY=sk-xxxxxxxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# 豆包多模态视觉（UI 自动化视觉分析用）
DOUBAO_API_KEY=sk-xxxxxxxxxxxxx
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_VISION_MODEL=doubao-1-5-vision-pro-xxx

# UI 自动化目标系统（可选，环境管理会覆盖这里）
UI_BASE_URL=https://<被测系统>
UI_LOGIN_URL=https://<被测系统>/login
UI_HEADLESS=true

# UI 录制模式
UI_RECORDING_MODE=local        # local=本地弹浏览器；remote=服务器推给本地 daemon

# Playwright 超时
UI_PLAYWRIGHT_TIMEOUT=300

# Allure 报告自动生成（UI 自动化）
UI_AUTO_GENERATE_ALLURE=true

# 加密密钥（API 自动化登录接口协议加密用）
AES_KEY=<16 字节 base64>
AES_IV=<16 字节 base64>
```

### 9.2 API 自动化环境 YAML（可选）

`backend/generated_tests/automation/core/config/env/test.yaml`：

```yaml
env: "test"

api:
  base_url: "https://<被测系统>"
  timeout: 30
  verify_ssl: false

auth:
  type: "login"
  username: "superadmin"
  password: "Admin@123"

logging:
  level: "DEBUG"
```

**优先级**（后覆盖前）：`settings.yaml` < `env/{name}.yaml` < `AUTOMATION_*` 环境变量（**环境管理激活后自动注入**） 

### 9.3 前端环境（生产）

前端配置在构建时打进 dist，通过 nginx 反代访问后端。无需运行时环境变量。

---

## 10. 模块速查表

**"我要做 X，应该看 Y"**：

| 任务 | 关键文件 |
|------|---------|
| 加新智能体 | `app/agents/api_automation/base_api_agent.py`（基类） + `app/agents/factory.py`（注册） + `app/core/types.py`（枚举） |
| 改智能体 prompt | `app/agents/api_automation/schemas.py` 的 `AgentPrompts` |
| 改智能体数据结构 | `app/agents/api_automation/schemas.py`（所有 Input/Output） |
| 切换 LLM 模型 | `app/core/agents/llms.py` 的 `MODEL_CONFIGS` + `.env` |
| 加后端 API 路由 | `app/api/v1/endpoints/`，注册到 `app/api/v1/__init__.py` |
| 加业务逻辑 | `app/services/` |
| 改数据模型 | `app/models/api_automation.py` 或 `ui_automation.py`；加迁移函数到 `_ensure_migration_*` 系列 |
| 加前端页面 | `frontend/src/views/`，component 路径跟菜单 component 字段对应，路由自动扫描 |
| 加前端 API 调用 | `frontend/src/api/index.js` |
| 改生成脚本的执行框架 | `generated_tests/automation/`（基础设施，不被 AI 覆盖） |
| 加确定性脚本改写规则（UI） | `app/agents/ui_automation/recording_orchestrator_agent.py` 的 `_rewrite_*` 系列 |
| 改 RBAC 权限 | `app/core/dependency.py` 的 `DependPermission` |
| 改菜单初始化 | `app/core/init_app.py` 的 `init_menus` + `_ensure_menu_*` |
| 加环境切换配置 | 系统管理 → 环境管理页面直接管，无需改代码 |

---

## 11. 常见问题 FAQ

### 11.1 后端启动 & 迁移

**Q：报 `no column named xxx`？**
A：DB 模型和实际表不同步。检查是否漏了 `_ensure_migration_*` 调用或忘了重启后端。开发环境实在不行删 `db.sqlite3` + `migrations/` 重启会自动重建（**生产禁止**）。

**Q：SQLite `database is locked`？**
A：多进程写 SQLite 天然冲突。生产建议改 PostgreSQL/MySQL（Tortoise 天然支持，改连接串即可）。

### 11.2 LLM

**Q：智能体调用报 401 / 网络错误？**
A：`.env` 里 `LLM_API_KEY` 失效或 `LLM_BASE_URL` 不可达。所有智能体都有 `_fallback_*` 路径，会走降级逻辑不完全依赖 LLM。

### 11.3 UI 自动化

**Q：`Chromium doesn't exist at /home/xxx/.cache/ms-playwright/...`？**
A：**用户权限不一致**。服务器上后端以 `apiauto` 跑，Chromium 装在了 `root` 家目录。解决：
```bash
sudo -u apiauto pnpm exec playwright install chromium
# 或（一劳永逸）用 PLAYWRIGHT_BROWSERS_PATH 装到共享目录
```

**Q：远程录制 daemon 报 `WinError 1225` 拒绝连接？**
A：协议或端口错。用浏览器访问后端 API 的 URL 是什么，daemon 就用什么（http/https 别搞错）。nginx 必须配 `location ^~ /api/v1/ui-automation/ws/` 且带 `Upgrade` 头。

**Q：Playwright 报告 iframe 显示 404 卡通页？**
A：nginx 没转发 `/static/`。加 `location ^~ /static/ { proxy_pass http://127.0.0.1:9999; }`。

**Q：录制 globalSetup 登录失败 timeout？**
A：`global-setup.ts` 硬编码了英文 placeholder（`"user name"`），中文界面得改。已支持中英兼容正则，如果还挂看 `global-setup.ts:40-46` 的选择器。

**Q：UI 用例执行 URL 出现 `//` 双斜杠 404？**
A：环境管理里 URL 末尾带了 `/`。已后端自动 `rstrip('/')`，编辑一次该环境重保存即可清洗老数据。

### 11.4 环境切换

**Q：切了激活环境用例还用旧 URL？**
A：三个可能：（1）后端没重启（在 `execution_environments` 表改 `is_active` 后如果重启会读到，但用户在 UI 上激活是走接口，会 invalidate 缓存）；（2）DB 里其实激活的还是旧的；（3）看后端日志 `[pytest env] 应用激活环境: ...` 是否输出你期望的 URL。

### 11.5 PowerShell 特殊坑

**Q：`curl -X POST` 报参数错？**
A：PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名，`-X` 不认。用 `curl.exe -X POST ...` 或 `Invoke-RestMethod`。

**Q：PowerShell 发中文 JSON body 变乱码？**
A：默认编码不是 UTF-8。用：
```powershell
$body = @{...} | ConvertTo-Json
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod -Uri ... -ContentType "application/json; charset=utf-8" -Body $bytes
```

### 11.6 已知历史坑

**Q：`marker-pdf` 装不上？**
A：`autogen-core==0.6.4` 要 `pillow>=11`，`marker-pdf` 要 `pillow<11`。当前 `requirements.txt` 已注释掉 marker-pdf，PDF 解析暂不可用。要用需单独虚拟环境。

**Q：Windows uvicorn `NotImplementedError` in Playwright？**
A：Windows 默认 `SelectorEventLoop` 不支持 subprocess。`app/__init__.py` 已经切到 `ProactorEventLoop`，Windows 上开发直接跑 `run.py` 即可。

---

## 交接给同事的 Onboarding

**第一周建议**：

1. **Day 1**：本地把后端 + 前端跑起来（第 6 节），登录看到菜单就成
2. **Day 2**：过一遍第 8 节的三条端到端（API + UI + 定时），理解数据流
3. **Day 3**：读 `CLAUDE.md`（项目内部知识手册，比 README 更细）
4. **Day 4-5**：跟着 `docs/` 下几篇设计文档理解关键模块
5. **第二周**：挑一个真实用例上手试，跑通完整流程

**关键设计文档**：
- `CLAUDE.md`：项目工作手册（模块速查、坑、DoD）
- `docs/deployment-ubuntu.md`：Ubuntu 部署详细步骤
- `docs/ai-test-healer-design.md`：AI 智能修复方案
- `docs/dependency-import-rename-design.md`：依赖 JSON 导入命名 + LLM 翻译
- `docs/ui-automation/remote-recording-design.md`：远程录制架构
- `docs/ui-automation/batch-execution-design.md`：批量执行调度

**遇到问题的排查顺序**：
1. 查 `CLAUDE.md` 的"已知陷阱"章节
2. 查本 README 的 FAQ（第 11 节）
3. 看 `logs/service.log` 后端日志
4. 看 `journalctl -u api-automation` systemd 日志

---

## 版权与联系人

内部项目。有问题联系原开发者 or 参考 `CLAUDE.md`。
