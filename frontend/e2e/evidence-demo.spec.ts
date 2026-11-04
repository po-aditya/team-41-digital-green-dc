import { test, expect } from '@playwright/test';

test('evidence tab renders golden results, confusion matrix, requirements and honest footer', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Evidence' }).click();

  await expect(page.getByRole('heading', { name: /Golden-set evaluation/ })).toBeVisible();
  await expect(page.getByText(/Improvement iterations/)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Confusion matrix/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Telemetry' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Schema validation/ })).toBeVisible();
  // honest-limits footer
  await expect(page.getByText(/RCTs remain the verifier/)).toBeVisible();

  expect(errors, errors.join('\n')).toEqual([]);
});

test('queues tab shows follow-up and human queues with fixed-template acknowledgement', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Queues' }).click();
  await expect(page.getByRole('tab', { name: 'Follow-up queue' })).toBeVisible();

  await page.getByRole('tab', { name: 'Human queue' }).click();
  await expect(page.getByText(/A FarmerChat team member will follow up/)).toBeVisible();
  await expect(page.getByText(/never new advice/)).toBeVisible();

  expect(errors, errors.join('\n')).toEqual([]);
});

test('guided demo starts, advances with Space, and exits with Escape', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');
  await page.getByRole('button', { name: /Demo/ }).click();

  const bar = page.getByRole('region', { name: 'Demo narration' });
  await expect(bar).toBeVisible();
  await expect(bar.getByText('1/7')).toBeVisible();

  await page.keyboard.press('Space');
  await expect(bar.getByText('2/7')).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(bar).toBeHidden();

  expect(errors, errors.join('\n')).toEqual([]);
});
