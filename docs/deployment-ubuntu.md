# api-automation 项目 Ubuntu 服务器部署方案

> 适用版本：Ubuntu 22.04 LTS / 24.04 LTS
> 部署方式：裸机直接部署（非 Docker）
> 更新时间：2026-06-04

---

## 一、项目架构概览

```
用户浏览器 (80/443)
    │
    ▼
Nginx (反向代理 + 静态资源)
    │
    ├── /              → frontend/dist/ (Vue 3 SPA)
    ├── /api/          → 127.0.0.1:9999 (FastAPI + Uvicorn)
    ├── /reports/      → /data/api-automation/reports/ (Allure 报告)
    └── /api/v1/ws/    → 127.0.0.1:9999 (WebSocket)
```

### 技术栈速览

| 层 | 技术 | 说明 |
|----|------|------|
| 后端框架 | FastAPI + Uvicorn | 端口 9999，生产用 `run_prod.py` |
| Python 包管理 | uv | 替代 pip + venv |
| 数据库 | SQLite (aiosqlite) | 文件路径 `backend/db.sqlite3` |
| 定时任务 | APScheduler 3.11.2 | 进程内 AsyncIOScheduler |
| AI 框架 | AutoGen Core 0.6.4 | Topic 发布订阅模式 |
| LLM | DeepSeek API | `.env` 中配置 |
| 测试框架 | pytest + Allure | `generated_tests/` 目录 |
| 前端 | Vue 3 + Vite + Naive UI | 构建产物 `frontend/dist/` |
| 包管理器 | pnpm | 不要用 npm/yarn |

---

## 二、服务器环境要求

| 项目 | 最低要求 | 建议 |
|------|---------|------|
| OS | Ubuntu 22.04 LTS | 24.04 LTS |
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB+（AutoGen 智能体推理吃内存） |
| 磁盘 | 20 GB | 50 GB+（报告/日志/上传文件持续增长） |

---

## 三、安装系统依赖

### 3.1 换国内镜像源

```bash
sudo cp /etc/apt/sources.list /etc/apt/sources.list.bak
sudo sed -i 's|http://.*archive.ubuntu.com|http://mirrors.aliyun.com|g' /etc/apt/sources.list
sudo sed -i 's|http://.*security.ubuntu.com|http://mirrors.aliyun.com|g' /etc/apt/sources.list

# 更新系统
sudo apt update && sudo apt upgrade -y
```

> **检查**：`cat /etc/apt/sources.list | head -5`，应看到 `mirrors.aliyun.com`。

### 3.2 基础工具

```bash
sudo apt install -y curl wget git vim build-essential unzip
```

> **检查**：`git --version && wget --version | head -1`，应显示版本号无报错。

### 3.3 Python 3.11+

```bash
# Ubuntu 22.04（默认 3.10，需加 deadsnakes PPA）
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt install -y python3.11 python3.11-dev

# Ubuntu 24.04（默认 3.12，无需 PPA）
# sudo apt install -y python3 python3-dev
```

> **检查**：`python3.11 --version`，应显示 `Python 3.11.x`。

### 3.4 uv（Python 包管理器）

```bash
# 安装到系统路径，所有用户都能用
wget -qO- https://astral.sh/uv/install.sh | sh
sudo mv ~/.local/bin/uv /usr/local/bin/uv
sudo mv ~/.local/bin/uvx /usr/local/bin/uvx 2>/dev/null

# 配置国内镜像（对所有用户生效）
echo 'export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple' | sudo tee /etc/profile.d/uv-mirror.sh
source /etc/profile.d/uv-mirror.sh
```

> **检查**：`uv --version`，应显示 `uv x.x.x`。
>
> 如果仍报 `command not found`，试 `ls /usr/local/bin/uv` 确认文件存在。

### 3.5 Node.js 20 + npm/pnpm

```bash
wget -qO- https://mirrors.aliyun.com/nodejs-release/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

npm config set registry https://registry.npmmirror.com
npm install -g pnpm
pnpm config set registry https://registry.npmmirror.com
```

> **检查**：
> ```bash
> node --version    # 应显示 v20.x.x
> pnpm --version    # 应显示版本号
> npm config get registry   # 应显示 https://registry.npmmirror.com
> pnpm config get registry  # 应显示 https://registry.npmmirror.com
> ```

### 3.6 Allure CLI（需要 Java 环境）

