import { test, expect } from '@playwright/test';

test.use({
  ignoreHTTPSErrors: true,
  storageState: 'D:/code/api-automation/backend/generated_ui_tests/.auth/user.json'
});

test('test', async ({ page }) => {
  await page.goto('https://172.16.8.189/');
  await page.getByRole('button', { name: '资产' }).click();
  await page.getByRole('link', { name: '资产管理' }).click();
  await page.getByRole('button', { name: ' 更多' }).click();
  await page.getByRole('button', { name: ' 更多' }).click();
  await page.getByRole('menuitem', { name: '添加资产' }).click();
  await page.getByRole('textbox', { name: '* 资产名称 :' }).click();
  await page.getByRole('textbox', { name: '* 资产名称 :' }).fill('测试资产新增');
  await page.getByRole('combobox', { name: '* 项目 :' }).click();
  await page.locator('.ant-select-item-option-content').first().click();
  await page.locator('div:nth-child(6) > .ant-row > .ant-col.ant-col-18 > .ant-form-item-control-input > .ant-form-item-control-input-content > .ant-select > .ant-select-selector > .ant-select-selection-item').click();
  await page.getByTitle('168数据集').click();
  await page.getByRole('textbox', { name: '* IP地址 :' }).click();
  await page.getByRole('textbox', { name: '* IP地址 :' }).fill('172.16.1.1');
  await page.locator('.ant-cascader-picker-label').click();
  await page.getByRole('menuitem', { name: '服务器 right' }).click();
  await page.getByRole('menuitem', { name: 'FTP服务器' }).click();
  await page.getByRole('combobox', { name: '* 资产等级 :' }).click();
  await page.getByText('未知', { exact: true }).nth(3).click();
  await page.getByRole('button', { name: '确 定' }).click();
  await page.getByRole('button', { name: '确 定' }).nth(1).click();
  await page.getByRole('textbox', { name: '请输入资产名称、IP' }).click();
  await page.getByRole('textbox', { name: '请输入资产名称、IP' }).fill('测试资产新增');
  await page.locator('.iconfont.icon-fangdajing').click();
  await page.getByRole('row', { name: '测试资产新增    服务器-FTP服务器 172.16.1' }).getByLabel('', { exact: true }).check();
  await page.getByRole('button', { name: '批量删除' }).click();
  await page.getByRole('button', { name: '确 定' }).click();
});