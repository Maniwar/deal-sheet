// Refresh results on the main screen: visible under the price, needs no sheet, shows what is happening, ends with a notice.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const tabs = async () => (await p.locator('.tabs .tab').allInnerTexts()).slice(0, 3);
  const toast = async () => ((await p.locator('.toast').isVisible().catch(() => false)) ? (await p.locator('.toast').innerText()).slice(0, 220) : '');
  const btn = p.locator('.verdict .refresh');
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  const box = await btn.boundingBox();
  log('1 on the main screen', { label: await btn.innerText(), visible: await btn.isVisible(), at: box && { x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.width), h: Math.round(box.height) }, tabs: await tabs() });
  await p.screenshot({ path: '/tmp/e2e/refresh-idle.png', timeout: 120000 }).catch((e) => console.log('shot failed'));
  await btn.click(); await p.waitForTimeout(700);
  log('2 no key: told where it goes', { toast: await toast(), keyFocused: await p.evaluate(() => { const s = [...document.querySelectorAll('*')].find(el => el.shadowRoot && el.shadowRoot.querySelector('.stage')).shadowRoot; return !!s.activeElement && s.activeElement.type === 'password'; }) });
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await btn.click(); await p.waitForTimeout(1500);
  const during = { label: (await btn.innerText()).replace(/\s+/g, ' '), disabled: await btn.isDisabled(), lines: await p.locator('.verdict .rlog .livelog div').allInnerTexts() };
  await p.screenshot({ path: '/tmp/e2e/refresh-running.png', timeout: 120000 }).catch((e) => console.log('shot failed'));
  const seen = new Set(during.lines); let note = '';
  for (let i = 0; i < 140; i++) { await p.waitForTimeout(400); for (const t of await p.locator('.verdict .rlog .livelog div').allInnerTexts().catch(() => [])) seen.add(t); note = note || await toast(); if ((await btn.innerText().catch(() => '')) === 'Refresh results' && i > 5) break; }
  log('3 while it runs', { ...during, linesSeen: seen.size });
  log('4 done', { label: await btn.innerText(), notice: note || await toast(), tabs: await tabs(), logGone: await p.locator('.verdict .rlog').isHidden() });
  await p.waitForTimeout(1500);
  await p.screenshot({ path: '/tmp/e2e/refresh-done.png', timeout: 120000 }).catch((e) => console.log('shot failed'));
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
