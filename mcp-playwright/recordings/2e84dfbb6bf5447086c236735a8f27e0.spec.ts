import { test, expect } from '@playwright/test';

test.use({
  ignoreHTTPSErrors: true
});

test('test', async ({ page }) => {
  await page.goto('https://172.16.8.190/AssetManagement');
  await page.getByRole('textbox', { name: '用户名' }).click();
});