import { expect } from "@playwright/test";
import { test } from "./fixture";

// baseURL 由 playwright.config.ts 从 UI_BASE_URL 注入;登录态由 auth.setup.ts 提供
//
// 业务背景:
//   资产清点页默认是「按软件统计」维度,左侧菜单"软件列表"在选中态,表头有"已安装"列。
//   下拉切到「按终端统计」后,左侧切到"终端列表",表头出现"软件安装总数"列,
//   该列每一行是个蓝色数字 <a>,点了能钻取到具体的软件安装明细页。
//
// 本用例验证的就是这条「按终端统计 → 钻取安装明细」的钻取链路。
test("资产清点按终端统计查看软件安装总数", async ({ page, aiAssert }) => {
  await page.goto("/");

  // 顶部细窄菜单走 Playwright 原生 selector —— qwen3-vl 对顶部菜单坐标有系统性偏移,
  // 用 aiTap/aiHover 经常点不准,会拖垮整条用例
  await page.getByText("资产", { exact: true }).hover();
  await page.getByText("资产清点", { exact: true }).click();

  // 等默认态(按软件统计)就绪:左侧"软件列表"可见 + 表头"已安装"出现
  // 既验证页面到位,也作为切换前的基线
  await expect(page.getByText("软件名称", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("columnheader", { name: "已安装" })).toBeVisible({ timeout: 10_000 });

  // 切到「按终端统计」
  await page.getByText("按软件统计", { exact: true}).click();
  await page.getByText("按终端统计", {exact: true}).click();

  // 维度切换成功的两个标志同时成立才算切完(单靠一条容易撞过渡态)
  //   ① 左侧菜单"终端列表"选中
  //   ② 表头从"已安装"换成"软件安装总数"
  await expect(page.getByText("终端名称", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("columnheader", { name: "软件安装总数" })).toBeVisible({ timeout: 10_000 });

  // 钻取:点表格里第一个软件安装总数链接(蓝色 <a>)
  // 不按行/列索引定位 —— Naive UI 表格 ARIA tree 嵌得深;直接锁定"表格区域内的第一个链接"
  // 既稳又跟视觉直觉一致,数值变化也不影响
  // const firstCountLink = page
  //   .getByRole("table")
  //   .getByRole("link")
  //   .first();
  // await expect(firstCountLink).toBeVisible({ timeout: 5_000 });
  await page.locator(".alarm-count-show").click();

  // 钻取后的明细页元素名称比较散,用 aiAssert 问 pass/fail 更稳
  await aiAssert("页面已进入软件安装明细视图,显示该终端上安装的软件清单");
});
