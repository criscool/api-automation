import { test, expect } from '@playwright/test';

test.use({
  ignoreHTTPSErrors: true,
  storageState: 'D:/code/api-automation/backend/generated_ui_tests/.auth/user.json'
});

test('test', async ({ page }) => {
  await page.goto('https://172.16.8.190/AssetManagement/AssetSegment');
  await page.getByRole('button', { name: ' 更多' }).click();
  await page.getByRole('menuitem', { name: '添加网段' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).fill('添加网段');
  await page.getByRole('textbox', { name: '* 网段 :' }).click();
  await page.getByRole('textbox', { name: '* 网段 :' }).fill('19.18.17.1/24');
  await page.getByRole('combobox', { name: '* 网络位置 :' }).click();
  await page.locator('.ant-select-item-option-content').first().click();
  await page.getByRole('combobox', { name: '* 数据集 :' }).click();
  await page.locator('div:nth-child(30) > div > .ant-select-dropdown > div > .rc-virtual-list > .rc-virtual-list-holder > div > .rc-virtual-list-holder-inner > .ant-select-item > .ant-select-item-option-content').click();
  await page.getByRole('button', { name: '确 定' }).click();
  await page.getByRole('button', { name: '确 定' }).nth(1).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).fill('添加网段');
  await page.locator('.iconfont.icon-fangdajing').click();
  await page.locator('.iconfont.icon-fangdajing').click();
  await page.getByRole('row', { name: '19.18.17.1/24 添加网段 手动添加 0' }).getByLabel('', { exact: true }).check();
  await page.getByRole('button', { name: '批量删除' }).click();
  await page.getByRole('button', { name: '确 定' }).click();
});