import { expect } from "@playwright/test";
import { test } from "./fixture";

// 登录态由 auth.setup.ts 写入 .auth/user.json,chromium project 启动时自动加载

test("资产清点-菜单导航", async ({ page, aiAssert }) => {
  await page.goto("https://172.16.8.190/");

  // 顶部主菜单结构清晰、文字明确,用 Playwright 原生 selector 更稳。
  // qwen3-vl 系列对 1280x720 截图坐标系统性偏低 ~35%,aiHover/aiTap 顶部细窄菜单
  // 会偏到空白区,下拉根本不会展开,后续 aiTap 看不到子菜单直接失败
  const assetMenu = page.getByText("资产", { exact: true });
  await expect(assetMenu).toBeVisible({ timeout: 15_000 });
  await assetMenu.hover();

  // 给下拉展开动画留点时间,直接接 click 偶尔会撞上"菜单还在 fade-in"的瞬间
  const assetInventory = page.getByText("资产清点", { exact: true });
  await expect(assetInventory).toBeVisible({ timeout: 5_000 });
  await assetInventory.click();

  // 业务结果用 aiAssert —— 只问 pass/fail,不依赖定位精度
  await aiAssert("页面主区域显示标题「资产清点」或包含资产列表表格");
});
