import { test, expect } from "@playwright/test";


test("资产管理-资产网段-批量增加-搜索-删除", async ({ page }) => {
  await page.goto("/AssetManagement/AssetSegment", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);
  await page.getByRole('button', { name: ' 更多' }).click();
  await page.getByRole('menuitem', { name: '批量添加' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).fill('13网段');
  await page.getByRole('textbox', { name: '* 网段 :' }).click();
  await page.getByRole('textbox', { name: '* 网段 :' }).fill('13.13.13.1/24');
  await page.getByRole('combobox', { name: '* 网络位置 :' }).click();
  await page.locator('.ant-select-item-option-content').filter({ hasText: /^内网$/ }).first().click();
  await page.getByRole('combobox', { name: '* 数据集 :' }).click();
  await page.locator('.ant-select-item-option-content').filter({ hasText: /^docker195$/ }).first().click();
  await page.getByRole('button', { name: '确 定' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).fill('13.13.13.1');
  await page.locator('.iconfont.icon-fangdajing').click();
  await page.getByRole('row', { name: '13.13.13.1/24 13网段 手动添加 0' }).getByLabel('', { exact: true }).check();
  await page.getByText('删除', { exact: true }).click();
  await page.getByRole('button', { name: '确 定' }).click();

  // ⚠️ LLM 未生成业务断言,本条为 deterministic 兜底通用断言;
  // 如失败请手动改为业务断言(如表格行内容 / 详情页字段 / 跳转后页面标题等)
  await expect(
    page.locator('.ant-message, .ant-notification, .ant-modal-confirm, .el-message').first()
  ).toBeVisible({ timeout: 3000 });
});
