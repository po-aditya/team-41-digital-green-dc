/** Pure parsers for channel button payloads. No rendering, easy to unit-test. */

export interface ParsedButton {
  item_id: string;
  value: string;
}

/** WhatsApp reply.id format: "S-20931|q1|yes" -> { item_id:q1, value:yes }. */
export function parseWaReplyId(id: string): ParsedButton | null {
  const parts = id.split('|');
  if (parts.length < 3) return null;
  const item_id = parts[parts.length - 2]!;
  const value = parts[parts.length - 1]!;
  if (!item_id || !value) return null;
  return { item_id, value };
}

/** Telegram callback_data format: "mel|S-20931|q1|yes" -> { item_id:q1, value:yes }. */
export function parseTgCallback(data: string): ParsedButton | null {
  const parts = data.split('|');
  if (parts.length < 2) return null;
  const item_id = parts[parts.length - 2]!;
  const value = parts[parts.length - 1]!;
  if (!item_id || !value) return null;
  return { item_id, value };
}

// --- minimal typed views over the raw render messages ---
export interface WaButton {
  title: string;
  id: string;
}
export interface WaInteractiveMessage {
  text: string;
  buttons: WaButton[];
}

export function readWaMessages(messages: unknown[]): WaInteractiveMessage[] {
  const out: WaInteractiveMessage[] = [];
  for (const raw of messages) {
    const m = raw as Record<string, unknown>;
    const interactive = m.interactive as
      | { body?: { text?: string }; action?: { buttons?: Array<{ reply?: { id?: string; title?: string } }> } }
      | undefined;
    if (interactive?.body?.text) {
      const buttons: WaButton[] = (interactive.action?.buttons ?? [])
        .map((b) => ({ title: b.reply?.title ?? '', id: b.reply?.id ?? '' }))
        .filter((b) => b.title);
      out.push({ text: interactive.body.text, buttons });
      continue;
    }
    // template / plain text messages: show whatever text we can find
    const template = m.template as { name?: string } | undefined;
    if (typeof m.text === 'string') out.push({ text: m.text, buttons: [] });
    else if (template?.name) out.push({ text: `[template: ${template.name}]`, buttons: [] });
  }
  return out;
}

export interface TgButton {
  title: string;
  callback_data: string;
}
export interface TgMessage {
  text: string;
  buttons: TgButton[];
}

export function readTgMessages(messages: unknown[]): TgMessage[] {
  const out: TgMessage[] = [];
  for (const raw of messages) {
    const m = raw as Record<string, unknown>;
    const text = typeof m.text === 'string' ? m.text : '';
    if (!text) continue;
    const markup = m.reply_markup as { inline_keyboard?: Array<Array<{ text?: string; callback_data?: string }>> } | undefined;
    const buttons: TgButton[] = (markup?.inline_keyboard ?? [])
      .flat()
      .map((b) => ({ title: b.text ?? '', callback_data: b.callback_data ?? '' }))
      .filter((b) => b.title);
    out.push({ text, buttons });
  }
  return out;
}
