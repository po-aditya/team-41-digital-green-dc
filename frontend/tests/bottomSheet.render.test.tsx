import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { BottomSheet } from '../src/phone/BottomSheet';
import type { BottomSheetRender } from '../src/data/types';

const appRender = JSON.parse(
  readFileSync(
    join(__dirname, '..', 'public', 'fixtures', 'scenarios', '1-mustard-aphid-spray', 'render', 'hi-IN', 'app.json'),
    'utf-8',
  ),
) as BottomSheetRender;

describe('BottomSheet renders backend render verbatim (hi-IN)', () => {
  it('shows the backend title, step label and first question in Hindi', () => {
    render(<BottomSheet render={appRender} lang="hi-IN" onComplete={() => {}} onClose={() => {}} />);
    expect(screen.getByText(appRender.sheet.title)).toBeInTheDocument();
    const firstStep = appRender.sheet.steps[0]!;
    expect(screen.getByText(firstStep.step_label)).toBeInTheDocument();
    expect(screen.getByText(firstStep.question)).toBeInTheDocument();
    // options rendered from backend labels
    for (const opt of firstStep.options) {
      expect(screen.getByText(opt.label)).toBeInTheDocument();
    }
  });

  it('primary button is disabled until an option is chosen, then advances', () => {
    render(<BottomSheet render={appRender} lang="hi-IN" onComplete={() => {}} onClose={() => {}} />);
    const next = screen.getByRole('button', { name: /Next/i });
    expect(next).toBeDisabled();
    const firstStep = appRender.sheet.steps[0]!;
    fireEvent.click(screen.getByText(firstStep.options[0]!.label));
    expect(next).toBeEnabled();
    fireEvent.click(next);
    // step 2 question now visible
    const secondStep = appRender.sheet.steps[1]!;
    expect(screen.getByText(secondStep.question)).toBeInTheDocument();
  });

  it('completing all steps shows the backend thank_you and calls onComplete with answers', () => {
    const onComplete = vi.fn();
    render(<BottomSheet render={appRender} lang="hi-IN" onComplete={onComplete} onClose={() => {}} />);
    for (let i = 0; i < appRender.sheet.steps.length; i++) {
      const step = appRender.sheet.steps[i]!;
      fireEvent.click(screen.getByText(step.options[0]!.label));
      const last = i === appRender.sheet.steps.length - 1;
      const name = last ? new RegExp(`^${appRender.sheet.close_label}$`) : /Next/i;
      const matches = screen.getAllByRole('button', { name }).filter((b) => !b.getAttribute('aria-label'));
      fireEvent.click(matches[matches.length - 1]!);
    }
    expect(screen.getByText(appRender.sheet.thank_you)).toBeInTheDocument();
    // finish button in thank-you view
    fireEvent.click(screen.getByRole('button', { name: appRender.sheet.close_label }));
    expect(onComplete).toHaveBeenCalledOnce();
    const arg = onComplete.mock.calls[0]![0] as { answers: Record<string, string> };
    expect(Object.keys(arg.answers)).toHaveLength(appRender.sheet.steps.length);
  });
});
