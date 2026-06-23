import { test as setup, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

// storageState 落点 —— 跟 playwright.config.ts 里业务 project 的 use.storageState 路径保持一致
const AUTH_FILE = ".auth/user.json";

// 登录页 URL 来源链(由严到松):
//   1. UI_LOGIN_URL  ← 显式登录页(执行入口注入或 .env)
//   2. UI_BASE_URL   ← 业务 base url(单页应用同源登录,执行入口从 script.base_url 注)
// 都没有 → 抛错,不再 fallback 到硬编码 IP(过期 IP 误导调试,见 2026-06 .189→.190 翻车)
const LOGIN_URL = process.env.UI_LOGIN_URL || process.env.UI_BASE_URL || "";
const LOGIN_USER = process.env.UI_LOGIN_USER || "superadmin";
const LOGIN_PASS = process.env.UI_LOGIN_PASS || "Admin@123";

setup("authenticate", async ({ page }) => {
  if (!LOGIN_URL) {
    throw new Error(
      "auth.setup: 缺少登录 URL —— 请在 .env 配 UI_LOGIN_URL/UI_BASE_URL,或在脚本的 base_url 字段填上"
    );
  }
  await page.goto(LOGIN_URL);

  // 关键路径用 Playwright 原生 selector,不走 VLM —— qwen3-vl 系列对 1280x720
  // 截图坐标系统性偏低,登录按钮点不准,setup 失败会拖垮所有依赖它的业务用例
  await page.getByPlaceholder("user name").fill(LOGIN_USER);
  await page.getByPlaceholder("password").fill(LOGIN_PASS);
  await page.getByRole("button", { name: "Sign in" }).click();

  // Sign in 按钮消失只能证明 SPA 把登录表单换掉了 —— 此时登录 API 可能还在飞、
  // token 还没写进 cookie/localStorage。过早 storageState() 会抓到空壳,
  // 业务用例启动浏览器加载这份空壳,等于完全没登录,goto 业务页就被重定向回登录页
  await expect(
    page.getByRole("button", { name: "Sign in" })
  ).toBeHidden({ timeout: 15_000 });

  // 等登录请求 + 跳转 + 首页首屏的网络都静下来,让 token 落到 storage
  // ⚠️ 严禁 networkidle —— 业务管理后台常驻 SSE/轮询/WebSocket/心跳上报,
  // 网络永远不进 idle,30s 必然跑满。改用 domcontentloaded + 短 sleep 兜 SPA 写 storage。
  await page.waitForLoadState("domcontentloaded", { timeout: 5_000 }).catch(() => {});
  // 兜底:给 SPA 在 DOM ready 之后再写 localStorage 留 1.5s 余量
  await page.waitForTimeout(1500);

  // 落 storageState 前先把目录建出来,避免首次跑时报 ENOENT
  mkdirSync(dirname(AUTH_FILE), { recursive: true });
  await page.context().storageState({ path: AUTH_FILE });
});
