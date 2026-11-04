import { test, expect } from '@playwright/test';

test('app mounts with honesty chrome and a working Hindi sheet', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });

  await page.goto('/');
  // persistent synthetic badge
  await expect(page.getByText('SYNTHETIC DATA · SIMULATED DELIVERY')).toBeVisible();
  // console stats from real fixtures
  await expect(page.getByText('Ingested')).toBeVisible();
  await expect(page.getByText('6,999')).toBeVisible();

  // open the phone sheet and complete it in Hindi (default language is hi-IN)
  await page.getByRole('button', { name: /Tap to answer/i }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();

  for (let i = 0; i < 5; i++) {
    const options = dialog.locator('button[aria-pressed]');
    if ((await options.count()) === 0) break;
    await options.first().click();
    const next = dialog.locator('button', { hasText: /Next|बंद करें/ }).last();
    await next.click();
    if (await page.getByText('धन्यवाद', { exact: false }).count()) break;
  }
  await expect(page.getByText('धन्यवाद', { exact: false }).first()).toBeVisible();
  expect(errors, errors.join('\n')).toEqual([]);
});
