// The ZIP code box in Settings: saved with the other settings, used to read Craigslist around the buyer, and eBay Motors read live.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const calls = (re) => (fs.readFileSync('/tmp/e2e/calls.log', 'utf8').match(re) || []);
  const ads = async () => { await p.locator('.tabs .tab[data-tab=case]').click().catch(() => {}); await p.waitForTimeout(900); await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(900);
    return { hint: await p.locator('.sheet-body .tozip').count(), cards: await p.locator('.sheet-body .card').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ')).filter((t) => /Craigslist|eBay Motors/.test(t)).map((t) => t.slice(0, 300))) }; };
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(3000);
  log('1 built with no ZIP code', { ...(await ads()), classifiedsCall: calls(/classifieds:.*/g).slice(-1)[0].slice(0, 120) });
  await p.locator('.sheet-body .tozip').click(); await p.waitForTimeout(1500);
  const box = p.getByRole('textbox', { name: 'Your ZIP code' });
  log('2 Open Settings shows the box', { box: await box.count(), visible: await box.isVisible().catch(() => false) });
  await box.fill('7520'); await box.press('Enter'); await p.waitForTimeout(2500);
  const bad = await p.locator('[data-testid="stSidebar"]').innerText();
  await box.fill('75201'); await box.press('Enter'); await p.waitForTimeout(2500);
  const good = await p.locator('[data-testid="stSidebar"]').innerText();
  log('3 a bad ZIP, then a good one', { bad: (bad.match(/That is not a ZIP code[^.]*\./) || [''])[0], good: (good.match(/Craigslist is read within[^.]*\./) || [''])[0] });
  await p.screenshot({ path: '/tmp/e2e/zip-settings.png' });
  await p.keyboard.press('Escape'); await p.locator('[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"]').first().click().catch(() => {}); await p.waitForTimeout(1500);
  const btn = p.locator('.verdict .refresh'); const toasts = [];
  await btn.click();
  for (let i = 0; i < 200; i++) { await p.waitForTimeout(400); const t = (await p.locator('.toast').evaluate((e) => (e.hidden ? '' : e.textContent)).catch(() => '')).replace(/\s+/g, ' '); if (t && toasts[toasts.length - 1] !== t) toasts.push(t); if ((await btn.innerText().catch(() => '')) === 'Refresh results' && i > 5) break; }
  await p.waitForTimeout(2000);
  log('4 refreshed with the ZIP code', { toast: (toasts.slice(-1)[0] || '').slice(0, 160), ...(await ads()), classifiedsCall: calls(/classifieds:.*/g).slice(-1)[0].slice(0, 190) });
  await p.locator('.sheet-body .card', { hasText: 'Craigslist' }).first().evaluate((e) => e.scrollIntoView({ block: 'start' })).catch(() => {}); await p.waitForTimeout(400);
  await p.screenshot({ path: '/tmp/e2e/zip-cards.png' });
  await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(16000);
  const saved = await p.evaluate(() => Object.keys(localStorage).map((k) => [k, (localStorage.getItem(k) || '').slice(0, 2000)]).filter(([k, v]) => /"zip"/.test(v)).map(([k, v]) => [k, (v.match(/"zip":"[^"]*"/) || [''])[0]]));
  log('5 after a reload the ZIP code is kept', { saved, pageReaderOpens: calls(/page reader:.*(ebay|craigslist)[^\n]*/g).length });
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
