import { Smartphone, Globe, MessageCircle, Send, Phone } from 'lucide-react';
import type { Channel } from '../data/types';
import styles from './ChannelSwitcher.module.css';

const CHANNELS: { id: Channel; label: string; icon: typeof Phone }[] = [
  { id: 'app', label: 'App', icon: Smartphone },
  { id: 'web', label: 'Web', icon: Globe },
  { id: 'whatsapp', label: 'WhatsApp', icon: MessageCircle },
  { id: 'telegram', label: 'Telegram', icon: Send },
  { id: 'voice', label: 'Voice', icon: Phone },
];

export function ChannelSwitcher({
  value,
  onChange,
}: {
  value: Channel;
  onChange: (c: Channel) => void;
}) {
  return (
    <div className={styles.row} role="tablist" aria-label="Delivery channel">
      {CHANNELS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          role="tab"
          aria-selected={value === id}
          className={`${styles.tab} ${value === id ? styles.on : ''}`}
          onClick={() => onChange(id)}
          type="button"
        >
          <Icon size={15} aria-hidden="true" />
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
