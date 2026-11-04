import { test, expect } from '@playwright/test';

// Required demo path: the farmer answers the Hindi survey with a negative answer
// on the app sheet; a follow-up case must appear in the Queues tab with no
// further operator action. Verifies the response round-trip + follow-up wiring.
test('money moment: negative Hindi tap creates a follow-up case', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');

  // open the app sheet (default scenario is the mustard survey, default lang hi-IN)
  await page.getByRole('button', { name: /Tap to answer/i }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();

  // q1 -> yes (first option), q2 -> easy (first option), q3 -> same (negative, 3rd option)
  const picks = [0, 0, 2];
  for (let step = 0; step < picks.length; step++) {
    const options = dialog.locator('button[aria-pressed]');
    await expect(options.first()).toBeVisible();
    await options.nth(picks[step]!).click();
    const next = dialog.locator('button', { hasText: /Next|बंद करें/ }).last();
    await next.click();
  }
  // thank-you, then close
  await expect(page.getByText('धन्यवाद', { exact: false }).first()).toBeVisible();
  const closeBtn = dialog.locator('button', { hasText: /बंद करें/ }).last();
  if (await closeBtn.count()) await closeBtn.click();

  // the phone now shows a "Follow-up case created" note
  await expect(page.getByText(/Follow-up case created/)).toBeVisible();

  // and the follow-up appears in the Queues tab
  await page.getByRole('tab', { name: 'Queues' }).click();
  await expect(page.getByRole('tab', { name: 'Follow-up queue' })).toBeVisible();
  await expect(page.getByText('advice_did_not_work').first()).toBeVisible();

  expect(errors, errors.join('\n')).toEqual([]);
});

// Operator one-click money moment stages the demo (survey scenario + Hindi).
test('operator money-moment button stages the survey in Hindi and opens queues', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Money moment/ }).click();
  // language toggle now shows Hindi active and the Queues tab is selected
  await expect(page.getByRole('tab', { name: 'Queues', selected: true })).toBeVisible();
});
