// Ended listings live under the Sold tab, folded; For sale now only holds cars that can be bought.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const pills = () => p.locator('.sheet-body .card:visible .pill').allInnerTexts();
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 200; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(2500);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1200);
  await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(1200);
  log('1 for sale tab pills', await pills());
  log('2 pointer', await p.locator('.sheet-body .endednote').innerText().catch(() => 'none'));
  await p.screenshot({ path: '/tmp/e2e/ended-sale.png', timeout: 120000 }).catch(() => {});
  await p.locator('.sheet-body .toended').click(); await p.waitForTimeout(1500);
  log('3 after the jump', { tabOn: await p.locator('.sheet-tabs .tab.on, .sheet-tabs .tab[aria-selected=true]').innerText().catch(() => ''), foldOpen: await p.locator('.sheet-body .endedfold').evaluate((e) => e.open), summary: await p.locator('.sheet-body .endedfold summary').innerText(), lead: (await p.locator('.sheet-body .endedfold .lead-sub').innerText()).slice(0, 150), cards: await p.locator('.sheet-body .endedfold .card .pill').allInnerTexts(), prices: await p.locator('.sheet-body .endedfold .card .c-price').allInnerTexts() });
  await p.screenshot({ path: '/tmp/e2e/ended-sold.png', timeout: 120000 }).catch(() => {});
  log('4 sold tab headings', await p.locator('.sheet-body h3').allInnerTexts());
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
