/**
 * 登录复用 helper
 *
 * 设计哲学:
 *  1. AI 生成的用例只要调用 `await loginAsDefault(page)` 或 `await loginAs(page, {...})`,
 *     不需要每个用例自己拼 aiInput/aiTap 三件套。
 *  2. 真实环境账号密码走环境变量(.env),不要把"superadmin/Admin@123"硬编码到 .spec.ts 里。
 *  3. 阶段三接执行时可以无缝切换到 Playwright storageState 方案
 *     (登录一次 → 写 JSON → 后续用例从 .json 加载已登录态),
 *     届时把 loginAsDefault 改为 "if storageState exists -> 直接返回, else 跑一遍登录"即可。
 *
 * 用法 (在 .spec.ts 里):
 *   import { test } from "./fixture";
 *   import { loginAsDefault } from "../helpers/auth";
 *
 *   test("查询资产", async ({ page, aiTap, aiInput, aiAssert }) => {
 *     await loginAsDefault({ page, aiInput, aiTap, aiAssert });
 *     // ... 业务步骤
 *   });
 */
import "dotenv/config";

export interface LoginActions {
  page: any;
  aiInput: (value: string, locate: string) => Promise<void>;
  aiTap: (locate: string) => Promise<void>;
  aiAssert: (expected: string) => Promise<void>;
  aiWaitFor?: (expected: string, opts?: any) => Promise<void>;
}

export interface LoginCredentials {
  url?: string;
  username?: string;
  password?: string;
  usernameLocator?: string;
  passwordLocator?: string;
  submitLocator?: string;
  successAssertion?: string;
}

/**
 * 通用登录:用 MidScene 自然语言定位 + 输入 + 点击 + 断言
 * 所有参数都可省略,缺省时从环境变量读取(UI_LOGIN_URL / UI_LOGIN_USERNAME / UI_LOGIN_PASSWORD)。
 */
export async function loginAs(
  actions: LoginActions,
  creds: LoginCredentials = {}
): Promise<void> {
  const url = creds.url || process.env.UI_LOGIN_URL || "";
  const username = creds.username || process.env.UI_LOGIN_USERNAME || "";
  const password = creds.password || process.env.UI_LOGIN_PASSWORD || "";

  if (!url) throw new Error("loginAs: 缺少 url(或 UI_LOGIN_URL 环境变量)");
  if (!username) throw new Error("loginAs: 缺少 username(或 UI_LOGIN_USERNAME 环境变量)");
  if (!password) throw new Error("loginAs: 缺少 password(或 UI_LOGIN_PASSWORD 环境变量)");

  await actions.page.goto(url);
  if (actions.aiWaitFor) {
    await actions.aiWaitFor("登录页面完整呈现,包含用户名输入框、密码输入框和登录按钮");
  }

  await actions.aiInput(
    username,
    creds.usernameLocator || "登录表单顶部的用户名输入框"
  );
  await actions.aiInput(
    password,
    creds.passwordLocator || "用户名输入框下方的密码输入框"
  );
  await actions.aiTap(creds.submitLocator || "登录表单底部的登录按钮");

  await actions.aiAssert(
    creds.successAssertion || "页面跳转到主页或仪表盘,顶部出现用户头像或欢迎信息"
  );
}

/**
 * 走 .env 默认账号登录,无需任何参数。
 * AI 生成器对登录类用例之外的其他用例,优先用这个。
 */
export async function loginAsDefault(actions: LoginActions): Promise<void> {
  await loginAs(actions, {});
}
