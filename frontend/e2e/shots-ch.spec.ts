import { test } from '@playwright/test';
test('channel screenshots', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'WhatsApp' }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'e2e/shots/whatsapp.png' });
  await page.getByRole('tab', { name: 'Voice' }).click();
  await page.getByRole('button', { name: /Answer call/i }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'e2e/shots/voice-call.png' });
});
