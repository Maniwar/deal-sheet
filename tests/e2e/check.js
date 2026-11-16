// The "Check they are still for sale" button after a build: notice wording, cards after the check, no errors.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 200; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(2500);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1200);
  await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(1200);
  log('1 before', await p.locator('.sheet-body .card .pill').allInnerTexts());
  await p.locator('.sheet-body .verify').click();
  for (let i = 0; i < 120; i++) { await p.waitForTimeout(500); const t = await p.locator('.sheet-body .verify').innerText().catch(() => ''); if (/Check they/.test(t) && i > 4) break; }
  await p.waitForTimeout(2500);
  log('2 notice', await p.locator('.toast, .notice, [class*=notice]').allInnerTexts().catch(() => []));
  log('3 after', await p.locator('.sheet-body .card').evaluateAll((els) => els.map((e) => ((e.querySelector('.pill') || {}).textContent || '') + ' ' + ((e.querySelector('.c-price') || {}).textContent || '') + ' | ' + ((e.querySelector('.c-seen') || {}).textContent || '').slice(0, 44))));
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