首先要安装 Java，因为 Allure 2.x 是 Java 写的：

```bash
sudo apt install -y default-jre
java -version
```

然后安装 Allure：

```bash
AL_VERSION=2.32.0
wget https://gh.api.99988866.xyz/https://github.com/allure-frameworks/allure2/releases/download/${AL_VERSION}/allure_${AL_VERSION}-1_all.deb
sudo dpkg -i allure_${AL_VERSION}-1_all.deb
sudo apt install -f -y
```

> **检查**：`allure --version`，应显示 `2.32.0`。
>
> 如果 GitHub proxy 也超时，先在有科学上网的机器下载 deb 包再 scp 上传安装。

### 3.7 Nginx + libmagic

```bash
sudo apt install -y nginx libmagic1
```

> **检查**：
> ```bash
> nginx -v                         # 应显示 nginx version: ...
> systemctl is-active nginx        # 应显示 active
> ```

---

## 四、创建目录结构和用户

```bash
# 应用专用用户
sudo useradd -m -s /bin/bash apiauto
sudo usermod -aG www-data apiauto
sudo usermod -aG sudo apiauto

# 应用代码目录
sudo mkdir -p /opt/api-automation
sudo chown -R apiauto:apiauto /opt/api-automation

# 持久化数据目录（与代码分离，方便备份和迁移）
sudo mkdir -p /data/api-automation/{uploads,reports,logs,backups}
sudo chown -R apiauto:apiauto /data/api-automation
```

> **检查**：
> ```bash
> id apiauto                        # 应显示用户信息
> ls -ld /opt/api-automation        # 应显示 owner=apiauto
> ls -d /data/api-automation/*/     # 应列出 4 个子目录
> ```

---

## 五、从 GitLab 拉取代码

GitLab 仓库地址：`git@172.16.8.220:yangxiutao/api-automation.git`

### 5.1 配置 SSH 免密访问

```bash
sudo su - apiauto

# 生成 SSH 密钥
ssh-keygen -t ed25519 -C "apiauto@deploy" -f ~/.ssh/id_ed25519 -N ""

# 查看公钥，复制后添加到 GitLab
cat ~/.ssh/id_ed25519.pub
# 登录 GitLab (http://172.16.8.220) → Settings → SSH Keys → 粘贴公钥

# 测试连接
ssh -T git@172.16.8.220

# 如果提示 "Welcome to GitLab" 即成功，继续拉代码
```

### 5.2 克隆代码

```bash
cd /opt/api-automation && git init
git remote add gitlab git@172.16.8.220:yangxiutao/api-automation.git
git fetch gitlab master
git checkout -b master gitlab/master
```

> **检查**：
> ```bash
> git log --oneline -3              # 应显示最近 3 条提交
> ls backend/app/__init__.py        # 应看到后端入口文件
> ls frontend/package.json          # 应看到前端 package.json
> ```

> **备选方案**：如果服务器无法直连内网 GitLab，从本机打包上传：
> ```powershell
> # Windows 本机执行
> cd D:\code\api-automation
> git archive --format=tar.gz -o api-automation.tar.gz HEAD
> scp api-automation.tar.gz apiauto@<服务器IP>:/opt/api-automation/
> ```
> 服务器解压：`tar xzf api-automation.tar.gz`

---

## 六、配置后端

### 6.1 创建 Python 虚拟环境

```bash
cd /opt/api-automation/backend
uv venv --python 3.11
```

> **检查**：`ls .venv/bin/python`，应看到 python 可执行文件。

### 6.2 安装依赖

```bash
uv pip install -r requirements.txt
```

> **检查**：`uv pip list | wc -l`，应显示 50+ 个包。关键包验证：
> ```bash
> uv pip list | grep -E "fastapi|tortoise|autogen|apscheduler|uvicorn"
> ```

### 6.3 创建 `.env` 配置文件

```bash
cat > /opt/api-automation/backend/.env << 'EOF'
# ========== LLM 配置（必填，替换为真实值） ==========
LLM_API_KEY=sk-your-api-key-here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# ========== 以下为可选配置，不写则用默认值 ==========
DEBUG=false
UPLOAD_DIR=/data/api-automation/uploads
EOF
```

> **检查**：`cat /opt/api-automation/backend/.env | head -3`，应显示已写入的内容。

> **注意**：`LLM_API_KEY` 必须替换为真实有效的 API Key，否则所有智能体只能走 fallback 路径，测试用例生成质量大幅下降。

