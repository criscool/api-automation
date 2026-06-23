import { expect } from "@playwright/test";
import { test } from "./fixture";

test.use({
  ignoreHTTPSErrors: true,
  storageState: 'D:/code/api-automation/backend/generated_ui_tests/.auth/user.json'
});

test("资产管理-增加资产", async ({ page }) => {
  await page.goto('https://172.16.8.190/situation');
  await page.getByRole('link', { name: '资产管理' }).click();
  await page.goto('https://172.16.8.190/AssetManagement');
  await page.getByRole('button', { name: ' 更多' }).click();
  await page.getByRole('menuitem', { name: '添加资产' }).click();
  await page.getByRole('textbox', { name: '* 资产名称 :' }).click();
  await page.getByRole('textbox', { name: '* 资产名称 :' }).fill('测试资产新增');
  await page.locator('div').filter({ hasText: /^请选择项目$/ }).nth(4).click();
  await page.locator('.ant-select-item-option-content').first().click();
  await page.locator('div:nth-child(6) > .ant-row > .ant-col.ant-col-18 > .ant-form-item-control-input > .ant-form-item-control-input-content > .ant-select > .ant-select-selector > .ant-select-selection-item').click();
  await page.locator('div:nth-child(30) > div > .ant-select-dropdown > div > .rc-virtual-list > .rc-virtual-list-holder > div > .rc-virtual-list-holder-inner > .ant-select-item > .ant-select-item-option-content').click();
  await page.getByRole('textbox', { name: '* IP地址 :' }).click();
  await page.getByRole('textbox', { name: '* IP地址 :' }).fill('172.16.12.1');
  await page.locator('.ant-cascader-picker-label').click();
  await page.getByRole('menuitem', { name: '服务器 right' }).click();
  await page.getByRole('menuitem', { name: 'HTTP服务器' }).click();
  await page.locator('div').filter({ hasText: /^请选择资产等级$/ }).nth(4).click();
  await page.getByText('未知', { exact: true }).nth(3).click();
  await page.getByRole('button', { name: '确 定' }).click();
  await page.getByRole('button', { name: '确 定' }).nth(1).click();
  await page.getByRole('textbox', { name: '请输入资产名称、IP' }).click();
  await page.getByRole('textbox', { name: '请输入资产名称、IP' }).fill('测试资产');
  await page.locator('.iconfont.icon-fangdajing').click();
  await page.getByRole('row', { name: '测试资产新增    服务器-HTTP服务器 172.16.' }).getByLabel('', { exact: true }).check();
  await page.getByRole('button', { name: '批量删除' }).click();
  await page.getByRole('button', { name: '确 定' }).click();
});
