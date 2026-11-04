import { test } from '@playwright/test';

test('evidence and queues screenshots', async ({ page }) => {
  await page.goto('/');

  await page.getByRole('tab', { name: 'Evidence' }).click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: 'e2e/shots/evidence.png', fullPage: true });

  await page.getByRole('tab', { name: 'Queues' }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'e2e/shots/queues-followups.png' });
  await page.getByRole('tab', { name: 'Human queue' }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'e2e/shots/queues-human.png' });

  // demo narration overlay
  await page.getByRole('button', { name: /Demo/ }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'e2e/shots/demo-narration.png' });
});
