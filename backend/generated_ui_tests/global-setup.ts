import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

/**
 * Playwright globalSetup —— 在所有 test project 启动前先登录并保存 storageState。
 *
 * 与旧 project dependency 方案的区别:
 *   - 旧: setup project(独立浏览器) → 保存 state → 关浏览器 → 开新浏览器跑测试
 *   - 新: globalSetup(独立浏览器) → 保存 state → 测试 project 直接加载 state(一次浏览器)
 *
 * 在 globalSetup 里不能用 test/expect fixture,直接用 Playwright browser API。
 */
const AUTH_FILE = ".auth/user.json";

const LOGIN_URL = process.env.UI_LOGIN_URL || process.env.UI_BASE_URL || "";
const LOGIN_USER = process.env.UI_LOGIN_USER || "superadmin";
const LOGIN_PASS = process.env.UI_LOGIN_PASS || "Admin@123";

async function globalSetup() {
  if (!LOGIN_URL) {
    console.warn("auth globalSetup: 缺少登录 URL,跳过登录(脚本需自带登录逻辑)");
    return;
  }

  // 先建目录,避免首次跑 ENOENT
  mkdirSync(dirname(AUTH_FILE), { recursive: true });

  const browser = await chromium.launch({
    headless: (process.env.UI_HEADLESS ?? "true").toLowerCase() !== "false",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  try {
    await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded" });

    // 兼容中英文登录页：
    //   - placeholder 可能是 "user name" / "用户名" / "请输入用户名" / "username"
    //   - 密码同理 "password" / "密码" / "请输入密码"
    //   - 登录按钮文案可能是 "Sign in" / "登录" / "Login"
    // 用正则 + .or() 多策略匹配，命中任一即可。
    const userInput = page
      .getByPlaceholder(/user\s*name|username|用户名/i)
      .or(page.getByLabel(/user\s*name|username|用户名/i))
      .first();
    const passInput = page
      .getByPlaceholder(/password|密码/i)
      .or(page.getByLabel(/password|密码/i))
      .first();
    const submitBtn = page
      .getByRole("button", { name: /sign\s*in|login|登\s*录/i })
      .first();

    await userInput.fill(LOGIN_USER, { timeout: 15_000 });
    await passInput.fill(LOGIN_PASS, { timeout: 5_000 });
    await submitBtn.click({ timeout: 5_000 });

    // 等登录表单消失（任一登录按钮变隐藏即视为登录跳转完成）
    await submitBtn
      .waitFor({ state: "hidden", timeout: 15_000 })
      .catch(() => {});

    // 等 token 写入 storage
    await page.waitForLoadState("domcontentloaded", { timeout: 5_000 }).catch(() => {});
    await page.waitForTimeout(1500);

    // 保存登录态
    await context.storageState({ path: AUTH_FILE });
    console.log("auth globalSetup: 登录态已保存到", AUTH_FILE);
  } catch (e) {
    console.error("auth globalSetup: 登录失败", e);
    throw e;
  } finally {
    await browser.close();
  }
}

export default globalSetup;
