import { test, expect } from '@playwright/test';

test.describe('Test group', () => {
  test('seed', async ({ page }) => {
    await page.goto('https://172.16.8.190/');
    await page.getByPlaceholder('user name').fill('superadmin');
    await page.getByPlaceholder('password').fill('Admin@123');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeHidden({ timeout: 15000 });
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1500);
  });
});
