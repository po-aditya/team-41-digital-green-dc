import { useMemo, useState } from 'react';
import { ArrowLeft, Info } from 'lucide-react';
import type { BottomSheetRender, Language } from '../data/types';
import { SegmentedProgress } from '../ui/SegmentedProgress';
import { OptionRow } from '../ui/OptionRow';
import { PrimaryButton } from '../ui/PrimaryButton';
import { Confetti } from '../ui/Confetti';
import {
  answer,
  back,
  close,
  currentStep,
  initSheet,
  skip,
  stepNumber,
  totalSteps,
  type SheetState,
} from '../state/sheetSteps';
import styles from './BottomSheet.module.css';

export interface SheetSubmission {
  answers: Record<string, string>;
  closedReason: SheetState['closedReason'];
}

export function BottomSheet({
  render,
  lang,
  onComplete,
  onClose,
  micSlot,
}: {
  render: BottomSheetRender;
  lang: Language;
  onComplete: (s: SheetSubmission) => void;
  onClose: () => void;
  micSlot?: (itemId: string, onPick: (value: string) => void) => React.ReactNode;
}) {
  const [state, setState] = useState<SheetState>(initSheet);
  const [choice, setChoice] = useState<string | null>(null);
  const step = currentStep(render, state);
  const total = totalSteps(render);
  const titleId = 'sheet-title';
  const deliveryTip = useMemo(
    () =>
      `Opens when: ${render.presentation.opens_when.join(', ')}. Waits for: ${render.presentation.waits_for.join(', ')}.`,
    [render],
  );

  if (state.phase === 'thank_you') {
    return (
      <div className={styles.thanks}>
        <Confetti active />
        <p className={styles.thankText} lang={lang}>
          {render.sheet.thank_you}
        </p>
        <PrimaryButton onClick={() => onComplete({ answers: state.answers, closedReason: state.closedReason })}>
          {render.sheet.close_label}
        </PrimaryButton>
      </div>
    );
  }
  if (state.phase === 'closed') {
    onClose();
    return null;
  }
  if (!step) return null;

  const advance = () => {
    if (choice == null) return;
    const next = answer(render, state, choice);
    setChoice(null);
    setState(next);
    if (next.phase === 'thank_you') {
      // completion handled by the thank-you render above
    }
  };

  return (
    <div className={styles.sheet}>
      <div className={styles.topbar}>
        {state.stepIndex > 0 ? (
          <button type="button" className={styles.back} aria-label="Back" onClick={() => { setChoice(null); setState(back(state)); }}>
            <ArrowLeft size={20} />
          </button>
        ) : (
          <span className={styles.backSpacer} />
        )}
        <button type="button" className={styles.tip} title={deliveryTip} aria-label="Delivery conditions">
          <Info size={16} />
        </button>
        <button
          type="button"
          className={styles.exit}
          aria-label={`Exit survey ()`}
          onClick={() => setState(close(state))}
        >
          {render.sheet.close_label}
        </button>
      </div>

      <SegmentedProgress total={total} filled={stepNumber(state)} ariaLabel={step.step_label} />

      <h2 id={titleId} className={styles.title} lang={lang}>
        {render.sheet.title}
      </h2>
      <p className={styles.stepLabel}>{step.step_label}</p>
      <p className={styles.question} lang={lang}>
        {step.question}
      </p>

      <div className={styles.options}>
        {step.options.map((opt) => (
          <OptionRow
            key={opt.answer}
            label={opt.label}
            selected={choice === opt.answer}
            onSelect={() => setChoice(opt.answer)}
            lang={lang}
          />
        ))}
      </div>

      {micSlot?.(step.item_id, (value) => {
        setChoice(value);
      })}

      <div className={styles.actions}>
        <PrimaryButton disabled={choice == null} onClick={advance}>
          {state.stepIndex >= total - 1 ? render.sheet.close_label : 'Next'}
        </PrimaryButton>
        <button type="button" className={styles.skip} onClick={() => { setChoice(null); setState(skip(render, state)); }}>
          {render.sheet.skip_label}
        </button>
      </div>
    </div>
  );
}
