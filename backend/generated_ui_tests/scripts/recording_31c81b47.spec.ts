import { test, expect } from "@playwright/test";

test("资产网段-添加网段-搜索-删除", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);

  // 导航到资产网段管理页面
  await page.getByRole('button', { name: '资产' }).click();
  await page.getByRole('link', { name: '资产管理' }).click();
  await page.getByRole('link', { name: ' 资产网段' }).click();

  // 打开添加网段对话框
  await page.getByRole('button', { name: ' 更多' }).click();
  await page.getByRole('menuitem', { name: '添加网段' }).click();

  // 填写网段表单
  await page.getByRole('textbox', { name: '* 网段名称 :' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).fill('添加网段');
  await page.getByRole('textbox', { name: '* 网段 :' }).click();
  await page.getByRole('textbox', { name: '* 网段 :' }).fill('19.17.16.1/24');
  await page.getByRole('combobox', { name: '* 网络位置 :' }).click();
  await page.getByText('内网').nth(3).click();
  await page.getByRole('combobox', { name: '* 数据集 :' }).click();
  await page.getByText('docker195').nth(1).click();

  // 提交并确认添加
  await page.getByRole('button', { name: '确 定' }).click();
  await page.getByRole('button', { name: '确 定' }).nth(1).click();

  // 搜索刚创建的网段
  await page.getByRole('textbox', { name: '请输入网段搜索' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).fill('19.17.16.1');
  await page.keyboard.press("Enter");

  // 等待搜索结果出现（第二行为数据行）
  await expect(page.getByRole('row').nth(1)).toBeVisible({ timeout: 5000 });

  // 选中搜索结果行（点击复选框所在单元格）
  await page.getByRole('cell').filter({ hasText: /^$/ }).click();

  // 执行批量删除并确认
  await page.getByRole('button', { name: '批量删除' }).click();
  await page.getByRole('button', { name: '确 定' }).click();

  // 验证删除成功提示
  await expect(page.getByText("删除成功")).toBeVisible({ timeout: 5000 });
});