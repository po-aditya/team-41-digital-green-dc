import type { ChatMessageRender, Language } from '../data/types';
import { parseTgCallback, readTgMessages } from './channelParse';
import styles from './ChatView.module.css';

export function TelegramView({
  render,
  lang,
  onAnswer,
}: {
  render: ChatMessageRender;
  lang: Language;
  onAnswer: (itemId: string, value: string) => void;
}) {
  const messages = readTgMessages(render.messages);
  return (
    <div className={styles.chat}>
      <p className={styles.caption}>{render.how_it_arrives}</p>
      {messages.map((m, i) => (
        <div key={i} className={`${styles.bubble} ${styles.tg}`}>
          <p className={styles.text} lang={lang}>
            {m.text}
          </p>
          {m.buttons.length > 0 && (
            <div className={styles.buttonsStack}>
              {m.buttons.map((b) => {
                const parsed = parseTgCallback(b.callback_data);
                return (
                  <button
                    key={b.callback_data}
                    type="button"
                    className={styles.callbackBtn}
                    lang={lang}
                    disabled={!parsed}
                    onClick={() => parsed && onAnswer(parsed.item_id, parsed.value)}
                  >
                    {b.title}
                  </button>
                );
              })}
            </div>
          )}
          <span className={styles.kind}>callback data</span>
        </div>
      ))}
    </div>
  );
}
