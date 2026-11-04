import type { ChatMessageRender, Language } from '../data/types';
import { parseWaReplyId, readWaMessages } from './channelParse';
import styles from './ChatView.module.css';

export function WhatsAppView({
  render,
  lang,
  onAnswer,
}: {
  render: ChatMessageRender;
  lang: Language;
  onAnswer: (itemId: string, value: string) => void;
}) {
  const messages = readWaMessages(render.messages);
  return (
    <div className={styles.chat}>
      <p className={styles.caption}>{render.how_it_arrives}</p>
      {messages.map((m, i) => (
        <div key={i} className={`${styles.bubble} ${styles.wa}`}>
          <p className={styles.text} lang={lang}>
            {m.text}
          </p>
          {m.buttons.length > 0 && (
            <div className={styles.buttons}>
              {m.buttons.map((b) => {
                const parsed = parseWaReplyId(b.id);
                return (
                  <button
                    key={b.id}
                    type="button"
                    className={styles.replyBtn}
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
          <span className={styles.kind}>button reply</span>
        </div>
      ))}
    </div>
  );
}
