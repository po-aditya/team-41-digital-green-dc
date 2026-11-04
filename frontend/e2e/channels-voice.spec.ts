import { test, expect } from '@playwright/test';

test('channel switch renders each channel; voice call completes by simulated speech', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');

  // WhatsApp
  await page.getByRole('tab', { name: 'WhatsApp' }).click();
  await expect(page.getByText('button reply').first()).toBeVisible();

  // Telegram
  await page.getByRole('tab', { name: 'Telegram' }).click();
  await expect(page.getByText('callback data').first()).toBeVisible();

  // Voice: answer the call, then answer every item via simulate-speech chips
  await page.getByRole('tab', { name: 'Voice' }).click();
  await page.getByRole('button', { name: /Answer call/i }).click();

  for (let i = 0; i < 4; i++) {
    const simLabel = page.getByText('Simulate a spoken answer:');
    if (!(await simLabel.count())) break;
    // click the first chip in the simulate row
    const chipRow = page.locator('[aria-label="Simulate a spoken answer"]');
    await chipRow.locator('button').first().click();
    // confirm read-back
    const confirm = page.getByRole('button', { name: /Yes, correct/i });
    await confirm.click();
  }
  // finish closing if present
  const finish = page.getByRole('button', { name: /^Finish$/ });
  if (await finish.count()) await finish.click();

  await expect(page.getByText(/Answered |Follow-up case created|Call ended/)).toBeVisible();
  expect(errors, errors.join('\n')).toEqual([]);
});