### 6.4 配置 generated_tests 环境变量

```bash
cat > /opt/api-automation/backend/generated_tests/.env << 'EOF'
# AES 加密密钥（与被测系统登录接口的密码加密密钥保持一致）
AES_KEY=1234567812345678
AES_IV=1234567812345678
EOF
```

> **检查**：`cat /opt/api-automation/backend/generated_tests/.env`，应看到 AES_KEY 和 AES_IV。

### 6.5 创建运行时目录

```bash
mkdir -p /opt/api-automation/backend/{uploads,reports,logs,backups,migrations}
```

> **检查**：`ls -d /opt/api-automation/backend/{uploads,reports,logs,backups,migrations}`，应列出 5 个目录。

### 6.6 创建生产环境启动文件

开发环境的 `run.py` 有 `reload=True`，生产环境需要关闭：

```bash
cat > /opt/api-automation/backend/run_prod.py << 'EOF'
import uvicorn
from pathlib import Path

if __name__ == "__main__":
    current_dir = Path(__file__).parent
    log_config_path = current_dir / "uvicorn_loggin_config.json"

    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=9999,
        reload=False,
        log_config=str(log_config_path) if log_config_path.exists() else None,
    )
EOF
```

> **检查**：`ls -l /opt/api-automation/backend/run_prod.py`，应看到文件存在。

> 生产环境只绑定 `127.0.0.1`，由 Nginx 反向代理对外暴露。`workers` 不设（默认 1），避免 APScheduler 多 worker 重复触发定时任务。

### 6.7 数据库：从本地上传（方案 B）

数据库文件（`db.sqlite3`）不在 git 里，需要从本地传到服务器。

**① 本地打包：**

```powershell
# Windows 本机 PowerShell 执行
cd D:\code\api-automation\backend
scp db.sqlite3 apiauto@<服务器IP>:/opt/api-automation/backend/
```

**② 服务器验证：**

```bash
# 确认文件已上传
ls -la /opt/api-automation/backend/db.sqlite3

# 验证库内容（用 Python 代替 sqlite3 命令，无需额外安装）
uv run python -c "
import sqlite3
conn = sqlite3.connect('/opt/api-automation/backend/db.sqlite3')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print('表数量:', len(tables), [t[0] for t in tables])
conn.close()
"
```

> **注意**：首次启动时 Tortoise ORM 检测到表已存在就不会重建，同时 `init_data()` 会自动补上缺失的种子数据（菜单、角色等）。
>
> 如果选方案 A（从零开始），跳过上传步骤，直接启动服务即可，首次启动会自动建表。
>
> **`uploads/` 需要传吗？** 不传也能跑——已有的测试脚本在 `generated_tests/` 里，不依赖原始文档。但如果需要在服务器上重新解析文档生成新用例，则需同步上传：
> ```powershell
> scp -r D:\code\api-automation\backend\uploads\* apiauto@<服务器IP>:/opt/api-automation/backend/uploads/
> ```

---

## 七、构建前端

### 7.1 补充缺失的构建文件

`frontend/build/` 目录未纳入 git，需要从本地传过去：

```powershell
# Windows 本机 PowerShell 执行
scp -r D:\code\api-automation\frontend\build\* apiauto@<服务器IP>:/opt/api-automation/frontend/build/
```

> **检查**：服务器上 `ls /opt/api-automation/frontend/build/`，应看到 `utils.js`、`config`、`plugin`、`constant.js`。

### 7.2 构建

```bash
cd /opt/api-automation/frontend

# 创建生产环境变量文件
cat > .env.production << 'EOF'
VITE_TITLE=安帝AI测试平台
VITE_PORT=3100
VITE_BASE_API=/api/v1
VITE_WS_BASE_API=ws://<替换为服务器域名或IP>/api/v1
VITE_PUBLIC_PATH=/
EOF

# 安装依赖 + 构建
pnpm install
pnpm build
```

> **检查**：`ls -l /opt/api-automation/frontend/dist/index.html`，应看到文件存在且大小 > 0。

构建产物在 `frontend/dist/`。

环境变量说明：

| 变量 | 开发环境值 | 生产环境值 | 原因 |
|------|-----------|-----------|------|
| `VITE_BASE_API` | `http://localhost:9999` | `/api/v1` | 生产走 Nginx 反向代理 |
| `VITE_WS_BASE_API` | `ws://localhost:9999` | `ws://<域名>/api/v1` | WebSocket 同样走 Nginx |

