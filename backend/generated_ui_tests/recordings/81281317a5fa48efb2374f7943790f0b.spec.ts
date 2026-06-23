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
  await page.getByRole('textbox', { name: '* 网段名称 :' }).fill('13网段');
  await page.getByRole('textbox', { name: '* 网段 :' }).click();
  await page.getByRole('textbox', { name: '* 网段 :' }).fill('13.13.13.1/24');
  await page.getByRole('combobox', { name: '* 网络位置 :' }).click();
  await page.getByText('内网').nth(4).click();
  await page.getByRole('combobox', { name: '* 数据集 :' }).click();
  await page.getByText('docker195').nth(1).click();
  await page.getByRole('button', { name: '确 定' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).click();
  await page.getByRole('textbox', { name: '请输入网段搜索' }).fill('13.13.13.1');
  await page.locator('.iconfont.icon-fangdajing').click();
  await page.getByRole('row', { name: '13.13.13.1/24 13网段 手动添加 0' }).getByLabel('', { exact: true }).check();
  await page.getByText('删除', { exact: true }).click();
  await page.getByRole('button', { name: '确 定' }).click();
});