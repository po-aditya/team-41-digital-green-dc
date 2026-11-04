import assert from 'node:assert/strict';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Standalone acceptance runner. Uses the desktop's bundled runtime, no installs.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const artifact = path.join(root, 'docs/farmerchat-briefing/index.html');
const out = process.env.BRIEFING_QA_DIR || '/private/tmp/farmerchat-qa';
const require = createRequire('/Users/dwayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const { chromium } = require('playwright');
const results = [];
const errors = [];
const network = [];
let browser;
let page;

async function check(name, fn) {
  try {
    await fn();
    results.push({ name, status: 'PASS' });
    console.log(`PASS ${name}`);
  } catch (error) {
    results.push({ name, status: 'FAIL', detail: error.message });
    console.error(`FAIL ${name}: ${error.message}`);
  }
}

await mkdir(out, { recursive: true });
await check('Artifact exists and contains required semantic landmarks', async () => {
  const html = await readFile(artifact, 'utf8');
  assert.match(html, /<html[^>]+lang="en"/);
  assert.match(html, /<main[\s>]/);
  assert.match(html, /id="claude-summary"/);
  assert.match(html, /id="codex-assessment"/);
  assert.match(html, /id="sources"/);
  assert.match(html, /id="hackathon-plan"/);
  assert.match(html, /id="model-contributions"/);
  assert.match(html, /id="enhancement-comparison"/);
  assert.match(html, /id="aws-map"/);
});

if (results.some(r => r.status === 'FAIL')) {
  await writeFile(path.join(out, 'results.json'), JSON.stringify({ results }, null, 2));
  process.exitCode = 1;
} else {
  try {
    // Use the installed browser; the bundled Playwright version's default
    // Chromium revision may not be cached on the desktop.
    browser = await chromium.launch({ headless: true, channel: 'chrome' });
    const context = await browser.newContext({ offline: true, viewport: { width: 1440, height: 960 } });
    page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    page.on('request', request => { if (/^https?:/i.test(request.url())) network.push(request.url()); });
    await page.goto(pathToFileURL(artifact).href, { waitUntil: 'load' });

    await check('Briefing loads fully offline without external requests', async () => {
      assert.equal(network.length, 0, network.join('\n'));
      assert.match(await page.title(), /FarmerChat/i);
      assert.equal(await page.locator('h1').count(), 1);
    });

    await check('Desktop content fits the viewport', async () => {
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({ path: path.join(out, 'desktop.png'), fullPage: true });
    });

    await check('Workflow stages change detail with keyboard activation', async () => {
      const stages = page.locator('button[data-stage]');
      assert(await stages.count() >= 4);
      const before = await page.locator('#stage-detail').innerText();
      await stages.nth(1).focus();
      await page.keyboard.press('Enter');
      const next = await page.locator('#stage-detail').innerText();
      assert.notEqual(next, before, 'Selecting another stage must change explanatory content');
      await stages.nth(0).focus();
      await page.keyboard.press('Space');
      assert.equal(await page.locator('#stage-detail').innerText(), before);
      assert(await stages.nth(0).evaluate(el => el.getAttribute('aria-pressed') === 'true' || el.getAttribute('aria-selected') === 'true'));
    });

    await check('Each scope filter shows only matching entries and updates the count', async () => {
      const filter = page.locator('#scope-filter');
      for (const scope of ['must', 'should', 'exploratory', 'out']) {
        await filter.selectOption(scope);
        const visible = page.locator('[data-scope]:visible');
        assert(await visible.count() > 0, `No visible ${scope} rows`);
        const values = await visible.evaluateAll(rows => rows.map(row => row.dataset.scope));
        assert(values.every(value => value === scope), `Mixed scope after selecting ${scope}`);
        assert.match(await page.locator('#scope-count').innerText(), new RegExp(`\\b${values.length}\\b`));
      }
      await filter.selectOption('all');
      assert(await page.locator('[data-scope]:visible').count() >= 12);
    });

    await check('Claude output is separate, attributed, and substantial', async () => {
      const summary = page.locator('#claude-summary');
      await summary.locator('summary').click();
      assert(await page.locator('#claude-output').isVisible());
      const raw = await page.locator('#claude-output').innerText();
      assert(raw.length > 1500, 'Expected actual completed summary, not a placeholder');
      assert.match(raw, /survey/i);
      assert.match(raw, /MVP|scope/i);
      assert.match(await summary.innerText(), /Claude/i);
      assert(await page.locator('#codex-assessment').isVisible());
      assert.match(await page.locator('#codex-assessment').innerText(), /Codex/i);
      await summary.locator('summary').click();
    });

    await check('Hackathon proposal covers frontend, backend and evals with pinned public provenance', async () => {
      const plan = page.locator('#hackathon-plan');
      const text = await plan.innerText();
      for (const role of [/front.?end/i, /back.?end/i, /eval/i]) assert.match(text, role);
      assert.match(text, /propos(ed|al)|recommend(ed|ation)/i);
      assert.match(text, /no.{0,40}(results|implementation)|not.{0,50}(built|implemented|results|completion)|unimplemented/is);
      const links = await plan.locator('a[href]').evaluateAll(anchors => anchors.map(anchor => anchor.href));
      assert(links.some(href => /^https:\/\/github\.com\/[^/]+\/DG_Open\/(commit|tree)\/[0-9a-f]{40}(?:[/?#]|$)/i.test(href)), 'Expected a DG_Open immutable commit or tree provenance link');
    });

    await check('Model contributions distinguish actual CLI results and independent assessment', async () => {
      const attribution = await page.locator('#model-contributions').innerText();
      assert.match(attribution, /Claude/i);
      assert.match(attribution, /CLI/i);
      assert.match(attribution, /Codex/i);
      assert.match(attribution, /Antigravity|Gemini/i);
      assert.match(attribution, /completed|returned|failed|blocked|unavailable/i);
      assert((await page.locator('#claude-output').textContent()).length > 1500);
    });

    await check('Five enhancement choices each explain a workflow and include an accessible offline diagram', async () => {
      const comparison = page.locator('#enhancement-comparison');
      const choices = comparison.locator('[data-enhancement]');
      assert.equal(await choices.count(), 5);
      const keys = await choices.evaluateAll(items => items.map(item => item.dataset.enhancement));
      assert.equal(new Set(keys).size, 5);
      assert.match(await comparison.innerText(), /choose one|select one|options|unselected|not selected/i);
      for (const choice of await choices.all()) {
        // Inspect the same native disclosures a reader opens for build detail.
        for (const summary of await choice.locator('details > summary').all()) {
          if (!await summary.evaluate(el => el.parentElement.open)) await summary.click();
        }
        const text = await choice.innerText();
        for (const topic of [/workflow/i, /input/i, /dependenc/i, /acceptance/i]) assert.match(text, topic);
        const diagram = choice.locator('svg, img').first();
        assert.equal(await diagram.count(), 1);
        assert(await diagram.evaluate(el => {
          if (el.tagName.toLowerCase() === 'img') return Boolean(el.getAttribute('alt')?.trim()) && !/^https?:/i.test(el.getAttribute('src') || '');
          return Boolean(el.getAttribute('aria-label')?.trim() || el.getAttribute('aria-labelledby')?.trim() || el.querySelector('title')?.textContent.trim());
        }), 'Diagram needs an accessible name and local content');
      }
    });

    await check('AWS mapping separates required Bedrock from optional services and plan fits one day', async () => {
      const aws = page.locator('#aws-map');
      const text = await aws.innerText();
      assert.match(text, /Bedrock/i);
      assert.match(text, /required/i);
      assert.match(text, /optional/i);
      const links = await aws.locator('a[href]').evaluateAll(anchors => anchors.map(anchor => anchor.href));
      assert(links.filter(href => /^https:\/\/docs\.aws\.amazon\.com\//i.test(href)).length >= 2, 'Expected official AWS service references');
      const plan = await page.locator('#hackathon-plan').innerText();
      assert.match(plan, /one.day|1.day|single.day/i);
      assert.doesNotMatch(plan, /day\s*2\b|second day|two.day plan/i);
    });

    await check('Enhancement shortlist starts empty, explains selected tradeoffs, and grants no implementation approval', async () => {
      const picks = page.locator('#enhancement-comparison input[data-pick]');
      assert.equal(await picks.count(), 5);
      assert.equal(await picks.evaluateAll(items => items.filter(item => item.checked).length), 0);
      const titles = [];
      for (let i = 0; i < 2; i++) {
        titles.push((await page.locator('[data-enhancement]').nth(i).locator('h2, h3, h4').first().innerText()).trim());
        await picks.nth(i).check();
      }
      const summary = await page.locator('#selection-summary').innerText();
      for (const title of titles) assert(summary.includes(title), `Missing selected title: ${title}`);
      assert.match(summary, /dependenc|trade.?off/i);
      assert.match(summary, /discussion|shortlist/i);
      assert.match(summary, /not.{0,60}(implementation|approval)|no.{0,40}(implementation|approval)/is);
      await page.locator('#reset-selection').click();
      assert.equal(await picks.evaluateAll(items => items.filter(item => item.checked).length), 0);
    });

    await check('Acceptance checklist records review actions without claiming implementation completion', async () => {
      const checks = page.locator('#acceptance-list input[type="checkbox"]');
      assert(await checks.count() >= 6);
      assert.equal(await checks.evaluateAll(items => items.filter(item => item.checked).length), 0);
      const original = await page.locator('#acceptance-count').innerText();
      await checks.first().check();
      assert.notEqual(await page.locator('#acceptance-count').innerText(), original);
      await page.locator('#reset-checklist').click();
      assert.equal(await checks.evaluateAll(items => items.filter(item => item.checked).length), 0);
      assert.match(await page.locator('#acceptance-list').locator('..').innerText(), /not.{0,50}(proof|evidence|complet)|no.{0,40}(implementation|MVP).{0,30}(verified|complete)|review.{0,30}(only|checklist)/is);
    });

    await check('Both original document links resolve locally', async () => {
      const hrefs = await page.locator('#sources a[href]').evaluateAll(links => links.map(link => link.href).filter(href => /\.docx$/i.test(href)));
      assert.equal(hrefs.length, 2);
      for (const href of hrefs) await access(fileURLToPath(href));
    });

    await check('Print view exposes the raw summary and all scope entries', async () => {
      await page.locator('#scope-filter').selectOption('must');
      await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
      await page.emulateMedia({ media: 'print' });
      assert(await page.locator('#claude-output').isVisible());
      assert.equal(await page.locator('[data-scope]:visible').count(), await page.locator('[data-scope]').count());
      await page.pdf({ path: path.join(out, 'briefing-print.pdf'), format: 'A4', printBackground: true });
      await page.emulateMedia({ media: 'screen' });
      await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
      assert(await page.locator('#print-button').isVisible());
      await page.locator('#scope-filter').selectOption('all');
    });

    await check('Mobile layout fits at 390px and controls remain usable', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.locator('#scope-filter').selectOption('must');
      assert(await page.locator('[data-scope]:visible').count() > 0);
      await page.locator('#scope-filter').selectOption('all');
      await page.screenshot({ path: path.join(out, 'mobile.png'), fullPage: true });
    });

    await check('No JavaScript or browser console errors throughout interactions', async () => {
      assert.deepEqual(errors, []);
      assert.deepEqual(network, []);
    });
  } catch (error) {
    results.push({ name: 'Browser setup and execution', status: 'FAIL', detail: error.stack });
    console.error(error.stack);
  } finally {
    if (browser) await browser.close();
    await writeFile(path.join(out, 'results.json'), JSON.stringify({ results, errors, network }, null, 2));
    process.exitCode = results.some(result => result.status === 'FAIL') ? 1 : 0;
  }
}