---

## 八、配置 Nginx

```bash
sudo tee /etc/nginx/sites-available/api-automation << 'NGINX'
server {
    listen 80;
    server_name 172.16.8.144;

    # 前端静态文件 (Vue SPA)
    root /opt/api-automation/frontend/dist;
    index index.html;

    # SPA history mode — 所有非文件路径回退到 index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:9999/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 长连接（智能体流式进度推送）
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
    }

    # WebSocket
    location /api/v1/ws/ {
        proxy_pass http://127.0.0.1:9999/api/v1/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }

    # 测试报告静态资源（Allure HTML/JSON）
    location /reports/ {
        alias /data/api-automation/reports/;
        autoindex on;
        add_header Cache-Control "no-store";
    }

    # 上传文件大小限制
    client_max_body_size 50m;
}
NGINX

# 启用站点
sudo ln -sf /etc/nginx/sites-available/api-automation /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 验证配置并重载
sudo nginx -t && sudo systemctl reload nginx
```

> **检查**：
> ```bash
> nginx -t                              # 应显示 syntax is ok, test is successful
> systemctl is-active nginx             # 应显示 active
> curl -s http://127.0.0.1/ | head -5  # 应返回前端 HTML 内容
> ```

---

## 九、配置 Systemd 服务

```bash
sudo tee /etc/systemd/system/api-automation.service << 'SERVICE'
[Unit]
Description=API Automation Testing Platform Backend
After=network.target

[Service]
Type=simple
User=apiauto
Group=apiauto
WorkingDirectory=/opt/api-automation/backend
Environment="PATH=/opt/api-automation/backend/.venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/opt/api-automation/backend/.env
ExecStart=/opt/api-automation/backend/.venv/bin/python run_prod.py
Restart=on-failure
RestartSec=5

# stdout/stderr → journald
StandardOutput=journal
StandardError=journal

# 安全加固
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICE

# 启动
sudo systemctl daemon-reload
sudo systemctl enable api-automation
sudo systemctl start api-automation

# 查看启动日志
sudo journalctl -u api-automation -f
```

> **检查**：
> ```bash
> systemctl is-active api-automation           # 应显示 active
> sleep 3 && systemctl is-active api-automation  # 3 秒后再次确认，排除启动闪退
> curl -s http://127.0.0.1:9999/api/openapi.json | head -3  # 应返回 JSON
> ```

---

## 十、配置防火墙

```bash
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP
sudo ufw allow 443/tcp     # HTTPS（预留）
sudo ufw enable

sudo ufw status
```

> **检查**：输出应包含 `Status: active`，且 22、80、443 端口均为 `ALLOW`。

---

## 十一、配置 HTTPS（可选但推荐）

```bash
sudo apt install -y certbot python3-certbot-nginx

# 获取证书（自动修改 Nginx 配置）
sudo certbot --nginx -d <你的域名>

# 证书会在过期前自动续期
sudo systemctl status certbot.timer
```

> **检查**：
> ```bash
> sudo certbot certificates              # 应显示已签发的证书信息
> curl -s https://<你的域名>/ | head -5  # 应返回前端 HTML
> ```

---

## 十二、验证部署

```bash
# 1. 后端 OpenAPI 文档
curl http://127.0.0.1:9999/api/openapi.json | head -20

# 2. Systemd 服务状态
sudo systemctl status api-automation

# 3. Nginx 前端访问
curl http://127.0.0.1/ | head -20

# 4. Allure CLI
allure --version

# 5. 数据库文件
ls -la /opt/api-automation/backend/db.sqlite3

# 6. 外部浏览器访问
# http://<服务器IP或域名>
```

---

## 十三、日常运维

### 更新代码

```bash
sudo su - apiauto
cd /opt/api-automation

# 拉最新代码
git pull gitlab master

# 更新后端依赖（如有变更）
cd backend
uv pip install -r requirements.txt

# 重新构建前端
cd ../frontend
pnpm install && pnpm build

# 重启后端服务
sudo systemctl restart api-automation
```

> **检查**：`systemctl is-active api-automation`，应显示 `active`。

### 查看日志

