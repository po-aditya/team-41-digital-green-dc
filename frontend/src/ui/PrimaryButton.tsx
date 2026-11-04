import type { ButtonHTMLAttributes } from 'react';
import styles from './PrimaryButton.module.css';

export function PrimaryButton({
  children,
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" className={`${styles.btn} ${className}`} {...rest}>
      {children}
    </button>
  );
}
