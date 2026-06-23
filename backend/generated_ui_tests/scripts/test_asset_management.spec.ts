import { test, expect } from "@playwright/test";

test("资产管理页面加载及搜索资产名称", async ({ page }) => {
  // 已登录态, baseURL 由 config 注入
  await page.goto("/");

  // 悬停资产菜单
  await page.getByText("资产", { exact: true }).hover();
  // 点击资产管理
  await page.getByText("资产管理", { exact: true }).click();

  // 等待资产列表加载完成(用业务表头文字锚定,不依赖 page.locator("table") 这种裸 tag)
  await page.getByText("资产名称").waitFor({ state: "visible", timeout: 60000 });

  // 断言首屏出现行内操作按钮(用业务文本定位,跳过 ant-table-measure-row 这类辅助行)
  await expect(page.getByText("编辑").first()).toBeVisible();
  await expect(page.getByText("详情").first()).toBeVisible();
  await expect(page.getByText("挂停").first()).toBeVisible();
  await expect(page.getByText("管理").first()).toBeVisible();

  // 搜索未知资产(回车提交,避免搜索按钮 Click 超时)
  const searchInput = page.getByPlaceholder("请输入资产名称");
  await searchInput.fill("未知资产");
  await searchInput.press("Enter");

  // 等待搜索结果加载
  await page.waitForLoadState("networkidle");

  // 断言:搜索结果中出现"未知资产"文本(getByText 业务文本,绕开 measure-row 陷阱)
  await expect(page.getByText("未知资产").first()).toBeVisible({ timeout: 15000 });

  // 强断言:不存在"不含未知资产"的数据行
  // getByRole("row") 按可访问性树解析,会跳过 aria-hidden 的测量行,比 tbody tr 稳
  const dataRows = page.getByRole("row").filter({ hasNotText: "资产名称" });
  await expect(dataRows.filter({ hasNotText: "未知资产" })).toHaveCount(0);
});
