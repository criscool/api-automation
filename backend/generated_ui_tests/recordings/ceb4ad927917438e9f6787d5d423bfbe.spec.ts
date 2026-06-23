import { test, expect } from '@playwright/test';

test.use({
  ignoreHTTPSErrors: true,
  storageState: 'D:/code/api-automation/backend/generated_ui_tests/.auth/user.json'
});

test('test', async ({ page }) => {
  await page.goto('https://172.16.8.189/AssetManagement/AssetSegment');
  await page.getByRole('button', { name: ' 更多' }).click();
  await page.getByRole('menuitem', { name: '批量添加' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).click();
  await page.getByRole('textbox', { name: '* 网段名称 :' }).fill('172网段');
  await page.getByRole('textbox', { name: '* 网段 :' }).click();
  await page.getByRole('textbox', { name: '* 网段 :' }).fill('17.17.18.1/24');
  await page.locator('div').filter({ hasText: /^请选择$/ }).nth(4).click();
  await page.getByText('内网').nth(3).click();
  await page.locator('div').filter({ hasText: /^请选择$/ }).nth(4).click();
  await page.getByText('所有告警').click();
  await page.getByRole('button', { name: '确 定' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).fill('17.17.17.18');
  await page.locator('.iconfont.icon-fangdajing').click();
  await page.getByRole('row', { name: '16.16.16.1/24 111 手动添加 0 31' }).getByLabel('', { exact: true }).check();
  await page.getByRole('button', { name: '批量删除' }).click();
  await page.getByRole('button', { name: '确 定' }).click();
});