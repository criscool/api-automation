import { test, expect } from "@playwright/test";

test('资产管理-添加资产-搜索-删除', async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);

  // 导航到资产管理
  await page.getByRole('button', { name: '资产' }).click();
  await page.getByRole('link', { name: '资产管理' }).click();

  // 打开更多菜单，添加资产
  await page.getByRole('button', { name: '更多' }).click();
  await page.getByRole('button', { name: '更多' }).click();
  await page.getByRole('menuitem', { name: '添加资产' }).click();

  // 填写资产基本信息
  await page.getByRole('textbox', { name: '* 资产名称 :' }).click();
  await page.getByRole('textbox', { name: '* 资产名称 :' }).fill('测试资产新增');

  // 选择项目
  await page.getByRole('combobox', { name: '* 项目 :' }).click();
  await page.locator('.ant-select-item-option-content').first().click();

  // 选择数据集
  // await page.locator('div:nth-child(6) > .ant-row > .ant-col.ant-col-18 > .ant-form-item-control-input > .ant-form-item-control-input-content > .ant-select > .ant-select-selector > .ant-select-selection-item').click();
  await page.locator("#asset_stream").click({ force: true });
  await page.getByTitle('168数据集').click();

  // 输入IP地址
  await page.getByRole('textbox', { name: '* IP地址 :' }).click();
  await page.getByRole('textbox', { name: '* IP地址 :' }).fill('172.16.1.1');

  // 选择资产类型：服务器 - FTP服务器
  await page.locator('.ant-cascader-picker-label').click();
  await page.getByRole('menuitem', { name: '服务器 right' }).click();
  await page.getByRole('menuitem', { name: 'FTP服务器' }).click();

  // 选择资产等级
  await page.getByRole('combobox', { name: '* 资产等级 :' }).click();
  await page.getByText('未知', { exact: true }).nth(3).click();

  // 提交添加
  await page.getByRole('button', { name: '确 定' }).click();
  // 确认弹窗
  await page.getByRole('button', { name: '确 定' }).nth(1).click();

  // 搜索刚添加的资产
  await page.getByRole('textbox', { name: '请输入资产名称、IP' }).click();
  await page.getByRole('textbox', { name: '请输入资产名称、IP' }).fill('测试资产新增');
  // 按回车提交搜索
  await page.keyboard.press("Enter");

  // 选择搜索结果并批量删除
  await page.getByRole('row', { name: '测试资产新增    服务器-FTP服务器 172.16.1' }).getByLabel('', { exact: true }).check();
  await page.getByRole('button', { name: '批量删除' }).click();
  // 确认删除
  await page.getByRole('button', { name: '确 定' }).click();

  // 终态断言:删除成功 toast 必须出现,否则用例 PASS 没有实际意义
  await expect(page.getByText('删除成功')).toBeVisible({ timeout: 5000 });
});