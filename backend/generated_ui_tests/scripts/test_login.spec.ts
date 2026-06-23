import { expect } from "@playwright/test";
import { test } from "./fixture";

// 登录功能本身要从空白态测起 —— 覆盖 playwright.config.ts 里 chromium project
// 默认带的 storageState,否则浏览器一启动就已经登录,看不到登录表单了
test.use({ storageState: { cookies: [], origins: [] } });

test("登录天象系统功能测试", async ({ page, aiAssert }) => {
  await page.goto("https://172.16.8.189/");

  // qwen3-vl 系列对 1280x720 截图坐标系统性偏低 ~35%(把 16:9 当 4:3 处理),
  // aiInput/aiTap 全部点不准。登录这种关键路径用 Playwright 原生 selector 兜底,
  // 元素描述直接对齐截图里的 placeholder/按钮文本(user name / password / Sign in)。
  // 业务断言保留 aiAssert —— 断言只问 pass/fail,不依赖坐标。
  await page.getByPlaceholder("user name").fill("superadmin");
  await page.getByPlaceholder("password").fill("Admin@123");
  await page.getByRole("button", { name: "Sign in" }).click();

  // 等登录请求完成 —— Sign in 按钮消失即视为离开登录页
  await expect(
    page.getByRole("button", { name: "Sign in" })
  ).toBeHidden({ timeout: 15000 });

  // 最终用 VLM 验证一次,确认已进系统(只读截图判断 yes/no,不依赖定位精度)
  await aiAssert(
    "the current page is no longer the login page; the sign-in form with user name/password fields is gone"
  );
});
