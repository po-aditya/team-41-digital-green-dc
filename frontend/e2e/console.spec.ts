import { test, expect } from '@playwright/test';

test('console: clock advance shows a diff; timeline row opens the drawer', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');
  // pipeline counts (exact to avoid matching the 'Pipeline & timeline' tab)
  await expect(page.getByText('Pipeline', { exact: true })).toBeVisible();
  await expect(page.getByText('6,999')).toBeVisible();

  // advance the clock
  await page.getByRole('button', { name: 'Next due' }).click();
  await expect(page.getByText(/delivered/).first()).toBeVisible();

  // timeline + drawer
  await expect(page.getByText('Survey timeline')).toBeVisible();
  const firstRow = page.locator('button', { hasText: /^S-/ }).first();
  await firstRow.click();
  await expect(page.getByRole('complementary', { name: 'Survey detail' })).toBeVisible();
  await expect(page.getByText('Source insight')).toBeVisible();
  await expect(page.getByText('Decision')).toBeVisible();

  expect(errors, errors.join('\n')).toEqual([]);
});