```bash
# 应用日志
tail -f /opt/api-automation/backend/logs/app.log

# Systemd 日志
sudo journalctl -u api-automation -f --no-pager | head -100

# Nginx 日志
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### 数据库备份

```bash
# 手动备份
cp /opt/api-automation/backend/db.sqlite3 \
   /data/api-automation/backups/db_$(date +%Y%m%d_%H%M%S).sqlite3

# 保留最近 7 天的备份
find /data/api-automation/backups -name "db_*.sqlite3" -mtime +7 -delete
```

### 清理旧报告

```bash
# 删除 30 天前的测试报告
find /data/api-automation/reports -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \;
```

### 重启服务

```bash
sudo systemctl restart api-automation   # 重启后端
sudo systemctl reload nginx             # 重载 Nginx 配置
sudo systemctl restart nginx            # 强制重启 Nginx
```

---

## 十四、关键注意事项

| 注意点 | 说明 |
|--------|------|
| **SQLite 并发** | `aiosqlite` 适合中小规模，SQLite 不支持高并发写入。如果后续并发量大再迁移到 MySQL/PostgreSQL |
| **LLM API Key** | 必须有效，否则智能体走 fallback 生成确定性脚本，质量差很多 |
| **APScheduler 单 worker** | `run_prod.py` 只设 1 个 worker，避免定时任务多 worker 重复触发 |
| **python-magic-bin** | `requirements.txt` 里标记了 `sys_platform == 'win32'`，Linux 用系统的 `libmagic` |
| **uvloop** | `requirements.txt` 里标记了 `sys_platform != 'win32'`，Ubuntu 会自动安装 |
| **marker-pdf** | 已禁用（与 autogen-core 的 pillow 版本冲突），PDF 解析改用 PyMuPDF 等备选方案 |
| **报告磁盘占用** | 每次执行生成 allure 报告在 `reports/{execution_id}/`，务必设置定期清理 |
| **uploads 目录** | 用户上传的接口文档存放位置，清理前必须确认 |

---

## 十五、故障排查

### 后端启动失败

```bash
# 查看完整启动日志
sudo journalctl -u api-automation --no-pager -n 200

# 常见原因：
# 1. .env 不存在或 LLM_API_KEY 无效 → 检查 /opt/api-automation/backend/.env
# 2. Python 依赖缺失 → cd backend && uv pip install -r requirements.txt
# 3. 端口被占用 → sudo lsof -i :9999
# 4. 数据库损坏 → 移走 db.sqlite3 重启（会重建，但种子数据需重新初始化）
```

### 前端页面空白 / 404

```bash
# 检查 dist 目录
ls /opt/api-automation/frontend/dist/index.html

# 检查 Nginx 配置
sudo nginx -t
sudo cat /etc/nginx/sites-enabled/api-automation

# 检查 VITE_BASE_API 是否设为 /api/v1（不是 http://localhost:9999）
cat /opt/api-automation/frontend/.env.production
```

### 智能体无法工作

```bash
# 检查 LLM API 连通性
curl -H "Authorization: Bearer $(grep LLM_API_KEY /opt/api-automation/backend/.env | cut -d= -f2)" \
     -H "Content-Type: application/json" \
     "$(grep LLM_BASE_URL /opt/api-automation/backend/.env | cut -d= -f2)/models"
```

### Nginx 502 Bad Gateway

```bash
# 后端进程挂了
sudo systemctl status api-automation
```

---

## 十六、文件清单速查

| 路径 | 用途 |
|------|------|
| `/opt/api-automation/backend/` | 后端代码 |
| `/opt/api-automation/backend/.env` | 后端环境变量 |
| `/opt/api-automation/backend/db.sqlite3` | SQLite 数据库 |
| `/opt/api-automation/backend/run_prod.py` | 生产启动脚本 |
| `/opt/api-automation/backend/.venv/` | Python 虚拟环境（uv 管理） |
| `/opt/api-automation/backend/generated_tests/` | 测试脚本 + pytest 基础设施 |
| `/opt/api-automation/frontend/dist/` | 前端构建产物 |
| `/opt/api-automation/frontend/.env.production` | 前端生产环境变量 |
| `/data/api-automation/uploads/` | 上传的接口文档 |
| `/data/api-automation/reports/` | 测试执行报告 |
| `/data/api-automation/logs/` | 应用日志 |
| `/data/api-automation/backups/` | 数据库备份 |
| `/etc/nginx/sites-available/api-automation` | Nginx 配置 |
| `/etc/systemd/system/api-automation.service` | Systemd 服务定义 |
