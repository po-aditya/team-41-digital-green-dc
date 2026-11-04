import { test } from '@playwright/test';
test('console screenshot', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Next due' }).click();
  await page.locator('button', { hasText: /^S-/ }).first().click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'e2e/shots/console-drawer.png' });
});
