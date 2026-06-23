import { test, expect } from "@playwright/test";


test("资产管理-资产网段-批量添加", async ({ page }) => {
  await page.goto("/AssetManagement/AssetSegment", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);
  await page.getByRole('button', { name: ' 更多' }).click();
  await page.getByRole('menuitem', { name: '批量添加' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).fill('17网段');
  await page.getByRole('textbox', { name: '* 网段 :' }).click();
  await page.getByRole('textbox', { name: '* 网段 :' }).fill('17.17.18.1/24');
  await page.locator('div').filter({ hasText: /^请选择$/ }).nth(4).click();
  await page.locator("div.ant-select-item-option-content").filter({hasText: /^内网$/}).click();
  await page.locator('div').filter({ hasText: /^请选择$/ }).nth(4).click();
  await page.locator("div.ant-select-item-option-content").filter({hasText: /^31数据集$/}).click();
  await page.getByRole('button', { name: '确 定' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).fill('17.17.18');
  await page.locator('.iconfont.icon-fangdajing').click();
  await page.getByRole('row', { name: '17.17.18.1/24 17网段 手动添加 0 31' }).getByLabel('', { exact: true }).check();
  await page.getByRole('button', { name: '批量删除' }).click();
  await page.getByRole('button', { name: '确 定' }).click();
});
