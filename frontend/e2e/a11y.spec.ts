import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const SERIOUS = new Set(['serious', 'critical']);

async function scan(page: import('@playwright/test').Page, context: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  const bad = results.violations.filter((v) => SERIOUS.has(v.impact ?? ''));
  const summary = bad
    .map((v) => `${v.id} (${v.impact}): ${v.nodes.length} node(s) — ${v.help}`)
    .join('\n');
  expect(bad, `${context} serious/critical a11y violations:\n${summary}`).toEqual([]);
}

test('a11y: console pipeline/timeline has no serious violations', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Next due' }).click();
  await scan(page, 'console');
});

test('a11y: evidence tab has no serious violations', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await page.waitForTimeout(500);
  await scan(page, 'evidence');
});

test('a11y: queues tab has no serious violations', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Queues' }).click();
  await page.getByRole('tab', { name: 'Human queue' }).click();
  await scan(page, 'queues');
});

test('a11y: open phone sheet has no serious violations', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Tap to answer/i }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await scan(page, 'phone-sheet');
});
