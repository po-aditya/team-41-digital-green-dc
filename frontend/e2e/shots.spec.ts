import { test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

test('capture phase-3 screenshots', async ({ page }) => {
  mkdirSync('e2e/shots', { recursive: true });
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: 'e2e/shots/split-view.png', fullPage: false });
  // in the narrow (phone) layout the console is shown first; switch to Phone
  const phoneTab = page.getByRole('tab', { name: 'Phone' });
  if (await phoneTab.count()) await phoneTab.click();
  await page.getByRole('button', { name: /Tap to answer/i }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'e2e/shots/sheet-step1.png' });
  const dialog = page.getByRole('dialog');
  await dialog.locator('button[aria-pressed]').first().click();
  await dialog.locator('button', { hasText: /Next/ }).last().click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'e2e/shots/sheet-step2.png' });
});
