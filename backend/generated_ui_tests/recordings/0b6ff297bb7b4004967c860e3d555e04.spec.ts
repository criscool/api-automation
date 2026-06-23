import { test, expect } from '@playwright/test';

test.use({
  ignoreHTTPSErrors: true,
  storageState: 'D:/code/api-automation/backend/generated_ui_tests/.auth/user.json'
});

test('test', async ({ page }) => {
});