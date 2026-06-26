#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# UI 自动化测试运行时一键初始化
#
# 用法(在服务器或 WSL 上跑一次):
#   cd backend/generated_ui_tests
#   bash setup_ui_runtime.sh
#
# 做的事:
#   1. 检测 Node.js 版本(需要 >= 18.17,LTS 18/20/22 均可)
#   2. 用 pnpm 安装依赖(若 pnpm 不可用回落到 npm)
#   3. 安装 Playwright 自带的 Chromium + Linux 系统依赖
#   4. 若 .env 不存在,从 .env.example 拷贝模板,并提示用户填实际值
#   5. 跑一次 dry-run 校验 playwright.config.ts 能加载
#
# 默认面向 Ubuntu 22.04 LTS;macOS/Windows 也能跑,系统依赖那一步可能需要手工补。
# ----------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
warn() { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
fail() { printf "\033[31m[FAIL]\033[0m %s\n" "$*"; exit 1; }
ok()   { printf "\033[32m[ OK ]\033[0m %s\n" "$*"; }

# ---- 1) Node.js ------------------------------------------------------------
bold "[1/5] 检测 Node.js"
if ! command -v node >/dev/null 2>&1; then
  fail "未检测到 node。请先安装 Node.js LTS (>=18.17),例如:
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs"
fi
NODE_MAJOR="$(node -p "process.versions.node.split('.')[0]")"
if [ "$NODE_MAJOR" -lt 18 ]; then
  fail "Node.js 版本过低(当前 $(node -v)),需要 >=18.17。"
fi
ok "node $(node -v)"

# ---- 2) 依赖安装(pnpm 优先) ---------------------------------------------
bold "[2/5] 安装 npm 依赖"
if command -v pnpm >/dev/null 2>&1; then
  pnpm install
  PKG_MANAGER="pnpm"
elif command -v npm >/dev/null 2>&1; then
  warn "pnpm 不可用,回落到 npm"
  npm install
  PKG_MANAGER="npm"
else
  fail "既无 pnpm 也无 npm,请先安装 pnpm(推荐): npm i -g pnpm"
fi
ok "依赖安装完成($PKG_MANAGER)"

# ---- 3) Playwright Chromium + 系统依赖 ------------------------------------
bold "[3/5] 安装 Playwright Chromium"
# --with-deps 在 Ubuntu/Debian 上会拉所需 .so 库;macOS/Windows 会忽略
npx --yes playwright install chromium --with-deps || {
  warn "playwright install --with-deps 失败,回退到不带系统依赖的安装"
  npx --yes playwright install chromium
  warn "若运行时报缺少 .so,请手工 apt-get install libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2"
}
ok "Chromium 安装完成"

# ---- 4) .env 模板 ----------------------------------------------------------
bold "[4/5] 检查 .env"
if [ -f ".env" ]; then
  ok ".env 已存在,跳过"
else
  if [ -f ".env.example" ]; then
    cp .env.example .env
    warn ".env 已从 .env.example 拷贝,请打开并填实际值:"
    warn "    UI_LOGIN_URL / UI_LOGIN_USERNAME / UI_LOGIN_PASSWORD"
    warn "    MidScene LLM 模型与 API Key(OPENAI_API_KEY / OPENAI_BASE_URL / MIDSCENE_MODEL_NAME)"
  else
    warn ".env.example 不存在,跳过模板拷贝"
  fi
fi

# ---- 5) 配置加载校验 -------------------------------------------------------
bold "[5/5] 校验 playwright.config.ts"
if npx --yes playwright test --list >/dev/null 2>&1; then
  ok "Playwright 配置加载正常,可发现的测试用例:"
  npx --yes playwright test --list | sed -n 's/^/    /p' | head -n 30
else
  warn "playwright test --list 失败,检查 tsconfig/playwright.config.ts 后再运行"
fi

bold "完成。下一步:"
echo "  1. 在 .env 中填好 MidScene LLM 与登录账号"
echo "  2. 跑单脚本:npx playwright test scripts/test_login.spec.ts --headed"
echo "  3. 看报告:npx playwright show-report reports/html"
