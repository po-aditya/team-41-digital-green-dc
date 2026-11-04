import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseWaReplyId, parseTgCallback, readWaMessages, readTgMessages } from '../src/phone/channelParse';
import type { ChatMessageRender } from '../src/data/types';

function load(scenario: string, lang: string, channel: string): ChatMessageRender {
  return JSON.parse(
    readFileSync(join(__dirname, '..', 'public', 'fixtures', 'scenarios', scenario, 'render', lang, `${channel}.json`), 'utf-8'),
  ) as ChatMessageRender;
}

describe('channel payload parsers', () => {
  it('parses WhatsApp reply ids', () => {
    expect(parseWaReplyId('S-20931|q1|yes')).toEqual({ item_id: 'q1', value: 'yes' });
    expect(parseWaReplyId('bad')).toBeNull();
  });
  it('parses Telegram callback_data', () => {
    expect(parseTgCallback('mel|S-20931|q1|no')).toEqual({ item_id: 'q1', value: 'no' });
    expect(parseTgCallback('x')).toBeNull();
  });

  for (const lang of ['en-IN', 'hi-IN']) {
    it(`reads WhatsApp buttons from real fixture (${lang}) and every id parses`, () => {
      const r = load('1-mustard-aphid-spray', lang, 'whatsapp');
      const msgs = readWaMessages(r.messages);
      const withButtons = msgs.filter((m) => m.buttons.length > 0);
      expect(withButtons.length).toBeGreaterThan(0);
      for (const m of withButtons) for (const b of m.buttons) expect(parseWaReplyId(b.id)).not.toBeNull();
    });
    it(`reads Telegram buttons from real fixture (${lang}) and every callback parses`, () => {
      const r = load('1-mustard-aphid-spray', lang, 'telegram');
      const msgs = readTgMessages(r.messages);
      const withButtons = msgs.filter((m) => m.buttons.length > 0);
      expect(withButtons.length).toBeGreaterThan(0);
      for (const m of withButtons) for (const b of m.buttons) expect(parseTgCallback(b.callback_data)).not.toBeNull();
    });
  }
});
